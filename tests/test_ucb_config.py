"""config_version 2 (UCB, Design §3.4) against the database (skipped locally without one)."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.main import create_app
from app.services.scoring import exploration_score

# Far from real core ids and from the other test modules; every test deletes its rows.
USER_ID = 900_601
SEEN, UNSEEN = 900_611, 900_612


def _activate(engine: Engine, version: int) -> None:
    # The unique index on is_active is checked row by row: everything off first, then one on.
    with engine.begin() as connection:
        connection.execute(text("UPDATE recommendation.algorithm_configs SET is_active = false"))
        connection.execute(
            text(
                "UPDATE recommendation.algorithm_configs SET is_active = true"
                " WHERE config_version = :v"
            ),
            {"v": version},
        )


def _cleanup(engine: Engine) -> None:
    with engine.begin() as connection:
        for table in ("recommendation_logs", "user_preference_vectors", "user_dish_scores"):
            connection.execute(
                text(f"DELETE FROM recommendation.{table} WHERE user_id = :u"), {"u": USER_ID}
            )
        connection.execute(
            text("DELETE FROM recommendation.dish_vectors WHERE dish_id BETWEEN 900600 AND 900699")
        )


@pytest.fixture
def client(migrated_engine: Engine, api_key: str) -> Iterator[TestClient]:
    """Two dishes reco cannot tell apart (no vector, no votes); the user has seen 20 dishes, 10 of
    them SEEN and none UNSEEN."""
    _cleanup(migrated_engine)
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO recommendation.dish_vectors (dish_id, source_hash, status) VALUES"
                " (:seen, :h, 'pending'), (:unseen, :h, 'pending')"
            ),
            {"seen": SEEN, "unseen": UNSEEN, "h": "0" * 64},
        )
        connection.execute(
            text(
                "INSERT INTO recommendation.user_preference_vectors (user_id, total_shown)"
                " VALUES (:u, 20)"
            ),
            {"u": USER_ID},
        )
        connection.execute(
            text(
                "INSERT INTO recommendation.user_dish_scores (user_id, dish_id, shown_count)"
                " VALUES (:u, :d, 10)"
            ),
            {"u": USER_ID, "d": SEEN},
        )
    try:
        with TestClient(create_app(), headers={"X-Api-Key": api_key}) as test_client:
            yield test_client
    finally:
        _activate(migrated_engine, 1)
        _cleanup(migrated_engine)


def _recommend(client: TestClient, user_id: int | None = USER_ID) -> Any:
    payload: dict[str, Any] = {"candidate_dish_ids": [SEEN, UNSEEN], "context": "list"}
    if user_id is not None:
        payload["user_id"] = user_id
    response = client.post("/recommendations", json=payload)
    assert response.status_code == 200
    return response.json()


def test_migration_adds_version_two_inactive_with_gamma_only_changed(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.connect() as connection:
        configs = {
            row.config_version: row
            for row in connection.execute(
                text(
                    "SELECT config_version, params, is_active"
                    " FROM recommendation.algorithm_configs WHERE config_version IN (1, 2)"
                )
            )
        }

    assert configs[1].is_active and not configs[2].is_active
    assert configs[1].params["gamma"] == 0
    assert configs[2].params["gamma"] == 0.1
    assert {**configs[2].params, "gamma": 0} == configs[1].params


def test_version_one_ignores_exploration(client: TestClient) -> None:
    body = _recommend(client)

    assert body["config_version"] == 1
    # γ = 0: equal Final scores, so the backend's order stays.
    assert [item["dish_id"] for item in body["items"]] == [SEEN, UNSEEN]
    assert all(item["recommend_score"] == item["final_score"] for item in body["items"])


def test_version_two_lifts_the_dish_the_user_has_not_seen(
    client: TestClient, migrated_engine: Engine
) -> None:
    _activate(migrated_engine, 2)

    body = _recommend(client)

    assert body["config_version"] == 2
    assert [item["dish_id"] for item in body["items"]] == [UNSEEN, SEEN]
    unseen, seen = body["items"]
    # Recommend = 0.9·Final + 0.1·Exploration, with ln(N_total + 1) (§3.4)
    assert unseen["exploration"] == pytest.approx(exploration_score(20, 0))
    assert seen["exploration"] == pytest.approx(exploration_score(20, 10))
    for item in (unseen, seen):
        expected = 0.9 * item["final_score"] + 0.1 * item["exploration"]
        assert item["recommend_score"] == pytest.approx(expected)
    with migrated_engine.connect() as connection:
        logged = connection.execute(
            text(
                "SELECT config_version FROM recommendation.recommendation_logs"
                " WHERE request_id = :r"
            ),
            {"r": body["request_id"]},
        ).scalar_one()
    assert logged == 2


def test_version_two_gives_guests_no_exploration(
    client: TestClient, migrated_engine: Engine
) -> None:
    _activate(migrated_engine, 2)

    body = _recommend(client, user_id=None)

    assert body["config_version"] == 2
    assert [item["dish_id"] for item in body["items"]] == [SEEN, UNSEEN]
    assert all(item["exploration"] == 0 for item in body["items"])
