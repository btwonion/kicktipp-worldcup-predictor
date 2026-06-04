from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import requests

from config import load_settings, require_api_key
from models import ProbabilityResult

from ..cache import CACHE_TTL, load_from_cache, save_to_cache
from ..elo import DataSourceUnavailable
from ..team_matching import team_names_match
from .base import ProviderContext


def normalize_bookmaker_odds_to_probabilities(
    odds: dict[str, Any] | list[dict[str, Any]]
) -> dict[str, float]:
    if isinstance(odds, list):
        by_name = {item["name"].lower(): item["price"] for item in odds}
        raw = {
            "home": by_name.get("home") or by_name.get("team_a") or by_name.get("1"),
            "draw": by_name.get("draw") or by_name.get("x"),
            "away": by_name.get("away") or by_name.get("team_b") or by_name.get("2"),
        }
    else:
        raw = {
            "home": odds.get("home")
            or odds.get("team_a")
            or odds.get("a")
            or odds.get("1"),
            "draw": odds.get("draw") or odds.get("x"),
            "away": odds.get("away")
            or odds.get("team_b")
            or odds.get("b")
            or odds.get("2"),
        }

    if raw["home"] is None or raw["draw"] is None or raw["away"] is None:
        raise ValueError("Odds must include home/draw/away.")
    prices = {
        "home": float(raw["home"]),
        "draw": float(raw["draw"]),
        "away": float(raw["away"]),
    }
    if any(value <= 1 for value in prices.values()):
        raise ValueError("Decimal odds must be > 1.")

    implied = {key: 1 / value for key, value in prices.items()}
    overround = sum(implied.values())
    if overround <= 0:
        raise ValueError("Invalid odds.")

    return {
        "p_a": implied["home"] / overround,
        "p_draw": implied["draw"] / overround,
        "p_b": implied["away"] / overround,
        "bookmaker_margin": overround - 1,
    }


def _extract_h2h_prices(
    event: dict[str, Any], team_a: str, team_b: str
) -> dict[str, float] | None:
    for bookmaker in event.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market.get("key") != "h2h":
                continue
            prices: dict[str, float] = {}
            for outcome in market.get("outcomes", []):
                name = outcome.get("name")
                price = outcome.get("price")
                if team_names_match(team_a, [str(name)]):
                    prices["home"] = price
                elif team_names_match(team_b, [str(name)]):
                    prices["away"] = price
                elif str(name).casefold() == "draw":
                    prices["draw"] = price
            if {"home", "draw", "away"} <= prices.keys():
                return prices
    return None


def _extract_balanced_total_line(bookmaker: dict[str, Any]) -> dict[str, float] | None:
    best_line: dict[str, float] | None = None
    best_balance: float | None = None

    for market in bookmaker.get("markets", []):
        if market.get("key") != "totals":
            continue

        prices_by_point: dict[float, dict[str, float]] = {}
        for outcome in market.get("outcomes", []):
            name = str(outcome.get("name", "")).casefold()
            point = outcome.get("point")
            price = outcome.get("price")
            if name not in {"over", "under"} or point is None or price is None:
                continue
            if float(price) <= 1:
                continue
            prices_by_point.setdefault(float(point), {})[name] = float(price)

        for point, prices in prices_by_point.items():
            if not {"over", "under"} <= prices.keys():
                continue
            implied_over = 1 / prices["over"]
            implied_under = 1 / prices["under"]
            overround = implied_over + implied_under
            if overround <= 0:
                continue
            p_over = implied_over / overround
            balance = abs(p_over - 0.5)
            if best_balance is None or balance < best_balance:
                best_balance = balance
                best_line = {
                    "point": point,
                    "over_price": prices["over"],
                    "under_price": prices["under"],
                    "p_over": p_over,
                }

    return best_line


def _extract_total_goals_market(event: dict[str, Any]) -> dict[str, Any] | None:
    lines: list[dict[str, Any]] = []
    for bookmaker in event.get("bookmakers", []):
        line = _extract_balanced_total_line(bookmaker)
        if line is None:
            continue
        lines.append(
            {
                "bookmaker": bookmaker.get("key") or bookmaker.get("title"),
                **line,
            }
        )

    if not lines:
        return None

    total_goals = sum(line["point"] for line in lines) / len(lines)
    return {
        "total_goals": total_goals,
        "bookmaker_count": len(lines),
        "lines": lines,
    }


def _extract_balanced_spread_line(
    bookmaker: dict[str, Any], team_a: str, team_b: str
) -> dict[str, float] | None:
    best_line: dict[str, float] | None = None
    best_balance: float | None = None

    for market in bookmaker.get("markets", []):
        if market.get("key") != "spreads":
            continue

        team_a_outcomes: list[dict[str, float]] = []
        team_b_outcomes: list[dict[str, float]] = []
        for outcome in market.get("outcomes", []):
            name = outcome.get("name")
            point = outcome.get("point")
            price = outcome.get("price")
            if name is None or point is None or price is None:
                continue
            if float(price) <= 1:
                continue

            item = {"point": float(point), "price": float(price)}
            if team_names_match(team_a, [str(name)]):
                team_a_outcomes.append(item)
            elif team_names_match(team_b, [str(name)]):
                team_b_outcomes.append(item)

        for team_a_outcome in team_a_outcomes:
            for team_b_outcome in team_b_outcomes:
                if team_a_outcome["point"] != -team_b_outcome["point"]:
                    continue

                implied_team_a = 1 / team_a_outcome["price"]
                implied_team_b = 1 / team_b_outcome["price"]
                overround = implied_team_a + implied_team_b
                if overround <= 0:
                    continue

                p_team_a_covers = implied_team_a / overround
                balance = abs(p_team_a_covers - 0.5)
                if best_balance is None or balance < best_balance:
                    best_balance = balance
                    best_line = {
                        "expected_goal_difference": -team_a_outcome["point"],
                        "team_a_point": team_a_outcome["point"],
                        "team_b_point": team_b_outcome["point"],
                        "team_a_price": team_a_outcome["price"],
                        "team_b_price": team_b_outcome["price"],
                        "p_team_a_covers": p_team_a_covers,
                    }

    return best_line


