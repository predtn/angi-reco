"""Real database contracts for request vectors and commit-only Agent impressions."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Engine, text

from app.main import create_app
from app.schemas.recommendation import RecommendationRequest

USER, SWEET, SPICY = 1_900_501, 1_900_511, 1_900_512
SWEET_VEC = [1.0] + [0.0] * 11
SPICY_VEC = [0.0] * 5 + [1.0] + [0.0] * 6


@pytest.fixture
def client(migrated_engine: Engine, api_key: str) -> Iterator[TestClient]:
    def cleanup() -> None:
        with migrated_engine.begin() as connection:
            for table in ("recommendation_logs", "user_dish_scores", "user_preference_vectors"):
                connection.execute(
                    text(f"DELETE FROM recommendation.{table} WHERE user_id=:u"), {"u": USER}
                )
            connection.execute(
                text("DELETE FROM recommendation.dish_vectors WHERE dish_id IN (:a,:b)"),
                {"a": SWEET, "b": SPICY},
            )

    cleanup()
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO recommendation.user_preference_vectors"
                " (user_id,vec,survey_answer_count) VALUES (:u,CAST(:v AS vector),6)"
            ),
            {"u": USER, "v": str(SWEET_VEC)},
        )
        for dish_id, vector in ((SWEET, SWEET_VEC), (SPICY, SPICY_VEC)):
            connection.execute(
                text(
                    "INSERT INTO recommendation.dish_vectors"
                    " (dish_id,vec,source_hash,status,is_active)"
                    " VALUES (:d,CAST(:v AS vector),:h,'ready',true)"
                ),
                {"d": dish_id, "v": str(vector), "h": "0" * 64},
            )
    try:
        with TestClient(create_app(), headers={"X-Api-Key": api_key}) as test_client:
            yield test_client
    finally:
        cleanup()


def recommend(client: TestClient, **extra: object) -> dict:
    response = client.post(
        "/recommendations",
        json={
            "user_id": USER,
            "candidate_dish_ids": [SWEET, SPICY],
            "top_k": 2,
            "context": "roadmap_ai",
            **extra,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_conversation_vector_changes_ranking_without_writing_profile(
    client: TestClient, migrated_engine: Engine
) -> None:
    assert recommend(client)["items"][0]["dish_id"] == SWEET
    ranked = recommend(client, vector_source="conversation", user_vector_override=SPICY_VEC)
    assert ranked["vector_source"] == "conversation"
    assert ranked["items"][0]["dish_id"] == SPICY
    profile = client.get(f"/users/{USER}/preferences").json()
    assert profile["vec"] == SWEET_VEC
    with migrated_engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT vector_source,effective_vector FROM recommendation.recommendation_logs"
                " WHERE request_id=:r"
            ),
            {"r": ranked["request_id"]},
        ).one()
        assert row.vector_source == "conversation"
        assert row.effective_vector == SPICY_VEC


def test_cold_start_and_zero_vector_keep_existing_algorithm(
    client: TestClient, migrated_engine: Engine
) -> None:
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE recommendation.user_preference_vectors SET survey_answer_count=0"
                " WHERE user_id=:u"
            ),
            {"u": USER},
        )
    normal = recommend(client)
    overridden = recommend(client, vector_source="conversation", user_vector_override=SPICY_VEC)
    assert [(i["dish_id"], i["recommend_score"]) for i in normal["items"]] == [
        (i["dish_id"], i["recommend_score"]) for i in overridden["items"]
    ]
    zero = recommend(client, vector_source="conversation", user_vector_override=[0] * 12)
    assert all(i["explicit_score"] == 0 for i in zero["items"])


def test_agent_impressions_require_commit_and_are_idempotent(
    client: TestClient, migrated_engine: Engine
) -> None:
    ranked = recommend(client, vector_source="conversation", user_vector_override=SPICY_VEC)
    payload = {"user_id": USER, "request_id": ranked["request_id"], "dish_ids": [SPICY]}
    denied = client.post("/impressions", json=payload)
    assert denied.status_code == 409
    assert denied.json()["error_code"] == "AGENT_COMMIT_REQUIRED"
    payload["agent_proposal_id"] = 42
    assert client.post("/impressions", json=payload).json()["counted"] == [SPICY]
    assert client.post("/impressions", json=payload).json()["counted"] == []
    with migrated_engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT feedback_count,total_shown,total_interactions"
                " FROM recommendation.user_preference_vectors WHERE user_id=:u"
            ),
            {"u": USER},
        ).one()
        assert tuple(row) == (0, 1, 6)
        assert (
            connection.execute(
                text(
                    "SELECT agent_proposal_id FROM recommendation.recommendation_items"
                    " WHERE request_id=:r AND dish_id=:d"
                ),
                {"r": ranked["request_id"], "d": SPICY},
            ).scalar_one()
            == 42
        )


def test_preferences_missing_row_is_read_only(client: TestClient, migrated_engine: Engine) -> None:
    assert client.get(f"/users/{USER + 1}/preferences").json()["vec"] is None
    with migrated_engine.connect() as connection:
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM recommendation.user_preference_vectors WHERE user_id=:u"
                ),
                {"u": USER + 1},
            ).scalar_one()
            == 0
        )


@pytest.mark.parametrize(
    "extra",
    [
        {"vector_source": "profile", "user_vector_override": SPICY_VEC},
        {"vector_source": "conversation", "user_vector_override": [1]},
        {"vector_source": "conversation", "user_id": None},
    ],
)
def test_invalid_override_rejected(client: TestClient, extra: dict) -> None:
    response = client.post(
        "/recommendations",
        json={"user_id": USER, "candidate_dish_ids": [SWEET], "context": "roadmap_ai", **extra},
    )
    assert response.status_code == 422


def test_inherited_feedback_components_need_not_be_in_unit_interval(client: TestClient) -> None:
    result = recommend(
        client, vector_source="conversation", user_vector_override=[-0.2, 1.4] + [0] * 10
    )
    assert result["vector_source"] == "conversation"


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_override_is_rejected(invalid: float) -> None:
    with pytest.raises(ValidationError):
        RecommendationRequest.model_validate(
            {
                "user_id": USER,
                "candidate_dish_ids": [SWEET],
                "context": "roadmap_ai",
                "vector_source": "conversation",
                "user_vector_override": [invalid] + [0] * 11,
            }
        )
