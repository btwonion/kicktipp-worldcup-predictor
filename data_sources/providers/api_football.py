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

API_FOOTBALL_BASE_URL = "https://v3.football.api-sports.io"


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
    if team_dict_matches(home, team_a) and team_dict_matches(away, team_b):
        return False
    if team_dict_matches(home, team_b) and team_dict_matches(away, team_a):
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
    cache_ttl: timedelta | None = None,
    cache_dir: str | Path | None = None,
    no_cache: bool = False,
) -> dict[str, Any]:
    if fixture_id is None and not match_date:
        raise ValueError(
            "API-Football benötigt --api-football-fixture-id oder --match-date."
        )

    cache_key = f"api_football:{fixture_id or match_date}:{team_a}:{team_b}"

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
    save_to_cache(cache_key, data, cache_dir=cache_dir, no_cache=no_cache)
    return data


class ApiFootballProvider:
    name = "api_football"
    label = "API-Football predictions"

    def fetch(self, context: ProviderContext) -> ProbabilityResult:
        data = fetch_predictions_from_api_football(
            context.team_a,
            context.team_b,
            fixture_id=context.api_football_fixture_id,
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