def _extract_spread_market(
    event: dict[str, Any], team_a: str, team_b: str
) -> dict[str, Any] | None:
    lines: list[dict[str, Any]] = []
    for bookmaker in event.get("bookmakers", []):
        line = _extract_balanced_spread_line(bookmaker, team_a, team_b)
        if line is None:
            continue
        lines.append(
            {
                "bookmaker": bookmaker.get("key") or bookmaker.get("title"),
                **line,
            }
        )

    if not lines:
        return None

    expected_goal_difference = sum(
        line["expected_goal_difference"] for line in lines
    ) / len(lines)
    return {
        "expected_goal_difference": expected_goal_difference,
        "bookmaker_count": len(lines),
        "lines": lines,
    }


def _event_matches(event: dict[str, Any], team_a: str, team_b: str) -> bool:
    teams = [
        str(team)
        for team in (event.get("home_team"), event.get("away_team"))
        if team
    ]
    return team_names_match(team_a, teams) and team_names_match(team_b, teams)


def fetch_odds_from_the_odds_api(
    team_a: str,
    team_b: str,
    sport_key: str = "soccer_fifa_world_cup",
    regions: str = "eu",
    api_key: str | None = None,
    refresh: bool = False,
    cache_ttl: timedelta | None = None,
    cache_dir: str | Path | None = None,
    no_cache: bool = False,
) -> dict[str, Any]:
    cache_key = (
        f"the_odds_api:{sport_key}:{regions}:h2h_spreads_totals:{team_a}:{team_b}"
    )

    if not refresh:
        cached = load_from_cache(
            cache_key,
            max_age=cache_ttl if cache_ttl is not None else CACHE_TTL,
            cache_dir=cache_dir,
            no_cache=no_cache,
        )
        if cached is not None:
            return cached

    settings = load_settings()
    resolved_key = require_api_key(
        "THE_ODDS_API_KEY", api_key or settings.the_odds_api_key
    )

    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    response = requests.get(
        url,
        params={
            "apiKey": resolved_key,
            "regions": regions,
            "markets": "h2h,spreads,totals",
            "oddsFormat": "decimal",
        },
        timeout=20,
    )
    response.raise_for_status()
    events = response.json()
    for event in events:
        if not _event_matches(event, team_a, team_b):
            continue
        prices = _extract_h2h_prices(event, team_a, team_b)
        if prices is None:
            continue
        data = {
            "source": "The Odds API",
            "team_a": team_a,
            "team_b": team_b,
            "odds": prices,
            "probabilities": normalize_bookmaker_odds_to_probabilities(prices),
            "raw_event": event,
        }
        total_goals_market = _extract_total_goals_market(event)
        if total_goals_market is not None:
            data["expected_total_goals"] = total_goals_market["total_goals"]
            data["total_goals_market"] = total_goals_market
        spread_market = _extract_spread_market(event, team_a, team_b)
        if spread_market is not None:
            data["expected_goal_difference"] = spread_market[
                "expected_goal_difference"
            ]
            data["spread_market"] = spread_market
        save_to_cache(cache_key, data, cache_dir=cache_dir, no_cache=no_cache)
        return data

    raise DataSourceUnavailable(
        f"No 1X2 odds found for {team_a} vs {team_b}. "
        "Use --p-a --p-draw --p-b."
    )


class TheOddsApiProvider:
    name = "odds_api"
    label = "The Odds API"

    def fetch(self, context: ProviderContext) -> ProbabilityResult:
        data = fetch_odds_from_the_odds_api(
            context.team_a,
            context.team_b,
            sport_key=context.odds_sport_key,
            regions=context.odds_regions,
            refresh=context.refresh,
            cache_ttl=context.cache_ttl,
            cache_dir=context.cache_dir,
            no_cache=context.no_cache,
        )
        probabilities = data["probabilities"]
        total_goals = data.get("expected_total_goals")
        total_source = None
        if total_goals is not None:
            total_market = data.get("total_goals_market") or {}
            bookmaker_count = total_market.get("bookmaker_count", 0)
            total_source = (
                f"The Odds API totals ({float(total_goals):.2f}; "
                f"{bookmaker_count} bookmakers)"
            )
        expected_goal_difference = data.get("expected_goal_difference")
        goal_difference_source = None
        if expected_goal_difference is not None:
            spread_market = data.get("spread_market") or {}
            bookmaker_count = spread_market.get("bookmaker_count", 0)
            goal_difference_source = (
                f"The Odds API spreads ({float(expected_goal_difference):+.2f}; "
                f"{bookmaker_count} bookmakers)"
            )
        return ProbabilityResult(
            p_a=probabilities["p_a"],
            p_draw=probabilities["p_draw"],
            p_b=probabilities["p_b"],
            source=data.get("source", self.label),
            expected_total_goals=(
                float(total_goals) if total_goals is not None else None
            ),
            total_goals_source=total_source,
            expected_goal_difference=(
                float(expected_goal_difference)
                if expected_goal_difference is not None
                else None
            ),
            goal_difference_source=goal_difference_source,
            raw=data,
        )
