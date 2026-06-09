import argparse
import json
import re

import pytest
import requests

import kicktipp_tool
from models import EloResult, ProbabilityResult

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    return ANSI_RE.sub("", text)


def test_odds_api_request_exception_exits_cleanly(monkeypatch):
    def failing_fetch(*args, **kwargs):
        raise requests.Timeout("request timed out")

    monkeypatch.setattr(kicktipp_tool, "fetch_odds_from_the_odds_api", failing_fetch)
    args = argparse.Namespace(
        team_a="Argentina",
        team_b="France",
        p_a=None,
        p_draw=None,
        p_b=None,
        use_odds_api=True,
        use_football_data=False,
        use_api_football=False,
        match_date=None,
        football_data_match_id=None,
        api_football_fixture_id=None,
        odds_sport_key="soccer_fifa_world_cup",
        odds_regions="eu",
        refresh=True,
    )

    with pytest.raises(SystemExit, match="Odds are missing: request timed out"):
        kicktipp_tool._resolve_probabilities(args)


def test_probability_source_errors_redact_api_keys(monkeypatch):
    def failing_fetch(*args, **kwargs):
        raise requests.ConnectionError(
            "failed for https://example.test/odds?apiKey=secret-value&markets=h2h"
        )

    monkeypatch.setattr(kicktipp_tool, "fetch_odds_from_the_odds_api", failing_fetch)
    args = argparse.Namespace(
        team_a="Argentina",
        team_b="France",
        p_a=None,
        p_draw=None,
        p_b=None,
        use_odds_api=True,
        use_football_data=False,
        use_api_football=False,
        match_date=None,
        football_data_match_id=None,
        api_football_fixture_id=None,
        odds_sport_key="soccer_fifa_world_cup",
        odds_regions="eu",
        refresh=True,
    )

    with pytest.raises(SystemExit) as exit_info:
        kicktipp_tool._resolve_probabilities(args)

    message = str(exit_info.value)
    assert "apiKey=<redacted>" in message
    assert "secret-value" not in message


def test_cli_passes_configured_odds_sport_key(monkeypatch):
    seen = {}

    def fake_fetch(*args, **kwargs):
        seen.update(kwargs)
        return {
            "source": "The Odds API",
            "probabilities": {"p_a": 0.4, "p_draw": 0.3, "p_b": 0.3},
        }

    monkeypatch.setattr(kicktipp_tool, "fetch_odds_from_the_odds_api", fake_fetch)
    args = argparse.Namespace(
        team_a="Argentina",
        team_b="France",
        p_a=None,
        p_draw=None,
        p_b=None,
        use_odds_api=True,
        use_football_data=False,
        use_api_football=False,
        match_date=None,
        football_data_match_id=None,
        api_football_fixture_id=None,
        odds_sport_key="soccer_epl",
        odds_regions="uk",
        refresh=False,
    )

    result = kicktipp_tool._resolve_probabilities(args)

    assert result.probabilities == {"p_a": 0.4, "p_draw": 0.3, "p_b": 0.3}
    assert result.source == "The Odds API"
    assert result.expected_total_goals is None
    assert result.total_goals_source is None
    assert seen["sport_key"] == "soccer_epl"
    assert seen["regions"] == "uk"


def test_cli_tries_all_probability_sources_by_default(monkeypatch):
    calls = []

    def fake_odds_fetch(*args, **kwargs):
        calls.append("odds")
        return {
            "source": "The Odds API",
            "probabilities": {"p_a": 0.41, "p_draw": 0.29, "p_b": 0.30},
        }

    monkeypatch.setattr(kicktipp_tool, "fetch_odds_from_the_odds_api", fake_odds_fetch)
    args = argparse.Namespace(
        team_a="Argentina",
        team_b="France",
        p_a=None,
        p_draw=None,
        p_b=None,
        use_odds_api=False,
        use_football_data=False,
        use_api_football=False,
        match_date=None,
        football_data_match_id=None,
        api_football_fixture_id=None,
        odds_sport_key="soccer_fifa_world_cup",
        odds_regions="eu",
        refresh=False,
    )

    result = kicktipp_tool._resolve_probabilities(args)

    assert calls == ["odds"]
    assert result.probabilities == {"p_a": 0.41, "p_draw": 0.29, "p_b": 0.30}
    assert result.source == "The Odds API"
    assert result.expected_total_goals is None
    assert result.total_goals_source is None


