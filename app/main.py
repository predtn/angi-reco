import logging

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    # The service is reachable from the internet on Render, so the docs are off in production.
    show_docs = settings.environment != "production"

    app = FastAPI(
        title="ANGI Recommendation Service",
        version="0.1.0",
        docs_url="/docs" if show_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if show_docs else None,
    )
    register_exception_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
