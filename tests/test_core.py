import pytest
from fastapi import Depends, FastAPI, status
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field, ValidationError

from app.core.config import Settings
from app.core.errors import AppError, register_exception_handlers
from app.core.security import require_api_key
from app.main import create_app


class _Body(BaseModel):
    dish_ids: list[int] = Field(min_length=1)


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/protected", dependencies=[Depends(require_api_key)])
    async def protected(body: _Body) -> dict[str, int]:
        return {"count": len(body.dish_ids)}

    @app.get("/not-ready")
    async def not_ready() -> None:
        raise AppError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "DISH_VECTOR_NOT_READY",
            "Dish vector is not ready.",
            headers={"Retry-After": "60"},
        )

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret detail")

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_build_app(), raise_server_exceptions=False)


@pytest.mark.parametrize("headers", [{}, {"X-Api-Key": "wrong-key"}])
def test_rejects_missing_or_wrong_api_key(client: TestClient, headers: dict[str, str]) -> None:
    response = client.post("/protected", json={"dish_ids": [1]}, headers=headers)

    assert response.status_code == 401
    assert response.json() == {
        "error_code": "UNAUTHORIZED",
        "message": "Missing or invalid X-Api-Key.",
    }


def test_accepts_valid_api_key(client: TestClient, api_key: str) -> None:
    response = client.post("/protected", json={"dish_ids": [1, 2]}, headers={"X-Api-Key": api_key})

    assert response.status_code == 200
    assert response.json() == {"count": 2}


def test_validation_error_lists_fields(client: TestClient, api_key: str) -> None:
    response = client.post("/protected", json={"dish_ids": []}, headers={"X-Api-Key": api_key})

    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "VALIDATION_FAILED"
    assert list(body["errors"]) == ["dish_ids"]


def test_app_error_keeps_status_code_and_headers(client: TestClient) -> None:
    response = client.get("/not-ready")

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "60"
    assert response.json()["error_code"] == "DISH_VECTOR_NOT_READY"


def test_unexpected_error_hides_details(client: TestClient) -> None:
    response = client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {"error_code": "INTERNAL_ERROR", "message": "Internal server error."}


def test_unknown_route_uses_error_shape() -> None:
    response = TestClient(create_app()).get("/unknown")

    assert response.status_code == 404
    assert response.json()["error_code"] == "NOT_FOUND"


def test_short_api_key_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url="postgresql+psycopg://x@localhost/x", reco_api_key="too-short")