def test_cli_falls_back_to_next_probability_source(monkeypatch):
    calls = []

    def failing_odds_fetch(*args, **kwargs):
        calls.append("odds")
        raise ValueError("THE_ODDS_API_KEY is missing")

    def fake_football_data_fetch(*args, **kwargs):
        calls.append("football-data")
        return {
            "source": "football-data.org",
            "probabilities": {"p_a": 0.39, "p_draw": 0.31, "p_b": 0.30},
        }

    monkeypatch.setattr(
        kicktipp_tool, "fetch_odds_from_the_odds_api", failing_odds_fetch
    )
    monkeypatch.setattr(
        kicktipp_tool, "fetch_odds_from_football_data", fake_football_data_fetch
    )
    args = argparse.Namespace(
        team_a="Argentina",
        team_b="France",
        p_a=None,
        p_draw=None,
        p_b=None,
        use_odds_api=False,
        use_football_data=False,
        use_api_football=False,
        match_date="2026-06-11",
        football_data_match_id=None,
        api_football_fixture_id=None,
        odds_sport_key="soccer_fifa_world_cup",
        odds_regions="eu",
        refresh=False,
    )

    result = kicktipp_tool._resolve_probabilities(args)

    assert calls == ["odds", "football-data"]
    assert result.probabilities == {"p_a": 0.39, "p_draw": 0.31, "p_b": 0.30}
    assert result.source == "football-data.org"
    assert result.expected_total_goals is None
    assert result.total_goals_source is None


def test_total_goals_requires_manual_value_or_auto_source():
    args = argparse.Namespace(total_goals=None)

    with pytest.raises(SystemExit, match="Expected total goals are missing"):
        kicktipp_tool._resolve_total_goals(args)


def test_total_goals_can_use_auto_source():
    args = argparse.Namespace(total_goals=None)

    total_goals, source = kicktipp_tool._resolve_total_goals(
        args,
        ProbabilityResult(
            0.4,
            0.3,
            0.3,
            "The Odds API",
            expected_total_goals=2.75,
            total_goals_source="The Odds API totals",
        ),
    )

    assert total_goals == pytest.approx(2.75)
    assert source == "The Odds API totals"


def test_total_goals_manual_value_has_priority_over_auto_source():
    args = argparse.Namespace(total_goals=2.4)

    total_goals, source = kicktipp_tool._resolve_total_goals(
        args,
        ProbabilityResult(
            0.4,
            0.3,
            0.3,
            "The Odds API",
            expected_total_goals=2.75,
            total_goals_source="The Odds API totals",
        ),
    )

    assert total_goals == pytest.approx(2.4)
    assert source == "manual CLI input"


def test_elo_uses_local_csv_before_remote(tmp_path, monkeypatch):
    elo_file = tmp_path / "elo.csv"
    elo_file.write_text("team,elo\n Argentina ,2139\nFrance,2085\n", encoding="utf-8")

    def failing_remote(*args, **kwargs):
        raise AssertionError("remote Elo should not be called")

    monkeypatch.setattr(kicktipp_tool, "fetch_remote_elo_ratings", failing_remote)
    args = argparse.Namespace(
        team_a="Argentina",
        team_b="France",
        elo_a=None,
        elo_b=None,
        use_elo=True,
        elo_path=str(elo_file),
        elo_url=None,
        refresh=False,
    )

    result = kicktipp_tool._resolve_elo(args)

    assert result.elo_a == pytest.approx(2139)
    assert result.elo_b == pytest.approx(2085)
    assert result.source == str(elo_file)


