"""RECO-04 against the database (skipped locally when it is not reachable)."""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.main import create_app

# Far from real core ids and from the other test modules; every test deletes its rows.
USER_ID, OTHER_USER_ID = 900_401, 900_402
SPICY, PENDING, INACTIVE, UNKNOWN = 900_411, 900_412, 900_413, 900_414
BETA = 0.03  # beta_u and beta_s of config_version 1


def _vector(**scores: float) -> list[float]:
    names = ("sweet", "sour", "salty", "bitter", "umami", "spicy", "cooling", "astringent",
             "fatty", "fresh", "rich", "aromatic")  # fmt: skip
    return [scores.get(name, 0.0) for name in names]


def _pg_vector(**scores: float) -> str:
    return "[" + ",".join(str(value) for value in _vector(**scores)) + "]"


def _cleanup(engine: Engine) -> None:
    with engine.begin() as connection:
        for table in ("interaction_events", "user_preference_vectors", "user_dish_scores"):
            connection.execute(
                text(f"DELETE FROM recommendation.{table} WHERE user_id IN (:a, :b)"),
                {"a": USER_ID, "b": OTHER_USER_ID},
            )
        for table in ("dish_vectors", "dish_stats"):
            connection.execute(
                text(f"DELETE FROM recommendation.{table} WHERE dish_id BETWEEN 900400 AND 900499")
            )


@pytest.fixture
def client(migrated_engine: Engine, api_key: str) -> Iterator[TestClient]:
    _cleanup(migrated_engine)
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO recommendation.dish_vectors"
                " (dish_id, vec, source_hash, status, is_active) VALUES"
                " (:spicy, CAST(:v AS vector), :h, 'ready', true),"
                " (:pending, NULL, :h, 'pending', true),"
                " (:inactive, CAST(:v AS vector), :h, 'ready', false)"
            ),
            {
                "spicy": SPICY,
                "pending": PENDING,
                "inactive": INACTIVE,
                "v": _pg_vector(spicy=1, umami=0.5),
                "h": "0" * 64,
            },
        )
    with TestClient(create_app(), headers={"X-Api-Key": api_key}) as test_client:
        yield test_client
    _cleanup(migrated_engine)


def _feedback(
    client: TestClient,
    event_type: str = "like",
    *,
    user_id: int = USER_ID,
    dish_id: int = SPICY,
    occurred_at: str = "2026-10-10T02:00:00Z",
    **body: Any,
) -> Any:
    payload = {
        "event_uuid": str(uuid.uuid4()),
        "user_id": user_id,
        "dish_id": dish_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
        **body,
    }
    return client.post(
        "/feedback", json=payload, headers={"Idempotency-Key": payload["event_uuid"]}
    )


def _state(engine: Engine, user_id: int = USER_ID, dish_id: int = SPICY) -> dict[str, Any]:
    with engine.connect() as connection:
        user = connection.execute(
            text(
                "SELECT vec::text AS vec, feedback_count, total_interactions"
                " FROM recommendation.user_preference_vectors WHERE user_id = :u"
            ),
            {"u": user_id},
        ).one_or_none()
        score = connection.execute(
            text(
                "SELECT implicit_raw, implicit_score, interaction_count, last_feedback"
                " FROM recommendation.user_dish_scores WHERE user_id = :u AND dish_id = :d"
            ),
            {"u": user_id, "d": dish_id},
        ).one_or_none()
        stats = connection.execute(
            text(
                "SELECT like_count, dislike_count FROM recommendation.dish_stats WHERE dish_id = :d"
            ),
            {"d": dish_id},
        ).one_or_none()
        events = connection.execute(
            text(
                "SELECT event_type, w, request_id, config_version"
                " FROM recommendation.interaction_events WHERE user_id = :u ORDER BY id"
            ),
            {"u": user_id},
        ).all()
    vector = None
    if user is not None and user.vec is not None:
        vector = [float(value) for value in user.vec.strip("[]").split(",")]
    return {"user": user, "vector": vector, "score": score, "stats": stats, "events": events}


def test_first_like_creates_the_user_vector_and_every_derived_row(
    client: TestClient, migrated_engine: Engine
) -> None:
    request_id = str(uuid.uuid4())

    response = _feedback(client, request_id=request_id)

    assert response.status_code == 200
    assert response.json()["result"] == "applied"
    state = _state(migrated_engine)
    assert [(e.event_type, e.w, str(e.request_id), e.config_version) for e in state["events"]] == [
        ("like", 1, request_id, 1)
    ]
    # No vector yet: User_old = 0, so the first like gives β_u·Dish (§3.2).
    assert state["vector"] == pytest.approx(_vector(spicy=BETA, umami=BETA * 0.5))
    assert (state["user"].feedback_count, state["user"].total_interactions) == (1, 1)
    score = state["score"]
    assert score.implicit_raw == pytest.approx(BETA)
    assert score.implicit_score == pytest.approx(0.5 + 0.5 * BETA / (1 + BETA))
    assert (score.interaction_count, score.last_feedback) == (1, 1)
    assert tuple(state["stats"]) == (1, 0)


