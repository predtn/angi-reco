"""RECO-01, RECO-02 and dish vector generation against the database (skipped without one)."""

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.core.ontology import DIMENSIONS
from app.db.session import create_engine
from app.main import create_app
from app.services.dish_scorer import ScoredDish, ScoringError
from app.services.dish_vectors import MAX_ATTEMPTS, content_hash, regenerate_pending

# Far from real core.dishes ids; every test deletes its rows.
DISH_ID = 900_101
OTHER_DISH_ID = 900_102
T0 = "2026-10-02T02:00:00Z"
T1 = "2026-10-02T03:00:00Z"


class FakeScorer:
    model_name = "fake-model"

    def __init__(self, scores: dict[str, Any] | None = None, error: Exception | None = None):
        self.scores = scores if scores is not None else {name: 0.5 for name in DIMENSIONS}
        self.error = error
        self.calls: list[tuple[str, str | None]] = []

    async def score(self, name: str, description: str | None) -> ScoredDish:
        self.calls.append((name, description))
        if self.error is not None:
            raise self.error
        return ScoredDish(scores=dict(self.scores), raw_output=dict(self.scores))


def _delete_dishes(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM recommendation.dish_vectors WHERE dish_id IN (:a, :b)"),
            {"a": DISH_ID, "b": OTHER_DISH_ID},
        )


@pytest.fixture
def scorer() -> FakeScorer:
    return FakeScorer()


@pytest.fixture
def client(migrated_engine: Engine, api_key: str, scorer: FakeScorer) -> Iterator[TestClient]:
    _delete_dishes(migrated_engine)
    with TestClient(create_app(), headers={"X-Api-Key": api_key}) as test_client:
        test_client.app.state.dish_scorer = scorer
        yield test_client
    _delete_dishes(migrated_engine)


def _dish(engine: Engine, dish_id: int = DISH_ID) -> dict[str, Any] | None:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT vec::text AS vec, status, attempt_count, last_error, is_active, name,"
                " description, source_hash, model_name, raw_ai_output, last_event_at"
                " FROM recommendation.dish_vectors WHERE dish_id = :id"
            ),
            {"id": dish_id},
        ).one_or_none()
    return None if row is None else dict(row._mapping)


def _upsert(
    client: TestClient,
    name: str = "Bún bò Huế",
    description: str | None = "Sả, mắm ruốc",
    occurred_at: str = T0,
    dish_id: int = DISH_ID,
) -> Any:
    return client.post(
        "/dishes/upsert",
        json={
            "dish_id": dish_id,
            "name": name,
            "description": description,
            "dish_form": "soup",
            "occurred_at": occurred_at,
            "restaurant_id": 7,
        },
        headers={"Idempotency-Key": "6f0c2b1e-8d7a-4c1e-9b3f-2a5d7e9c1f00"},
    )


def test_content_hash_uses_trimmed_name_and_description() -> None:
    assert content_hash(" Phở ", " Bò tái ") == content_hash("Phở", "Bò tái")
    assert content_hash("Phở", None) == content_hash("Phở", "")
    assert content_hash("Phở", "Bò tái") != content_hash("Phở", "Bò chín")


def test_new_dish_is_created_and_its_vector_generated(
    client: TestClient, migrated_engine: Engine, scorer: FakeScorer
) -> None:
    response = _upsert(client)

    assert response.status_code == 200
    assert response.json() == {"dish_id": DISH_ID, "result": "created"}
    dish = _dish(migrated_engine)
    assert dish is not None
    assert dish["status"] == "ready"
    assert dish["vec"] == "[" + ",".join(["0.5"] * 12) + "]"
    assert dish["model_name"] == "fake-model"
    assert dish["attempt_count"] == 1
    assert dish["source_hash"] == content_hash("Bún bò Huế", "Sả, mắm ruốc")
    assert scorer.calls == [("Bún bò Huế", "Sả, mắm ruốc")]


def test_same_content_is_unchanged_and_not_scored_again(
    client: TestClient, scorer: FakeScorer
) -> None:
    _upsert(client)
    response = _upsert(client, occurred_at=T1)

    assert response.json()["result"] == "unchanged"
    assert len(scorer.calls) == 1


def test_older_event_is_stale_and_changes_nothing(
    client: TestClient, migrated_engine: Engine
) -> None:
    _upsert(client, occurred_at=T1)
    response = _upsert(client, name="Bún bò cũ", occurred_at=T0)

    assert response.json()["result"] == "stale"
    dish = _dish(migrated_engine)
    assert dish is not None
    assert dish["name"] == "Bún bò Huế"


def test_changed_content_clears_and_regenerates_the_vector(
    client: TestClient, migrated_engine: Engine, scorer: FakeScorer
) -> None:
    _upsert(client)
    scorer.scores = {name: 0.25 for name in DIMENSIONS}
    response = _upsert(client, description="Thêm chả cua", occurred_at=T1)

    assert response.json()["result"] == "content_changed"
    dish = _dish(migrated_engine)
    assert dish is not None
    assert dish["status"] == "ready"
    assert dish["vec"] == "[" + ",".join(["0.25"] * 12) + "]"
    assert dish["attempt_count"] == 1
    assert dish["description"] == "Thêm chả cua"


