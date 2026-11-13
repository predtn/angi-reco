"""add the conversation floor together with UCB

config_version 4 is config_version 3 (conversation_m_min = 5) with gamma = 0.1, the UCB starting
value of Recommendation_System_Design_Ver1.1 §3.5 already used by version 2. Version 2 has no
floor, so switching to it would drop the floor; this version keeps both. Added inactive like
0003 and 0005; switching is a separate step (docs/runtime-behavior.md, "Algorithm configuration").

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-13 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Copied rather than read from config_version 3 so that this migration keeps producing the same row.
FLOOR_WITH_UCB_PARAMS = {
    "beta_u": 0.03,
    "beta_s": 0.03,
    "k": 5,
    "k_prime": 5,
    "z": 1.96,
    "gamma": 0.1,
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
                "config_version": 4,
                "params": FLOOR_WITH_UCB_PARAMS,
                "is_active": False,
                "note": "Version 3 (conversation_m_min = 5) with UCB gamma = 0.1 (Design §3.4,"
                " §3.5); not active yet.",
            }
        ],
    )


def downgrade() -> None:
    # If version 4 was switched on, version 3 (the same without UCB) takes over again. Deleting it
    # fails while recommendation_logs or interaction_events refer to it, keeping that history.
    op.execute(
        "UPDATE recommendation.algorithm_configs SET is_active = false"
        " WHERE config_version = 4 AND is_active"
    )
    op.execute(
        "UPDATE recommendation.algorithm_configs SET is_active = true WHERE config_version = 3"
        " AND NOT EXISTS (SELECT 1 FROM recommendation.algorithm_configs WHERE is_active)"
    )
    op.execute(algorithm_configs.delete().where(algorithm_configs.c.config_version == 4))
