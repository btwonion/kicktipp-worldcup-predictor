from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

Score = tuple[int, int]


@dataclass(frozen=True)
class ProbabilityResult:
    p_a: float
    p_draw: float
    p_b: float
    source: str
    expected_total_goals: float | None = None
    total_goals_source: str | None = None
    expected_goal_difference: float | None = None
    goal_difference_source: str | None = None
    raw: dict[str, Any] | None = None

    @property
    def probabilities(self) -> dict[str, float]:
        return {"p_a": self.p_a, "p_draw": self.p_draw, "p_b": self.p_b}


@dataclass(frozen=True)
class EloResult:
    elo_a: float | None
    elo_b: float | None
    source: str


@dataclass(frozen=True)
class PredictionInput:
    team_a: str
    team_b: str
    probabilities: ProbabilityResult
    total_goals: float
    elo: EloResult


def poisson_pmf(k: int, lambda_: float) -> float:
    if k < 0:
        raise ValueError("k must be >= 0.")
    if lambda_ <= 0:
        raise ValueError("lambda_ must be > 0.")
    return math.exp(-lambda_) * (lambda_**k) / math.factorial(k)


def _normalize(score_matrix: dict[Score, float]) -> dict[Score, float]:
    total = sum(score_matrix.values())
    if total <= 0:
        raise ValueError("Score matrix has no positive total probability.")
    return {score: probability / total for score, probability in score_matrix.items()}


def build_score_matrix(
    lambda_a: float, lambda_b: float, max_goals: int
) -> dict[Score, float]:
    if lambda_a <= 0 or lambda_b <= 0:
        raise ValueError("lambda_a and lambda_b must be > 0.")
    if max_goals < 4:
        raise ValueError("max_goals must be at least 4.")

    matrix: dict[Score, float] = {}
    for goals_a in range(max_goals + 1):
        p_a = poisson_pmf(goals_a, lambda_a)
        for goals_b in range(max_goals + 1):
            matrix[(goals_a, goals_b)] = p_a * poisson_pmf(goals_b, lambda_b)
    return _normalize(matrix)


def infer_expected_goals(
    p_a: float,
    p_draw: float,
    p_b: float,
    total_goals: float,
    elo_a: float | None = None,
    elo_b: float | None = None,
) -> tuple[float, float]:
    for name, value in {"p_a": p_a, "p_draw": p_draw, "p_b": p_b}.items():
        if not 0 <= value <= 1:
            raise ValueError(f"{name} must be between 0 and 1.")
    probability_sum = p_a + p_draw + p_b
    if not math.isclose(probability_sum, 1.0, abs_tol=0.04):
        raise ValueError("1X2 probabilities must add up to approximately 1.")
    if total_goals <= 0:
        raise ValueError("total_goals must be > 0.")

    normalized_p_a = p_a / probability_sum
    normalized_p_b = p_b / probability_sum

    market_signal = math.log((normalized_p_a + 0.08) / (normalized_p_b + 0.08))
    elo_signal = 0.0
    if elo_a is not None and elo_b is not None:
        elo_signal = (elo_a - elo_b) / 400.0 * math.log(10)

    combined_signal = market_signal + 0.25 * elo_signal
    share_a = 1 / (1 + math.exp(-combined_signal))

    # Avoid unrealistic zero-attack estimates while keeping the requested total.
    share_a = min(max(share_a, 0.18), 0.82)
    lambda_a = total_goals * share_a
    lambda_b = total_goals - lambda_a
    return lambda_a, lambda_b


def infer_expected_goals_from_market_difference(
    total_goals: float,
    expected_goal_difference: float,
) -> tuple[float, float]:
    if total_goals <= 0:
        raise ValueError("total_goals must be > 0.")
    if abs(expected_goal_difference) >= total_goals:
        raise ValueError(
            "expected_goal_difference must be smaller than total_goals."
        )

    lambda_a = (total_goals + expected_goal_difference) / 2
    lambda_b = total_goals - lambda_a
    return lambda_a, lambda_b


def apply_low_score_adjustment(
    score_matrix: dict[Score, float], rho: float = -0.08
) -> dict[Score, float]:
    adjusted = dict(score_matrix)

    # Dixon-Coles-style small correction for the most common low-score cells.
    intensity = 2.5
    factors = {
        (0, 0): 1 - intensity * rho,
        (0, 1): 1 + intensity * rho,
        (1, 0): 1 + intensity * rho,
        (1, 1): 1 - intensity * rho,
    }
    for score, factor in factors.items():
        if score in adjusted:
            adjusted[score] = max(0.0, adjusted[score] * factor)

    return _normalize(adjusted)
