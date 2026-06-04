from __future__ import annotations

import argparse
import re
import sys

import requests

from data_sources import (
    DataSourceUnavailable,
    default_elo_ratings_url,
    fetch_odds_from_football_data,
    fetch_odds_from_the_odds_api,
    fetch_predictions_from_api_football,
    fetch_remote_elo_ratings,
    load_elo_ratings,
)
from models import (
    apply_low_score_adjustment,
    build_score_matrix,
    infer_expected_goals,
)
from scoring import rank_tips


SECRET_URL_PARAM_RE = re.compile(r"([?&](?:apiKey|key)=)[^&\s)]+")


def _format_score(score: tuple[int, int]) -> str:
    return f"{score[0]}:{score[1]}"


def _probability(value: float) -> str:
    return f"{value * 100:.1f} %"


def _tendency_label(score: tuple[int, int], team_a: str, team_b: str) -> str:
    goals_a, goals_b = score
    if goals_a > goals_b:
        return f"Sieg {team_a}"
    if goals_a < goals_b:
        return f"Sieg {team_b}"
    return "Unentschieden"


def _add_predict_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("predict", help="Erzeuge einen Kicktipp-Tipp.")
    parser.add_argument("--team-a", required=True)
    parser.add_argument("--team-b", required=True)
    parser.add_argument("--p-a", type=float)
    parser.add_argument("--p-draw", type=float)
    parser.add_argument("--p-b", type=float)
    parser.add_argument("--total-goals", type=float)
    parser.add_argument("--elo-a", type=float)
    parser.add_argument("--elo-b", type=float)
    parser.add_argument(
        "--use-elo",
        action="store_true",
        default=True,
        help="Elo-Ratings laden. Standardmäßig aktiv.",
    )
    parser.add_argument(
        "--no-elo",
        action="store_false",
        dest="use_elo",
        help="Elo-Ratings nicht automatisch laden.",
    )
    parser.add_argument("--elo-path", default="data/elo_ratings.csv")
    parser.add_argument(
        "--elo-url",
        help=(
            "Remote-Quelle für Elo-Ratings. Standard: international-football.net "
            "für das aktuelle Datum."
        ),
    )
    parser.add_argument(
        "--use-odds-api",
        action="store_true",
        help="Automatische 1X2-Suche auf The Odds API beschränken.",
    )
    parser.add_argument(
        "--use-football-data",
        action="store_true",
        help="Automatische 1X2-Suche auf football-data.org beschränken.",
    )
    parser.add_argument(
        "--use-api-football",
        action="store_true",
        help="Automatische 1X2-Suche auf API-Football-Prognosen beschränken.",
    )
    parser.add_argument(
        "--match-date",
        help="Spieldatum im Format YYYY-MM-DD für football-data.org/API-Football.",
    )
    parser.add_argument("--football-data-match-id", type=int)
    parser.add_argument("--api-football-fixture-id", type=int)
    parser.add_argument(
        "--odds-sport-key",
        default="soccer_fifa_world_cup",
        help="The Odds API sport key, z. B. soccer_fifa_world_cup oder soccer_epl.",
    )
    parser.add_argument("--odds-regions", default="eu")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--max-goals", type=int, default=6)
    parser.add_argument("--tip-max-goals", type=int, default=5)
    parser.add_argument("--rho", type=float, default=-0.08)
    parser.set_defaults(func=run_predict)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Lokales Kicktipp-Tool mit Poisson-Modell und EV-Ranking."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_predict_parser(subparsers)
    return parser


def _selected_probability_sources(args: argparse.Namespace) -> list[str]:
    selected_sources = [
        name
        for name, selected in (
            ("odds_api", args.use_odds_api),
            ("football_data", args.use_football_data),
            ("api_football", args.use_api_football),
        )
        if selected
    ]
    if selected_sources:
        return selected_sources
    return ["odds_api", "football_data", "api_football"]


def _source_label(source: str) -> str:
    return {
        "odds_api": "The Odds API",
        "football_data": "football-data.org",
        "api_football": "API-Football predictions",
    }[source]


def _safe_error_message(error: Exception) -> str:
    return SECRET_URL_PARAM_RE.sub(r"\1<redacted>", str(error))


def _normalize_lookup_name(value: str) -> str:
    return " ".join(value.casefold().split())


def _rating_for_team(ratings: dict[str, float], team_name: str) -> float | None:
    if team_name in ratings:
        return ratings[team_name]

    expected = _normalize_lookup_name(team_name)
    for candidate, rating in ratings.items():
        if _normalize_lookup_name(candidate) == expected:
            return rating
    return None


