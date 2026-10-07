"""initial recommendation schema

The 9 tables of schema recommendation (ANGI_Data_Dictionary_Ver1.2) and the first algorithm
configuration (Recommendation_System_Design_Ver1.1 §3.5).

Revision ID: 0001
Revises:
Create Date: 2026-10-07 23:10:10.991681
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# gamma = 0 until UCB lands in phase 3; that adds a new config_version with gamma = 0.1.
INITIAL_PARAMS = {
    "beta_u": 0.03,
    "beta_s": 0.03,
    "k": 5,
    "k_prime": 5,
    "z": 1.96,
    "gamma": 0,
    "explicit_norm": "minmax_cosine",
    "ontology_version": 1,
}


def upgrade() -> None:
    # Locally and on Render a superuser installs vector first (a non-superuser cannot create it),
    # so this is a no-op there; it only matters on a database where angi_reco is the owner.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")

    algorithm_configs = op.create_table(
        "algorithm_configs",
        sa.Column("config_version", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("config_version", name=op.f("pk_algorithm_configs")),
        schema="recommendation",
    )
    op.create_index(
        "uq_algorithm_configs_is_active",
        "algorithm_configs",
        ["is_active"],
        unique=True,
        schema="recommendation",
        postgresql_where=sa.text("is_active"),
    )
    op.create_table(
        "dish_stats",
        sa.Column("dish_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("like_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("dislike_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "like_count >= 0 AND dislike_count >= 0", name=op.f("ck_dish_stats_counts")
        ),
        sa.PrimaryKeyConstraint("dish_id", name=op.f("pk_dish_stats")),
        schema="recommendation",
    )
    op.create_table(
        "dish_vectors",
        sa.Column("dish_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("vec", pgvector.sqlalchemy.vector.VECTOR(dim=12), nullable=True),
        sa.Column("raw_ai_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=True),
        sa.Column(
            "ontology_version", sa.SmallInteger(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column(
            "status", sa.String(length=10), server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column("attempt_count", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status <> 'ready' OR vec IS NOT NULL", name=op.f("ck_dish_vectors_ready_has_vec")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'ready', 'failed')", name=op.f("ck_dish_vectors_status")
        ),
        sa.CheckConstraint("attempt_count >= 0", name=op.f("ck_dish_vectors_attempt_count")),
        sa.CheckConstraint(
            "vec IS NULL OR vector_norm(vec) > 0", name=op.f("ck_dish_vectors_vec_not_zero")
        ),
        sa.PrimaryKeyConstraint("dish_id", name=op.f("pk_dish_vectors")),
        schema="recommendation",
    )
    op.create_index(
        "ix_dish_vectors_not_ready",
        "dish_vectors",
        ["status"],
        unique=False,
        schema="recommendation",
        postgresql_where=sa.text("status <> 'ready'"),
    )
    op.create_table(
        "survey_option_vectors",
        sa.Column("option_code", sa.String(length=50), nullable=False),
        sa.Column("vec", pgvector.sqlalchemy.vector.VECTOR(dim=12), nullable=False),
        sa.Column("dim_mask", pgvector.sqlalchemy.vector.VECTOR(dim=12), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "vector_norm(dim_mask) > 0", name=op.f("ck_survey_option_vectors_dim_mask_not_zero")
        ),
        sa.PrimaryKeyConstraint("option_code", name=op.f("pk_survey_option_vectors")),
        schema="recommendation",
    )
    op.create_table(
        "user_dish_scores",
        sa.Column("user_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("dish_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("implicit_raw", sa.REAL(), server_default=sa.text("0"), nullable=False),
        sa.Column("implicit_score", sa.REAL(), server_default=sa.text("0.5"), nullable=False),
        sa.Column("interaction_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("shown_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_feedback", sa.SmallInteger(), nullable=True),
        sa.Column("last_feedback_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "implicit_score >= 0 AND implicit_score <= 1",
            name=op.f("ck_user_dish_scores_implicit_score"),
        ),
        sa.CheckConstraint(
            "interaction_count >= 0 AND shown_count >= 0", name=op.f("ck_user_dish_scores_counts")
        ),
        sa.CheckConstraint(
            "last_feedback IN (1, -1)", name=op.f("ck_user_dish_scores_last_feedback")
        ),
        sa.PrimaryKeyConstraint("user_id", "dish_id", name=op.f("pk_user_dish_scores")),
        schema="recommendation",
    )
    op.create_table(
        "user_preference_vectors",
        sa.Column("user_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("initial_vec", pgvector.sqlalchemy.vector.VECTOR(dim=12), nullable=True),
        sa.Column("vec", pgvector.sqlalchemy.vector.VECTOR(dim=12), nullable=True),
        sa.Column("survey_answer_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("feedback_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "total_interactions",
            sa.Integer(),
            sa.Computed("survey_answer_count + feedback_count", persisted=True),
            nullable=True,
        ),
        sa.Column("total_shown", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("survey_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("survey_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "initial_vec IS NULL OR vector_norm(initial_vec) > 0",
            name=op.f("ck_user_preference_vectors_initial_vec_not_zero"),
        ),
        sa.CheckConstraint(
            "survey_answer_count >= 0 AND feedback_count >= 0 AND total_shown >= 0",
            name=op.f("ck_user_preference_vectors_counts"),
        ),
        sa.CheckConstraint(
            "vec IS NULL OR vector_norm(vec) > 0",
            name=op.f("ck_user_preference_vectors_vec_not_zero"),
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_user_preference_vectors")),
        schema="recommendation",
    )
    op.create_table(
        "interaction_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("event_uuid", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("dish_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=10), nullable=False),
        sa.Column("w", sa.SmallInteger(), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=True),
        sa.Column("config_version", sa.Integer(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(event_type = 'like' AND w = 1) OR (event_type = 'dislike' AND w = -1)",
            name=op.f("ck_interaction_events_w"),
        ),
        sa.CheckConstraint(
            "event_type IN ('like', 'dislike')", name=op.f("ck_interaction_events_event_type")
        ),
        sa.ForeignKeyConstraint(
            ["config_version"],
            ["recommendation.algorithm_configs.config_version"],
            name=op.f("fk_interaction_events_algorithm_configs_config_version"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_interaction_events")),
        sa.UniqueConstraint("event_uuid", name=op.f("uq_interaction_events_event_uuid")),
        schema="recommendation",
    )
    op.create_index(
        "ix_interaction_events_user_id_occurred_at",
        "interaction_events",
        ["user_id", "occurred_at"],
        unique=False,
        schema="recommendation",
    )
    op.create_table(
        "recommendation_logs",
        sa.Column(
            "request_id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column(
            "context", sa.String(length=20), server_default=sa.text("'list'"), nullable=False
        ),
        sa.Column("m", sa.Integer(), nullable=False),
        sa.Column("n_total", sa.BigInteger(), nullable=False),
        sa.Column("delta", sa.REAL(), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("top_k", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "context IN ('list', 'home', 'roll', 'roadmap_manual', 'roadmap_ai')",
            name=op.f("ck_recommendation_logs_context"),
        ),
        sa.ForeignKeyConstraint(
            ["config_version"],
            ["recommendation.algorithm_configs.config_version"],
            name=op.f("fk_recommendation_logs_algorithm_configs_config_version"),
        ),
        sa.PrimaryKeyConstraint("request_id", name=op.f("pk_recommendation_logs")),
        schema="recommendation",
    )
    op.create_index(
        "ix_recommendation_logs_user_id_created_at",
        "recommendation_logs",
        ["user_id", "created_at"],
        unique=False,
        schema="recommendation",
    )
    op.create_table(
        "recommendation_items",
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("dish_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("is_returned", sa.Boolean(), nullable=False),
        sa.Column("cosine_sim", sa.REAL(), nullable=True),
        sa.Column("explicit_score", sa.REAL(), nullable=False),
        sa.Column("implicit_score", sa.REAL(), nullable=False),
        sa.Column("alpha", sa.REAL(), nullable=False),
        sa.Column("personalized", sa.REAL(), nullable=False),
        sa.Column("wilson", sa.REAL(), nullable=False),
        sa.Column("final_score", sa.REAL(), nullable=False),
        sa.Column("exploration", sa.REAL(), nullable=False),
        sa.Column("recommend_score", sa.REAL(), nullable=False),
        sa.Column("shown_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["recommendation.recommendation_logs.request_id"],
            name=op.f("fk_recommendation_items_recommendation_logs_request_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("request_id", "dish_id", name=op.f("pk_recommendation_items")),
        schema="recommendation",
    )

    op.bulk_insert(
        algorithm_configs,
        [
            {
                "config_version": 1,
                "params": INITIAL_PARAMS,
                "is_active": True,
                "note": "Initial parameters (Recommendation_System_Design_Ver1.1 §3.5), no UCB.",
            }
        ],
    )


def downgrade() -> None:
    # The vector extension stays: it lives in schema public and other schemas may use it.
    op.drop_table("recommendation_items", schema="recommendation")
    op.drop_index(
        "ix_recommendation_logs_user_id_created_at",
        table_name="recommendation_logs",
        schema="recommendation",
    )
    op.drop_table("recommendation_logs", schema="recommendation")
    op.drop_index(
        "ix_interaction_events_user_id_occurred_at",
        table_name="interaction_events",
        schema="recommendation",
    )
    op.drop_table("interaction_events", schema="recommendation")
    op.drop_table("user_preference_vectors", schema="recommendation")
    op.drop_table("user_dish_scores", schema="recommendation")
    op.drop_table("survey_option_vectors", schema="recommendation")
    op.drop_index(
        "ix_dish_vectors_not_ready",
        table_name="dish_vectors",
        schema="recommendation",
        postgresql_where=sa.text("status <> 'ready'"),
    )
    op.drop_table("dish_vectors", schema="recommendation")
    op.drop_table("dish_stats", schema="recommendation")
    op.drop_index(
        "uq_algorithm_configs_is_active",
        table_name="algorithm_configs",
        schema="recommendation",
        postgresql_where=sa.text("is_active"),
    )
    op.drop_table("algorithm_configs", schema="recommendation")
