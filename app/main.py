import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.router import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.db.session import create_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Background jobs (e.g. regenerating pending dish vectors every 5 minutes) start here too.
    engine = create_engine(get_settings())
    app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield
    finally:
        await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    # The service is reachable from the internet on Render, so the docs are off in production.
    show_docs = settings.environment != "production"

    app = FastAPI(
        title="ANGI Recommendation Service",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if show_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if show_docs else None,
    )
    register_exception_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
