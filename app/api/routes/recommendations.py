from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.recommendation import (
    ImpressionRequest,
    ImpressionResponse,
    RecoItem,
    RecommendationRequest,
    RecommendationResponse,
)
from app.services import recommendations

router = APIRouter(tags=["recommendations"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("/recommendations", response_model=RecommendationResponse)
async def recommend(body: RecommendationRequest, session: Session) -> RecommendationResponse:
    """RECO-05: ranks the backend's candidates (Design §3). Does not count impressions."""
    result = await recommendations.recommend(
        session,
        body.user_id,
        body.candidate_dish_ids,
        body.top_k,
        body.context,
        body.vector_source,
        body.user_vector_override,
    )
    return RecommendationResponse(
        vector_source=body.vector_source,
        request_id=result.request_id,
        config_version=result.config_version,
        items=[
            RecoItem(
                dish_id=item.dish_id,
                rank=item.rank,
                recommend_score=item.recommend,
                final_score=item.final,
                explicit_score=item.explicit,
                wilson=item.wilson,
                exploration=item.exploration,
            )
            for item in result.items
        ],
        ignored_dish_ids=result.ignored_dish_ids,
    )


@router.post("/impressions", response_model=ImpressionResponse)
async def record_impressions(body: ImpressionRequest, session: Session) -> ImpressionResponse:
    """RECO-06: dishes the app really showed; each counts once per request."""
    result = await recommendations.record_impressions(
        session,
        body.user_id,
        body.request_id,
        body.dish_ids,
        body.shown_at,
        body.agent_proposal_id,
    )
    return ImpressionResponse(
        request_id=result.request_id, counted=result.counted, ignored=result.ignored
    )
