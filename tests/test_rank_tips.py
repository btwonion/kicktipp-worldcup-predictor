from models import apply_low_score_adjustment, build_score_matrix, infer_expected_goals
from scoring import rank_tips


def test_rank_tips_returns_sorted_results():
    matrix = build_score_matrix(1.2, 1.1, max_goals=6)
    tips = rank_tips(matrix, tip_max_goals=5)

    assert tips
    assert tips[0]["expected_points"] >= tips[1]["expected_points"]


def test_balanced_match_has_one_one_near_top():
    lambda_a, lambda_b = infer_expected_goals(0.35, 0.30, 0.35, 2.4)
    matrix = apply_low_score_adjustment(build_score_matrix(lambda_a, lambda_b, 6))
    top_scores = [tip["score"] for tip in rank_tips(matrix, tip_max_goals=5)[:5]]

    assert (1, 1) in top_scores


def test_clear_favorite_has_favorite_win_near_top():
    lambda_a, lambda_b = infer_expected_goals(0.62, 0.23, 0.15, 2.7, 2100, 1850)
    matrix = apply_low_score_adjustment(build_score_matrix(lambda_a, lambda_b, 7))
    top_scores = [tip["score"] for tip in rank_tips(matrix, tip_max_goals=5)[:5]]

    assert any(score in top_scores for score in [(1, 0), (2, 0), (2, 1)])


def test_market_goal_difference_raises_blowout_tip_for_strong_favorite():
    default_lambda_a, default_lambda_b = infer_expected_goals(0.86, 0.09, 0.05, 3.5)
    default_matrix = apply_low_score_adjustment(
        build_score_matrix(default_lambda_a, default_lambda_b, 8)
    )
    default_top_scores = [
        tip["score"] for tip in rank_tips(default_matrix, tip_max_goals=5)[:5]
    ]

    market_matrix = apply_low_score_adjustment(build_score_matrix(3.0, 0.5, 8))
    market_top_scores = [
        tip["score"] for tip in rank_tips(market_matrix, tip_max_goals=5)[:5]
    ]

    assert (4, 0) not in default_top_scores
    assert (4, 0) in market_top_scores
