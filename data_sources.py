from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

from config import load_settings, require_api_key


CACHE_DIR = Path("cache")
API_FOOTBALL_BASE_URL = "https://v3.football.api-sports.io"
ELO_RATINGS_BASE_URL = "https://www.international-football.net/elo-ratings-table"


class DataSourceUnavailable(RuntimeError):
    pass


def _cache_path(key: str) -> Path:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    safe_key = "".join(char if char.isalnum() or char in "-_" else "_" for char in key)
    return CACHE_DIR / f"{safe_key[:80]}_{digest}.json"


def load_from_cache(key: str) -> dict | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_to_cache(key: str, data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with _cache_path(key).open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2, sort_keys=True)


def _load_json_from_path_or_url(path_or_url: str) -> Any:
    if path_or_url.startswith(("http://", "https://")):
        response = requests.get(path_or_url, timeout=20)
        response.raise_for_status()
        return response.json()

    with Path(path_or_url).open("r", encoding="utf-8") as file:
        return json.load(file)


def default_elo_ratings_url(rating_date: date | None = None) -> str:
    rating_date = rating_date or date.today()
    query = urlencode(
        {
            "day": rating_date.day,
            "month": f"{rating_date.month:02d}",
            "year": rating_date.year,
        }
    )
    return f"{ELO_RATINGS_BASE_URL}?{query}"


