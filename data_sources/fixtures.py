from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

from .cache import load_from_cache, save_to_cache

DEFAULT_WORLD_CUP_FIXTURES_URL = (
    "https://raw.githubusercontent.com/openfootball/worldcup.json/master/"
    "2026/worldcup.json"
)


def _load_json_from_path_or_url(path_or_url: str) -> Any:
    if path_or_url.startswith(("http://", "https://")):
        response = requests.get(path_or_url, timeout=20)
        response.raise_for_status()
        return response.json()

    with Path(path_or_url).open("r", encoding="utf-8") as file:
        return json.load(file)


def _load_json_from_path_or_cached_url(
    path_or_url: str,
    *,
    refresh: bool = False,
    cache_dir: str | Path | None = None,
    no_cache: bool = False,
) -> Any:
    if not path_or_url.startswith(("http://", "https://")):
        return _load_json_from_path_or_url(path_or_url)

    cache_key = f"fixtures:{path_or_url}"
    if not refresh:
        cached = load_from_cache(
            cache_key,
            max_age=None,
            cache_dir=cache_dir,
            no_cache=no_cache,
        )
        if cached is not None:
            return cached["payload"]

    payload = _load_json_from_path_or_url(path_or_url)
    save_to_cache(
        cache_key,
        {"payload": payload},
        cache_dir=cache_dir,
        no_cache=no_cache,
    )
    return payload


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


def load_fixtures_from_openfootball(path_or_url: str) -> list[dict[str, Any]]:
    payload = _load_json_from_path_or_url(path_or_url)
    return _fixtures_from_openfootball_payload(payload)


def load_cached_fixtures_from_openfootball(
    path_or_url: str = DEFAULT_WORLD_CUP_FIXTURES_URL,
    *,
    refresh: bool = False,
    cache_dir: str | Path | None = None,
    no_cache: bool = False,
) -> list[dict[str, Any]]:
    payload = _load_json_from_path_or_cached_url(
        path_or_url,
        refresh=refresh,
        cache_dir=cache_dir,
        no_cache=no_cache,
    )
    return _fixtures_from_openfootball_payload(payload)


def _fixtures_from_openfootball_payload(payload: Any) -> list[dict[str, Any]]:
    fixtures: list[dict[str, Any]] = []

    if isinstance(payload, dict) and "rounds" in payload:
        rounds = payload["rounds"]
    elif isinstance(payload, dict) and "matches" in payload:
        rounds = [{"name": None, "matches": payload["matches"]}]
    elif isinstance(payload, list):
        rounds = [{"name": None, "matches": payload}]
    else:
        raise ValueError("Unsupported fixture JSON format.")

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
            fixture = {
                "team_a": team_a,
                "team_b": team_b,
                "date": match.get("date"),
                "stage": (
                    round_item.get("name") or match.get("stage") or match.get("round")
                ),
                "raw": match,
            }
            group = match.get("group") or round_item.get("group")
            if group:
                fixture["group"] = group
            time = match.get("time") or match.get("kickoff")
            if time:
                fixture["time"] = time
            fixtures.append(fixture)

    return fixtures
