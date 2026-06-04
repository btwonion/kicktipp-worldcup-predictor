import pytest

from models import (
    build_score_matrix,
    infer_expected_goals,
    infer_expected_goals_from_market_difference,
    poisson_pmf,
)


def test_poisson_probabilities_are_positive():
    assert poisson_pmf(0, 1.4) > 0
    assert poisson_pmf(3, 1.4) > 0


def test_score_matrix_is_normalized():
    matrix = build_score_matrix(1.3, 1.1, max_goals=6)
    assert sum(matrix.values()) == pytest.approx(1.0)


def test_higher_lambda_shifts_probability_to_higher_scores():
    low = build_score_matrix(0.8, 0.8, max_goals=8)
    high = build_score_matrix(1.8, 1.8, max_goals=8)

    low_high_score_probability = sum(
        probability for (a, b), probability in low.items() if a + b >= 4
    )
    high_high_score_probability = sum(
        probability for (a, b), probability in high.items() if a + b >= 4
    )

    assert high_high_score_probability > low_high_score_probability


def test_infer_expected_goals_preserves_total_and_favors_stronger_side():
    lambda_a, lambda_b = infer_expected_goals(0.55, 0.25, 0.20, 2.6, 2050, 1900)

    assert lambda_a + lambda_b == pytest.approx(2.6)
    assert lambda_a > lambda_b


def test_market_goal_difference_directly_shapes_expected_goals():
    lambda_a, lambda_b = infer_expected_goals_from_market_difference(3.5, 2.5)

    assert lambda_a + lambda_b == pytest.approx(3.5)
    assert lambda_a - lambda_b == pytest.approx(2.5)
    assert lambda_a == pytest.approx(3.0)
    assert lambda_b == pytest.approx(0.5)
