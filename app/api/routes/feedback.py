import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.feedback import FeedbackRequest, FeedbackResponse
from app.services import feedback

logger = logging.getLogger(__name__)

router = APIRouter(tags=["feedback"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("/feedback", response_model=FeedbackResponse)
async def record_feedback(
    body: FeedbackRequest,
    session: Session,
    # = event_uuid, which already makes a resend a duplicate, so the key is only logged.
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> FeedbackResponse:
    """RECO-04: a like / dislike updates Implicit, the user vector, m and dish_stats (§5.2)."""
    result = await feedback.apply_feedback(
        session,
        body.event_uuid,
        body.user_id,
        body.dish_id,
        body.event_type,
        body.request_id,
        body.occurred_at,
    )
    logger.info(
        "Feedback %s (%s, user %s, dish %s): %s (Idempotency-Key %s)",
        body.event_uuid,
        body.event_type,
        body.user_id,
        body.dish_id,
        result,
        idempotency_key,
    )
    return FeedbackResponse(event_uuid=body.event_uuid, result=result)
