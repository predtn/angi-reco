"""Dish vectors: RECO-01 (upsert), RECO-02 (deactivate) and their generation (Design §2.4).

RECO-01 answers at once; the vector is generated right after in a background task, and the loop
started in app.main retries pending / failed dishes every 5 minutes, at most MAX_ATTEMPTS times
per content.
"""

import asyncio
import hashlib
import logging
from datetime import datetime
from enum import StrEnum

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.ontology import ONTOLOGY_VERSION, OntologyError, vector_from_scores
from app.models import DishVector
from app.models.enums import DishVectorStatus
from app.services.dish_scorer import DishScorer, ScoringError

logger = logging.getLogger(__name__)

# Tries per content; RECO-01 with new content starts again from 0 (Design §2.4).
MAX_ATTEMPTS = 5
REGENERATION_INTERVAL_SECONDS = 5 * 60
REGENERATION_BATCH_SIZE = 100
_LAST_ERROR_MAX_LENGTH = 1000


class UpsertResult(StrEnum):
    CREATED = "created"
    CONTENT_CHANGED = "content_changed"
    UNCHANGED = "unchanged"
    STALE = "stale"


class DeactivateResult(StrEnum):
    DEACTIVATED = "deactivated"
    STALE = "stale"
    NOT_FOUND = "not_found"


def content_hash(name: str, description: str | None) -> str:
    """dish_vectors.source_hash: sha256 of the trimmed name and description, the only inputs of
    the vector. The same text always gives the same hash, so the AI is not called again."""
    content = f"{name.strip()}\n{(description or '').strip()}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def upsert_dish(
    session: AsyncSession,
    dish_id: int,
    name: str,
    description: str | None,
    occurred_at: datetime,
) -> UpsertResult:
    """RECO-01. CREATED and CONTENT_CHANGED leave the dish pending without a vector; the caller
    then generates it. An event older than the last applied one is STALE and changes nothing."""
    source_hash = content_hash(name, description)
    inserted = await session.scalar(
        insert(DishVector)
        .values(
            dish_id=dish_id,
            name=name,
            description=description,
            source_hash=source_hash,
            last_event_at=occurred_at,
        )
        .on_conflict_do_nothing(index_elements=[DishVector.dish_id])
        .returning(DishVector.dish_id)
    )
    if inserted is not None:
        await session.commit()
        return UpsertResult.CREATED

    # Row lock: two events of the same dish are applied one after the other.
    dish = await session.scalar(
        select(DishVector).where(DishVector.dish_id == dish_id).with_for_update()
    )
    assert dish is not None  # the insert above found the row
    if dish.last_event_at is not None and occurred_at < dish.last_event_at:
        await session.rollback()
        return UpsertResult.STALE

    dish.is_active = True
    dish.last_event_at = occurred_at
    dish.name = name
    dish.description = description
    if dish.source_hash == source_hash:
        await session.commit()
        return UpsertResult.UNCHANGED

    # New content: the old vector no longer describes the dish.
    dish.source_hash = source_hash
    dish.status = DishVectorStatus.PENDING
    dish.vec = None
    dish.raw_ai_output = None
    dish.model_name = None
    dish.attempt_count = 0
    dish.last_error = None
    await session.commit()
    return UpsertResult.CONTENT_CHANGED


async def deactivate_dish(
    session: AsyncSession, dish_id: int, occurred_at: datetime | None
) -> DeactivateResult:
    """RECO-02. The dish leaves every candidate list; its vector is kept for when it comes back."""
    dish = await session.scalar(
        select(DishVector).where(DishVector.dish_id == dish_id).with_for_update()
    )
    if dish is None:
        return DeactivateResult.NOT_FOUND
    if occurred_at is not None and dish.last_event_at is not None:
        if occurred_at < dish.last_event_at:
            await session.rollback()
            return DeactivateResult.STALE
    dish.is_active = False
    if occurred_at is not None:
        dish.last_event_at = occurred_at
    await session.commit()
    return DeactivateResult.DEACTIVATED


async def generate_vector(
    sessionmaker: async_sessionmaker[AsyncSession], scorer: DishScorer, dish_id: int
) -> None:
    """Asks the model for the dish's scores and stores the vector (ready) or the error (failed).

    The result is written only if the content is still the one that was scored, so a RECO-01
    that arrives meanwhile is never overwritten by an answer about the old content.
    """
    async with sessionmaker() as session:
        dish = await session.get(DishVector, dish_id)
        if (
            dish is None
            or not dish.is_active
            or dish.status == DishVectorStatus.READY
            or dish.attempt_count >= MAX_ATTEMPTS
            or dish.name is None
        ):
            return
        source_hash, name, description = dish.source_hash, dish.name, dish.description

    raw_output = None
    try:
        scored = await scorer.score(name, description)
        raw_output = scored.raw_output
        vector = vector_from_scores(scored.scores)
    except (ScoringError, OntologyError) as exc:
        if isinstance(exc, ScoringError):
            raw_output = exc.raw_output
        logger.warning("Dish %s vector generation failed: %s", dish_id, exc)
        values = {
            "status": DishVectorStatus.FAILED,
            "last_error": str(exc)[:_LAST_ERROR_MAX_LENGTH],
            "raw_ai_output": raw_output,
        }
    else:
        values = {
            "status": DishVectorStatus.READY,
            "vec": vector,
            "raw_ai_output": raw_output,
            "model_name": scorer.model_name,
            "ontology_version": ONTOLOGY_VERSION,
            "last_error": None,
        }

    async with sessionmaker() as session:
        await session.execute(
            update(DishVector)
            .where(DishVector.dish_id == dish_id, DishVector.source_hash == source_hash)
            .values(attempt_count=DishVector.attempt_count + 1, **values)
        )
        await session.commit()


async def regenerate_pending(
    sessionmaker: async_sessionmaker[AsyncSession], scorer: DishScorer
) -> int:
    """One pass of the background loop: generates pending / failed active dishes that have tries
    left, oldest first. Returns how many dishes it tried."""
    async with sessionmaker() as session:
        dish_ids = list(
            await session.scalars(
                select(DishVector.dish_id)
                .where(
                    DishVector.status != DishVectorStatus.READY,
                    DishVector.is_active,
                    DishVector.attempt_count < MAX_ATTEMPTS,
                )
                .order_by(DishVector.updated_at)
                .limit(REGENERATION_BATCH_SIZE)
            )
        )
    for dish_id in dish_ids:
        await generate_vector(sessionmaker, scorer, dish_id)
    return len(dish_ids)


async def run_regeneration_loop(
    sessionmaker: async_sessionmaker[AsyncSession],
    scorer: DishScorer,
    interval_seconds: float = REGENERATION_INTERVAL_SECONDS,
) -> None:
    """Runs regenerate_pending every interval until cancelled at shutdown. Reco runs as a single
    instance, so no row locking between passes is needed (API Design, Tổng quan)."""
    while True:
        try:
            tried = await regenerate_pending(sessionmaker, scorer)
            if tried:
                logger.info("Background loop tried %s pending or failed dish vectors", tried)
        except Exception:
            # One bad pass (database down, ...) must not stop the loop.
            logger.exception("Background dish vector loop failed")
        await asyncio.sleep(interval_seconds)
