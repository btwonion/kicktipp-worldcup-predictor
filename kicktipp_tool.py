from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import timedelta
from typing import Any

import requests

from data_sources import (
    DataSourceUnavailable,
    ProviderContext,
    default_elo_ratings_url,
    fetch_odds_from_football_data,
    fetch_odds_from_the_odds_api,
    fetch_predictions_from_api_football,
    fetch_remote_elo_ratings,
    load_elo_ratings,
)
from data_sources.providers.base import ProbabilityProvider
from data_sources.team_matching import team_names_match
from models import (
    EloResult,
    PredictionInput,
    ProbabilityResult,
    apply_low_score_adjustment,
    build_score_matrix,
    infer_expected_goals,
    infer_expected_goals_from_market_difference,
)
from scoring import RankedTip, rank_tips

SECRET_URL_PARAM_RE = re.compile(r"([?&](?:apiKey|key)=)[^&\s)]+")


def _format_score(score: tuple[int, int]) -> str:
    return f"{score[0]}:{score[1]}"


def _probability(value: float) -> str:
    return f"{value * 100:.1f} %"


def _compact_probability(value: float) -> str:
    return f"{value * 100:.1f}%"


def _color(text: str, *codes: str) -> str:
    return f"\033[{';'.join(codes)}m{text}\033[0m"


def _display_score(score: tuple[int, int]) -> str:
    return f"{score[0]}–{score[1]}"


def _format_number(value: float) -> str:
    return f"{value:g}"


def _format_elo_signal(elo: EloResult, team_a: str) -> str:
    if elo.elo_a is None or elo.elo_b is None:
        return elo.source

    diff = elo.elo_a - elo.elo_b
    return f"{team_a} {diff:+g}"


def _format_handicap_line(
    expected_goal_difference: float | None, team_a: str
) -> str:
    if expected_goal_difference is None:
        return "not available"
    return f"{team_a} {expected_goal_difference:+.2f}"


def _boxed_summary(
    team_a: str,
    team_b: str,
    best: RankedTip,
) -> list[str]:
    title = f"{team_a} vs {team_b}"
    lines = [
        f"Pick: {team_a} {_display_score(best['score'])} {team_b}",
        (
            f"Confidence: {_tendency_label(best['score'], team_a, team_b)} "
            f"{_compact_probability(best['tendency_probability'])}"
        ),
        f"Exact score probability: {_compact_probability(best['exact_probability'])}",
        f"Expected points: {best['expected_points']:.2f}",
    ]
    width = max(53, len(title) + 4, *(len(line) for line in lines))
    top = f"┌─ {title} " + "─" * max(1, width - len(title) - 1) + "┐"
    bottom = "└" + "─" * (width + 2) + "┘"
    return [
        _color(top, "1", "36"),
        *(
            f"{_color('│', '1', '36')} {line.ljust(width)} "
            f"{_color('│', '1', '36')}"
            for line in lines
        ),
        _color(bottom, "1", "36"),
    ]


def _tendency_label(score: tuple[int, int], team_a: str, team_b: str) -> str:
    goals_a, goals_b = score
    if goals_a > goals_b:
        return f"{team_a} win"
    if goals_a < goals_b:
        return f"{team_b} win"
    return "draw"


