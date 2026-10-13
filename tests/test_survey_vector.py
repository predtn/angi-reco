"""Survey answers -> user vector (Recommendation_System_Design_Ver1.1 §3.2), without a database."""

import pytest

from app.core.ontology import DIMENSIONS
from app.services.survey import WeightedOption, build_user_vector


def _option(scale: float = 1.0, **scores: float) -> WeightedOption:
    return WeightedOption(
        vec=[scores.get(name, 0.0) for name in DIMENSIONS],
        dim_mask=[1.0 if name in scores else 0.0 for name in DIMENSIONS],
        scale=scale,
    )


def _vector(**scores: float) -> list[float]:
    return [scores.get(name, 0.0) for name in DIMENSIONS]


def test_example_of_the_survey_document() -> None:
    # spicy_medium, broth_rich, herbs_lots (Preference_Survey_Ver1.0, Example)
    answers = [
        _option(spicy=0.5),
        _option(umami=1, rich=1, fatty=0.5),
        _option(aromatic=1, fresh=0.75),
    ]

    assert build_user_vector(answers) == _vector(
        spicy=0.5, umami=1, rich=1, fatty=0.5, aromatic=1, fresh=0.75
    )


def test_options_touching_the_same_dimension_are_averaged_by_scale_value() -> None:
    # fresh: (1 * 0.75 + 0.5 * 1) / (1 + 0.5) = 0.8333...
    answers = [_option(aromatic=1, fresh=0.75), _option(0.5, cooling=1, fresh=1)]

    vector = build_user_vector(answers)

    assert vector is not None
    assert vector[DIMENSIONS.index("fresh")] == pytest.approx(1.25 / 1.5)
    assert vector[DIMENSIONS.index("aromatic")] == 1
    assert vector[DIMENSIONS.index("cooling")] == 1


def test_a_zero_intensity_answer_pulls_its_dimension_down() -> None:
    # spicy_none and spicy_very_hot together give 0.5, not 1: the 0 answer has an opinion.
    vector = build_user_vector([_option(spicy=0), _option(spicy=1), _option(sweet=0.5)])

    assert vector == _vector(spicy=0.5, sweet=0.5)


def test_dimensions_no_answer_touches_stay_zero() -> None:
    vector = build_user_vector([_option(sour=1)])

    assert vector == _vector(sour=1)


@pytest.mark.parametrize(
    "answers",
    [[], [_option(spicy=0), _option(sweet=0)], [_option(0.0, spicy=1)]],
    ids=["skipped", "only-zero-options", "zero-scale"],
)
def test_no_vector_when_the_result_is_zero(answers: list[WeightedOption]) -> None:
    assert build_user_vector(answers) is None
