"""RECO-03 and RECO-09 bodies (API Design, sheet Chi tiết Request-Response)."""

from datetime import datetime

from pydantic import BaseModel, Field


class SurveyAnswer(BaseModel):
    # Must exist in survey_option_vectors.option_code (varchar(50)); unknown -> UNKNOWN_OPTION_CODE.
    option_code: str = Field(min_length=1, max_length=50)
    # Weight of the answer; left out = 1 (Design §3.2).
    scale_value: float | None = Field(default=None, ge=0, le=1)


class SurveyRequest(BaseModel):
    # Empty = the user skipped the survey (PREF-03).
    answers: list[SurveyAnswer] = Field(max_length=50)
    # When the user took the survey; kept in survey_payload.
    occurred_at: datetime | None = None


class SurveyResponse(BaseModel):
    user_id: int
    survey_answer_count: int
    has_vector: bool
    survey_at: datetime


class SurveyStatusResponse(BaseModel):
    user_id: int
    # True once the user answered or skipped the survey.
    completed: bool
    survey_at: datetime | None
    # 0 = skipped (or not done yet).
    survey_answer_count: int
