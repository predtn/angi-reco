import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Path, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.dish import DishDeactivateResponse, DishUpsertRequest, DishUpsertResponse
from app.services import dish_vectors
from app.services.dish_vectors import UpsertResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dishes", tags=["dishes"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("/upsert", response_model=DishUpsertResponse)
async def upsert_dish(
    body: DishUpsertRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session,
    # = outbox event_uuid. Repeats are already harmless: same content is unchanged and an older
    # occurred_at is stale, so the key is only logged.
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> DishUpsertResponse:
    """RECO-01: stores the dish; new or changed content gets a new vector in the background."""
    result = await dish_vectors.upsert_dish(
        session, body.dish_id, body.name, body.description, body.occurred_at
    )
    logger.info(
        "Dish %s upsert: %s (restaurant %s, event %s)",
        body.dish_id,
        result,
        body.restaurant_id,
        idempotency_key,
    )
    scorer = request.app.state.dish_scorer
    if scorer is not None and result in (UpsertResult.CREATED, UpsertResult.CONTENT_CHANGED):
        background_tasks.add_task(
            dish_vectors.generate_vector, request.app.state.sessionmaker, scorer, body.dish_id
        )
    return DishUpsertResponse(dish_id=body.dish_id, result=result)


@router.delete("/{dish_id}", response_model=DishDeactivateResponse)
async def deactivate_dish(
    dish_id: Annotated[int, Path(gt=0)],
    session: Session,
    occurred_at: Annotated[datetime | None, Query()] = None,
) -> DishDeactivateResponse:
    """RECO-02: removes the dish from every candidate list. not_found is still 200 so the outbox
    worker treats the event as done."""
    result = await dish_vectors.deactivate_dish(session, dish_id, occurred_at)
    return DishDeactivateResponse(dish_id=dish_id, result=result)