def _fetch_probabilities_from_source(
    source: str, args: argparse.Namespace
) -> tuple[dict[str, float], str, float | None, str | None]:
    if source == "odds_api":
        odds_data = fetch_odds_from_the_odds_api(
            args.team_a,
            args.team_b,
            sport_key=args.odds_sport_key,
            regions=args.odds_regions,
            refresh=args.refresh,
        )
        probabilities = odds_data["probabilities"]
        total_goals = odds_data.get("expected_total_goals")
        total_source = None
        if total_goals is not None:
            total_market = odds_data.get("total_goals_market") or {}
            bookmaker_count = total_market.get("bookmaker_count", 0)
            total_source = (
                f"The Odds API totals ({float(total_goals):.2f}; "
                f"{bookmaker_count} Bookmaker)"
            )
        return (
            {
                "p_a": probabilities["p_a"],
                "p_draw": probabilities["p_draw"],
                "p_b": probabilities["p_b"],
            },
            odds_data.get("source", "The Odds API"),
            float(total_goals) if total_goals is not None else None,
            total_source,
        )

    if source == "football_data":
        odds_data = fetch_odds_from_football_data(
            args.team_a,
            args.team_b,
            match_id=args.football_data_match_id,
            match_date=args.match_date,
            refresh=args.refresh,
        )
        probabilities = odds_data["probabilities"]
        return (
            {
                "p_a": probabilities["p_a"],
                "p_draw": probabilities["p_draw"],
                "p_b": probabilities["p_b"],
            },
            odds_data.get("source", "football-data.org"),
            None,
            None,
        )

    if source == "api_football":
        prediction_data = fetch_predictions_from_api_football(
            args.team_a,
            args.team_b,
            fixture_id=args.api_football_fixture_id,
            match_date=args.match_date,
            refresh=args.refresh,
        )
        probabilities = prediction_data["probabilities"]
        return (
            {
                "p_a": probabilities["p_a"],
                "p_draw": probabilities["p_draw"],
                "p_b": probabilities["p_b"],
            },
            prediction_data.get("source", "API-Football predictions"),
            None,
            None,
        )

    raise ValueError(f"Unbekannte Datenquelle: {source}")


def _resolve_probabilities(
    args: argparse.Namespace,
) -> tuple[dict[str, float], str, float | None, str | None]:
    manual_values = (args.p_a, args.p_draw, args.p_b)
    if all(value is not None for value in manual_values):
        return (
            {"p_a": args.p_a, "p_draw": args.p_draw, "p_b": args.p_b},
            "manuelle CLI-Eingabe",
            None,
            None,
        )
    if any(value is not None for value in manual_values):
        raise SystemExit(
            "Unvollständige 1X2-Wahrscheinlichkeiten. Setze --p-a, --p-draw und --p-b "
            "oder lasse alle drei Werte weg."
        )

    selected_sources = _selected_probability_sources(args)
    explicit_source_selection = any(
        (args.use_odds_api, args.use_football_data, args.use_api_football)
    )
    errors: list[str] = []
    for source in selected_sources:
        try:
            return _fetch_probabilities_from_source(source, args)
        except (ValueError, DataSourceUnavailable, requests.RequestException) as error:
            message = _safe_error_message(error)
            if explicit_source_selection and len(selected_sources) == 1:
                raise SystemExit(f"Quoten fehlen: {message}") from error
            errors.append(f"{_source_label(source)}: {message}")

    details = "\n".join(f"* {error}" for error in errors)
    raise SystemExit(
        "1X2-Wahrscheinlichkeiten konnten nicht automatisch geladen werden. "
        "Setze API-Keys in .env, ergänze Match-IDs/Datum falls nötig oder nutze "
        "--p-a --p-draw --p-b.\n"
        + details
    )


def _resolve_total_goals(
    args: argparse.Namespace,
    auto_total_goals: float | None = None,
    auto_total_source: str | None = None,
) -> tuple[float, str]:
    if args.total_goals is None:
        if auto_total_goals is not None:
            return auto_total_goals, auto_total_source or "automatisch abgerufen"
        raise SystemExit(
            "Erwartete Gesamttore fehlen. Setze --total-goals oder nutze eine Quelle, "
            "die Total-Goals/Over-Under-Quoten liefert (z. B. The Odds API mit totals)."
        )
    return args.total_goals, "manuelle CLI-Eingabe"


