import json
import os
import time

import pytest

import data_sources
from config import Settings
from data_sources import (
    fetch_odds_from_football_data,
    fetch_odds_from_the_odds_api,
    fetch_predictions_from_api_football,
    fetch_remote_elo_ratings,
    load_elo_ratings,
    load_fixtures_from_openfootball,
    load_from_cache,
    normalize_bookmaker_odds_to_probabilities,
    save_to_cache,
    team_names_match,
)


def test_cache_write_and_read_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(data_sources, "CACHE_DIR", tmp_path)

    save_to_cache("example-key", {"ok": True, "value": 7})

    assert load_from_cache("example-key") == {"ok": True, "value": 7}


def test_odds_normalization_removes_bookmaker_margin():
    probabilities = normalize_bookmaker_odds_to_probabilities(
        {"home": 1.90, "draw": 3.40, "away": 4.20}
    )

    assert (
        probabilities["p_a"] + probabilities["p_draw"] + probabilities["p_b"]
    ) == pytest.approx(1.0)
    assert probabilities["bookmaker_margin"] > 0


def test_load_elo_ratings_reads_local_csv(tmp_path):
    elo_file = tmp_path / "elo.csv"
    elo_file.write_text("Team,Elo\nArgentina,2139\nFrance,2085\n", encoding="utf-8")

    assert load_elo_ratings(str(elo_file)) == {
        "Argentina": 2139.0,
        "France": 2085.0,
    }


def test_load_elo_ratings_accepts_clubelo_style_csv(tmp_path):
    elo_file = tmp_path / "clubelo.csv"
    elo_file.write_text(
        "Rank,Club,Country,Elo\n1,ManCity,ENG,2074.42\n", encoding="utf-8"
    )

    assert load_elo_ratings(str(elo_file)) == {"ManCity": 2074.42}


