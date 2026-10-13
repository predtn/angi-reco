"""seed survey option vectors

The 27 options of the preference survey (.docs/Preference_Survey_Ver1.0.md): for each option_code,
its vector and the mask of the dimensions it has an opinion on.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-13 21:00:00.000000
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Ontology version 1, in vector order (Recommendation_System_Design_Ver1.1 §2.2). Copied rather than
# imported so that this migration keeps producing the same rows if the ontology module changes.
DIMENSIONS = (
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

# option_code -> {masked dimension: intensity}; table "Option vectors" of Preference_Survey_Ver1.0.
OPTIONS: dict[str, dict[str, float]] = {
    "spicy_none": {"spicy": 0},
    "spicy_mild": {"spicy": 0.25},
    "spicy_medium": {"spicy": 0.5},
    "spicy_hot": {"spicy": 0.75},
    "spicy_very_hot": {"spicy": 1},
    "sweet_low": {"sweet": 0},
    "sweet_medium": {"sweet": 0.5},
    "sweet_high": {"sweet": 1},
    "sour_low": {"sour": 0},
    "sour_medium": {"sour": 0.5},
    "sour_high": {"sour": 1},
    "salty_low": {"salty": 0},
    "salty_medium": {"salty": 0.5},
    "salty_high": {"salty": 1},
    "broth_light": {"umami": 0.5, "rich": 0.25, "fresh": 0.75},
    "broth_rich": {"umami": 1, "rich": 1, "fatty": 0.5},
    "fatty_low": {"fatty": 0},
    "fatty_medium": {"fatty": 0.5},
    "fatty_high": {"fatty": 1},
    "herbs_none": {"aromatic": 0},
    "herbs_some": {"aromatic": 0.5, "fresh": 0.5},
    "herbs_lots": {"aromatic": 1, "fresh": 0.75},
    "bitter_avoid": {"bitter": 0, "astringent": 0},
    "bitter_ok": {"bitter": 0.5, "astringent": 0.5},
    "bitter_like": {"bitter": 1, "astringent": 1},
    "cool_light": {"cooling": 1, "fresh": 1},
    "warm_hearty": {"cooling": 0, "rich": 0.75},
}


def _rows() -> list[dict[str, object]]:
    return [
        {
            "option_code": code,
            "vec": [float(scores.get(name, 0)) for name in DIMENSIONS],
            "dim_mask": [1.0 if name in scores else 0.0 for name in DIMENSIONS],
        }
        for code, scores in OPTIONS.items()
    ]


def upgrade() -> None:
    survey_option_vectors = sa.table(
        "survey_option_vectors",
        sa.column("option_code", sa.String(50)),
        sa.column("vec", pgvector.sqlalchemy.vector.VECTOR(dim=12)),
        sa.column("dim_mask", pgvector.sqlalchemy.vector.VECTOR(dim=12)),
        schema="recommendation",
    )
    op.bulk_insert(survey_option_vectors, _rows())


def downgrade() -> None:
    survey_option_vectors = sa.table(
        "survey_option_vectors",
        sa.column("option_code", sa.String(50)),
        schema="recommendation",
    )
    op.execute(
        survey_option_vectors.delete().where(survey_option_vectors.c.option_code.in_(list(OPTIONS)))
    )