def test_elo_falls_back_to_remote_when_local_file_is_missing(monkeypatch):
    seen = {}

    def fake_remote(source_url, refresh):
        seen["source_url"] = source_url
        seen["refresh"] = refresh
        return {"Argentina": 2139.0, "France": 2085.0}

    monkeypatch.setattr(kicktipp_tool, "fetch_remote_elo_ratings", fake_remote)
    args = argparse.Namespace(
        team_a="Argentina",
        team_b="France",
        elo_a=None,
        elo_b=None,
        use_elo=True,
        elo_path="missing.csv",
        elo_url="https://example.test/elo",
        refresh=True,
    )

    result = kicktipp_tool._resolve_elo(args)

    assert result.elo_a == pytest.approx(2139)
    assert result.elo_b == pytest.approx(2085)
    assert result.source == "https://example.test/elo"
    assert seen == {"source_url": "https://example.test/elo", "refresh": True}


def test_elo_remote_lookup_matches_team_aliases(monkeypatch):
    def fake_remote(source_url, refresh):
        return {"Portugal": 1984.0, "Dem. Rep. of Congo": 1655.0}

    monkeypatch.setattr(kicktipp_tool, "fetch_remote_elo_ratings", fake_remote)
    args = argparse.Namespace(
        team_a="Portugal",
        team_b="DR Congo",
        elo_a=None,
        elo_b=None,
        use_elo=True,
        elo_path="missing.csv",
        elo_url="https://example.test/elo",
        refresh=True,
    )

    result = kicktipp_tool._resolve_elo(args)

    assert result.elo_a == pytest.approx(1984)
    assert result.elo_b == pytest.approx(1655)
    assert result.source == "https://example.test/elo"


def test_elo_can_be_disabled(monkeypatch):
    def failing_remote(*args, **kwargs):
        raise AssertionError("remote Elo should not be called")

    monkeypatch.setattr(kicktipp_tool, "fetch_remote_elo_ratings", failing_remote)
    args = argparse.Namespace(
        team_a="Argentina",
        team_b="France",
        elo_a=None,
        elo_b=None,
        use_elo=False,
        elo_path="missing.csv",
        elo_url="https://example.test/elo",
        refresh=False,
    )

    assert kicktipp_tool._resolve_elo(args) == EloResult(
        None, None, "neutral / unavailable"
    )


