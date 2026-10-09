
import pytest


def calculate_final_score(
    semantic_score,
    role_score,
    skill_score
):
    return (
        0.50 * semantic_score
        + 0.30 * role_score
        + 0.20 * skill_score
    )


@pytest.mark.parametrize(
    "semantic, role, skill, expected",
    [
        (100, 100, 100, 100),
        (0, 0, 0, 0),
        (80, 60, 90, 76),
        (50, 50, 50, 50),
        (100, 0, 0, 50),
        (0, 100, 0, 30),
        (0, 0, 100, 20),
    ]
)
def test_weighted_score(
    semantic,
    role,
    skill,
    expected
):
    result = calculate_final_score(
        semantic,
        role,
        skill
    )

    assert result == pytest.approx(expected)


def test_score_bounds():
    for semantic in [0, 50, 100]:
        for role in [0, 50, 100]:
            for skill in [0, 50, 100]:

                score = calculate_final_score(
                    semantic,
                    role,
                    skill
                )

                assert 0 <= score <= 100


def test_weights_sum_to_one():
    weights = [0.50, 0.30, 0.20]

    assert sum(weights) == pytest.approx(1.0)
