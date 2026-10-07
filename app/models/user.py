from datetime import datetime
from typing import Any

from sqlalchemy import (
    REAL,
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    Integer,
    SmallInteger,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, not_zero_vector
from app.models._columns import ontology_vector, updated_at


class UserPreferenceVector(Base):
    """User vector (from the survey, then updated online) and the counters m and N_total."""

    __tablename__ = "user_preference_vectors"
    __table_args__ = (
        CheckConstraint(not_zero_vector("initial_vec"), name="initial_vec_not_zero"),
        CheckConstraint(not_zero_vector("vec"), name="vec_not_zero"),
        CheckConstraint(
            "survey_answer_count >= 0 AND feedback_count >= 0 AND total_shown >= 0",
            name="counts",
        ),
    )

    # = core.users.id (soft reference)
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    initial_vec: Mapped[list[float] | None] = mapped_column(ontology_vector())
    # NULL = no vector yet (Explicit = 0).
    vec: Mapped[list[float] | None] = mapped_column(ontology_vector())
    # q = number of survey answers
    survey_answer_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    feedback_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # m = q + likes/dislikes
    total_interactions: Mapped[int | None] = mapped_column(
        Integer, Computed("survey_answer_count + feedback_count", persisted=True)
    )
    # N_total = times any dish was shown to the user (POST /impressions)
    total_shown: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    survey_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Not NULL = survey done or skipped; it is accepted only once.
    survey_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = updated_at()


class UserDishScore(Base):
    """Implicit score and counters per (user, dish). Sparse: a missing row means r = 0, n = 0,
    N_i = 0."""

    __tablename__ = "user_dish_scores"
    __table_args__ = (
        CheckConstraint("implicit_score >= 0 AND implicit_score <= 1", name="implicit_score"),
        CheckConstraint("interaction_count >= 0 AND shown_count >= 0", name="counts"),
        CheckConstraint("last_feedback IN (1, -1)", name="last_feedback"),
    )

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    dish_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    # r = sum of beta_s * w, never squashed (Design §3.2)
    implicit_raw: Mapped[float] = mapped_column(REAL, server_default=text("0"))
    # Implicit = 0.5 + 0.5 * r / (1 + |r|), recomputed from implicit_raw on every update
    implicit_score: Mapped[float] = mapped_column(REAL, server_default=text("0.5"))
    # n
    interaction_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # N_i
    shown_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    # Vote currently counted in dish_stats: 1 like, -1 dislike
    last_feedback: Mapped[int | None] = mapped_column(SmallInteger)
    last_feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = updated_at()
