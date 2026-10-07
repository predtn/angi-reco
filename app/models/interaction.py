import uuid
from datetime import datetime

from sqlalchemy import (
    UUID,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, in_check
from app.models._columns import created_at
from app.models.enums import FeedbackType


class InteractionEvent(Base):
    """Append-only like/dislike log, the source of truth the derived tables can be replayed from."""

    __tablename__ = "interaction_events"
    __table_args__ = (
        CheckConstraint(in_check("event_type", FeedbackType), name="event_type"),
        CheckConstraint(
            f"(event_type = '{FeedbackType.LIKE}' AND w = 1)"
            f" OR (event_type = '{FeedbackType.DISLIKE}' AND w = -1)",
            name="w",
        ),
        Index("ix_interaction_events_user_id_occurred_at", "user_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # = core.dish_feedbacks.event_uuid; a retry with the same uuid is a duplicate
    event_uuid: Mapped[uuid.UUID] = mapped_column(UUID, unique=True)
    user_id: Mapped[int] = mapped_column(Integer)
    dish_id: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(10))
    # +1 like, -1 dislike
    w: Mapped[int] = mapped_column(SmallInteger)
    # recommendation_logs.request_id when the dish came from a recommendation (no FK: guests and
    # fallbacks have none, and logs may be pruned)
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    config_version: Mapped[int | None] = mapped_column(
        ForeignKey("algorithm_configs.config_version")
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = created_at()
