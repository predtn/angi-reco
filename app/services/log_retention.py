"""Retention of recommendation_items (Recommendation Design §6.2, data for offline evaluation).

RECO-05 logs every candidate it ranks, up to 2000 rows per call, but only the top_k returned to the
user (is_returned = true) feed the evaluation metrics (like-rate of top-k, replay of what was
shown). Rows that were not returned are kept for RETENTION_DAYS, then deleted in small batches so
the table stays bounded. recommendation_logs and returned items are never deleted here.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.recommendation import RecommendationItem, RecommendationLog

logger = logging.getLogger(__name__)

RETENTION_DAYS = 30
CLEANUP_INTERVAL_SECONDS = 60 * 60
# One batch per transaction: short locks, and a slow first run does not hold the table.
BATCH_SIZE = 5000


async def delete_expired_items(
    sessionmaker: async_sessionmaker[AsyncSession],
    now: datetime | None = None,
    batch_size: int = BATCH_SIZE,
) -> int:
    """Deletes non-returned items of logs older than RETENTION_DAYS; returns how many rows."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=RETENTION_DAYS)
    expired = (
        select(RecommendationItem.request_id, RecommendationItem.dish_id)
        .join(RecommendationLog, RecommendationLog.request_id == RecommendationItem.request_id)
        .where(RecommendationItem.is_returned.is_(False), RecommendationLog.created_at < cutoff)
        .limit(batch_size)
    )
    total = 0
    while True:
        async with sessionmaker() as session:
            result = await session.execute(
                delete(RecommendationItem).where(
                    tuple_(RecommendationItem.request_id, RecommendationItem.dish_id).in_(expired)
                )
            )
            await session.commit()
        deleted = result.rowcount or 0
        total += deleted
        if deleted < batch_size:
            return total


async def run_retention_loop(
    sessionmaker: async_sessionmaker[AsyncSession],
    interval_seconds: float = CLEANUP_INTERVAL_SECONDS,
) -> None:
    """Runs delete_expired_items every interval until cancelled (reco runs as one instance)."""
    while True:
        try:
            deleted = await delete_expired_items(sessionmaker)
            if deleted:
                logger.info(
                    "Deleted %s non-returned recommendation items older than %s days",
                    deleted,
                    RETENTION_DAYS,
                )
        except Exception:
            # One bad pass (database down, ...) must not stop the loop.
            logger.exception("Recommendation log retention pass failed")
        await asyncio.sleep(interval_seconds)
