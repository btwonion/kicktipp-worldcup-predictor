from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import requests

from config import load_settings, require_api_key

from . import cache as _cache
from . import elo as _elo
from . import fixtures as _fixtures
from .providers import (
    DEFAULT_PROVIDERS,
    ApiFootballProvider,
    FootballDataProvider,
    ProbabilityProvider,
    ProviderContext,
    TheOddsApiProvider,
    normalize_bookmaker_odds_to_probabilities,
)
from .providers import api_football as _api_football
from .providers import football_data as _football_data
from .providers import the_odds_api as _the_odds_api
from .team_matching import (
    TEAM_ALIASES,
    normalize_team_name,
    team_dict_matches,
    team_names_match,
)


CACHE_DIR = _cache.CACHE_DIR
CACHE_TTL = _cache.CACHE_TTL
DataSourceUnavailable = _elo.DataSourceUnavailable
default_elo_ratings_url = _elo.default_elo_ratings_url


def _sync_compat_globals() -> None:
    _cache.CACHE_DIR = Path(CACHE_DIR)
    _cache.CACHE_TTL = CACHE_TTL
    _elo.requests = requests
    _fixtures.requests = requests
    _the_odds_api.requests = requests
    _football_data.requests = requests
    _api_football.requests = requests


def configure_cache(
    cache_dir: str | Path | None = None,
    cache_ttl: timedelta | None = None,
) -> None:
    global CACHE_DIR, CACHE_TTL
    if cache_dir is not None:
        CACHE_DIR = Path(cache_dir)
    if cache_ttl is not None:
        CACHE_TTL = cache_ttl
    _cache.configure_cache(CACHE_DIR, CACHE_TTL)


def _cache_path(key: str) -> Path:
    _sync_compat_globals()
    return _cache._cache_path(key, cache_dir=CACHE_DIR)


def load_from_cache(
    key: str,
    max_age: timedelta | None = None,
) -> dict[str, Any] | None:
    _sync_compat_globals()
    return _cache.load_from_cache(key, max_age=max_age, cache_dir=CACHE_DIR)


def save_to_cache(key: str, data: dict[str, Any]) -> None:
    _sync_compat_globals()
    _cache.save_to_cache(key, data, cache_dir=CACHE_DIR)


def fetch_remote_elo_ratings(
    source_url: str | None = None,
    refresh: bool = False,
    cache_ttl: timedelta | None = None,
    cache_dir: str | Path | None = None,
    no_cache: bool = False,
) -> dict[str, float]:
    _sync_compat_globals()
    return _elo.fetch_remote_elo_ratings(
        source_url,
        refresh=refresh,
        cache_ttl=cache_ttl if cache_ttl is not None else CACHE_TTL,
        cache_dir=cache_dir if cache_dir is not None else CACHE_DIR,
        no_cache=no_cache,
    )


def load_elo_ratings(
    path_or_url: str,
    refresh: bool = False,
    cache_ttl: timedelta | None = None,
    cache_dir: str | Path | None = None,
    no_cache: bool = False,
) -> dict[str, float]:
    _sync_compat_globals()
    return _elo.load_elo_ratings(
        path_or_url,
        refresh=refresh,
        cache_ttl=cache_ttl if cache_ttl is not None else CACHE_TTL,
        cache_dir=cache_dir if cache_dir is not None else CACHE_DIR,
        no_cache=no_cache,
    )


def load_fixtures_from_openfootball(path_or_url: str) -> list[dict[str, Any]]:
    _sync_compat_globals()
    return _fixtures.load_fixtures_from_openfootball(path_or_url)


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
    _sync_compat_globals()
    resolved_cache_ttl = cache_ttl if cache_ttl is not None else CACHE_TTL
    resolved_cache_dir = cache_dir if cache_dir is not None else CACHE_DIR
    cache_key = f"the_odds_api:{sport_key}:{regions}:h2h_totals:{team_a}:{team_b}"
    if not refresh:
        cached = _cache.load_from_cache(
            cache_key,
            max_age=resolved_cache_ttl,
            cache_dir=resolved_cache_dir,
            no_cache=no_cache,
        )
        if cached is not None:
            return cached
    resolved_key = require_api_key(
        "THE_ODDS_API_KEY", api_key or load_settings().the_odds_api_key
    )
    return _the_odds_api.fetch_odds_from_the_odds_api(
        team_a,
        team_b,
        sport_key=sport_key,
        regions=regions,
        api_key=resolved_key,
        refresh=True,
        cache_ttl=resolved_cache_ttl,
        cache_dir=resolved_cache_dir,
        no_cache=no_cache,
    )


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
    _sync_compat_globals()
    resolved_cache_ttl = cache_ttl if cache_ttl is not None else CACHE_TTL
    resolved_cache_dir = cache_dir if cache_dir is not None else CACHE_DIR
    cache_key = f"football_data:{match_id or match_date or 'today'}:{team_a}:{team_b}"
    if not refresh:
        cached = _cache.load_from_cache(
            cache_key,
            max_age=resolved_cache_ttl,
            cache_dir=resolved_cache_dir,
            no_cache=no_cache,
        )
        if cached is not None:
            return cached
    resolved_key = require_api_key(
        "FOOTBALL_DATA_API_KEY", api_key or load_settings().football_data_api_key
    )
    return _football_data.fetch_odds_from_football_data(
        team_a,
        team_b,
        match_id=match_id,
        match_date=match_date,
        api_key=resolved_key,
        refresh=True,
        cache_ttl=resolved_cache_ttl,
        cache_dir=resolved_cache_dir,
        no_cache=no_cache,
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
    _sync_compat_globals()
    resolved_cache_ttl = cache_ttl if cache_ttl is not None else CACHE_TTL
    resolved_cache_dir = cache_dir if cache_dir is not None else CACHE_DIR
    cache_key = f"api_football:{fixture_id or match_date}:{team_a}:{team_b}"
    if not refresh:
        cached = _cache.load_from_cache(
            cache_key,
            max_age=resolved_cache_ttl,
            cache_dir=resolved_cache_dir,
            no_cache=no_cache,
        )
        if cached is not None:
            return cached
    resolved_key = require_api_key(
        "API_FOOTBALL_KEY", api_key or load_settings().api_football_key
    )
    return _api_football.fetch_predictions_from_api_football(
        team_a,
        team_b,
        fixture_id=fixture_id,
        match_date=match_date,
        api_key=resolved_key,
        refresh=True,
        cache_ttl=resolved_cache_ttl,
        cache_dir=resolved_cache_dir,
        no_cache=no_cache,
    )


__all__ = [
    "ApiFootballProvider",
    "CACHE_DIR",
    "CACHE_TTL",
    "DEFAULT_PROVIDERS",
    "DataSourceUnavailable",
    "FootballDataProvider",
    "ProbabilityProvider",
    "ProviderContext",
    "TEAM_ALIASES",
    "TheOddsApiProvider",
    "_cache_path",
    "configure_cache",
    "default_elo_ratings_url",
    "fetch_odds_from_football_data",
    "fetch_odds_from_the_odds_api",
    "fetch_predictions_from_api_football",
    "fetch_remote_elo_ratings",
    "load_elo_ratings",
    "load_fixtures_from_openfootball",
    "load_from_cache",
    "load_settings",
    "normalize_bookmaker_odds_to_probabilities",
    "normalize_team_name",
    "requests",
    "save_to_cache",
    "team_dict_matches",
    "team_names_match",
]