def test_remote_elo_ratings_parse_html_and_write_cache(tmp_path, monkeypatch):
    class FakeResponse:
        headers = {"content-type": "text/html"}
        text = """
        <html>
          <body>
            <h2>World football Elo ratings as on June 4th, 2026</h2>
            <div>1.</div><div>Argentina 2139</div>
            <div>2.</div><div>France 2085</div>
          </body>
        </html>
        """

        def raise_for_status(self):
            return None

    calls = []

    def fake_get(url, timeout):
        calls.append({"url": url, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr(data_sources, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(data_sources.requests, "get", fake_get)

    ratings = fetch_remote_elo_ratings("https://example.test/elo", refresh=True)
    cached_ratings = fetch_remote_elo_ratings("https://example.test/elo")

    assert ratings == {"Argentina": 2139.0, "France": 2085.0}
    assert cached_ratings == ratings
    assert calls == [{"url": "https://example.test/elo", "timeout": 20}]


def test_missing_the_odds_api_key_is_handled_cleanly(tmp_path, monkeypatch):
    monkeypatch.setattr(data_sources, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(
        data_sources,
        "load_settings",
        lambda: Settings(the_odds_api_key=None),
    )

    with pytest.raises(ValueError, match="THE_ODDS_API_KEY is missing"):
        fetch_odds_from_the_odds_api("Argentina", "France", api_key=None)


def test_missing_football_data_key_is_handled_cleanly(tmp_path, monkeypatch):
    monkeypatch.setattr(data_sources, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(
        data_sources,
        "load_settings",
        lambda: Settings(football_data_api_key=None),
    )

    with pytest.raises(ValueError, match="FOOTBALL_DATA_API_KEY is missing"):
        fetch_odds_from_football_data("Argentina", "France", api_key=None)


def test_missing_api_football_key_is_handled_cleanly(tmp_path, monkeypatch):
    monkeypatch.setattr(data_sources, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(
        data_sources,
        "load_settings",
        lambda: Settings(api_football_key=None),
    )

    with pytest.raises(ValueError, match="API_FOOTBALL_KEY is missing"):
        fetch_predictions_from_api_football(
            "Argentina", "France", fixture_id=123, api_key=None
        )


def test_odds_api_uses_cache_without_api_key_when_not_refreshing(tmp_path, monkeypatch):
    monkeypatch.setattr(data_sources, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(
        data_sources,
        "load_settings",
        lambda: Settings(the_odds_api_key=None),
    )
    cached = {
        "source": "cache",
        "probabilities": {"p_a": 0.4, "p_draw": 0.3, "p_b": 0.3},
    }
    save_to_cache(
        "the_odds_api:soccer_fifa_world_cup:eu:h2h_spreads_totals:Argentina:France",
        cached,
    )

    assert fetch_odds_from_the_odds_api("Argentina", "France") == cached


def test_odds_api_ignores_cache_older_than_one_day(tmp_path, monkeypatch):
    monkeypatch.setattr(data_sources, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(
        data_sources,
        "load_settings",
        lambda: Settings(the_odds_api_key=None),
    )
    cache_key = (
        "the_odds_api:soccer_fifa_world_cup:eu:h2h_spreads_totals:Argentina:France"
    )
    save_to_cache(
        cache_key,
        {
            "source": "stale cache",
            "probabilities": {"p_a": 0.4, "p_draw": 0.3, "p_b": 0.3},
        },
    )
    old_timestamp = time.time() - 25 * 60 * 60
    os.utime(data_sources._cache_path(cache_key), (old_timestamp, old_timestamp))

    with pytest.raises(ValueError, match="THE_ODDS_API_KEY is missing"):
        fetch_odds_from_the_odds_api("Argentina", "France")


def test_no_cache_ignores_cached_api_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(data_sources, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(
        data_sources,
        "load_settings",
        lambda: Settings(the_odds_api_key=None),
    )
    cache_key = (
        "the_odds_api:soccer_fifa_world_cup:eu:h2h_spreads_totals:Argentina:France"
    )
    save_to_cache(
        cache_key,
        {
            "source": "cached",
            "probabilities": {"p_a": 0.4, "p_draw": 0.3, "p_b": 0.3},
        },
    )

    with pytest.raises(ValueError, match="THE_ODDS_API_KEY is missing"):
        fetch_odds_from_the_odds_api("Argentina", "France", no_cache=True)


def test_team_matching_handles_aliases_and_accents():
    assert team_names_match("Germany", ["Deutschland"])
    assert team_names_match("Côte d'Ivoire", ["Cote d Ivoire"])


@pytest.mark.parametrize(
    ("expected_name", "candidates"),
    [
        ("Algeria", ["ALG", "Algerien"]),
        ("Argentina", ["ARG", "Argentinien"]),
        ("Australia", ["AUS", "Australien"]),
        ("Austria", ["AUT", "Österreich"]),
        ("Belgium", ["BEL", "Belgien"]),
        ("Bosnia and Herzegovina", ["BIH", "Bosnien-Herzegowina"]),
        ("Brazil", ["BRA", "Brasilien"]),
        ("Cabo Verde", ["CPV", "Cape Verde", "Kap Verde"]),
        ("Canada", ["CAN", "Kanada"]),
        ("Colombia", ["COL", "Kolumbien"]),
        ("Congo DR", ["COD", "DR Congo", "Democratic Republic of Congo"]),
        ("Côte d'Ivoire", ["CIV", "Ivory Coast", "Elfenbeinküste"]),
        ("Curaçao", ["CUW", "Curacao", "Curazao"]),
        ("Croatia", ["CRO", "Kroatien"]),
        ("Czechia", ["CZE", "Czech Republic", "Tschechien"]),
        ("Ecuador", ["ECU"]),
        ("Egypt", ["EGY", "Ägypten"]),
        ("England", ["ENG", "England"]),
        ("France", ["FRA", "Frankreich"]),
        ("Germany", ["GER", "Deutschland"]),
        ("Ghana", ["GHA"]),
        ("Haiti", ["HAI", "Haïti"]),
        ("IR Iran", ["IRN", "Iran", "Islamic Republic of Iran"]),
        ("Iraq", ["IRQ", "Irak"]),
        ("Japan", ["JPN"]),
        ("Jordan", ["JOR", "Jordanien"]),
        ("Korea Republic", ["KOR", "South Korea", "Südkorea"]),
        ("Mexico", ["MEX", "Mexiko"]),
        ("Morocco", ["MAR", "Marokko"]),
        ("Netherlands", ["NED", "Niederlande"]),
        ("New Zealand", ["NZL", "Neuseeland"]),
        ("Norway", ["NOR", "Norwegen"]),
        ("Panama", ["PAN", "Panamá"]),
        ("Paraguay", ["PAR"]),
        ("Portugal", ["POR"]),
        ("Qatar", ["QAT", "Katar"]),
        ("Saudi Arabia", ["KSA", "Saudi-Arabien"]),
        ("Scotland", ["SCO", "Schottland"]),
        ("Senegal", ["SEN"]),
        ("South Africa", ["RSA", "Südafrika"]),
        ("Spain", ["ESP", "Spanien"]),
        ("Sweden", ["SWE", "Schweden"]),
        ("Switzerland", ["SUI", "Schweiz"]),
        ("Tunisia", ["TUN", "Tunesien"]),
        ("Türkiye", ["TUR", "Turkey", "Türkei"]),
        ("Uruguay", ["URU"]),
        ("USA", ["United States", "United States of America"]),
        ("Uzbekistan", ["UZB", "Usbekistan"]),
    ],
)
def test_team_matching_handles_world_cup_2026_participant_aliases(
    expected_name, candidates
):
    assert team_names_match(expected_name, candidates)


def test_team_matching_does_not_fuzzy_match_short_country_codes():
    assert not team_names_match("USA", ["AUS"])
    assert not team_names_match("IRN", ["IRQ"])


def test_odds_api_default_uses_valid_world_cup_sport_key(tmp_path, monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                {
                    "home_team": "Argentina",
                    "away_team": "France",
                    "bookmakers": [
                        {
                            "markets": [
                                {
                                    "key": "h2h",
                                    "outcomes": [
                                        {"name": "Argentina", "price": 2.4},
                                        {"name": "Draw", "price": 3.3},
                                        {"name": "France", "price": 2.5},
                                    ],
                                }
                            ]
                        }
                    ],
                }
            ]

    seen = {}

    def fake_get(url, params, timeout):
        seen["url"] = url
        seen["params"] = params
        seen["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(data_sources, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(data_sources.requests, "get", fake_get)

    result = fetch_odds_from_the_odds_api(
        "Argentina", "France", api_key="test-key", refresh=True
    )

    assert seen["url"].endswith("/v4/sports/soccer_fifa_world_cup/odds")
    assert seen["params"]["apiKey"] == "test-key"
    assert seen["params"]["markets"] == "h2h,spreads,totals"
    assert result["probabilities"]["p_a"] > 0


def test_odds_api_extracts_total_goals_and_goal_difference_markets(
    tmp_path, monkeypatch
):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                {
                    "home_team": "Argentina",
                    "away_team": "France",
                    "bookmakers": [
                        {
                            "key": "book-a",
                            "markets": [
                                {
                                    "key": "h2h",
                                    "outcomes": [
                                        {"name": "Argentina", "price": 2.4},
                                        {"name": "Draw", "price": 3.3},
                                        {"name": "France", "price": 2.5},
                                    ],
                                },
                                {
                                    "key": "totals",
                                    "outcomes": [
                                        {"name": "Over", "point": 2.5, "price": 1.91},
                                        {"name": "Under", "point": 2.5, "price": 1.91},
                                        {"name": "Over", "point": 3.5, "price": 2.8},
                                        {"name": "Under", "point": 3.5, "price": 1.45},
                                    ],
                                },
                                {
                                    "key": "spreads",
                                    "outcomes": [
                                        {
                                            "name": "Argentina",
                                            "point": -2.5,
                                            "price": 1.91,
                                        },
                                        {
                                            "name": "France",
                                            "point": 2.5,
                                            "price": 1.91,
                                        },
                                        {
                                            "name": "Argentina",
                                            "point": -3.5,
                                            "price": 2.8,
                                        },
                                        {
                                            "name": "France",
                                            "point": 3.5,
                                            "price": 1.45,
                                        },
                                    ],
                                },
                            ],
                        },
                        {
                            "key": "book-b",
                            "markets": [
                                {
                                    "key": "h2h",
                                    "outcomes": [
                                        {"name": "Argentina", "price": 2.35},
                                        {"name": "Draw", "price": 3.4},
                                        {"name": "France", "price": 2.55},
                                    ],
                                },
                                {
                                    "key": "totals",
                                    "outcomes": [
                                        {"name": "Over", "point": 3.0, "price": 1.95},
                                        {"name": "Under", "point": 3.0, "price": 1.87},
                                    ],
                                },
                                {
                                    "key": "spreads",
                                    "outcomes": [
                                        {
                                            "name": "Argentina",
                                            "point": -3.0,
                                            "price": 1.95,
                                        },
                                        {
                                            "name": "France",
                                            "point": 3.0,
                                            "price": 1.87,
                                        },
                                    ],
                                },
                            ],
                        },
                    ],
                }
            ]

    monkeypatch.setattr(data_sources, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(
        data_sources.requests, "get", lambda *args, **kwargs: FakeResponse()
    )

    result = fetch_odds_from_the_odds_api(
        "Argentina", "France", api_key="test-key", refresh=True
    )

    assert result["expected_total_goals"] == pytest.approx(2.75)
    assert result["total_goals_market"]["bookmaker_count"] == 2
    assert result["expected_goal_difference"] == pytest.approx(2.75)
    assert result["spread_market"]["bookmaker_count"] == 2


def test_football_data_fetches_match_odds_with_env_key(tmp_path, monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "matches": [
                    {
                        "id": 42,
                        "homeTeam": {"name": "Argentina", "tla": "ARG"},
                        "awayTeam": {"name": "France", "tla": "FRA"},
                        "odds": {"homeWin": 2.4, "draw": 3.3, "awayWin": 2.5},
                    }
                ]
            }

    seen = {}

    def fake_get(url, params, headers, timeout):
        seen["url"] = url
        seen["params"] = params
        seen["headers"] = headers
        seen["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(data_sources, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(
        data_sources,
        "load_settings",
        lambda: Settings(football_data_api_key="football-data-key"),
    )
    monkeypatch.setattr(data_sources.requests, "get", fake_get)

    result = fetch_odds_from_football_data(
        "Argentina", "France", match_date="2026-06-11", refresh=True
    )

    assert seen["url"] == "https://api.football-data.org/v4/matches"
    assert seen["params"] == {"date": "2026-06-11"}
    assert seen["headers"] == {"X-Auth-Token": "football-data-key"}
    assert result["source"] == "football-data.org"
    assert result["probabilities"]["p_a"] > 0


def test_api_football_fetches_prediction_percentages(tmp_path, monkeypatch):
    class FixtureResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "response": [
                    {
                        "fixture": {"id": 99},
                        "teams": {
                            "home": {"name": "Argentina"},
                            "away": {"name": "France"},
                        },
                    }
                ]
            }

    class PredictionResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "response": [
                    {
                        "teams": {
                            "home": {"name": "Argentina"},
                            "away": {"name": "France"},
                        },
                        "predictions": {
                            "percent": {"home": "42%", "draw": "28%", "away": "30%"}
                        },
                    }
                ]
            }

    seen = []

    def fake_get(url, params, headers, timeout):
        seen.append(
            {"url": url, "params": params, "headers": headers, "timeout": timeout}
        )
        if url.endswith("/fixtures"):
            return FixtureResponse()
        return PredictionResponse()

    monkeypatch.setattr(data_sources, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(
        data_sources,
        "load_settings",
        lambda: Settings(api_football_key="api-football-key"),
    )
    monkeypatch.setattr(data_sources.requests, "get", fake_get)

    result = fetch_predictions_from_api_football(
        "Argentina", "France", match_date="2026-06-11", refresh=True
    )

    assert seen[0]["url"] == "https://v3.football.api-sports.io/fixtures"
    assert seen[0]["params"] == {"date": "2026-06-11"}
    assert seen[0]["headers"] == {"x-apisports-key": "api-football-key"}
    assert seen[1]["url"] == "https://v3.football.api-sports.io/predictions"
    assert seen[1]["params"] == {"fixture": 99}
    assert result["fixture_id"] == 99
    assert result["probabilities"] == {"p_a": 0.42, "p_draw": 0.28, "p_b": 0.3}


def test_fixture_loader_reads_openfootball_style_json(tmp_path):
    fixture_file = tmp_path / "worldcup.json"
    fixture_file.write_text(
        json.dumps(
            {
                "name": "World Cup",
                "rounds": [
                    {
                        "name": "Final",
                        "matches": [
                            {
                                "date": "2022-12-18",
                                "team1": "Argentina",
                                "team2": "France",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    fixtures = load_fixtures_from_openfootball(str(fixture_file))

    assert fixtures == [
        {
            "team_a": "Argentina",
            "team_b": "France",
            "date": "2022-12-18",
            "stage": "Final",
            "raw": {
                "date": "2022-12-18",
                "team1": "Argentina",
                "team2": "France",
            },
        }
    ]


def test_fixture_loader_reads_openfootball_top_level_matches_json(tmp_path):
    fixture_file = tmp_path / "worldcup.json"
    fixture_file.write_text(
        json.dumps(
            {
                "name": "World Cup",
                "matches": [
                    {
                        "round": "Round of 32",
                        "num": 82,
                        "date": "2026-07-01",
                        "time": "13:00 UTC-7",
                        "team1": "1G",
                        "team2": "3A/E/H/I/J",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    fixtures = load_fixtures_from_openfootball(str(fixture_file))

    assert fixtures == [
        {
            "team_a": "1G",
            "team_b": "3A/E/H/I/J",
            "date": "2026-07-01",
            "time": "13:00 UTC-7",
            "stage": "Round of 32",
            "raw": {
                "round": "Round of 32",
                "num": 82,
                "date": "2026-07-01",
                "time": "13:00 UTC-7",
                "team1": "1G",
                "team2": "3A/E/H/I/J",
            },
        }
    ]
