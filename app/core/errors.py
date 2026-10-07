"""Error responses of the Reco API.

Responses are not wrapped (API Design, sheet Tổng quan). Every error body has the same shape so
the backend can branch on `error_code`:

    {"error_code": "SURVEY_ALREADY_SUBMITTED", "message": "...", "errors": {...}}

`errors` (field -> messages) is present only for 422 VALIDATION_FAILED. The outbox worker treats
4xx as final (dead) and 5xx as retryable, so pick the status with that in mind.
"""

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

_HTTP_ERROR_CODES = {
    status.HTTP_404_NOT_FOUND: "NOT_FOUND",
    status.HTTP_405_METHOD_NOT_ALLOWED: "METHOD_NOT_ALLOWED",
}


class AppError(Exception):
    """An expected error with its HTTP status and error code (sheet Reco API)."""

    def __init__(
        self,
        status_code: int,
        error_code: str,
        message: str,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.headers = dict(headers) if headers else None


def error_response(
    status_code: int,
    error_code: str,
    message: str,
    errors: dict[str, list[str]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {"error_code": error_code, "message": message}
    if errors is not None:
        body["errors"] = errors
    return JSONResponse(status_code=status_code, content=body, headers=headers)


def _field_name(location: Sequence[int | str]) -> str:
    # ("body", "answers", 0, "option_code") -> "answers.0.option_code"
    parts = location[1:] if location and location[0] in ("body", "query", "path") else location
    return ".".join(str(part) for part in parts) or "body"


async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    return error_response(exc.status_code, exc.error_code, exc.message, headers=exc.headers)


async def _handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors: dict[str, list[str]] = {}
    for error in exc.errors():
        errors.setdefault(_field_name(error["loc"]), []).append(error["msg"])
    return error_response(
        status.HTTP_422_UNPROCESSABLE_CONTENT, "VALIDATION_FAILED", "Invalid request.", errors
    )


async def _handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    error_code = _HTTP_ERROR_CODES.get(exc.status_code, "HTTP_ERROR")
    return error_response(exc.status_code, error_code, str(exc.detail), headers=exc.headers)


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "Internal server error."
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)