def test_predict_output_explains_exact_probability_and_summarizes_tendency(
    monkeypatch, capsys
):
    monkeypatch.setattr(
        kicktipp_tool,
        "_resolve_probabilities",
        lambda args: ProbabilityResult(
            0.62,
            0.22,
            0.16,
            "Test odds",
            expected_total_goals=2.48,
            total_goals_source="Test totals",
        ),
    )
    monkeypatch.setattr(
        kicktipp_tool,
        "_resolve_total_goals",
        lambda args, probabilities: (
            probabilities.expected_total_goals,
            probabilities.total_goals_source,
        ),
    )
    monkeypatch.setattr(
        kicktipp_tool,
        "_resolve_elo",
        lambda args: EloResult(None, None, "neutral / unavailable"),
    )
    monkeypatch.setattr(
        kicktipp_tool, "infer_expected_goals", lambda *args: (1.6, 0.8)
    )
    monkeypatch.setattr(kicktipp_tool, "build_score_matrix", lambda *args: {})
    monkeypatch.setattr(
        kicktipp_tool, "apply_low_score_adjustment", lambda matrix, rho: matrix
    )
    monkeypatch.setattr(
        kicktipp_tool,
        "rank_tips",
        lambda matrix, tip_max_goals: [
            {
                "score": (2, 0),
                "expected_points": 1.86,
                "exact_probability": 0.176,
                "tendency_probability": 0.723,
            },
            {
                "score": (1, 0),
                "expected_points": 1.81,
                "exact_probability": 0.138,
                "tendency_probability": 0.723,
            },
            {
                "score": (2, 1),
                "expected_points": 1.75,
                "exact_probability": 0.078,
                "tendency_probability": 0.723,
            },
            {
                "score": (3, 1),
                "expected_points": 1.73,
                "exact_probability": 0.053,
                "tendency_probability": 0.723,
            },
            {
                "score": (3, 0),
                "expected_points": 1.71,
                "exact_probability": 0.119,
                "tendency_probability": 0.723,
            },
        ],
    )
    args = argparse.Namespace(
        team_a="Mexico",
        team_b="South Africa",
        max_goals=6,
        tip_max_goals=5,
        rho=-0.08,
    )

    assert kicktipp_tool.run_predict(args) == 0

    output = capsys.readouterr().out
    output_lines = output.splitlines()
    plain_output = _plain(output)
    assert "\x1b[" in output
    assert output_lines[1].startswith("\x1b[1;36m│\x1b[0m Pick:")
    assert output_lines[1].endswith("\x1b[1;36m│\x1b[0m")
    assert "┌─ Mexico vs South Africa" in plain_output
    assert "│ Pick: Mexico 2–0 South Africa" in plain_output
    assert "│ Confidence: Mexico win 72.3%" in plain_output
    assert "│ Exact score probability: 17.6%" in plain_output
    assert "│ Expected points: 1.86" in plain_output
    assert "└" in plain_output
    assert "Key model signals" in plain_output
    assert "xG              Mexico 1.60   South Africa 0.80" in plain_output
    assert "Total goals     2.48" in plain_output
    assert "Handicap        not available" in plain_output
    assert "Elo             neutral / unavailable" in plain_output
    assert "1X2 probabilities" in plain_output
    assert "Mexico          62.0%" in plain_output
    assert "Draw            22.0%" in plain_output
    assert "South Africa    16.0%" in plain_output
    assert "Sources:" not in plain_output
    assert "* 1X2 probabilities: Test odds" not in plain_output
    assert "* Expected goals: Test totals" not in plain_output
    assert "Top 5 tips:" not in plain_output
    assert "Top 5 outcome" not in plain_output
    assert "Top scorelines" in plain_output
    assert "1. 2–0  Mexico win   EV 1.86   Prob 17.6%" in plain_output
    assert "exakt" not in output


def test_predict_output_shows_elo_values_not_elo_source_url(monkeypatch, capsys):
    monkeypatch.setattr(
        kicktipp_tool,
        "_resolve_probabilities",
        lambda args: ProbabilityResult(
            0.86,
            0.09,
            0.05,
            "Test odds",
            expected_total_goals=3.5,
            total_goals_source="Test totals",
            expected_goal_difference=2.5,
            goal_difference_source="Test spreads",
        ),
    )
    monkeypatch.setattr(
        kicktipp_tool,
        "_resolve_total_goals",
        lambda args, probabilities: (3.5, "Test totals"),
    )
    monkeypatch.setattr(
        kicktipp_tool,
        "_resolve_elo",
        lambda args: EloResult(1900, 1650, "https://example.test/elo"),
    )
    monkeypatch.setattr(
        kicktipp_tool,
        "infer_expected_goals_from_market_difference",
        lambda *args: (3.0, 0.5),
    )
    monkeypatch.setattr(kicktipp_tool, "build_score_matrix", lambda *args: {})
    monkeypatch.setattr(
        kicktipp_tool, "apply_low_score_adjustment", lambda matrix, rho: matrix
    )
    monkeypatch.setattr(
        kicktipp_tool,
        "rank_tips",
        lambda matrix, tip_max_goals: [
            {
                "score": (4, 0),
                "expected_points": 2.10,
                "exact_probability": 0.14,
                "tendency_probability": 0.88,
            }
        ],
    )
    args = argparse.Namespace(
        team_a="Portugal",
        team_b="DR Congo",
        max_goals=8,
        tip_max_goals=5,
        rho=-0.08,
        output_json=False,
        quiet=False,
    )

    assert kicktipp_tool.run_predict(args) == 0

    plain_output = _plain(capsys.readouterr().out)
    model_inputs = plain_output.split("Key model signals", 1)[1].split(
        "1X2 probabilities", 1
    )[0]
    assert "xG              Portugal 3.00   DR Congo 0.50" in model_inputs
    assert "Handicap        Portugal +2.50" in model_inputs
    assert "Elo             Portugal +250" in model_inputs
    assert "https://example.test/elo" not in model_inputs
    assert "Sources:" not in plain_output
    assert "https://example.test/elo" not in plain_output
    assert "Top 5 tips:" not in plain_output


