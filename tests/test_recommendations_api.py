"""RECO-05 and RECO-06 against the database (skipped locally when it is not reachable)."""

import time
from collections.abc import Iterator
from typing import Any

import pytest
from asyncpg import UniqueViolationError
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.main import create_app
from app.services import recommendations

# Far from real core ids; every test deletes its rows.
USER_ID = 900_301
OTHER_USER_ID = 900_302
SPICY, SWEET, PENDING, INACTIVE, UNKNOWN = 900_311, 900_312, 900_313, 900_314, 900_315
BULK_FIRST = 950_000


def _pg_vector(**scores: float) -> str:
    names = ("sweet", "sour", "salty", "bitter", "umami", "spicy", "cooling", "astringent",
             "fatty", "fresh", "rich", "aromatic")  # fmt: skip
    return "[" + ",".join(str(scores.get(name, 0)) for name in names) + "]"


def _cleanup(engine: Engine) -> None:
    with engine.begin() as connection:
        for table in ("recommendation_logs", "user_preference_vectors", "user_dish_scores"):
            connection.execute(
                text(f"DELETE FROM recommendation.{table} WHERE user_id IN (:a, :b)"),
                {"a": USER_ID, "b": OTHER_USER_ID},
            )
        for table in ("dish_vectors", "dish_stats"):
            connection.execute(
                text(f"DELETE FROM recommendation.{table} WHERE dish_id BETWEEN 900300 AND 999999")
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
                " (:sweet, CAST(:v_sweet AS vector), :h, 'ready', true),"
                " (:pending, NULL, :h, 'pending', true),"
                " (:inactive, CAST(:v_spicy AS vector), :h, 'ready', false)"
            ),
            {
                "spicy": SPICY,
                "sweet": SWEET,
                "pending": PENDING,
                "inactive": INACTIVE,
                "v_spicy": _pg_vector(spicy=1, umami=0.75),
                "v_sweet": _pg_vector(sweet=1),
                "h": "0" * 64,
            },
        )
        # The sweet dish is liked by the community; the spicy one has no votes yet.
        connection.execute(
            text("INSERT INTO recommendation.dish_stats (dish_id, like_count) VALUES (:id, 9)"),
            {"id": SWEET},
        )
    with TestClient(create_app(), headers={"X-Api-Key": api_key}) as test_client:
        yield test_client
    _cleanup(migrated_engine)