@pytest.mark.parametrize(
    "bad_scorer",
    [
        FakeScorer(scores={**{name: 0.5 for name in DIMENSIONS}, "note": 1}),
        FakeScorer(scores={name: 0 for name in DIMENSIONS}),
        FakeScorer(error=ScoringError("OpenAI request failed: timeout")),
    ],
    ids=["unknown-key", "zero-vector", "openai-error"],
)
def test_unusable_answer_marks_the_dish_failed(
    client: TestClient, migrated_engine: Engine, bad_scorer: FakeScorer
) -> None:
    client.app.state.dish_scorer = bad_scorer

    _upsert(client)

    dish = _dish(migrated_engine)
    assert dish is not None
    assert dish["status"] == "failed"
    assert dish["vec"] is None
    assert dish["attempt_count"] == 1
    assert dish["last_error"]


def test_without_llm_settings_the_dish_stays_pending(
    client: TestClient, migrated_engine: Engine
) -> None:
    client.app.state.dish_scorer = None

    assert _upsert(client).json()["result"] == "created"

    dish = _dish(migrated_engine)
    assert dish is not None
    assert dish["status"] == "pending"
    assert dish["attempt_count"] == 0


def test_deactivate_and_show_again(client: TestClient, migrated_engine: Engine) -> None:
    assert client.delete(f"/dishes/{DISH_ID}").json() == {"dish_id": DISH_ID, "result": "not_found"}
    _upsert(client, occurred_at=T0)

    stale = client.delete(f"/dishes/{DISH_ID}", params={"occurred_at": "2026-10-01T00:00:00Z"})
    deactivated = client.delete(f"/dishes/{DISH_ID}", params={"occurred_at": T1})

    assert stale.json()["result"] == "stale"
    assert deactivated.status_code == 200
    assert deactivated.json()["result"] == "deactivated"
    dish = _dish(migrated_engine)
    assert dish is not None
    assert dish["is_active"] is False
    assert dish["vec"] is not None

    shown_again = _upsert(client, occurred_at="2026-10-02T04:00:00Z")
    assert shown_again.json()["result"] == "unchanged"
    dish = _dish(migrated_engine)
    assert dish is not None
    assert dish["is_active"] is True


def test_background_pass_retries_until_the_attempt_limit(migrated_engine: Engine) -> None:
    _delete_dishes(migrated_engine)
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO recommendation.dish_vectors"
                " (dish_id, name, source_hash, status, attempt_count) VALUES"
                " (:a, 'Phở', :h, 'failed', :tries_left), (:b, 'Cơm tấm', :h, 'failed', :spent)"
            ),
            {
                "a": DISH_ID,
                "b": OTHER_DISH_ID,
                "h": "0" * 64,
                "tries_left": MAX_ATTEMPTS - 1,
                "spent": MAX_ATTEMPTS,
            },
        )
    scorer = FakeScorer()

    async def run_pass() -> None:
        engine = create_engine(get_settings())
        try:
            await regenerate_pending(async_sessionmaker(engine, expire_on_commit=False), scorer)
        finally:
            await engine.dispose()

    try:
        asyncio.run(run_pass())

        assert scorer.calls == [("Phở", None)]
        retried = _dish(migrated_engine, DISH_ID)
        spent = _dish(migrated_engine, OTHER_DISH_ID)
        assert retried is not None and retried["status"] == "ready"
        assert spent is not None and spent["status"] == "failed"
    finally:
        _delete_dishes(migrated_engine)


def test_answer_about_old_content_is_discarded(client: TestClient, migrated_engine: Engine) -> None:
    class ContentChangesWhileScoring(FakeScorer):
        async def score(self, name: str, description: str | None) -> ScoredDish:
            # A newer RECO-01 lands while the model is answering.
            with migrated_engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE recommendation.dish_vectors SET source_hash = :h"
                        " WHERE dish_id = :id"
                    ),
                    {"h": "f" * 64, "id": DISH_ID},
                )
            return await super().score(name, description)

    client.app.state.dish_scorer = ContentChangesWhileScoring()

    _upsert(client)

    dish = _dish(migrated_engine)
    assert dish is not None
    assert dish["status"] == "pending"
    assert dish["vec"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"dish_id": 0, "name": "Phở", "occurred_at": T0},
        {"dish_id": DISH_ID, "name": "", "occurred_at": T0},
        {"dish_id": DISH_ID, "name": "Phở"},
        {"dish_id": DISH_ID, "name": "Phở", "occurred_at": T0, "dish_form": "noodle"},
    ],
    ids=["dish-id-0", "empty-name", "no-occurred-at", "unknown-form"],
)
def test_invalid_upsert_is_a_validation_error(client: TestClient, body: dict[str, Any]) -> None:
    response = client.post("/dishes/upsert", json=body)

    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_FAILED"


def test_dish_endpoints_require_the_api_key(client: TestClient) -> None:
    assert client.delete(f"/dishes/{DISH_ID}", headers={"X-Api-Key": "wrong"}).status_code == 401
