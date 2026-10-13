"""RECO-01 and RECO-02 bodies (API Design, sheet Chi tiết Request-Response)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DishUpsertRequest(BaseModel):
    # = core.dishes.id
    dish_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=200)
    # name + description are the only inputs of the vector
    description: str | None = None
    # Not part of the vector (Design §2.5); accepted because the outbox payload carries it.
    dish_form: Literal["soup", "dry", "other"] | None = None
    # When the dish changed in core; older than the last applied event -> stale
    occurred_at: datetime
    # Ignored, only logged
    restaurant_id: int | None = None


class DishUpsertResponse(BaseModel):
    dish_id: int
    result: Literal["created", "content_changed", "unchanged", "stale"]


class DishDeactivateResponse(BaseModel):
    dish_id: int
    result: Literal["deactivated", "stale", "not_found"]
