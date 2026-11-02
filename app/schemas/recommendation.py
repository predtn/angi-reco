"""RECO-05 and RECO-06 bodies (API Design, sheet Chi tiết Request-Response; DTO RecoItem)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, FiniteFloat, model_validator

from app.models.enums import RecoContext

# Reco default when top_k is left out (RECO-05).
DEFAULT_TOP_K = 50


class RecommendationRequest(BaseModel):
    # Left out = Guest: ranked by Wilson only, nothing logged, request_id = null
    user_id: int | None = Field(default=None, gt=0)
    # Filtered and sorted by the backend (restaurant rating, then like_count); at most 2000
    candidate_dish_ids: list[int] = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=DEFAULT_TOP_K, ge=1, le=200)
    context: RecoContext
    vector_source: Literal["profile", "conversation"] = "profile"
    user_vector_override: list[FiniteFloat] | None = Field(
        default=None, min_length=12, max_length=12
    )

    @model_validator(mode="after")
    def validate_vector_source(self) -> "RecommendationRequest":
        if self.vector_source == "conversation" and self.user_id is None:
            raise ValueError("A conversation vector requires user_id.")
        if self.vector_source == "profile" and self.user_vector_override is not None:
            raise ValueError("A vector override requires vector_source=conversation.")
        if self.user_vector_override is not None and not any(self.user_vector_override):
            self.user_vector_override = None
        return self


class RecoItem(BaseModel):
    dish_id: int
    rank: int
    recommend_score: float
    final_score: float
    explicit_score: float
    wilson: float
    exploration: float


class RecommendationResponse(BaseModel):
    vector_source: Literal["profile", "conversation"] = "profile"
    # null for a Guest (not logged)
    request_id: uuid.UUID | None
    config_version: int
    items: list[RecoItem]
    # Dishes reco never received or that are inactive
    ignored_dish_ids: list[int]


class ImpressionRequest(BaseModel):
    user_id: int = Field(gt=0)
    request_id: uuid.UUID
    dish_ids: list[int] = Field(min_length=1, max_length=200)
    shown_at: datetime | None = None
    agent_proposal_id: int | None = Field(default=None, gt=0)


class ImpressionResponse(BaseModel):
    request_id: uuid.UUID
    # Counted for the first time in this request (N_i + 1)
    counted: list[int]
    # Already counted, or not part of the request
    ignored: list[int]
