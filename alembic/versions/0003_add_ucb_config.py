"""add the UCB configuration

config_version 2 turns on exploration (Recommendation_System_Design_Ver1.1 §3.4) with gamma = 0.1,
the starting value of §3.5; every other parameter is the one of config_version 1. It is added
inactive: UCB only matters once the app reports impressions (IMP-01), and switching is a separate
decision (README, "Algorithm configuration").

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-15 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Copied rather than read from config_version 1 so that this migration keeps producing the same row.
UCB_PARAMS = {
    "beta_u": 0.03,
    "beta_s": 0.03,
    "k": 5,
    "k_prime": 5,
    "z": 1.96,
    "gamma": 0.1,
    "explicit_norm": "minmax_cosine",
    "ontology_version": 1,
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
                "config_version": 2,
                "params": UCB_PARAMS,
                "is_active": False,
                "note": "UCB exploration with gamma = 0.1 (Design §3.4, §3.5); not active yet.",
            }
        ],
    )


def downgrade() -> None:
    # If version 2 was switched on, version 1 takes over again. Deleting it fails while
    # recommendation_logs or interaction_events refer to it, which keeps that history intact.
    # The unique index on is_active is checked row by row: version 2 off before version 1 on.
    op.execute(
        "UPDATE recommendation.algorithm_configs SET is_active = false"
        " WHERE config_version = 2 AND is_active"
    )
    op.execute(
        "UPDATE recommendation.algorithm_configs SET is_active = true WHERE config_version = 1"
        " AND NOT EXISTS (SELECT 1 FROM recommendation.algorithm_configs WHERE is_active)"
    )
    op.execute(algorithm_configs.delete().where(algorithm_configs.c.config_version == 2))
