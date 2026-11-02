"""Read-only preference snapshot used to initialize a conversation."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ontology import ONTOLOGY_VERSION
from app.db.session import get_session
from app.models import UserPreferenceVector

router = APIRouter(tags=["users"])


class UserPreferenceResponse(BaseModel):
    user_id: int
    ontology_version: int
    vec: list[float] | None
    updated_at: datetime | None


@router.get("/users/{user_id}/preferences", response_model=UserPreferenceResponse)
async def get_preferences(
    user_id: Annotated[int, Path(gt=0)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserPreferenceResponse:
    row = await session.get(UserPreferenceVector, user_id)
    return UserPreferenceResponse(
        user_id=user_id,
        ontology_version=ONTOLOGY_VERSION,
        vec=None if row is None or row.vec is None else [float(v) for v in row.vec],
        updated_at=None if row is None else row.updated_at,
    )