def _survey_user(engine: Engine, user_id: int = USER_ID) -> None:
    """A user who likes spicy, umami food and answered 6 survey questions (m = 6)."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO recommendation.user_preference_vectors"
                " (user_id, initial_vec, vec, survey_answer_count, survey_at)"
                " VALUES (:id, CAST(:v AS vector), CAST(:v AS vector), 6, now())"
            ),
            {"id": user_id, "v": _pg_vector(spicy=1, umami=0.5)},
        )


def _recommend(client: TestClient, user_id: int | None = USER_ID, **body: Any) -> Any:
    payload = {
        "candidate_dish_ids": [SWEET, SPICY, PENDING, INACTIVE, UNKNOWN],
        "top_k": 2,
        "context": "list",
        **body,
    }
    if user_id is not None:
        payload["user_id"] = user_id
    return client.post("/recommendations", json=payload)


def test_guest_is_ranked_by_wilson_and_not_logged(
    client: TestClient, migrated_engine: Engine
) -> None:
    response = _recommend(client, user_id=None)

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] is None
    assert body["config_version"] == 1
    # Sweet has community likes; spicy and pending tie at Wilson 0 and keep the order sent.
    assert [item["dish_id"] for item in body["items"]] == [SWEET, SPICY]
    assert body["ignored_dish_ids"] == [INACTIVE, UNKNOWN]
    with migrated_engine.connect() as connection:
        count = connection.execute(
            text("SELECT count(*) FROM recommendation.recommendation_logs WHERE user_id IS NULL")
        ).scalar_one()
    assert count == 0


def test_surveyed_user_gets_personalized_ranking_and_a_full_log(
    client: TestClient, migrated_engine: Engine
) -> None:
    _survey_user(migrated_engine)

    response = _recommend(client, top_k=2)

    body = response.json()
    assert response.status_code == 200
    assert body["request_id"] is not None
    # Δ = 6/11: the spicy dish matches the taste and overtakes the community favourite.
    assert [item["dish_id"] for item in body["items"]] == [SPICY, SWEET]
    first = body["items"][0]
    assert first["rank"] == 1
    assert first["explicit_score"] == 1
    assert first["recommend_score"] == pytest.approx(first["final_score"])  # γ = 0
    assert set(first) == {
        "dish_id", "rank", "recommend_score", "final_score", "explicit_score", "wilson",
        "exploration",
    }  # fmt: skip

    with migrated_engine.connect() as connection:
        log = connection.execute(
            text(
                "SELECT m, n_total, delta, candidate_count, top_k, context"
                " FROM recommendation.recommendation_logs WHERE request_id = :r"
            ),
            {"r": body["request_id"]},
        ).one()
        items = connection.execute(
            text(
                "SELECT dish_id, rank, is_returned, cosine_sim, shown_at"
                " FROM recommendation.recommendation_items WHERE request_id = :r ORDER BY rank"
            ),
            {"r": body["request_id"]},
        ).all()
    assert (log.m, log.n_total, log.candidate_count, log.top_k, log.context) == (6, 0, 5, 2, "list")
    assert log.delta == pytest.approx(6 / 11)
    # Every known candidate is logged, returned or not; ignored dishes are not.
    assert [(row.dish_id, row.rank, row.is_returned) for row in items] == [
        (SPICY, 1, True),
        (SWEET, 2, True),
        (PENDING, 3, False),
    ]
    assert items[2].cosine_sim is None
    assert all(row.shown_at is None for row in items)


def test_impressions_count_each_dish_once_per_request(
    client: TestClient, migrated_engine: Engine
) -> None:
    _survey_user(migrated_engine)
    request_id = _recommend(client, top_k=3).json()["request_id"]

    first = client.post(
        "/impressions",
        json={"user_id": USER_ID, "request_id": request_id, "dish_ids": [SPICY, SWEET, SPICY]},
    )
    again = client.post(
        "/impressions",
        json={
            "user_id": USER_ID,
            "request_id": request_id,
            "dish_ids": [SWEET, PENDING, UNKNOWN],
            "shown_at": "2026-10-02T02:15:00Z",
        },
    )

    assert first.status_code == 200
    assert first.json() == {"request_id": request_id, "counted": [SPICY, SWEET], "ignored": []}
    assert again.json() == {
        "request_id": request_id,
        "counted": [PENDING],
        "ignored": [SWEET, UNKNOWN],
    }
    with migrated_engine.connect() as connection:
        total_shown = connection.execute(
            text(
                "SELECT total_shown FROM recommendation.user_preference_vectors WHERE user_id = :u"
            ),
            {"u": USER_ID},
        ).scalar_one()
        shown = dict(
            connection.execute(
                text(
                    "SELECT dish_id, shown_count FROM recommendation.user_dish_scores"
                    " WHERE user_id = :u"
                ),
                {"u": USER_ID},
            ).all()
        )
    assert total_shown == 3
    assert shown == {SPICY: 1, SWEET: 1, PENDING: 1}


def test_impressions_feed_exploration_and_m_of_the_next_recommendation(
    client: TestClient, migrated_engine: Engine
) -> None:
    _survey_user(migrated_engine)
    request_id = _recommend(client).json()["request_id"]
    client.post(
        "/impressions", json={"user_id": USER_ID, "request_id": request_id, "dish_ids": [SPICY]}
    )

    body = _recommend(client, top_k=3).json()

    by_id = {item["dish_id"]: item for item in body["items"]}
    # N_total = 1: the dish already shown explores less than the ones never shown.
    assert by_id[SPICY]["exploration"] < by_id[SWEET]["exploration"]


def test_impressions_of_an_unknown_or_foreign_request_are_rejected(
    client: TestClient, migrated_engine: Engine
) -> None:
    _survey_user(migrated_engine)
    request_id = _recommend(client).json()["request_id"]

    unknown = client.post(
        "/impressions",
        json={
            "user_id": USER_ID,
            "request_id": "6f0c2b1e-8d7a-4c1e-9b3f-2a5d7e9c1f00",
            "dish_ids": [SPICY],
        },
    )
    foreign = client.post(
        "/impressions",
        json={"user_id": OTHER_USER_ID, "request_id": request_id, "dish_ids": [SPICY]},
    )

    assert unknown.status_code == 404
    assert unknown.json()["error_code"] == "REQUEST_NOT_FOUND"
    assert foreign.status_code == 403
    assert foreign.json()["error_code"] == "FORBIDDEN"


def test_two_thousand_candidates_are_ranked_within_the_backend_budget(
    client: TestClient, migrated_engine: Engine
) -> None:
    _survey_user(migrated_engine)
    ids = list(range(BULK_FIRST, BULK_FIRST + 2000))
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO recommendation.dish_vectors (dish_id, vec, source_hash, status)"
                " SELECT g, CAST(:v AS vector), :h, 'ready' FROM generate_series(:a, :b) AS g"
            ),
            {"v": _pg_vector(spicy=0.5, sweet=0.5), "h": "0" * 64, "a": ids[0], "b": ids[-1]},
        )

    started = time.perf_counter()
    response = _recommend(client, candidate_dish_ids=ids, top_k=200)
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    assert len(response.json()["items"]) == 200
    # Identical dishes: the order sent is kept.
    assert [item["dish_id"] for item in response.json()["items"]] == ids[:200]
    with migrated_engine.connect() as connection:
        counts = connection.execute(
            text(
                "SELECT count(*), count(*) FILTER (WHERE is_returned),"
                " count(*) FILTER (WHERE shown_at IS NOT NULL)"
                " FROM recommendation.recommendation_items WHERE request_id = :r"
            ),
            {"r": response.json()["request_id"]},
        ).one()
    assert tuple(counts) == (2000, 200, 0)
    # The backend waits 800 ms; leave room for slower machines and CI.
    assert elapsed < 0.8, f"took {elapsed:.3f}s"


def test_score_copy_failure_rolls_back_the_parent_log(
    client: TestClient, migrated_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_rank = recommendations.rank_candidates

    def duplicate_dish(*args: Any, **kwargs: Any) -> Any:
        ranked = original_rank(*args, **kwargs)
        return [*ranked, ranked[0]]

    monkeypatch.setattr(recommendations, "rank_candidates", duplicate_dish)
    with pytest.raises(UniqueViolationError):
        _recommend(client)

    with migrated_engine.connect() as connection:
        count = connection.execute(
            text("SELECT count(*) FROM recommendation.recommendation_logs WHERE user_id = :u"),
            {"u": USER_ID},
        ).scalar_one()
    assert count == 0


@pytest.mark.parametrize(
    "body",
    [
        {"candidate_dish_ids": [], "context": "list"},
        {"candidate_dish_ids": [1] * 2001, "context": "list"},
        {"candidate_dish_ids": [1], "context": "list", "top_k": 201},
        {"candidate_dish_ids": [1], "context": "search"},
        {"candidate_dish_ids": [1]},
    ],
    ids=["no-candidate", "more-than-2000", "top-k-201", "unknown-context", "no-context"],
)
def test_invalid_recommendation_body(client: TestClient, body: dict[str, Any]) -> None:
    response = client.post("/recommendations", json=body)

    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_FAILED"


def test_recommendation_endpoints_require_the_api_key(client: TestClient) -> None:
    response = client.post(
        "/recommendations",
        json={"candidate_dish_ids": [1], "context": "list"},
        headers={"X-Api-Key": "wrong"},
    )
    assert response.status_code == 401
