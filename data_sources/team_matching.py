from __future__ import annotations

import difflib
import unicodedata
from typing import Any, Iterable


TEAM_ALIASES: dict[str, set[str]] = {
    "argentina": {"arg", "argentinien"},
    "england": {"eng", "englisch", "grossbritannien"},
    "france": {"fra", "frankreich"},
    "germany": {"deu", "ger", "deutschland"},
    "mexico": {"mex", "mexiko"},
    "netherlands": {"ned", "niederlande", "holland"},
    "south africa": {"rsa", "sudafrika", "suedafrika"},
    "spain": {"esp", "spanien"},
    "united states": {"usa", "us", "united states of america", "vereinigte staaten"},
}


def normalize_team_name(value: str | None) -> str:
    if not value:
        return ""
    without_accents = "".join(
        char
        for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    )
    punctuation_normalized = "".join(
        char if char.isalnum() else " " for char in without_accents.casefold()
    )
    return " ".join(punctuation_normalized.split())


def canonical_team_names(value: str | None) -> set[str]:
    normalized = normalize_team_name(value)
    if not normalized:
        return set()

    names = {normalized}
    for canonical, aliases in TEAM_ALIASES.items():
        if normalized == canonical or normalized in aliases:
            names.add(canonical)
            names.update(aliases)
            break
    return names


def team_value_candidates(team: dict[str, Any] | None) -> list[str]:
    if not team:
        return []
    return [
        str(candidate)
        for candidate in (
            team.get("name"),
            team.get("shortName"),
            team.get("tla"),
            team.get("code"),
            team.get("country"),
        )
        if candidate
    ]


def team_names_match(
    expected_name: str,
    candidates: Iterable[str],
    *,
    allow_fuzzy: bool = True,
) -> bool:
    expected_names = canonical_team_names(expected_name)
    candidate_names: set[str] = set()
    for candidate in candidates:
        candidate_names.update(canonical_team_names(candidate))

    if expected_names & candidate_names:
        return True

    if not allow_fuzzy:
        return False

    expected = normalize_team_name(expected_name)
    if len(expected) < 5:
        return False
    return any(
        difflib.SequenceMatcher(None, expected, candidate).ratio() >= 0.88
        for candidate in candidate_names
        if len(candidate) >= 5
    )


def team_dict_matches(team: dict[str, Any] | None, expected_name: str) -> bool:
    return team_names_match(expected_name, team_value_candidates(team))
