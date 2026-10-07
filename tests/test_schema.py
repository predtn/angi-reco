"""Constraints of schema recommendation that later code relies on (needs a database)."""

import uuid

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import DataError, IntegrityError

V12 = "[" + ",".join(["0.5"] * 12) + "]"
ZERO12 = "[" + ",".join(["0"] * 12) + "]"


def test_initial_config_is_active_without_ucb(db: Connection) -> None:
    row = db.execute(
        text("SELECT config_version, params FROM recommendation.algorithm_configs WHERE is_active")
    ).one()

    assert row.config_version == 1
    assert row.params["gamma"] == 0
    assert row.params["ontology_version"] == 1


def test_total_interactions_is_survey_answers_plus_feedback(db: Connection) -> None:
    db.execute(
        text(
            "INSERT INTO recommendation.user_preference_vectors"
            " (user_id, survey_answer_count, feedback_count) VALUES (1, 2, 6)"
        )
    )

    m = db.scalar(
        text(
            "SELECT total_interactions FROM recommendation.user_preference_vectors"
            " WHERE user_id = 1"
        )
    )
    assert m == 8


def test_user_dish_score_defaults_are_neutral(db: Connection) -> None:
    db.execute(text("INSERT INTO recommendation.user_dish_scores (user_id, dish_id) VALUES (1, 2)"))

    row = db.execute(
        text("SELECT implicit_raw, implicit_score FROM recommendation.user_dish_scores")
    ).one()
    assert (row.implicit_raw, row.implicit_score) == (0, 0.5)


@pytest.mark.parametrize(
    "statement",
    [
        pytest.param(
            "INSERT INTO recommendation.algorithm_configs (config_version, params, is_active)"
            " VALUES (2, '{}', true)",
            id="second-active-config",
        ),
        pytest.param(
            "INSERT INTO recommendation.dish_vectors (dish_id, vec, source_hash, status)"
            f" VALUES (1, '{ZERO12}', repeat('a', 64), 'ready')",
            id="zero-dish-vector",
        ),
        pytest.param(
            "INSERT INTO recommendation.dish_vectors (dish_id, source_hash, status)"
            " VALUES (1, repeat('a', 64), 'ready')",
            id="ready-without-vector",
        ),
        pytest.param(
            "INSERT INTO recommendation.dish_vectors (dish_id, source_hash, status)"
            " VALUES (1, repeat('a', 64), 'done')",
            id="unknown-status",
        ),
        pytest.param(
            "INSERT INTO recommendation.user_preference_vectors (user_id, vec)"
            f" VALUES (1, '{ZERO12}')",
            id="zero-user-vector",
        ),
        pytest.param(
            "INSERT INTO recommendation.user_dish_scores (user_id, dish_id, implicit_score)"
            " VALUES (1, 2, 1.2)",
            id="implicit-score-out-of-range",
        ),
        pytest.param(
            "INSERT INTO recommendation.interaction_events"
            " (event_uuid, user_id, dish_id, event_type, w, occurred_at)"
            f" VALUES ('{uuid.uuid4()}', 1, 2, 'like', -1, now())",
            id="like-with-negative-weight",
        ),
        pytest.param(
            "INSERT INTO recommendation.recommendation_logs"
            " (user_id, config_version, context, m, n_total, delta, candidate_count, top_k)"
            " VALUES (1, 1, 'search', 0, 0, 0, 1, 1)",
            id="unknown-context",
        ),
    ],
)
def test_rejects_invalid_rows(db: Connection, statement: str) -> None:
    with pytest.raises(IntegrityError):
        db.execute(text(statement))


def test_rejects_vector_with_wrong_dimension(db: Connection) -> None:
    with pytest.raises(DataError):
        db.execute(
            text(
                "INSERT INTO recommendation.dish_vectors (dish_id, vec, source_hash)"
                " VALUES (1, '[0.5,0.5]', repeat('a', 64))"
            )
        )


def test_rejects_duplicate_event_uuid(db: Connection) -> None:
    insert = text(
        "INSERT INTO recommendation.interaction_events"
        " (event_uuid, user_id, dish_id, event_type, w, occurred_at)"
        " VALUES (:event_uuid, 1, 2, 'like', 1, now())"
    )
    event_uuid = uuid.uuid4()
    db.execute(insert, {"event_uuid": event_uuid})

    with pytest.raises(IntegrityError):
        db.execute(insert, {"event_uuid": event_uuid})


def test_cosine_distance_works_on_stored_vectors(db: Connection) -> None:
    db.execute(
        text(
            "INSERT INTO recommendation.dish_vectors (dish_id, vec, source_hash, status)"
            f" VALUES (1, '{V12}', repeat('a', 64), 'ready')"
        )
    )

    distance = db.scalar(
        text(f"SELECT vec <=> '{V12}' FROM recommendation.dish_vectors WHERE dish_id = 1")
    )
    assert distance == pytest.approx(0)
