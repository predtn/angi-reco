from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models._columns import created_at, ontology_vector, updated_at


class AlgorithmConfig(Base):
    """Versioned algorithm parameters; every recommendation logs the version it used."""

    __tablename__ = "algorithm_configs"
    __table_args__ = (
        # Only one active configuration at a time.
        Index(
            "uq_algorithm_configs_is_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    config_version: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    # beta_u, beta_s, k, k_prime, z, gamma, explicit_norm, ontology_version (Design §3.5)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at()


class SurveyOptionVector(Base):
    """Maps a survey option (option_code sent by the app) to the ontology dimensions."""

    __tablename__ = "survey_option_vectors"
    __table_args__ = (
        # vec may be all zeros (e.g. "no spicy food"), but the option must cover a dimension.
        CheckConstraint("vector_norm(dim_mask) > 0", name="dim_mask_not_zero"),
    )

    option_code: Mapped[str] = mapped_column(String(50), primary_key=True)
    vec: Mapped[list[float]] = mapped_column(ontology_vector())
    dim_mask: Mapped[list[float]] = mapped_column(ontology_vector())
    updated_at: Mapped[datetime] = updated_at()
