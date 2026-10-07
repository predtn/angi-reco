import logging
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models import AlgorithmConfig
from app.schemas.health import HealthResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["operations"])


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": HealthResponse,
            "description": "Database unreachable or no active algorithm configuration",
        }
    },
)
async def health(session: Annotated[AsyncSession, Depends(get_session)]) -> JSONResponse:
    """RECO-07: service and database status. No X-Api-Key, so it returns nothing sensitive."""
    try:
        version = await session.scalar(
            select(AlgorithmConfig.config_version).where(AlgorithmConfig.is_active)
        )
    # asyncpg raises plain OSError (ConnectionError, TimeoutError) when the server is down.
    except (SQLAlchemyError, OSError):
        logger.warning("Health check cannot reach the database", exc_info=True)
        return _response(HealthResponse(db="error", active_config_version=None))

    if version is None:
        logger.error("No active row in algorithm_configs; run the migrations")
    return _response(HealthResponse(db="ok", active_config_version=version))


def _response(body: HealthResponse) -> JSONResponse:
    healthy = body.db == "ok" and body.active_config_version is not None
    return JSONResponse(
        status_code=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        content=body.model_dump(),
    )
