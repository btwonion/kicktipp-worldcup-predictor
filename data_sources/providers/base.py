from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Protocol

from models import ProbabilityResult


@dataclass(frozen=True)
class ProviderContext:
    team_a: str
    team_b: str
    refresh: bool = False
    cache_dir: str | Path | None = None
    no_cache: bool = False
    cache_ttl: timedelta | None = None
    match_date: str | None = None
    football_data_match_id: int | None = None
    api_football_fixture_id: int | None = None
    odds_sport_key: str = "soccer_fifa_world_cup"
    odds_regions: str = "eu"


class ProbabilityProvider(Protocol):
    name: str
    label: str

    def fetch(self, context: ProviderContext) -> ProbabilityResult:
        ...
