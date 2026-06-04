from __future__ import annotations

import csv
import re
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode

import requests

from .cache import CACHE_TTL, load_from_cache, save_to_cache

ELO_RATINGS_BASE_URL = "https://www.international-football.net/elo-ratings-table"


class DataSourceUnavailable(RuntimeError):
    pass


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
    source_url: str | None = None,
    refresh: bool = False,
    cache_ttl: timedelta | None = None,
    cache_dir: str | Path | None = None,
    no_cache: bool = False,
) -> dict[str, float]:
    source_url = source_url or default_elo_ratings_url()
    cache_key = f"elo_ratings:{source_url}"

    if not refresh:
        cached = load_from_cache(
            cache_key,
            max_age=cache_ttl if cache_ttl is not None else CACHE_TTL,
            cache_dir=cache_dir,
            no_cache=no_cache,
        )
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

    save_to_cache(
        cache_key,
        {"source": source_url, "ratings": ratings},
        cache_dir=cache_dir,
        no_cache=no_cache,
    )
    return ratings


def load_elo_ratings(
    path_or_url: str,
    refresh: bool = False,
    cache_ttl: timedelta | None = None,
    cache_dir: str | Path | None = None,
    no_cache: bool = False,
) -> dict[str, float]:
    if path_or_url.startswith(("http://", "https://")):
        return fetch_remote_elo_ratings(
            path_or_url,
            refresh=refresh,
            cache_ttl=cache_ttl,
            cache_dir=cache_dir,
            no_cache=no_cache,
        )

    rating_path = Path(path_or_url)
    if not rating_path.exists():
        return {}

    return _load_elo_ratings_from_csv_text(rating_path.read_text(encoding="utf-8"))