def test_predict_json_output(monkeypatch, capsys):
    monkeypatch.setattr(
        kicktipp_tool,
        "_resolve_probabilities",
        lambda args: ProbabilityResult(
            0.62,
            0.22,
            0.16,
            "Test odds",
            expected_total_goals=2.48,
            total_goals_source="Test totals",
        ),
    )
    monkeypatch.setattr(
        kicktipp_tool,
        "_resolve_total_goals",
        lambda args, probabilities: (2.48, "Test totals"),
    )
    monkeypatch.setattr(
        kicktipp_tool,
        "_resolve_elo",
        lambda args: EloResult(None, None, "neutral / unavailable"),
    )
    monkeypatch.setattr(
        kicktipp_tool, "infer_expected_goals", lambda *args: (1.6, 0.8)
    )
    monkeypatch.setattr(kicktipp_tool, "build_score_matrix", lambda *args: {})
    monkeypatch.setattr(
        kicktipp_tool, "apply_low_score_adjustment", lambda matrix, rho: matrix
    )
    monkeypatch.setattr(
        kicktipp_tool,
        "rank_tips",
        lambda matrix, tip_max_goals: [
            {
                "score": (2, 0),
                "expected_points": 1.86,
                "exact_probability": 0.176,
                "tendency_probability": 0.723,
            }
        ],
    )
    args = argparse.Namespace(
        team_a="Mexico",
        team_b="South Africa",
        max_goals=6,
        tip_max_goals=5,
        rho=-0.08,
        output_json=True,
        quiet=False,
    )

    assert kicktipp_tool.run_predict(args) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["recommendation"]["score"] == "2:0"
    assert payload["data_sources"]["probabilities"] == "Test odds"
    assert payload["inputs"]["total_goals"] == pytest.approx(2.48)


def test_predict_uses_market_goal_difference_when_available(monkeypatch):
    monkeypatch.setattr(
        kicktipp_tool,
        "_resolve_probabilities",
        lambda args: ProbabilityResult(
            0.86,
            0.09,
            0.05,
            "Test odds",
            expected_total_goals=3.5,
            total_goals_source="Test totals",
            expected_goal_difference=2.5,
            goal_difference_source="Test spreads",
        ),
    )
    monkeypatch.setattr(
        kicktipp_tool,
        "_resolve_total_goals",
        lambda args, probabilities: (3.5, "Test totals"),
    )
    monkeypatch.setattr(
        kicktipp_tool,
        "_resolve_elo",
        lambda args: EloResult(None, None, "neutral / unavailable"),
    )

    calls = []

    def fail_old_inference(*args):
        raise AssertionError("1X2 inference should not run when spreads are available")

    def market_inference(total_goals, expected_goal_difference):
        calls.append((total_goals, expected_goal_difference))
        return 3.0, 0.5

    monkeypatch.setattr(kicktipp_tool, "infer_expected_goals", fail_old_inference)
    monkeypatch.setattr(
        kicktipp_tool,
        "infer_expected_goals_from_market_difference",
        market_inference,
    )
    monkeypatch.setattr(kicktipp_tool, "build_score_matrix", lambda *args: {})
    monkeypatch.setattr(
        kicktipp_tool, "apply_low_score_adjustment", lambda matrix, rho: matrix
    )
    monkeypatch.setattr(
        kicktipp_tool,
        "rank_tips",
        lambda matrix, tip_max_goals: [
            {
                "score": (4, 0),
                "expected_points": 2.1,
                "exact_probability": 0.14,
                "tendency_probability": 0.88,
            }
        ],
    )
    args = argparse.Namespace(
        team_a="Portugal",
        team_b="DR Congo",
        max_goals=8,
        tip_max_goals=5,
        rho=-0.08,
        output_json=True,
        quiet=False,
    )

    assert kicktipp_tool.run_predict(args) == 0
    assert calls == [(3.5, 2.5)]


