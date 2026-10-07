import hmac
from typing import Annotated

from fastapi import Depends, Security, status
from fastapi.security import APIKeyHeader

from app.core.config import Settings, get_settings
from app.core.errors import AppError

_api_key_header = APIKeyHeader(name="X-Api-Key", auto_error=False)


async def require_api_key(
    api_key: Annotated[str | None, Security(_api_key_header)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """Every endpoint except /health requires the shared key (API Design, Backend ↔ Reco)."""
    expected = settings.reco_api_key.get_secret_value().encode()
    if api_key is None or not hmac.compare_digest(api_key.encode(), expected):
        raise AppError(
            status.HTTP_401_UNAUTHORIZED, "UNAUTHORIZED", "Missing or invalid X-Api-Key."
        )
