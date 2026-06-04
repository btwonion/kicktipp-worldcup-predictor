from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import requests

from config import load_settings, require_api_key
from models import ProbabilityResult

from ..cache import CACHE_TTL, load_from_cache, save_to_cache
from ..elo import DataSourceUnavailable
from ..team_matching import team_dict_matches
from .base import ProviderContext
from .the_odds_api import normalize_bookmaker_odds_to_probabilities


def _football_data_matches_from_payload(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    if isinstance(payload.get("matches"), list):
        return payload["matches"]
    if isinstance(payload.get("match"), dict):
        return [payload["match"]]
    if payload.get("id") and payload.get("homeTeam") and payload.get("awayTeam"):
        return [payload]
    return []


def _extract_football_data_prices(
    match: dict[str, Any], team_a: str, team_b: str
) -> dict[str, float] | None:
    odds = match.get("odds") or {}
    home_price = odds.get("homeWin") or odds.get("home")
    draw_price = odds.get("draw")
    away_price = odds.get("awayWin") or odds.get("away")
    if home_price is None or draw_price is None or away_price is None:
        return None

    home_team = match.get("homeTeam") or {}
    away_team = match.get("awayTeam") or {}
    if team_dict_matches(home_team, team_a) and team_dict_matches(away_team, team_b):
        return {"home": home_price, "draw": draw_price, "away": away_price}
    if team_dict_matches(home_team, team_b) and team_dict_matches(away_team, team_a):
        return {"home": away_price, "draw": draw_price, "away": home_price}
    return None


def fetch_odds_from_football_data(
    team_a: str,
    team_b: str,
    match_id: int | None = None,
    match_date: str | None = None,
    api_key: str | None = None,
    refresh: bool = False,
    cache_ttl: timedelta | None = None,
    cache_dir: str | Path | None = None,
    no_cache: bool = False,
) -> dict[str, Any]:
    cache_key = f"football_data:{match_id or match_date or 'today'}:{team_a}:{team_b}"

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
        "FOOTBALL_DATA_API_KEY", api_key or settings.football_data_api_key
    )

    if match_id is not None:
        url = f"https://api.football-data.org/v4/matches/{match_id}"
        params: dict[str, Any] = {}
    else:
        url = "https://api.football-data.org/v4/matches"
        params = {"date": match_date} if match_date else {}

    response = requests.get(
        url,
        params=params,
        headers={"X-Auth-Token": resolved_key},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()

    for match in _football_data_matches_from_payload(payload):
        prices = _extract_football_data_prices(match, team_a, team_b)
        if prices is None:
            continue
        data = {
            "source": "football-data.org",
            "team_a": team_a,
            "team_b": team_b,
            "odds": prices,
            "probabilities": normalize_bookmaker_odds_to_probabilities(prices),
            "raw_match": match,
        }
        save_to_cache(cache_key, data, cache_dir=cache_dir, no_cache=no_cache)
        return data

    raise DataSourceUnavailable(
        f"No football-data.org 1X2 odds found for {team_a} vs {team_b}."
    )


class FootballDataProvider:
    name = "football_data"
    label = "football-data.org"

    def fetch(self, context: ProviderContext) -> ProbabilityResult:
        data = fetch_odds_from_football_data(
            context.team_a,
            context.team_b,
            match_id=context.football_data_match_id,
            match_date=context.match_date,
            refresh=context.refresh,
            cache_ttl=context.cache_ttl,
            cache_dir=context.cache_dir,
            no_cache=context.no_cache,
        )
        probabilities = data["probabilities"]
        return ProbabilityResult(
            p_a=probabilities["p_a"],
            p_draw=probabilities["p_draw"],
            p_b=probabilities["p_b"],
            source=data.get("source", self.label),
            raw=data,
        )