def _team_name(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("name", "team", "country", "code"):
            if value.get(key):
                return str(value[key])
    return str(value)


def _normalize_name(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def _team_matches(team: dict[str, Any] | None, expected_name: str) -> bool:
    if not team:
        return False
    candidates = (
        team.get("name"),
        team.get("shortName"),
        team.get("tla"),
        team.get("code"),
        team.get("country"),
    )
    expected = _normalize_name(expected_name)
    return any(
        _normalize_name(str(candidate)) == expected
        for candidate in candidates
        if candidate
    )


def load_fixtures_from_openfootball(path_or_url: str) -> list[dict]:
    payload = _load_json_from_path_or_url(path_or_url)
    fixtures: list[dict] = []

    if isinstance(payload, dict) and "rounds" in payload:
        rounds = payload["rounds"]
    elif isinstance(payload, list):
        rounds = [{"name": None, "matches": payload}]
    else:
        raise ValueError("Nicht unterstütztes Fixture-JSON-Format.")

    for round_item in rounds:
        for match in round_item.get("matches", []):
            team_a = _team_name(
                match.get("team1")
                or match.get("home_team")
                or match.get("team_a")
                or match.get("home")
            )
            team_b = _team_name(
                match.get("team2")
                or match.get("away_team")
                or match.get("team_b")
                or match.get("away")
            )
            if not team_a or not team_b:
                continue
            fixtures.append(
                {
                    "team_a": team_a,
                    "team_b": team_b,
                    "date": match.get("date"),
                    "stage": round_item.get("name") or match.get("stage"),
                    "raw": match,
                }
            )

    return fixtures


def _load_elo_ratings_from_csv_text(text: str) -> dict[str, float]:
    def row_value(row: dict[str, str], *keys: str) -> str | None:
        normalized = {key.casefold(): value for key, value in row.items()}
        for key in keys:
            value = normalized.get(key)
            if value:
                return value
        return None

    ratings: dict[str, float] = {}
    reader = csv.DictReader(text.splitlines())
    for row in reader:
        team = row_value(row, "team", "name", "club", "country")
        elo = row_value(row, "elo", "rating", "value")
        if not team or not elo:
            continue
        ratings[team.strip()] = float(elo)
    return ratings


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.fragments: list[str] = []

    def handle_data(self, data: str) -> None:
        stripped = " ".join(data.split())
        if stripped:
            self.fragments.append(stripped)


def _text_fragments_from_html(html: str) -> list[str]:
    parser = _HTMLTextExtractor()
    parser.feed(html)
    return parser.fragments


def _parse_elo_rating_entry(value: str) -> tuple[str, float] | None:
    value = re.sub(r"\bImage:\s*", "", value).strip()
    match = re.match(
        r"^(?:\d+\.\s*)?(?P<team>.+?)\s+(?P<rating>\d{3,4}(?:\.\d+)?)$",
        value,
    )
    if not match:
        return None

    team = " ".join(match.group("team").split())
    if not team or team.casefold() in {"select year", "select month", "select day"}:
        return None
    return team, float(match.group("rating"))


def _is_rating_value(value: str) -> bool:
    return re.match(r"^\d{3,4}(?:\.\d+)?$", value) is not None


def _load_elo_ratings_from_html_text(html: str) -> dict[str, float]:
    fragments = _text_fragments_from_html(html)
    ratings: dict[str, float] = {}
    index = 0
    while index < len(fragments):
        fragment = fragments[index]

        if (
            fragment.isdigit()
            and index + 3 < len(fragments)
            and fragments[index + 1] == "."
            and _is_rating_value(fragments[index + 3])
        ):
            ratings[" ".join(fragments[index + 2].split())] = float(
                fragments[index + 3]
            )
            index += 4
            continue

        combined = fragment
        rank_match = re.match(r"^\d+\.$", fragment)
        if rank_match and index + 1 < len(fragments):
            combined = f"{fragment} {fragments[index + 1]}"
            index += 1

        parsed = None
        if re.match(r"^\d+\.?\s+", combined):
            parsed = _parse_elo_rating_entry(combined)
        if parsed is not None:
            team, rating = parsed
            ratings[team] = rating
        index += 1

    return ratings


def _load_elo_ratings_from_text(text: str, content_type: str = "") -> dict[str, float]:
    if "csv" in content_type or text.lstrip().casefold().startswith(
        ("team,", "country,", "name,")
    ):
        return _load_elo_ratings_from_csv_text(text)
    return _load_elo_ratings_from_html_text(text)


def fetch_remote_elo_ratings(
    source_url: str | None = None, refresh: bool = False
) -> dict[str, float]:
    source_url = source_url or default_elo_ratings_url()
    cache_key = f"elo_ratings:{source_url}"

    if not refresh:
        cached = load_from_cache(cache_key)
        if cached is not None:
            ratings = cached.get("ratings")
            if isinstance(ratings, dict):
                return {str(team): float(rating) for team, rating in ratings.items()}

    response = requests.get(source_url, timeout=20)
    response.raise_for_status()
    ratings = _load_elo_ratings_from_text(
        response.text, response.headers.get("content-type", "")
    )
    if not ratings:
        raise DataSourceUnavailable(f"Keine Elo-Ratings in {source_url} gefunden.")

    save_to_cache(cache_key, {"source": source_url, "ratings": ratings})
    return ratings


def load_elo_ratings(path_or_url: str, refresh: bool = False) -> dict[str, float]:
    if path_or_url.startswith(("http://", "https://")):
        return fetch_remote_elo_ratings(path_or_url, refresh=refresh)

    rating_path = Path(path_or_url)
    if not rating_path.exists():
        return {}

    return _load_elo_ratings_from_csv_text(
        rating_path.read_text(encoding="utf-8")
    )


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

    if any(value is None for value in raw.values()):
        raise ValueError("Odds müssen home/draw/away enthalten.")
    if any(float(value) <= 1 for value in raw.values()):
        raise ValueError("Dezimalquoten müssen > 1 sein.")

    implied = {key: 1 / float(value) for key, value in raw.items()}
    overround = sum(implied.values())
    if overround <= 0:
        raise ValueError("Ungültige Quoten.")

    return {
        "p_a": implied["home"] / overround,
        "p_draw": implied["draw"] / overround,
        "p_b": implied["away"] / overround,
        "bookmaker_margin": overround - 1,
    }


def _probabilities_from_percentages(
    home: Any, draw: Any, away: Any, reverse: bool = False
) -> dict[str, float]:
    def parse(value: Any) -> float:
        if value is None:
            raise ValueError("Prozentwert fehlt.")
        if isinstance(value, str):
            value = value.strip().removesuffix("%")
        parsed = float(value)
        if parsed > 1:
            parsed /= 100
        return parsed

    parsed_home = parse(home)
    parsed_draw = parse(draw)
    parsed_away = parse(away)
    total = parsed_home + parsed_draw + parsed_away
    if total <= 0:
        raise ValueError(
            "API-Football-Prognose hat keine positive Gesamtwahrscheinlichkeit."
        )

    if reverse:
        parsed_home, parsed_away = parsed_away, parsed_home

    return {
        "p_a": parsed_home / total,
        "p_draw": parsed_draw / total,
        "p_b": parsed_away / total,
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
                if name == team_a:
                    prices["home"] = price
                elif name == team_b:
                    prices["away"] = price
                elif str(name).lower() == "draw":
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


def fetch_odds_from_the_odds_api(
    team_a: str,
    team_b: str,
    sport_key: str = "soccer_fifa_world_cup",
    regions: str = "eu",
    api_key: str | None = None,
    refresh: bool = False,
) -> dict:
    cache_key = f"the_odds_api:{sport_key}:{regions}:h2h_totals:{team_a}:{team_b}"

    if not refresh:
        cached = load_from_cache(cache_key)
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
            "markets": "h2h,totals",
            "oddsFormat": "decimal",
        },
        timeout=20,
    )
    response.raise_for_status()
    events = response.json()
    for event in events:
        teams = {event.get("home_team"), event.get("away_team")}
        if {team_a, team_b} <= teams:
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
            save_to_cache(cache_key, data)
            return data

    raise DataSourceUnavailable(
        f"Keine 1X2-Quoten für {team_a} vs {team_b} gefunden. Nutze --p-a --p-draw --p-b."
    )


def _football_data_matches_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
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
    if _team_matches(home_team, team_a) and _team_matches(away_team, team_b):
        return {"home": home_price, "draw": draw_price, "away": away_price}
    if _team_matches(home_team, team_b) and _team_matches(away_team, team_a):
        return {"home": away_price, "draw": draw_price, "away": home_price}
    return None


def fetch_odds_from_football_data(
    team_a: str,
    team_b: str,
    match_id: int | None = None,
    match_date: str | None = None,
    api_key: str | None = None,
    refresh: bool = False,
) -> dict:
    cache_key = f"football_data:{match_id or match_date or 'today'}:{team_a}:{team_b}"

    if not refresh:
        cached = load_from_cache(cache_key)
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
        save_to_cache(cache_key, data)
        return data

    raise DataSourceUnavailable(
        f"Keine football-data.org-1X2-Quoten für {team_a} vs {team_b} gefunden."
    )


def _api_football_response_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("response")
    if isinstance(items, list):
        return items
    return []


def _api_football_fixture_orientation(
    fixture: dict[str, Any], team_a: str, team_b: str
) -> bool | None:
    teams = fixture.get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}
    if _team_matches(home, team_a) and _team_matches(away, team_b):
        return False
    if _team_matches(home, team_b) and _team_matches(away, team_a):
        return True
    return None


