"""config_version 3: floor on m for a conversation vector, against the database (needs one).

The case behind it: a new user (no survey, no feedback, m = 0) tells the Agent "Nay tôi thích ăn
một chút đồ cay". Without the floor Δ = 0 and the popular dish wins whatever the user said.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.main import create_app

# Far from real core ids and from the other test modules; every test deletes its rows.
NEW_USER, REGULAR = 1_900_701, 1_900_702
SPICY, POPULAR = 1_900_711, 1_900_712
STATED = [0.0] * 5 + [0.25] + [0.0] * 6  # "một chút cay"
SPICY_VEC = [0.0, 0.0, 0.25, 0.0, 0.0, 0.75] + [0.0] * 6
POPULAR_VEC = [1.0] + [0.0] * 5 + [0.75] + [0.0] * 5


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
        for table in ("recommendation_logs", "user_dish_scores", "user_preference_vectors"):
            connection.execute(
                text(f"DELETE FROM recommendation.{table} WHERE user_id IN (:a, :b)"),
                {"a": NEW_USER, "b": REGULAR},
            )
        for table in ("dish_stats", "dish_vectors"):
            connection.execute(
                text(f"DELETE FROM recommendation.{table} WHERE dish_id IN (:a, :b)"),
                {"a": SPICY, "b": POPULAR},
            )


@pytest.fixture
def client(migrated_engine: Engine, api_key: str) -> Iterator[TestClient]:
    """A spicy dish nobody voted on and a popular non-spicy one (6 likes). NEW_USER has no row
    (m = 0); REGULAR has m = 8 (6 survey answers, 2 likes/dislikes)."""
    with migrated_engine.connect() as connection:
        active = connection.execute(
            text("SELECT config_version FROM recommendation.algorithm_configs WHERE is_active")
        ).scalar_one()
    _cleanup(migrated_engine)
    with migrated_engine.begin() as connection:
        for dish_id, vector in ((SPICY, SPICY_VEC), (POPULAR, POPULAR_VEC)):
            connection.execute(
                text(
                    "INSERT INTO recommendation.dish_vectors"
                    " (dish_id, vec, source_hash, status, is_active)"
                    " VALUES (:d, CAST(:v AS vector), :h, 'ready', true)"
                ),
                {"d": dish_id, "v": str(vector), "h": "0" * 64},
            )
        connection.execute(
            text("INSERT INTO recommendation.dish_stats (dish_id, like_count) VALUES (:d, 6)"),
            {"d": POPULAR},
        )
        connection.execute(
            text(
                "INSERT INTO recommendation.user_preference_vectors"
                " (user_id, vec, survey_answer_count, feedback_count)"
                " VALUES (:u, CAST(:v AS vector), 6, 2)"
            ),
            {"u": REGULAR, "v": str(POPULAR_VEC)},
        )
    try:
        with TestClient(create_app(), headers={"X-Api-Key": api_key}) as test_client:
            yield test_client
    finally:
        _activate(migrated_engine, active)
        _cleanup(migrated_engine)


def _recommend(client: TestClient, user_id: int, **extra: object) -> Any:
    response = client.post(
        "/recommendations",
        json={
            "user_id": user_id,
            "candidate_dish_ids": [POPULAR, SPICY],
            "top_k": 2,
            "context": "roadmap_ai",
            **extra,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _logged(engine: Engine, request_id: str) -> Any:
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT config_version, m, delta FROM recommendation.recommendation_logs"
                " WHERE request_id = :r"
            ),
            {"r": request_id},
        ).one()


def test_migration_adds_version_three_inactive_as_version_one_plus_the_floor(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.connect() as connection:
        configs = {
            row.config_version: row
            for row in connection.execute(
                text(
                    "SELECT config_version, params FROM recommendation.algorithm_configs"
                    " WHERE config_version IN (1, 3)"
                )
            )
        }
    assert configs[3].params["conversation_m_min"] == 5
    assert {k: v for k, v in configs[3].params.items() if k != "conversation_m_min"} == (
        configs[1].params
    )


def test_without_the_floor_a_new_users_stated_taste_is_ignored(
    client: TestClient, migrated_engine: Engine
) -> None:
    _activate(migrated_engine, 1)
    body = _recommend(client, NEW_USER, vector_source="conversation", user_vector_override=STATED)
    assert [item["dish_id"] for item in body["items"]] == [POPULAR, SPICY]
    assert _logged(migrated_engine, body["request_id"]).delta == 0


def test_with_the_floor_a_new_users_stated_taste_counts(
    client: TestClient, migrated_engine: Engine
) -> None:
    _activate(migrated_engine, 3)
    body = _recommend(client, NEW_USER, vector_source="conversation", user_vector_override=STATED)
    assert body["config_version"] == 3
    assert [item["dish_id"] for item in body["items"]] == [SPICY, POPULAR]
    log = _logged(migrated_engine, body["request_id"])
    # The real m is logged; Δ is the one used: 5 / (5 + 5).
    assert (log.config_version, log.m, log.delta) == (3, 0, pytest.approx(0.5))
    # Nothing was written to the long-term profile.
    assert client.get(f"/users/{NEW_USER}/preferences").json()["vec"] is None


def test_the_floor_leaves_profile_requests_and_regular_users_alone(
    client: TestClient, migrated_engine: Engine
) -> None:
    _activate(migrated_engine, 3)
    profile = _recommend(client, NEW_USER)
    assert _logged(migrated_engine, profile["request_id"]).delta == 0
    zero = _recommend(client, NEW_USER, vector_source="conversation", user_vector_override=[0] * 12)
    assert _logged(migrated_engine, zero["request_id"]).delta == 0
    regular = _recommend(client, REGULAR, vector_source="conversation", user_vector_override=STATED)
    log = _logged(migrated_engine, regular["request_id"])
    assert (log.m, log.delta) == (8, pytest.approx(8 / 13))


def test_migration_adds_version_four_as_version_three_with_ucb(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as connection:
        configs = {
            row.config_version: row.params
            for row in connection.execute(
                text(
                    "SELECT config_version, params FROM recommendation.algorithm_configs"
                    " WHERE config_version IN (2, 3, 4)"
                )
            )
        }
    assert configs[4]["gamma"] == configs[2]["gamma"] == 0.1
    assert {**configs[4], "gamma": 0} == configs[3]


def test_version_four_keeps_the_floor(client: TestClient, migrated_engine: Engine) -> None:
    _activate(migrated_engine, 4)
    body = _recommend(client, NEW_USER, vector_source="conversation", user_vector_override=STATED)
    assert body["config_version"] == 4
    assert [item["dish_id"] for item in body["items"]] == [SPICY, POPULAR]
    log = _logged(migrated_engine, body["request_id"])
    assert (log.config_version, log.m, log.delta) == (4, 0, pytest.approx(0.5))
    # Nothing was shown to this user yet (N_total = 0): Exploration is 0, Recommend = 0.9·Final.
    for item in body["items"]:
        assert item["exploration"] == 0
        assert item["recommend_score"] == pytest.approx(0.9 * item["final_score"])
