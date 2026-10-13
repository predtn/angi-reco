from typing import Annotated

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas.survey import SurveyRequest, SurveyResponse, SurveyStatusResponse
from app.services import survey

router = APIRouter(prefix="/users/{user_id}/survey", tags=["users"])

# = core.users.id
UserId = Annotated[int, Path(gt=0)]
Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=SurveyResponse)
async def submit_survey(user_id: UserId, body: SurveyRequest, session: Session) -> SurveyResponse:
    """RECO-03: turns the answers into the user vector (Design §3.2). Accepted once per user."""
    result = await survey.submit_survey(
        session,
        user_id,
        [(answer.option_code, answer.scale_value) for answer in body.answers],
        payload=body.model_dump(mode="json"),
    )
    return SurveyResponse(
        user_id=result.user_id,
        survey_answer_count=result.survey_answer_count,
        has_vector=result.has_vector,
        survey_at=result.survey_at,
    )


@router.get("", response_model=SurveyStatusResponse)
async def get_survey_status(user_id: UserId, session: Session) -> SurveyStatusResponse:
    """RECO-09: whether the user answered or skipped the survey."""
    result = await survey.get_survey_status(session, user_id)
    return SurveyStatusResponse(
        user_id=result.user_id,
        completed=result.completed,
        survey_at=result.survey_at,
        survey_answer_count=result.survey_answer_count,
    )