def test_a_resent_event_is_a_duplicate_and_changes_nothing(
    client: TestClient, migrated_engine: Engine
) -> None:
    event_uuid = str(uuid.uuid4())
    first = _feedback(client, event_uuid=event_uuid)
    before = _state(migrated_engine)

    again = _feedback(client, "dislike", event_uuid=event_uuid)

    assert first.json() == {"event_uuid": event_uuid, "result": "applied"}
    assert again.status_code == 200
    assert again.json() == {"event_uuid": event_uuid, "result": "duplicate"}
    assert _state(migrated_engine) == before


def test_a_user_keeps_one_vote_and_changing_their_mind_moves_it(
    client: TestClient, migrated_engine: Engine
) -> None:
    _feedback(client, "like", occurred_at="2026-10-10T02:00:00Z")
    _feedback(client, "like", occurred_at="2026-10-11T02:00:00Z")
    liked_twice = _state(migrated_engine)
    _feedback(client, "dislike", occurred_at="2026-10-12T02:00:00Z")
    _feedback(client, "like", user_id=OTHER_USER_ID, occurred_at="2026-10-12T03:00:00Z")

    # Two likes count once in dish_stats, but twice in r, n and m.
    assert tuple(liked_twice["stats"]) == (1, 0)
    assert liked_twice["score"].implicit_raw == pytest.approx(2 * BETA)
    assert liked_twice["score"].interaction_count == 2
    state = _state(migrated_engine)
    # The dislike moved this user's vote; the other user's like is a separate vote.
    assert tuple(state["stats"]) == (1, 1)
    assert state["score"].implicit_raw == pytest.approx(BETA)
    assert (state["score"].interaction_count, state["score"].last_feedback) == (3, -1)
    assert state["user"].feedback_count == 3


def test_an_older_event_does_not_replace_the_latest_vote(
    client: TestClient, migrated_engine: Engine
) -> None:
    _feedback(client, "dislike", occurred_at="2026-10-12T02:00:00Z")

    response = _feedback(client, "like", occurred_at="2026-10-10T02:00:00Z")

    assert response.json()["result"] == "applied"
    state = _state(migrated_engine)
    assert tuple(state["stats"]) == (0, 1)
    assert state["score"].last_feedback == -1
    # It still counts as an interaction: r and n include it.
    assert state["score"].implicit_raw == pytest.approx(0, abs=1e-6)  # real (float32)
    assert state["score"].interaction_count == 2


def test_feedback_moves_an_existing_survey_vector(
    client: TestClient, migrated_engine: Engine
) -> None:
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO recommendation.user_preference_vectors"
                " (user_id, initial_vec, vec, survey_answer_count, survey_at)"
                " VALUES (:u, CAST(:v AS vector), CAST(:v AS vector), 6, now())"
            ),
            {"u": USER_ID, "v": _pg_vector(sweet=1)},
        )

    _feedback(client, "dislike")

    state = _state(migrated_engine)
    # User_new = User + β_u·w·(Dish − User) with w = −1
    assert state["vector"] == pytest.approx(
        _vector(sweet=1 + BETA, spicy=-BETA, umami=-BETA * 0.5), abs=1e-6
    )
    assert state["user"].total_interactions == 7  # m = 6 survey answers + 1 feedback


def test_a_deactivated_dish_with_a_vector_still_counts(
    client: TestClient, migrated_engine: Engine
) -> None:
    response = _feedback(client, dish_id=INACTIVE)

    assert response.json()["result"] == "applied"
    assert tuple(_state(migrated_engine, dish_id=INACTIVE)["stats"]) == (1, 0)


def test_unknown_dish_is_404_and_a_pending_vector_is_503_with_retry_after(
    client: TestClient, migrated_engine: Engine
) -> None:
    unknown = _feedback(client, dish_id=UNKNOWN)
    pending = _feedback(client, dish_id=PENDING)

    assert unknown.status_code == 404
    assert unknown.json()["error_code"] == "DISH_NOT_FOUND"
    assert pending.status_code == 503
    assert pending.json()["error_code"] == "DISH_VECTOR_NOT_READY"
    assert pending.headers["Retry-After"] == "60"
    state = _state(migrated_engine, dish_id=PENDING)
    assert state["events"] == [] and state["user"] is None and state["stats"] is None


@pytest.mark.parametrize(
    "change",
    [
        {"event_type": "love"},
        {"user_id": 0},
        {"dish_id": -1},
        {"occurred_at": "2026-10-10T02:00:00"},  # no time zone
        {"event_uuid": "not-a-uuid"},
    ],
)
def test_invalid_body_is_422(client: TestClient, change: dict[str, Any]) -> None:
    body = {
        "event_uuid": str(uuid.uuid4()),
        "user_id": USER_ID,
        "dish_id": SPICY,
        "event_type": "like",
        "occurred_at": "2026-10-10T02:00:00Z",
        **change,
    }

    response = client.post("/feedback", json=body)

    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_FAILED"


def test_feedback_requires_the_api_key(client: TestClient) -> None:
    response = client.post("/feedback", json={}, headers={"X-Api-Key": "wrong"})

    assert response.status_code == 401
