import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.router import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.db.session import create_engine
from app.services.dish_scorer import create_scorer
from app.services.dish_vectors import run_regeneration_loop


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = create_engine(settings)
    app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    # None until LLM_API_KEY and LLM_MODEL are set: dishes then stay pending (Design §2.4).
    app.state.dish_scorer = create_scorer(settings)
    loop_task = None
    if app.state.dish_scorer is None:
        logging.getLogger(__name__).warning("LLM_API_KEY / LLM_MODEL not set: no dish vectors")
    else:
        # Retries pending / failed dish vectors every 5 minutes.
        loop_task = asyncio.create_task(
            run_regeneration_loop(app.state.sessionmaker, app.state.dish_scorer)
        )
    try:
        yield
    finally:
        if loop_task is not None:
            loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await loop_task
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
