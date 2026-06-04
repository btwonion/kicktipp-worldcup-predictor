from __future__ import annotations

from .api_football import ApiFootballProvider, fetch_predictions_from_api_football
from .base import ProbabilityProvider, ProviderContext
from .football_data import FootballDataProvider, fetch_odds_from_football_data
from .the_odds_api import (
    TheOddsApiProvider,
    fetch_odds_from_the_odds_api,
    normalize_bookmaker_odds_to_probabilities,
)

DEFAULT_PROVIDERS: tuple[ProbabilityProvider, ...] = (
    TheOddsApiProvider(),
    FootballDataProvider(),
    ApiFootballProvider(),
)


__all__ = [
    "ApiFootballProvider",
    "DEFAULT_PROVIDERS",
    "FootballDataProvider",
    "ProbabilityProvider",
    "ProviderContext",
    "TheOddsApiProvider",
    "fetch_odds_from_football_data",
    "fetch_odds_from_the_odds_api",
    "fetch_predictions_from_api_football",
    "normalize_bookmaker_odds_to_probabilities",
]
