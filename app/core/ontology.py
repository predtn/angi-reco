"""Food ontology shared by dish and user vectors (Recommendation_System_Design_Ver1.1 §2).

The order of DIMENSIONS is the order inside every vector(12) column. Changing it, or the number
of dimensions, invalidates every stored vector: bump ONTOLOGY_VERSION and regenerate them.

Dish scores from the AI and survey option vectors become vectors only through
`vector_from_scores`, so every vector in schema recommendation has the same order and range.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

ONTOLOGY_VERSION = 1


@dataclass(frozen=True)
class Dimension:
    """One axis of the ontology (Design §2.2): its key, its group and what it measures."""

    name: str
    group: str
    meaning: str


FOOD_TASTES = "food_tastes"
FOOD_SENSATIONS = "food_sensations"
FOOD_CHARACTERISTICS = "food_characteristics"

# Design §2.2, in vector order. `meaning` is the definition given to the AI (§2.4).
DIMENSION_DEFINITIONS: tuple[Dimension, ...] = (
    Dimension("sweet", FOOD_TASTES, "Vị ngọt"),
    Dimension("sour", FOOD_TASTES, "Vị chua"),
    Dimension("salty", FOOD_TASTES, "Vị mặn"),
    Dimension("bitter", FOOD_TASTES, "Vị đắng"),
    Dimension("umami", FOOD_TASTES, "Vị umami (ngọt thịt, đậm từ nước dùng, hải sản, nước mắm)"),
    Dimension("spicy", FOOD_SENSATIONS, "Độ cay"),
    Dimension("cooling", FOOD_SENSATIONS, "Cảm giác mát"),
    Dimension("astringent", FOOD_SENSATIONS, "Cảm giác chát, se"),
    Dimension(
        "fatty",
        FOOD_CHARACTERISTICS,
        "Lượng chất béo cảm nhận được (dầu mỡ, nước cốt dừa, bơ, sữa)",
    ),
    Dimension(
        "fresh",
        FOOD_CHARACTERISTICS,
        "Độ tươi, thanh (rau sống, hải sản tươi, ít nấu chín kỹ)",
    ),
    Dimension(
        "rich",
        FOOD_CHARACTERISTICS,
        "Độ đậm đà, sâu và dày của vị tổng thể (nước dùng hầm lâu, sốt đậm)",
    ),
    Dimension(
        "aromatic",
        FOOD_CHARACTERISTICS,
        "Độ nổi bật của mùi thơm (rau thơm, gia vị, mùi nướng)",
    ),
)

DIMENSIONS: tuple[str, ...] = tuple(dimension.name for dimension in DIMENSION_DEFINITIONS)

DIMENSION_COUNT = len(DIMENSIONS)

# Discrete intensity scale the AI is asked to use (§2.2). Validation accepts any value in [0, 1].
SCALE: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0)


class OntologyError(ValueError):
    """Scores or a vector that do not fit the ontology; a dish vector then becomes failed."""


def vector_from_scores(scores: Mapping[str, object], *, allow_zero: bool = False) -> list[float]:
    """Turns {dimension: score} into a vector in DIMENSIONS order (Design §2.4).

    Exactly the 12 dimension names are accepted: a missing or unknown key (a misspelt dimension
    included) is an error. Each score must be a real number in [0, 1]; it is kept as is, off the
    discrete scale too. The zero vector is rejected unless `allow_zero` (a survey option such as
    "no spicy food" may be all zero; a dish vector may not).
    """
    keys = set(scores)
    missing = [name for name in DIMENSIONS if name not in keys]
    unknown = sorted(str(key) for key in keys - set(DIMENSIONS))
    if missing or unknown:
        raise OntologyError(
            f"Expected the {DIMENSION_COUNT} ontology dimensions;"
            f" missing {missing}, unknown {unknown}."
        )

    vector = [_score(name, scores[name]) for name in DIMENSIONS]
    if not allow_zero and not any(vector):
        raise OntologyError("The vector is zero on every dimension.")
    return vector


def scores_from_vector(vector: Sequence[float]) -> dict[str, float]:
    """Turns a stored vector back into {dimension: score}, for logs and raw outputs."""
    if len(vector) != DIMENSION_COUNT:
        raise OntologyError(f"Expected {DIMENSION_COUNT} values, got {len(vector)}.")
    return {name: float(value) for name, value in zip(DIMENSIONS, vector, strict=True)}


def describe_dimensions() -> str:
    """One line per dimension, in vector order, for the prompt that scores a dish (Design §2.4)."""
    return "\n".join(
        f"{index}. {dimension.name} ({dimension.group}): {dimension.meaning}"
        for index, dimension in enumerate(DIMENSION_DEFINITIONS)
    )


def _score(name: str, value: object) -> float:
    # bool is an int subclass, so True would otherwise pass as 1.
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise OntologyError(f"Score of {name!r} must be a number, got {value!r}.")
    score = float(value)
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise OntologyError(f"Score of {name!r} must be in [0, 1], got {value!r}.")
    return score
