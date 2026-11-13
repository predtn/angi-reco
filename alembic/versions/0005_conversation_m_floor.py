"""add the conversation floor on m

config_version 3 is config_version 1 plus conversation_m_min = 5: a conversation request with a
taste vector ranks with max(m, 5) in Δ = m / (m + k′), so a new user's stated taste is not
ignored (Conversation_Preferences_Ver1.0). Like 0003 it is added inactive; switching is a separate
step (docs/runtime-behavior.md, "Algorithm configuration").

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-13 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Copied rather than read from config_version 1 so that this migration keeps producing the same row.
CONVERSATION_FLOOR_PARAMS = {
    "beta_u": 0.03,
    "beta_s": 0.03,
    "k": 5,
    "k_prime": 5,
    "z": 1.96,
    "gamma": 0,
    "explicit_norm": "minmax_cosine",
    "ontology_version": 1,
    "conversation_m_min": 5,
}

algorithm_configs = sa.table(
    "algorithm_configs",
    sa.column("config_version", sa.Integer()),
    sa.column("params", postgresql.JSONB()),
    sa.column("is_active", sa.Boolean()),
    sa.column("note", sa.Text()),
    schema="recommendation",
)


def upgrade() -> None:
    op.bulk_insert(
        algorithm_configs,
        [
            {
                "config_version": 3,
                "params": CONVERSATION_FLOOR_PARAMS,
                "is_active": False,
                "note": "Version 1 plus conversation_m_min = 5 (floor on m for a conversation"
                " vector); not active yet.",
            }
        ],
    )


def downgrade() -> None:
    # Same as 0003: if version 3 was switched on, version 1 takes over again, and deleting it fails
    # while recommendation_logs or interaction_events refer to it, which keeps that history intact.
    op.execute(
        "UPDATE recommendation.algorithm_configs SET is_active = false"
        " WHERE config_version = 3 AND is_active"
    )
    op.execute(
        "UPDATE recommendation.algorithm_configs SET is_active = true WHERE config_version = 1"
        " AND NOT EXISTS (SELECT 1 FROM recommendation.algorithm_configs WHERE is_active)"
    )
    op.execute(algorithm_configs.delete().where(algorithm_configs.c.config_version == 3))
