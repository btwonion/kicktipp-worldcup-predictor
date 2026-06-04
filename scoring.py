from __future__ import annotations


Score = tuple[int, int]


def _outcome(score: Score) -> int:
    goals_a, goals_b = score
    if goals_a > goals_b:
        return 1
    if goals_a < goals_b:
        return -1
    return 0


def kicktipp_points(predicted_score: Score, actual_score: Score) -> int:
    if predicted_score == actual_score:
        return 4

    predicted_outcome = _outcome(predicted_score)
    actual_outcome = _outcome(actual_score)
    if predicted_outcome != actual_outcome:
        return 0

    if predicted_outcome == 0:
        return 2

    predicted_diff = predicted_score[0] - predicted_score[1]
    actual_diff = actual_score[0] - actual_score[1]
    if predicted_diff == actual_diff:
        return 3

    return 2


def expected_kicktipp_points(
    predicted_score: Score, score_matrix: dict[Score, float]
) -> float:
    return sum(
        probability * kicktipp_points(predicted_score, actual_score)
        for actual_score, probability in score_matrix.items()
    )


def tendency_probability(predicted_score: Score, score_matrix: dict[Score, float]) -> float:
    predicted_outcome = _outcome(predicted_score)
    return sum(
        probability
        for actual_score, probability in score_matrix.items()
        if _outcome(actual_score) == predicted_outcome
    )


def rank_tips(
    score_matrix: dict[Score, float], tip_max_goals: int = 5
) -> list[dict[str, object]]:
    tips: list[dict[str, object]] = []
    for goals_a in range(tip_max_goals + 1):
        for goals_b in range(tip_max_goals + 1):
            predicted = (goals_a, goals_b)
            tips.append(
                {
                    "score": predicted,
                    "expected_points": expected_kicktipp_points(predicted, score_matrix),
                    "exact_probability": score_matrix.get(predicted, 0.0),
                    "tendency_probability": tendency_probability(predicted, score_matrix),
                }
            )

    return sorted(
        tips,
        key=lambda item: (
            item["expected_points"],
            item["exact_probability"],
            -sum(item["score"]),
        ),
        reverse=True,
    )
