"""Design §3.2–3.3 end to end inside reco: likes / dislikes sent to RECO-04 change the
Personalized and Final scores RECO-05 computes (skipped locally without a database)."""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.main import create_app
from app.services.scoring import implicit_score, wilson_lower_bound

# Far from real core ids and from the other test modules; every test deletes its rows.
USER_ID, NEW_USER_ID = 900_501, 900_502
COMMUNITY = (900_503, 900_504, 900_505)
SPICY, SWEET = 900_511, 900_512
BETA, K, K_PRIME, Z = 0.03, 5, 5, 1.96  # config_version 1


def _pg_vector(**scores: float) -> str:
    names = ("sweet", "sour", "salty", "bitter", "umami", "spicy", "cooling", "astringent",
             "fatty", "fresh", "rich", "aromatic")  # fmt: skip
    return "[" + ",".join(str(scores.get(name, 0)) for name in names) + "]"


def _cleanup(engine: Engine) -> None:
    users = (USER_ID, NEW_USER_ID, *COMMUNITY)
    with engine.begin() as connection:
        for table in (
            "recommendation_logs",
            "interaction_events",
            "user_preference_vectors",
            "user_dish_scores",
        ):
            connection.execute(
                text(f"DELETE FROM recommendation.{table} WHERE user_id = ANY(:users)"),
                {"users": list(users)},
            )
        for table in ("dish_vectors", "dish_stats"):
            connection.execute(
                text(f"DELETE FROM recommendation.{table} WHERE dish_id BETWEEN 900500 AND 900599")
            )


@pytest.fixture
def client(migrated_engine: Engine, api_key: str) -> Iterator[TestClient]:
    _cleanup(migrated_engine)
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO recommendation.dish_vectors"
                " (dish_id, vec, source_hash, status, is_active) VALUES"
                " (:spicy, CAST(:v_spicy AS vector), :h, 'ready', true),"
                " (:sweet, CAST(:v_sweet AS vector), :h, 'ready', true)"
            ),
            {
                "spicy": SPICY,
                "sweet": SWEET,
                "v_spicy": _pg_vector(spicy=1, umami=0.5),
                "v_sweet": _pg_vector(sweet=1),
                "h": "0" * 64,
            },
        )
    with TestClient(create_app(), headers={"X-Api-Key": api_key}) as test_client:
        yield test_client
    _cleanup(migrated_engine)


def _feedback(client: TestClient, user_id: int, dish_id: int, event_type: str) -> None:
    response = client.post(
        "/feedback",
        json={
            "event_uuid": str(uuid.uuid4()),
            "user_id": user_id,
            "dish_id": dish_id,
            "event_type": event_type,
            "occurred_at": "2026-10-15T02:00:00Z",
        },
    )
    assert response.json()["result"] == "applied"


def _recommend(client: TestClient, user_id: int) -> Any:
    response = client.post(
        "/recommendations",
        # The backend sends SWEET first (better restaurant rating), so a tie keeps it first.
        json={"user_id": user_id, "candidate_dish_ids": [SWEET, SPICY], "context": "list"},
    )
    assert response.status_code == 200
    return response.json()


def _logged(engine: Engine, request_id: str) -> dict[int, Any]:
    with engine.connect() as connection:
        log = connection.execute(
            text("SELECT m, delta FROM recommendation.recommendation_logs WHERE request_id = :r"),
            {"r": request_id},
        ).one()
        rows = connection.execute(
            text(
                "SELECT dish_id, explicit_score, implicit_score, alpha, personalized, wilson,"
                " final_score FROM recommendation.recommendation_items WHERE request_id = :r"
            ),
            {"r": request_id},
        ).all()
    return {"log": log, **{row.dish_id: row for row in rows}}


def test_community_likes_rank_a_new_user_by_wilson(
    client: TestClient, migrated_engine: Engine
) -> None:
    for user_id in COMMUNITY:
        _feedback(client, user_id, SPICY, "like")

    body = _recommend(client, NEW_USER_ID)

    # A new user has m = 0, so Δ = 0 and Final = Pooled Wilson (§3.3): SPICY's three likes lift it
    # over SWEET, which the backend had sent first.
    assert [item["dish_id"] for item in body["items"]] == [SPICY, SWEET]
    logged = _logged(migrated_engine, body["request_id"])
    assert (logged["log"].m, logged["log"].delta) == (0, 0)
    assert logged[SPICY].wilson == pytest.approx(wilson_lower_bound(3, 0, Z), abs=1e-6)
    assert logged[SPICY].final_score == pytest.approx(logged[SPICY].wilson, abs=1e-6)
    assert logged[SWEET].final_score == 0


def test_a_users_likes_and_dislikes_personalize_their_final_score(
    client: TestClient, migrated_engine: Engine
) -> None:
    # SWEET is the community favourite; this user, without a survey, likes SPICY twice and
    # dislikes SWEET once.
    for user_id in COMMUNITY:
        _feedback(client, user_id, SWEET, "like")
    _feedback(client, USER_ID, SPICY, "like")
    _feedback(client, USER_ID, SPICY, "like")
    _feedback(client, USER_ID, SWEET, "dislike")

    body = _recommend(client, USER_ID)

    assert [item["dish_id"] for item in body["items"]] == [SPICY, SWEET]
    logged = _logged(migrated_engine, body["request_id"])
    m = 3
    delta = m / (m + K_PRIME)
    assert (logged["log"].m, logged["log"].delta) == pytest.approx((m, delta))

    spicy = logged[SPICY]
    # The vector learned from the feedback points at SPICY, so it has the highest Explicit.
    assert spicy.explicit_score == 1
    assert spicy.implicit_score == pytest.approx(implicit_score(2 * BETA), abs=1e-6)
    assert spicy.alpha == pytest.approx(2 / (2 + K))
    assert spicy.personalized == pytest.approx(
        (1 - spicy.alpha) * spicy.explicit_score + spicy.alpha * spicy.implicit_score, abs=1e-6
    )
    # Two likes from one user are one vote in dish_stats (§3.3).
    assert spicy.wilson == pytest.approx(wilson_lower_bound(1, 0, Z), abs=1e-6)

    sweet = logged[SWEET]
    # One dislike: Implicit below neutral, and this user's vote is one of the four in dish_stats.
    assert sweet.implicit_score == pytest.approx(implicit_score(-BETA), abs=1e-6)
    assert sweet.implicit_score < 0.5
    assert sweet.explicit_score == 0
    assert sweet.wilson == pytest.approx(wilson_lower_bound(3, 1, Z), abs=1e-6)

    for row in (spicy, sweet):
        assert row.final_score == pytest.approx(
            delta * row.personalized + (1 - delta) * row.wilson, abs=1e-6
        )