def _add_predict_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("predict", help="Generate a Kicktipp tip.")
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
        help="Load Elo ratings. Enabled by default.",
    )
    parser.add_argument(
        "--no-elo",
        action="store_false",
        dest="use_elo",
        help="Do not load Elo ratings automatically.",
    )
    parser.add_argument("--elo-path", default="data/elo_ratings.csv")
    parser.add_argument(
        "--elo-url",
        help=(
            "Remote source for Elo ratings. Default: international-football.net "
            "for the current date."
        ),
    )
    parser.add_argument(
        "--use-odds-api",
        action="store_true",
        help="Restrict automatic 1X2 lookup to The Odds API.",
    )
    parser.add_argument(
        "--use-football-data",
        action="store_true",
        help="Restrict automatic 1X2 lookup to football-data.org.",
    )
    parser.add_argument(
        "--use-api-football",
        action="store_true",
        help="Restrict automatic 1X2 lookup to API-Football predictions.",
    )
    parser.add_argument(
        "--match-date",
        help="Match date in YYYY-MM-DD format for football-data.org/API-Football.",
    )
    parser.add_argument("--football-data-match-id", type=int)
    parser.add_argument("--api-football-fixture-id", type=int)
    parser.add_argument(
        "--odds-sport-key",
        default="soccer_fifa_world_cup",
        help="The Odds API sport key, e.g. soccer_fifa_world_cup or soccer_epl.",
    )
    parser.add_argument("--odds-regions", default="eu")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Do not read from or write to the cache.",
    )
    parser.add_argument(
        "--cache-ttl",
        type=float,
        default=None,
        help="Cache TTL in hours. Default: 24.",
    )
    parser.add_argument("--json", action="store_true", dest="output_json")
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print the recommended tip.",
    )
    parser.add_argument("--max-goals", type=int, default=6)
    parser.add_argument("--tip-max-goals", type=int, default=5)
    parser.add_argument("--rho", type=float, default=-0.08)
    parser.set_defaults(func=run_predict)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local Kicktipp tool with Poisson model and EV ranking."
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
    return _provider_map()[source].label


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
        if team_names_match(team_name, [candidate], allow_fuzzy=False):
            return rating
    return None


def _cache_ttl(args: argparse.Namespace) -> timedelta | None:
    value = getattr(args, "cache_ttl", None)
    if value is None:
        return None
    if value < 0:
        raise SystemExit("--cache-ttl must be >= 0.")
    return timedelta(hours=value)


class _CliProbabilityProvider:
    def __init__(self, name: str, label: str) -> None:
        self.name = name
        self.label = label

    def fetch(self, context: ProviderContext) -> ProbabilityResult:
        return _fetch_probabilities_from_source(self.name, context)


def _provider_map() -> dict[str, ProbabilityProvider]:
    return {
        "odds_api": _CliProbabilityProvider("odds_api", "The Odds API"),
        "football_data": _CliProbabilityProvider("football_data", "football-data.org"),
        "api_football": _CliProbabilityProvider(
            "api_football", "API-Football predictions"
        ),
    }


def _provider_context(args: argparse.Namespace) -> ProviderContext:
    return ProviderContext(
        team_a=args.team_a,
        team_b=args.team_b,
        refresh=getattr(args, "refresh", False),
        cache_dir=getattr(args, "cache_dir", None),
        no_cache=getattr(args, "no_cache", False),
        cache_ttl=_cache_ttl(args),
        match_date=getattr(args, "match_date", None),
        football_data_match_id=getattr(args, "football_data_match_id", None),
        api_football_fixture_id=getattr(args, "api_football_fixture_id", None),
        odds_sport_key=getattr(args, "odds_sport_key", "soccer_fifa_world_cup"),
        odds_regions=getattr(args, "odds_regions", "eu"),
    )


