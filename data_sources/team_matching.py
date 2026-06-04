from __future__ import annotations

import difflib
import unicodedata
from collections.abc import Iterable
from typing import Any

TEAM_ALIASES: dict[str, set[str]] = {
    "algeria": {"alg", "algerien"},
    "argentina": {"arg", "argentinien"},
    "australia": {"aus", "australien"},
    "austria": {"aut", "osterreich"},
    "belgium": {"bel", "belgien"},
    "bosnia and herzegovina": {
        "bih",
        "bosnia herzegovina",
        "bosnien und herzegowina",
        "bosnien herzegowina",
    },
    "brazil": {"bra", "brasilien"},
    "cabo verde": {"cape verde", "cpv", "kap verde", "kapverden"},
    "canada": {"can", "kanada"},
    "colombia": {"col", "kolumbien"},
    "congo dr": {
        "cod",
        "congo democratic republic",
        "democratic republic of congo",
        "dr congo",
        "dr kongo",
        "drc",
        "rd congo",
    },
    "cote d ivoire": {
        "civ",
        "cote d ivoire",
        "cote divoire",
        "cote ivoire",
        "costa de marfil",
        "elfenbeinkuste",
        "elfenbeinkueste",
        "ivory coast",
    },
    "croatia": {"cro", "kroatien"},
    "curacao": {"cuw", "curacao", "curazao"},
    "czechia": {"cze", "czech republic", "tschechien"},
    "ecuador": {"ecu"},
    "egypt": {"agypten", "aegypten", "egy", "egypte"},
    "england": {"eng", "englisch", "grossbritannien"},
    "france": {"fra", "frankreich"},
    "germany": {"deu", "ger", "deutschland"},
    "ghana": {"gha"},
    "haiti": {"hai"},
    "ir iran": {
        "iran",
        "irn",
        "islamic republic of iran",
        "ri iran",
    },
    "iraq": {"irak", "irq"},
    "japan": {"jpn"},
    "jordan": {"jor", "jordanien"},
    "korea republic": {
        "kor",
        "republic of korea",
        "south korea",
        "sudkorea",
        "suedkorea",
    },
    "mexico": {"mex", "mexiko"},
    "morocco": {"mar", "marokko"},
    "netherlands": {"holland", "ned", "niederlande"},
    "new zealand": {"neuseeland", "nzl"},
    "norway": {"nor", "norwegen"},
    "panama": {"pan"},
    "paraguay": {"par"},
    "portugal": {"por"},
    "qatar": {"katar", "qat"},
    "saudi arabia": {
        "ksa",
        "saudi arabia",
        "saudi arabien",
    },
    "scotland": {"sco", "schottland"},
    "senegal": {"sen"},
    "south africa": {"rsa", "sudafrika", "suedafrika"},
    "spain": {"esp", "spanien"},
    "sweden": {"schweden", "swe"},
    "switzerland": {"schweiz", "sui"},
    "tunisia": {"tun", "tunesien"},
    "turkiye": {"tur", "turkei", "turkey"},
    "uruguay": {"uru"},
    "usa": {
        "united states",
        "united states of america",
        "us",
        "usa",
        "vereinigte staaten",
    },
    "uzbekistan": {"usbekistan", "uzb"},
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
