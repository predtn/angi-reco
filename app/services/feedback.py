"""RECO-04 (POST /feedback): a like / dislike sent by the outbox worker (FEEDBACK_CREATED).

Design §5.2: a known event_uuid is a duplicate and changes nothing; a dish without a ready vector
answers 503 so the worker retries later. Otherwise, in one transaction holding the user's row lock:
the event goes to interaction_events, user_dish_scores gets r += β_s·w, Implicit = SoftSign01(r),
n + 1 and the latest vote, the user vector moves towards (like) or away from (dislike) the dish and
feedback_count (so m) grows by 1, and dish_stats keeps one vote per user and dish.
"""

import uuid
from datetime import datetime

from fastapi import status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import (
    AlgorithmConfig,
    DishStats,
    DishVector,
    InteractionEvent,
    UserDishScore,
    UserPreferenceVector,
)
from app.models.enums import DishVectorStatus, FeedbackType
from app.schemas.feedback import FeedbackResult
from app.services.scoring import implicit_score, move_user_vector

# A pending vector is generated right after RECO-01 and retried every 5 minutes (Design §2.4).
RETRY_AFTER_SECONDS = 60


async def _is_known(session: AsyncSession, event_uuid: uuid.UUID) -> bool:
    found = await session.scalar(
        select(InteractionEvent.id).where(InteractionEvent.event_uuid == event_uuid)
    )
    return found is not None


async def apply_feedback(
    session: AsyncSession,
    event_uuid: uuid.UUID,
    user_id: int,
    dish_id: int,
    event_type: FeedbackType,
    request_id: uuid.UUID | None,
    occurred_at: datetime,
) -> FeedbackResult:
    """Raises 404 DISH_NOT_FOUND for a dish reco never received (the worker marks it dead) and 503
    DISH_VECTOR_NOT_READY with Retry-After while the dish vector is pending or failed.

    A deactivated dish that has a vector still counts: the user did like or dislike it.
    """
    if await _is_known(session, event_uuid):
        return FeedbackResult.DUPLICATE

    dish = await session.get(DishVector, dish_id)
    if dish is None:
        raise AppError(status.HTTP_404_NOT_FOUND, "DISH_NOT_FOUND", "Dish not found.")
    if dish.status != DishVectorStatus.READY or dish.vec is None:
        raise AppError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "DISH_VECTOR_NOT_READY",
            "The dish vector is not ready yet; retry later.",
            headers={"Retry-After": str(RETRY_AFTER_SECONDS)},
        )
    dish_vector = [float(value) for value in dish.vec]

    config = await session.scalar(select(AlgorithmConfig).where(AlgorithmConfig.is_active))
    if config is None:
        # A 5xx: the worker retries, and /health reports the same problem.
        raise RuntimeError("No active row in algorithm_configs; run the migrations")
    beta_u = float(config.params["beta_u"])
    beta_s = float(config.params["beta_s"])
    w = 1 if event_type == FeedbackType.LIKE else -1

    # The user's row is the lock that serializes every update of this user (vector, counters).
    await session.execute(
        insert(UserPreferenceVector).values(user_id=user_id).on_conflict_do_nothing()
    )
    user = await session.scalar(
        select(UserPreferenceVector)
        .where(UserPreferenceVector.user_id == user_id)
        .with_for_update()
    )
    assert user is not None
    # The same event can arrive twice at once (worker retry after a timeout); the second one waits
    # for the lock above and then finds the first.
    if await _is_known(session, event_uuid):
        await session.rollback()
        return FeedbackResult.DUPLICATE

    session.add(
        InteractionEvent(
            event_uuid=event_uuid,
            user_id=user_id,
            dish_id=dish_id,
            event_type=event_type,
            w=w,
            request_id=request_id,
            config_version=config.config_version,
            occurred_at=occurred_at,
        )
    )

    score = await session.get(UserDishScore, (user_id, dish_id))
    previous_vote = None if score is None else score.last_feedback
    # The latest feedback is the vote that counts; the worker sends a user's events in order, and
    # occurred_at keeps an older event from replacing a newer vote anyway.
    is_latest = (
        score is None or score.last_feedback_at is None or occurred_at >= score.last_feedback_at
    )
    raw = (0.0 if score is None else score.implicit_raw) + beta_s * w
    if score is None:
        score = UserDishScore(user_id=user_id, dish_id=dish_id, interaction_count=0)
        session.add(score)
    score.implicit_raw = raw
    score.implicit_score = implicit_score(raw)
    score.interaction_count += 1
    if is_latest:
        score.last_feedback = w
        score.last_feedback_at = occurred_at

    user.vec = move_user_vector(user.vec, dish_vector, beta_u, w)
    user.feedback_count += 1

    if is_latest and previous_vote != w:
        # One vote per user: a changed mind moves the vote, a first feedback adds one.
        likes = (1 if w == 1 else 0) - (1 if previous_vote == 1 else 0)
        dislikes = (1 if w == -1 else 0) - (1 if previous_vote == -1 else 0)
        await session.execute(
            insert(DishStats)
            .values(dish_id=dish_id, like_count=max(likes, 0), dislike_count=max(dislikes, 0))
            .on_conflict_do_update(
                index_elements=[DishStats.dish_id],
                set_={
                    "like_count": DishStats.like_count + likes,
                    "dislike_count": DishStats.dislike_count + dislikes,
                },
            )
        )

    await session.commit()
    return FeedbackResult.APPLIED