def _fetch_probabilities_from_source(
    source: str, context: ProviderContext
) -> ProbabilityResult:
    if source == "odds_api":
        odds_data = fetch_odds_from_the_odds_api(
            context.team_a,
            context.team_b,
            sport_key=context.odds_sport_key,
            regions=context.odds_regions,
            refresh=context.refresh,
            cache_ttl=context.cache_ttl,
            cache_dir=context.cache_dir,
            no_cache=context.no_cache,
        )
        probabilities = odds_data["probabilities"]
        total_goals = odds_data.get("expected_total_goals")
        total_source = None
        if total_goals is not None:
            total_market = odds_data.get("total_goals_market") or {}
            bookmaker_count = total_market.get("bookmaker_count", 0)
            total_source = (
                f"The Odds API totals ({float(total_goals):.2f}; "
                f"{bookmaker_count} bookmakers)"
            )
        expected_goal_difference = odds_data.get("expected_goal_difference")
        goal_difference_source = None
        if expected_goal_difference is not None:
            spread_market = odds_data.get("spread_market") or {}
            bookmaker_count = spread_market.get("bookmaker_count", 0)
            goal_difference_source = (
                f"The Odds API spreads ({float(expected_goal_difference):+.2f}; "
                f"{bookmaker_count} bookmakers)"
            )
        return ProbabilityResult(
            p_a=probabilities["p_a"],
            p_draw=probabilities["p_draw"],
            p_b=probabilities["p_b"],
            source=odds_data.get("source", "The Odds API"),
            expected_total_goals=(
                float(total_goals) if total_goals is not None else None
            ),
            total_goals_source=total_source,
            expected_goal_difference=(
                float(expected_goal_difference)
                if expected_goal_difference is not None
                else None
            ),
            goal_difference_source=goal_difference_source,
            raw=odds_data,
        )

    if source == "football_data":
        odds_data = fetch_odds_from_football_data(
            context.team_a,
            context.team_b,
            match_id=context.football_data_match_id,
            match_date=context.match_date,
            refresh=context.refresh,
            cache_ttl=context.cache_ttl,
            cache_dir=context.cache_dir,
            no_cache=context.no_cache,
        )
        probabilities = odds_data["probabilities"]
        return ProbabilityResult(
            p_a=probabilities["p_a"],
            p_draw=probabilities["p_draw"],
            p_b=probabilities["p_b"],
            source=odds_data.get("source", "football-data.org"),
            raw=odds_data,
        )

    if source == "api_football":
        prediction_data = fetch_predictions_from_api_football(
            context.team_a,
            context.team_b,
            fixture_id=context.api_football_fixture_id,
            match_date=context.match_date,
            refresh=context.refresh,
            cache_ttl=context.cache_ttl,
            cache_dir=context.cache_dir,
            no_cache=context.no_cache,
        )
        probabilities = prediction_data["probabilities"]
        return ProbabilityResult(
            p_a=probabilities["p_a"],
            p_draw=probabilities["p_draw"],
            p_b=probabilities["p_b"],
            source=prediction_data.get("source", "API-Football predictions"),
            raw=prediction_data,
        )

    raise ValueError(f"Unknown data source: {source}")


def _resolve_probabilities(args: argparse.Namespace) -> ProbabilityResult:
    manual_values = (args.p_a, args.p_draw, args.p_b)
    if all(value is not None for value in manual_values):
        return ProbabilityResult(
            p_a=args.p_a,
            p_draw=args.p_draw,
            p_b=args.p_b,
            source="manual CLI input",
        )
    if any(value is not None for value in manual_values):
        raise SystemExit(
            "Incomplete 1X2 probabilities. Set --p-a, --p-draw, and --p-b "
            "or omit all three values."
        )

    selected_sources = _selected_probability_sources(args)
    explicit_source_selection = any(
        (args.use_odds_api, args.use_football_data, args.use_api_football)
    )
    errors: list[str] = []
    context = _provider_context(args)
    providers = _provider_map()
    for source in selected_sources:
        try:
            return providers[source].fetch(context)
        except (ValueError, DataSourceUnavailable, requests.RequestException) as error:
            message = _safe_error_message(error)
            if explicit_source_selection and len(selected_sources) == 1:
                raise SystemExit(f"Odds are missing: {message}") from error
            errors.append(f"{_source_label(source)}: {message}")

    details = "\n".join(f"* {error}" for error in errors)
    raise SystemExit(
        "1X2 probabilities could not be loaded automatically. "
        "Set API keys in .env, add match IDs/date if needed, or use "
        "--p-a --p-draw --p-b.\n"
        + details
    )


