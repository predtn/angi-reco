import uuid
from datetime import datetime

from sqlalchemy import (
    REAL,
    UUID,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, in_check
from app.models._columns import created_at
from app.models.enums import RecoContext


class RecommendationLog(Base):
    """One call of POST /recommendations by a signed-in user (guests are not logged)."""

    __tablename__ = "recommendation_logs"
    __table_args__ = (
        CheckConstraint(in_check("context", RecoContext), name="context"),
        Index("ix_recommendation_logs_user_id_created_at", "user_id", "created_at"),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID, primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[int] = mapped_column(Integer)
    config_version: Mapped[int] = mapped_column(ForeignKey("algorithm_configs.config_version"))
    context: Mapped[str] = mapped_column(String(20), server_default=text(f"'{RecoContext.LIST}'"))
    m: Mapped[int] = mapped_column(Integer)
    n_total: Mapped[int] = mapped_column(BigInteger)
    # Δ = m / (m + k')
    delta: Mapped[float] = mapped_column(REAL)
    candidate_count: Mapped[int] = mapped_column(Integer)
    top_k: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = created_at()


class RecommendationItem(Base):
    """Score of every layer for one candidate dish of a recommendation (Design §3)."""

    __tablename__ = "recommendation_items"

    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("recommendation_logs.request_id", ondelete="CASCADE"), primary_key=True
    )
    dish_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    # Rank in the whole candidate set; ties keep the order the backend sent
    rank: Mapped[int] = mapped_column(Integer)
    is_returned: Mapped[bool] = mapped_column(Boolean)
    # NULL when the user has no vector
    cosine_sim: Mapped[float | None] = mapped_column(REAL)
    explicit_score: Mapped[float] = mapped_column(REAL)
    implicit_score: Mapped[float] = mapped_column(REAL)
    alpha: Mapped[float] = mapped_column(REAL)
    personalized: Mapped[float] = mapped_column(REAL)
    wilson: Mapped[float] = mapped_column(REAL)
    final_score: Mapped[float] = mapped_column(REAL)
    exploration: Mapped[float] = mapped_column(REAL)
    recommend_score: Mapped[float] = mapped_column(REAL)
    # First time the dish was shown to the user (POST /impressions); NULL = not seen
    shown_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
