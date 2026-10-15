"""RECO-04 bodies (API Design, sheet Chi tiết Request-Response)."""

import uuid
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, Field

from app.models.enums import FeedbackType


class FeedbackResult(StrEnum):
    APPLIED = "applied"
    # The event_uuid was already processed; nothing changed.
    DUPLICATE = "duplicate"


class FeedbackRequest(BaseModel):
    # = core.dish_feedbacks.event_uuid = outbox event_uuid (also the Idempotency-Key)
    event_uuid: uuid.UUID
    user_id: int = Field(gt=0)
    dish_id: int = Field(gt=0)
    event_type: FeedbackType
    # reco_request_id of the roadmap item when the dish came from a recommendation
    request_id: uuid.UUID | None = None
    # dish_feedbacks.created_at; with a time zone, since it decides which vote is the latest
    occurred_at: AwareDatetime


class FeedbackResponse(BaseModel):
    event_uuid: uuid.UUID
    result: FeedbackResult