def _resolve_total_goals(
    args: argparse.Namespace,
    probabilities: ProbabilityResult | None = None,
) -> tuple[float, str]:
    if args.total_goals is None:
        if probabilities is not None and probabilities.expected_total_goals is not None:
            return (
                probabilities.expected_total_goals,
                probabilities.total_goals_source or "automatic lookup",
            )
        raise SystemExit(
            "Expected total goals are missing. Set --total-goals or use a source "
            "that provides total-goals/over-under odds (e.g. The Odds API with totals)."
        )
    return args.total_goals, "manual CLI input"


def _resolve_elo(args: argparse.Namespace) -> EloResult:
    if args.elo_a is not None or args.elo_b is not None:
        if args.elo_a is None or args.elo_b is None:
            raise SystemExit(
                "Manual Elo requires both --elo-a and --elo-b."
            )
        return EloResult(args.elo_a, args.elo_b, "manual CLI input")

    if args.use_elo:
        ratings = load_elo_ratings(
            args.elo_path,
            refresh=getattr(args, "refresh", False),
            cache_ttl=_cache_ttl(args),
            cache_dir=getattr(args, "cache_dir", None),
            no_cache=getattr(args, "no_cache", False),
        )
        elo_a = _rating_for_team(ratings, args.team_a)
        elo_b = _rating_for_team(ratings, args.team_b)
        if elo_a is not None and elo_b is not None:
            return EloResult(elo_a, elo_b, args.elo_path)

        remote_source = args.elo_url or default_elo_ratings_url()
        try:
            if any(
                hasattr(args, name)
                for name in ("cache_ttl", "cache_dir", "no_cache")
            ):
                remote_ratings = fetch_remote_elo_ratings(
                    remote_source,
                    refresh=getattr(args, "refresh", False),
                    cache_ttl=_cache_ttl(args),
                    cache_dir=getattr(args, "cache_dir", None),
                    no_cache=getattr(args, "no_cache", False),
                )
            else:
                remote_ratings = fetch_remote_elo_ratings(
                    remote_source, refresh=getattr(args, "refresh", False)
                )
        except (DataSourceUnavailable, ValueError, requests.RequestException) as error:
            if ratings:
                print(
                    f"Elo was not fully found in {args.elo_path}; "
                    f"remote Elo failed: {_safe_error_message(error)}. "
                    "Using neutral Elo.",
                    file=sys.stderr,
                )
            else:
                print(
                    f"Remote Elo failed: {_safe_error_message(error)}. "
                    "Using neutral Elo.",
                    file=sys.stderr,
                )
            return EloResult(None, None, "neutral / unavailable")

        elo_a = _rating_for_team(remote_ratings, args.team_a)
        elo_b = _rating_for_team(remote_ratings, args.team_b)
        if elo_a is not None and elo_b is not None:
            return EloResult(elo_a, elo_b, remote_source)

        if ratings:
            print(
                f"Elo was not fully found in {args.elo_path} or the "
                "remote source; "
                "using neutral Elo.",
                file=sys.stderr,
            )
        elif remote_ratings:
            print(
                "Elo was not fully found in the remote source; using neutral Elo.",
                file=sys.stderr,
            )

    return EloResult(None, None, "neutral / unavailable")


def _tip_payload(tip: RankedTip, team_a: str, team_b: str) -> dict[str, Any]:
    return {
        "score": _format_score(tip["score"]),
        "score_tuple": list(tip["score"]),
        "expected_points": tip["expected_points"],
        "exact_probability": tip["exact_probability"],
        "tendency": _tendency_label(tip["score"], team_a, team_b),
        "tendency_probability": tip["tendency_probability"],
    }