def test_predict_quiet_output(monkeypatch, capsys):
    monkeypatch.setattr(
        kicktipp_tool,
        "_resolve_probabilities",
        lambda args: ProbabilityResult(0.62, 0.22, 0.16, "Test odds"),
    )
    monkeypatch.setattr(
        kicktipp_tool,
        "_resolve_total_goals",
        lambda args, probabilities: (2.48, "manual CLI input"),
    )
    monkeypatch.setattr(
        kicktipp_tool,
        "_resolve_elo",
        lambda args: EloResult(None, None, "neutral / unavailable"),
    )
    monkeypatch.setattr(
        kicktipp_tool, "infer_expected_goals", lambda *args: (1.6, 0.8)
    )
    monkeypatch.setattr(kicktipp_tool, "build_score_matrix", lambda *args: {})
    monkeypatch.setattr(
        kicktipp_tool, "apply_low_score_adjustment", lambda matrix, rho: matrix
    )
    monkeypatch.setattr(
        kicktipp_tool,
        "rank_tips",
        lambda matrix, tip_max_goals: [
            {
                "score": (2, 0),
                "expected_points": 1.86,
                "exact_probability": 0.176,
                "tendency_probability": 0.723,
            }
        ],
    )
    args = argparse.Namespace(
        team_a="Mexico",
        team_b="South Africa",
        max_goals=6,
        tip_max_goals=5,
        rho=-0.08,
        output_json=False,
        quiet=True,
    )

    assert kicktipp_tool.run_predict(args) == 0

    assert capsys.readouterr().out == "2:0\n"


