"""Retention of non-returned recommendation items (log_retention.py), against the database."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.db.session import create_engine
from app.services.log_retention import RETENTION_DAYS, delete_expired_items

# Far from real users; every test deletes its rows (items cascade with their log).
USER_ID = 900_201
NOW = datetime(2026, 11, 6, 3, 0, tzinfo=UTC)


def _insert_log(engine: Engine, created_at: datetime, items: list[tuple[int, bool]]) -> uuid.UUID:
    request_id = uuid.uuid4()
    with engine.begin() as connection:
        config = connection.execute(
            text("SELECT config_version FROM recommendation.algorithm_configs WHERE is_active")
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO recommendation.recommendation_logs"
                " (request_id, user_id, config_version,"
                " m, n_total, delta, candidate_count, top_k, created_at)"
                " VALUES (:r, :u, :c, 0, 0, 0, :n, 1, :t)"
            ),
            {"r": request_id, "u": USER_ID, "c": config, "n": len(items), "t": created_at},
        )
        for rank, (dish_id, returned) in enumerate(items, start=1):
            connection.execute(
                text(
                    "INSERT INTO recommendation.recommendation_items (request_id, dish_id, rank,"
                    " is_returned, explicit_score, implicit_score, alpha, personalized, wilson,"
                    " final_score, exploration, recommend_score)"
                    " VALUES (:r, :d, :k, :ret, 0, 0, 0, 0, 0, 0, 0, 0)"
                ),
                {"r": request_id, "d": dish_id, "k": rank, "ret": returned},
            )
    return request_id


def _items(engine: Engine, request_id: uuid.UUID) -> list[tuple[int, bool]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT dish_id, is_returned FROM recommendation.recommendation_items"
                " WHERE request_id = :r ORDER BY dish_id"
            ),
            {"r": request_id},
        )
        return [(row.dish_id, row.is_returned) for row in rows]


def _delete_logs(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM recommendation.recommendation_logs WHERE user_id = :u"),
            {"u": USER_ID},
        )


def _run(batch_size: int) -> int:
    async def run() -> int:
        engine = create_engine(get_settings())
        try:
            return await delete_expired_items(
                async_sessionmaker(engine, expire_on_commit=False), NOW, batch_size
            )
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_old_non_returned_items_go_and_everything_else_stays(migrated_engine: Engine) -> None:
    _delete_logs(migrated_engine)
    old = _insert_log(
        migrated_engine,
        NOW - timedelta(days=RETENTION_DAYS, minutes=1),
        [(1, True), (2, False), (3, False), (4, False), (5, False)],
    )
    recent = _insert_log(
        migrated_engine,
        NOW - timedelta(days=RETENTION_DAYS - 1),
        [(1, True), (2, False)],
    )
    try:
        # A batch smaller than the work proves the loop keeps going until nothing is left.
        deleted = _run(batch_size=2)

        assert deleted == 4
        # The returned dish and the log itself stay for the evaluation metrics.
        assert _items(migrated_engine, old) == [(1, True)]
        assert _items(migrated_engine, recent) == [(1, True), (2, False)]
        assert _run(batch_size=2) == 0
    finally:
        _delete_logs(migrated_engine)