def _resolve_elo(args: argparse.Namespace) -> tuple[float | None, float | None, str]:
    if args.elo_a is not None or args.elo_b is not None:
        if args.elo_a is None or args.elo_b is None:
            raise SystemExit("Für manuelles Elo müssen --elo-a und --elo-b gesetzt sein.")
        return args.elo_a, args.elo_b, "manuelle CLI-Eingabe"

    if args.use_elo:
        ratings = load_elo_ratings(args.elo_path, refresh=args.refresh)
        elo_a = _rating_for_team(ratings, args.team_a)
        elo_b = _rating_for_team(ratings, args.team_b)
        if elo_a is not None and elo_b is not None:
            return elo_a, elo_b, args.elo_path

        remote_source = args.elo_url or default_elo_ratings_url()
        try:
            remote_ratings = fetch_remote_elo_ratings(
                remote_source, refresh=args.refresh
            )
        except (DataSourceUnavailable, ValueError, requests.RequestException) as error:
            if ratings:
                print(
                    f"Elo nicht vollständig gefunden in {args.elo_path}; "
                    f"Remote-Elo fehlgeschlagen: {_safe_error_message(error)}. "
                    "Nutze neutrales Elo.",
                    file=sys.stderr,
                )
            else:
                print(
                    f"Remote-Elo fehlgeschlagen: {_safe_error_message(error)}. "
                    "Nutze neutrales Elo.",
                    file=sys.stderr,
                )
            return None, None, "neutral / nicht verfügbar"

        elo_a = _rating_for_team(remote_ratings, args.team_a)
        elo_b = _rating_for_team(remote_ratings, args.team_b)
        if elo_a is not None and elo_b is not None:
            return elo_a, elo_b, remote_source

        if ratings:
            print(
                f"Elo nicht vollständig gefunden in {args.elo_path} oder Remote-Quelle; "
                "nutze neutrales Elo.",
                file=sys.stderr,
            )
        elif remote_ratings:
            print(
                "Elo nicht vollständig in Remote-Quelle gefunden; nutze neutrales Elo.",
                file=sys.stderr,
            )

    return None, None, "neutral / nicht verfügbar"


def run_predict(args: argparse.Namespace) -> int:
    (
        probabilities,
        probability_source,
        auto_total_goals,
        auto_total_source,
    ) = _resolve_probabilities(args)
    total_goals, goals_source = _resolve_total_goals(
        args, auto_total_goals, auto_total_source
    )
    elo_a, elo_b, elo_source = _resolve_elo(args)

    lambda_a, lambda_b = infer_expected_goals(
        probabilities["p_a"],
        probabilities["p_draw"],
        probabilities["p_b"],
        total_goals,
        elo_a,
        elo_b,
    )
    matrix = build_score_matrix(lambda_a, lambda_b, args.max_goals)
    matrix = apply_low_score_adjustment(matrix, rho=args.rho)
    tips = rank_tips(matrix, tip_max_goals=args.tip_max_goals)
    best = tips[0]
    top_tips = tips[:5]
    top_tendency_labels = {
        _tendency_label(tip["score"], args.team_a, args.team_b) for tip in top_tips
    }
    show_tendency_per_tip = len(top_tendency_labels) > 1

    print(f"Spiel: {args.team_a} vs {args.team_b}")
    print("Datenquellen:")
    print(f"* 1X2-Wahrscheinlichkeiten: {probability_source}")
    print(f"* Erwartete Tore: {goals_source}")
    print(f"* Elo: {elo_source}")
    print()
    print(f"Empfohlener Tipp: {_format_score(best['score'])}")
    print(f"Erwartete Punkte: {best['expected_points']:.2f}")
    print(
        f"Wahrscheinlichkeit für genau {_format_score(best['score'])}: "
        f"{_probability(best['exact_probability'])}"
    )
    print(
        f"Tendenz {_tendency_label(best['score'], args.team_a, args.team_b)}: "
        f"{_probability(best['tendency_probability'])}"
    )
    print()
    print("Top 5 Tipps:")
    if not show_tendency_per_tip:
        first_tip = top_tips[0]
        print(
            f"Tendenz der Top 5: "
            f"{_tendency_label(first_tip['score'], args.team_a, args.team_b)} "
            f"({_probability(first_tip['tendency_probability'])})"
        )
    for index, tip in enumerate(top_tips, start=1):
        line = (
            f"{index}. {_format_score(tip['score'])} - EV {tip['expected_points']:.2f} "
            f"- genau dieses Ergebnis {_probability(tip['exact_probability'])}"
        )
        if show_tendency_per_tip:
            line += (
                f" - Tendenz {_tendency_label(tip['score'], args.team_a, args.team_b)} "
                f"({_probability(tip['tendency_probability'])})"
            )
        print(line)

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