def _prediction_payload(
    prediction_input: PredictionInput,
    lambda_a: float,
    lambda_b: float,
    best: RankedTip,
    top_tips: list[RankedTip],
) -> dict[str, Any]:
    return {
        "match": {
            "team_a": prediction_input.team_a,
            "team_b": prediction_input.team_b,
        },
        "data_sources": {
            "probabilities": prediction_input.probabilities.source,
            "total_goals": prediction_input.probabilities.total_goals_source
            or "manual CLI input",
            "elo": prediction_input.elo.source,
        },
        "inputs": {
            "p_a": prediction_input.probabilities.p_a,
            "p_draw": prediction_input.probabilities.p_draw,
            "p_b": prediction_input.probabilities.p_b,
            "total_goals": prediction_input.total_goals,
            "expected_goal_difference": (
                prediction_input.probabilities.expected_goal_difference
            ),
            "elo_a": prediction_input.elo.elo_a,
            "elo_b": prediction_input.elo.elo_b,
        },
        "model": {
            "lambda_a": lambda_a,
            "lambda_b": lambda_b,
            "goal_difference_source": (
                prediction_input.probabilities.goal_difference_source
            ),
        },
        "recommendation": _tip_payload(
            best, prediction_input.team_a, prediction_input.team_b
        ),
        "top_tips": [
            _tip_payload(tip, prediction_input.team_a, prediction_input.team_b)
            for tip in top_tips
        ],
    }


def run_predict(args: argparse.Namespace) -> int:
    probabilities = _resolve_probabilities(args)
    total_goals, goals_source = _resolve_total_goals(args, probabilities)
    elo = _resolve_elo(args)
    prediction_input = PredictionInput(
        team_a=args.team_a,
        team_b=args.team_b,
        probabilities=probabilities,
        total_goals=total_goals,
        elo=elo,
    )

    if probabilities.expected_goal_difference is None:
        lambda_a, lambda_b = infer_expected_goals(
            probabilities.p_a,
            probabilities.p_draw,
            probabilities.p_b,
            total_goals,
            elo.elo_a,
            elo.elo_b,
        )
    else:
        lambda_a, lambda_b = infer_expected_goals_from_market_difference(
            total_goals,
            probabilities.expected_goal_difference,
        )
    matrix = build_score_matrix(lambda_a, lambda_b, args.max_goals)
    matrix = apply_low_score_adjustment(matrix, rho=args.rho)
    tips = rank_tips(matrix, tip_max_goals=args.tip_max_goals)
    best = tips[0]
    top_tips = tips[:5]

    if getattr(args, "output_json", False):
        payload = _prediction_payload(
            prediction_input, lambda_a, lambda_b, best, top_tips
        )
        payload["data_sources"]["total_goals"] = goals_source
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if getattr(args, "quiet", False):
        print(_format_score(best["score"]))
        return 0

    for line in _boxed_summary(args.team_a, args.team_b, best):
        print(line)
    print()
    print(_color("Key model signals", "1", "36"))
    print(
        f"  {'xG':<15} {args.team_a} {lambda_a:.2f}   "
        f"{args.team_b} {lambda_b:.2f}"
    )
    print(f"  {'Total goals':<15} {total_goals:.2f}")
    print(
        f"  {'Handicap':<15} "
        f"{_format_handicap_line(probabilities.expected_goal_difference, args.team_a)}"
    )
    print(f"  {'Elo':<15} {_format_elo_signal(elo, args.team_a)}")
    print()
    print(_color("1X2 probabilities", "1", "36"))
    print(f"  {args.team_a:<15} {_compact_probability(probabilities.p_a)}")
    print(f"  {'Draw':<15} {_compact_probability(probabilities.p_draw)}")
    print(f"  {args.team_b:<15} {_compact_probability(probabilities.p_b)}")
    print()
    print(_color("Top scorelines", "1", "36"))
    for index, tip in enumerate(top_tips, start=1):
        print(
            f"  {index}. {_display_score(tip['score'])}  "
            f"{_tendency_label(tip['score'], args.team_a, args.team_b)}   "
            f"EV {tip['expected_points']:.2f}   "
            f"Prob {_compact_probability(tip['exact_probability']):>5}"
        )

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
