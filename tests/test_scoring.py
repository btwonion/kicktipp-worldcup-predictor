from scoring import kicktipp_points


def test_exact_score_scores_four_points():
    assert kicktipp_points((2, 1), (2, 1)) == 4


def test_same_goal_difference_scores_three_points():
    assert kicktipp_points((1, 0), (2, 1)) == 3


def test_same_tendency_scores_two_points():
    assert kicktipp_points((1, 0), (3, 1)) == 2


def test_wrong_tendency_scores_zero_points():
    assert kicktipp_points((1, 0), (0, 1)) == 0


def test_different_draw_scores_two_points():
    assert kicktipp_points((1, 1), (2, 2)) == 2


def test_exact_draw_scores_four_points():
    assert kicktipp_points((0, 0), (0, 0)) == 4
