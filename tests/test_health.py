from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError

from app.db.session import get_session
from app.main import create_app


class _FakeSession:
    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error

    async def scalar(self, _: Any) -> Any:
        if self._error is not None:
            raise self._error
        return self._result


def _client_with(session: _FakeSession) -> TestClient:
    app = create_app()

    async def override() -> _FakeSession:
        return session

    app.dependency_overrides[get_session] = override
    return TestClient(app)


@pytest.mark.parametrize(
    "error",
    [
        OperationalError("SELECT 1", {}, Exception("password authentication failed")),
        ConnectionError("unexpected connection_lost() call"),
        TimeoutError(),
    ],
    ids=["sqlalchemy-error", "connection-lost", "timeout"],
)
def test_reports_database_error_with_503(error: Exception) -> None:
    response = _client_with(_FakeSession(error=error)).get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "ok", "db": "error", "active_config_version": None}


def test_reports_missing_active_config_with_503() -> None:
    response = _client_with(_FakeSession(result=None)).get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "ok", "db": "ok", "active_config_version": None}


@pytest.mark.usefixtures("migrated_engine")
def test_reports_active_config_without_api_key(migrated_engine: Engine) -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok", "active_config_version": 1}
