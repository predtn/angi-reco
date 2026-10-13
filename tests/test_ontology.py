"""The 12-dimension ontology and the rules that turn scores into vectors (Design §2.2, §2.4)."""

import math

import pytest

from app.core.ontology import (
    DIMENSION_COUNT,
    DIMENSION_DEFINITIONS,
    DIMENSIONS,
    FOOD_CHARACTERISTICS,
    FOOD_SENSATIONS,
    FOOD_TASTES,
    ONTOLOGY_VERSION,
    SCALE,
    OntologyError,
    describe_dimensions,
    scores_from_vector,
    vector_from_scores,
)


def _scores(**overrides: object) -> dict[str, object]:
    scores: dict[str, object] = dict.fromkeys(DIMENSIONS, 0.0)
    scores["umami"] = 0.75
    scores.update(overrides)
    return scores


def test_dimensions_follow_the_design_table() -> None:
    assert DIMENSIONS == (
        "sweet",
        "sour",
        "salty",
        "bitter",
        "umami",
        "spicy",
        "cooling",
        "astringent",
        "fatty",
        "fresh",
        "rich",
        "aromatic",
    )
    assert DIMENSION_COUNT == 12
    assert ONTOLOGY_VERSION == 1
    assert SCALE == (0.0, 0.25, 0.5, 0.75, 1.0)


def test_dimensions_are_grouped_as_in_the_design() -> None:
    groups = [dimension.group for dimension in DIMENSION_DEFINITIONS]

    assert groups == [FOOD_TASTES] * 5 + [FOOD_SENSATIONS] * 3 + [FOOD_CHARACTERISTICS] * 4
    assert all(dimension.meaning for dimension in DIMENSION_DEFINITIONS)


def test_vector_follows_dimension_order_whatever_the_key_order() -> None:
    scores = {name: index / 20 for index, name in enumerate(DIMENSIONS)}
    shuffled = dict(reversed(list(scores.items())))

    vector = vector_from_scores(shuffled)

    assert vector == [index / 20 for index in range(DIMENSION_COUNT)]


def test_vector_keeps_values_off_the_discrete_scale() -> None:
    vector = vector_from_scores(_scores(spicy=0.6, rich=1))

    assert vector[DIMENSIONS.index("spicy")] == 0.6
    assert vector[DIMENSIONS.index("rich")] == 1.0


@pytest.mark.parametrize(
    "scores",
    [
        {name: 0.5 for name in DIMENSIONS if name != "aromatic"},
        _scores(note="broth heavy"),
        {**{name: 0.5 for name in DIMENSIONS if name != "umami"}, "umani": 0.5},
    ],
    ids=["missing", "extra", "misspelt"],
)
def test_vector_rejects_missing_or_unknown_keys(scores: dict[str, object]) -> None:
    with pytest.raises(OntologyError):
        vector_from_scores(scores)


@pytest.mark.parametrize("value", [-0.25, 1.25, math.nan, math.inf, True, "0.5", None])
def test_vector_rejects_scores_that_are_not_numbers_in_range(value: object) -> None:
    with pytest.raises(OntologyError):
        vector_from_scores(_scores(sweet=value))


def test_zero_vector_is_rejected_for_a_dish_and_allowed_for_a_survey_option() -> None:
    zero = dict.fromkeys(DIMENSIONS, 0)

    with pytest.raises(OntologyError):
        vector_from_scores(zero)
    assert vector_from_scores(zero, allow_zero=True) == [0.0] * DIMENSION_COUNT


def test_scores_round_trip_through_a_vector() -> None:
    scores = {name: index / 20 for index, name in enumerate(DIMENSIONS)}

    assert scores_from_vector(vector_from_scores(scores)) == scores


def test_scores_from_vector_rejects_a_wrong_length() -> None:
    with pytest.raises(OntologyError):
        scores_from_vector([0.5] * 11)


def test_prompt_description_lists_every_dimension_in_order() -> None:
    lines = describe_dimensions().splitlines()

    assert len(lines) == DIMENSION_COUNT
    assert lines[0] == "0. sweet (food_tastes): Vị ngọt"
    assert lines[11].startswith("11. aromatic (food_characteristics): ")
    assert [line.split(" ")[1] for line in lines] == list(DIMENSIONS)