def test_predict_day_selects_first_group_fixtures_and_displays_pending(
    tmp_path, capsys
):
    fixture_file = tmp_path / "fixtures.json"
    fixture_file.write_text(
        json.dumps(
            {
                "rounds": [
                    {
                        "name": "Match day 1",
                        "matches": [
                            {
                                "date": "2026-06-11",
                                "time": "18:00",
                                "group": "Group A",
                                "team1": "Mexico",
                                "team2": "South Africa",
                            },
                            {
                                "date": "2026-06-11",
                                "time": "21:00",
                                "group": "Group A",
                                "team1": "Winner Group A",
                                "team2": "Runner-up Group B",
                            },
                        ],
                    },
                    {
                        "name": "Matchday 2",
                        "matches": [
                            {
                                "date": "2026-06-12",
                                "time": "18:00",
                                "group": "Group B",
                                "team1": "Canada",
                                "team2": "Bosnia & Herzegovina",
                            },
                            {
                                "date": "2026-06-13",
                                "time": "12:00",
                                "group": "Group B",
                                "team1": "Qatar",
                                "team2": "Switzerland",
                            },
                        ],
                    },
                    {
                        "name": "Matchday 8",
                        "matches": [
                            {
                                "date": "2026-06-18",
                                "time": "12:00",
                                "group": "Group A",
                                "team1": "Czech Republic",
                                "team2": "South Africa",
                            },
                            {
                                "date": "2026-06-18",
                                "time": "19:00",
                                "group": "Group A",
                                "team1": "Mexico",
                                "team2": "South Korea",
                            },
                        ],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    assert (
        kicktipp_tool.main(
            [
                "predict-day",
                "--match-day",
                "Matchday 1",
                "--fixtures",
                str(fixture_file),
                "--p-a",
                "0.62",
                "--p-draw",
                "0.22",
                "--p-b",
                "0.16",
                "--total-goals",
                "2.48",
                "--no-elo",
            ]
        )
        == 0
    )

    output = _plain(capsys.readouterr().out)
    assert "Predictions for Matchday 1" in output
    assert "Ready fixtures" in output
    assert "18:00  Mexico vs South Africa" in output
    assert "18:00  Canada vs Bosnia & Herzegovina" in output
    assert "12:00  Qatar vs Switzerland" in output
    assert "Czech Republic vs South Africa" not in output
    assert "Mexico vs South Korea" not in output
    assert "EV" in output
    assert "Pending fixtures" in output
    assert "21:00  Winner Group A vs Runner-up Group B" in output


def test_predict_day_writes_markdown_report(tmp_path, capsys):
    fixture_file = tmp_path / "fixtures.json"
    output_file = tmp_path / "predictions.md"
    fixture_file.write_text(
        json.dumps(
            {
                "rounds": [
                    {
                        "name": "Semi-finals",
                        "matches": [
                            {
                                "date": "2026-07-14",
                                "time": "21:00",
                                "team1": "Winner Quarter-final 1",
                                "team2": "Winner Quarter-final 2",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert (
        kicktipp_tool.main(
            [
                "predict-day",
                "--match-day",
                "semi finals",
                "--fixtures",
                str(fixture_file),
                "--output",
                str(output_file),
            ]
        )
        == 0
    )

    stdout = capsys.readouterr().out
    report = output_file.read_text(encoding="utf-8")
    assert f"Report written to {output_file}" in stdout
    assert "# Predictions for Semi-finals" in report
    assert "No ready fixtures to predict yet." in report
    assert "- 21:00  Winner Quarter-final 1 vs Winner Quarter-final 2" in report


def test_predict_day_numeric_knockout_playday_selects_bracket_round(
    tmp_path, capsys
):
    fixture_file = tmp_path / "fixtures.json"
    fixture_file.write_text(
        json.dumps(
            {
                "matches": [
                    {
                        "round": "Round of 32",
                        "date": "2026-07-01",
                        "time": "13:00 UTC-7",
                        "team1": "1G",
                        "team2": "3A/E/H/I/J",
                    },
                    {
                        "round": "Round of 16",
                        "date": "2026-07-04",
                        "time": "20:00 UTC-4",
                        "team1": "W82",
                        "team2": "W83",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    assert (
        kicktipp_tool.main(
            [
                "predict-day",
                "--match-day",
                "4",
                "--fixtures",
                str(fixture_file),
            ]
        )
        == 0
    )

    output = _plain(capsys.readouterr().out)
    assert "Predictions for Matchday 4" in output
    assert "13:00 UTC-7  1G vs 3A/E/H/I/J" in output
    assert "W82 vs W83" not in output


def test_predict_day_treats_openfootball_knockout_codes_as_pending(
    tmp_path, capsys
):
    fixture_file = tmp_path / "fixtures.json"
    fixture_file.write_text(
        json.dumps(
            {
                "matches": [
                    {
                        "round": "Round of 32",
                        "date": "2026-07-01",
                        "time": "13:00 UTC-7",
                        "team1": "1G",
                        "team2": "3A/E/H/I/J",
                    },
                    {
                        "round": "Semi-final",
                        "date": "2026-07-14",
                        "time": "20:00 UTC-4",
                        "team1": "W97",
                        "team2": "W98",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    assert (
        kicktipp_tool.main(
            [
                "predict-day",
                "--match-day",
                "Round of 32",
                "--fixtures",
                str(fixture_file),
            ]
        )
        == 0
    )

    output = _plain(capsys.readouterr().out)
    assert "Predictions for Round of 32" in output
    assert "No ready fixtures to predict yet." in output
    assert "Pending fixtures" in output
    assert "13:00 UTC-7  1G vs 3A/E/H/I/J" in output

    assert (
        kicktipp_tool.main(
            [
                "predict-day",
                "--match-day",
                "Semi-finals",
                "--fixtures",
                str(fixture_file),
            ]
        )
        == 0
    )

    output = _plain(capsys.readouterr().out)
    assert "Predictions for Semi-final" in output
    assert "No ready fixtures to predict yet." in output
    assert "Pending fixtures" in output
    assert "Failed fixtures" not in output
    assert "20:00 UTC-4  W97 vs W98" in output