def _find_api_football_fixture(
    team_a: str,
    team_b: str,
    match_date: str,
    api_key: str,
) -> tuple[int, bool, dict[str, Any]]:
    response = requests.get(
        f"{API_FOOTBALL_BASE_URL}/fixtures",
        params={"date": match_date},
        headers={"x-apisports-key": api_key},
        timeout=20,
    )
    response.raise_for_status()

    for fixture in _api_football_response_items(response.json()):
        reverse = _api_football_fixture_orientation(fixture, team_a, team_b)
        if reverse is None:
            continue
        fixture_id = (fixture.get("fixture") or {}).get("id")
        if fixture_id is not None:
            return int(fixture_id), reverse, fixture

    raise DataSourceUnavailable(
        f"Kein API-Football-Fixture für {team_a} vs {team_b} am {match_date} gefunden."
    )


def fetch_predictions_from_api_football(
    team_a: str,
    team_b: str,
    fixture_id: int | None = None,
    match_date: str | None = None,
    api_key: str | None = None,
    refresh: bool = False,
) -> dict:
    if fixture_id is None and not match_date:
        raise ValueError(
            "API-Football benötigt --api-football-fixture-id oder --match-date."
        )

    cache_key = f"api_football:{fixture_id or match_date}:{team_a}:{team_b}"

    if not refresh:
        cached = load_from_cache(cache_key)
        if cached is not None:
            return cached

    settings = load_settings()
    resolved_key = require_api_key(
        "API_FOOTBALL_KEY", api_key or settings.api_football_key
    )

    raw_fixture = None
    reverse = False
    resolved_fixture_id = fixture_id
    if resolved_fixture_id is None:
        resolved_fixture_id, reverse, raw_fixture = _find_api_football_fixture(
            team_a, team_b, match_date or "", resolved_key
        )

    response = requests.get(
        f"{API_FOOTBALL_BASE_URL}/predictions",
        params={"fixture": resolved_fixture_id},
        headers={"x-apisports-key": resolved_key},
        timeout=20,
    )
    response.raise_for_status()
    predictions = _api_football_response_items(response.json())
    if not predictions:
        raise DataSourceUnavailable(
            f"Keine API-Football-Prognose für Fixture {resolved_fixture_id} gefunden."
        )

    prediction = predictions[0]
    if raw_fixture is None:
        reverse = _api_football_fixture_orientation(prediction, team_a, team_b) or False

    percentages = ((prediction.get("predictions") or {}).get("percent") or {})
    probabilities = _probabilities_from_percentages(
        percentages.get("home"),
        percentages.get("draw"),
        percentages.get("away"),
        reverse=reverse,
    )
    data = {
        "source": "API-Football predictions",
        "team_a": team_a,
        "team_b": team_b,
        "fixture_id": resolved_fixture_id,
        "probabilities": probabilities,
        "raw_fixture": raw_fixture,
        "raw_prediction": prediction,
    }
    save_to_cache(cache_key, data)
    return data
