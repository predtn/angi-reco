"""RECO-03 and RECO-09 against the database (skipped locally when it is not reachable)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.core.ontology import DIMENSIONS
from app.main import create_app

# Far from real core.users ids; every test deletes its rows.
USER_ID = 900_001


@pytest.fixture
def client(migrated_engine: Engine, api_key: str) -> Iterator[TestClient]:
    _delete_user(migrated_engine)
    with TestClient(create_app(), headers={"X-Api-Key": api_key}) as test_client:
        yield test_client
    _delete_user(migrated_engine)


def _delete_user(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM recommendation.user_preference_vectors WHERE user_id = :id"),
            {"id": USER_ID},
        )


def _user_row(engine: Engine) -> dict[str, object] | None:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT initial_vec::text AS initial_vec, vec::text AS vec, survey_answer_count,"
                " feedback_count, total_interactions, survey_payload, survey_at"
                " FROM recommendation.user_preference_vectors WHERE user_id = :id"
            ),
            {"id": USER_ID},
        ).one_or_none()
    return None if row is None else dict(row._mapping)


def _as_pgvector(**scores: float) -> str:
    return "[" + ",".join(f"{scores.get(name, 0):g}" for name in DIMENSIONS) + "]"


def test_survey_options_match_the_survey_document(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT option_code, vec::text AS vec, dim_mask::text AS dim_mask"
                " FROM recommendation.survey_option_vectors"
            )
        ).all()
    options = {row.option_code: (row.vec, row.dim_mask) for row in rows}

    assert len(options) == 27
    assert options["broth_rich"] == (
        _as_pgvector(umami=1, rich=1, fatty=0.5),
        _as_pgvector(umami=1, rich=1, fatty=1),
    )
    assert options["spicy_none"] == (_as_pgvector(), _as_pgvector(spicy=1))


def test_submit_stores_the_user_vector_and_status_reports_it(
    client: TestClient, migrated_engine: Engine
) -> None:
    response = client.post(
        f"/users/{USER_ID}/survey",
        json={
            "answers": [
                {"option_code": "spicy_medium"},
                {"option_code": "broth_rich"},
                {"option_code": "herbs_lots", "scale_value": 1},
            ],
            "occurred_at": "2026-10-02T02:30:00Z",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["user_id"] == USER_ID
    assert body["survey_answer_count"] == 3
    assert body["has_vector"] is True
    expected = _as_pgvector(spicy=0.5, umami=1, rich=1, fatty=0.5, aromatic=1, fresh=0.75)
    row = _user_row(migrated_engine)
    assert row is not None
    assert row["initial_vec"] == expected
    assert row["vec"] == expected
    assert row["total_interactions"] == 3
    assert row["survey_payload"]["occurred_at"] == "2026-10-02T02:30:00Z"

    status = client.get(f"/users/{USER_ID}/survey")
    assert status.status_code == 200
    assert status.json() == {
        "user_id": USER_ID,
        "completed": True,
        "survey_at": body["survey_at"],
        "survey_answer_count": 3,
    }


def test_skip_completes_the_survey_without_a_vector(
    client: TestClient, migrated_engine: Engine
) -> None:
    response = client.post(f"/users/{USER_ID}/survey", json={"answers": []})

    assert response.status_code == 201
    assert response.json()["survey_answer_count"] == 0
    assert response.json()["has_vector"] is False
    row = _user_row(migrated_engine)
    assert row is not None
    assert row["vec"] is None
    assert row["survey_at"] is not None
    assert client.get(f"/users/{USER_ID}/survey").json()["completed"] is True


def test_only_zero_options_count_answers_but_store_no_vector(
    client: TestClient, migrated_engine: Engine
) -> None:
    response = client.post(
        f"/users/{USER_ID}/survey",
        json={"answers": [{"option_code": "spicy_none"}, {"option_code": "sweet_low"}]},
    )

    assert response.status_code == 201
    assert response.json()["survey_answer_count"] == 2
    assert response.json()["has_vector"] is False
    row = _user_row(migrated_engine)
    assert row is not None
    assert row["vec"] is None


def test_second_submission_is_rejected(client: TestClient) -> None:
    first = client.post(f"/users/{USER_ID}/survey", json={"answers": []})
    second = client.post(
        f"/users/{USER_ID}/survey", json={"answers": [{"option_code": "spicy_hot"}]}
    )

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json() == {
        "error_code": "SURVEY_ALREADY_SUBMITTED",
        "message": "Survey already submitted.",
    }


def test_unknown_option_code_writes_nothing(client: TestClient, migrated_engine: Engine) -> None:
    response = client.post(
        f"/users/{USER_ID}/survey",
        json={"answers": [{"option_code": "spicy_hot"}, {"option_code": "broth_umani"}]},
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "UNKNOWN_OPTION_CODE"
    assert "broth_umani" in response.json()["message"]
    assert _user_row(migrated_engine) is None


def test_submission_keeps_counters_of_an_existing_row(
    client: TestClient, migrated_engine: Engine
) -> None:
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO recommendation.user_preference_vectors"
                " (user_id, feedback_count, total_shown) VALUES (:id, 4, 20)"
            ),
            {"id": USER_ID},
        )

    response = client.post(
        f"/users/{USER_ID}/survey", json={"answers": [{"option_code": "sour_high"}]}
    )

    assert response.status_code == 201
    row = _user_row(migrated_engine)
    assert row is not None
    assert row["feedback_count"] == 4
    assert row["total_interactions"] == 5


def test_status_of_a_user_without_survey(client: TestClient) -> None:
    response = client.get(f"/users/{USER_ID}/survey")

    assert response.status_code == 200
    assert response.json() == {
        "user_id": USER_ID,
        "completed": False,
        "survey_at": None,
        "survey_answer_count": 0,
    }


@pytest.mark.parametrize(
    "body",
    [
        {"answers": [{"option_code": "spicy_hot", "scale_value": 1.5}]},
        {"answers": [{"option_code": ""}]},
        {"answers": [{"option_code": "spicy_hot"}] * 51},
        {},
    ],
    ids=["scale-above-1", "empty-code", "more-than-50", "no-answers-field"],
)
def test_invalid_body_is_a_validation_error(client: TestClient, body: dict[str, object]) -> None:
    response = client.post(f"/users/{USER_ID}/survey", json=body)

    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_FAILED"


def test_survey_requires_the_api_key(client: TestClient) -> None:
    response = client.get(f"/users/{USER_ID}/survey", headers={"X-Api-Key": "wrong-key"})

    assert response.status_code == 401
