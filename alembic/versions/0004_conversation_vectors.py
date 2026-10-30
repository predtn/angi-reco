"""Conversation vector provenance and committed Agent impressions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "recommendation_logs",
        sa.Column(
            "vector_source", sa.String(16), nullable=False, server_default=sa.text("'profile'")
        ),
        schema="recommendation",
    )
    op.add_column(
        "recommendation_logs",
        sa.Column("effective_vector", postgresql.JSONB()),
        schema="recommendation",
    )
    op.add_column(
        "recommendation_items",
        sa.Column("agent_proposal_id", sa.BigInteger()),
        schema="recommendation",
    )


def downgrade() -> None:
    op.drop_column("recommendation_items", "agent_proposal_id", schema="recommendation")
    op.drop_column("recommendation_logs", "effective_vector", schema="recommendation")
    op.drop_column("recommendation_logs", "vector_source", schema="recommendation")
