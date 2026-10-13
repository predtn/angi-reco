"""Preference survey: RECO-03 (submit or skip) and RECO-09 (status).

Answers become the user vector by Recommendation_System_Design_Ver1.1 §3.2; the options and their
vectors are in .docs/Preference_Survey_Ver1.0.md (table survey_option_vectors).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.ontology import DIMENSION_COUNT
from app.models import SurveyOptionVector, UserPreferenceVector

# A scale_value left out counts as 1 (Design §3.2).
DEFAULT_SCALE = 1.0


@dataclass(frozen=True)
class WeightedOption:
    """One answer ready for §3.2: the option's vec and dim_mask with the answer's scale value."""

    vec: Sequence[float]
    dim_mask: Sequence[float]
    scale: float


@dataclass(frozen=True)
class SurveyResult:
    user_id: int
    survey_answer_count: int
    has_vector: bool
    survey_at: datetime


@dataclass(frozen=True)
class SurveyStatus:
    user_id: int
    completed: bool
    survey_at: datetime | None
    survey_answer_count: int


def build_user_vector(answers: Sequence[WeightedOption]) -> list[float] | None:
    """Design §3.2: User[d] = Σ s·vec[d]·mask[d] / Σ s·mask[d], and 0 when no answer touches d.

    Returns None for no answer or for the zero vector: a skipped survey or answers that only pick
    0-intensity options store vec = NULL (Explicit = 0), never the zero vector.
    """
    numerators = [0.0] * DIMENSION_COUNT
    denominators = [0.0] * DIMENSION_COUNT
    for answer in answers:
        for d in range(DIMENSION_COUNT):
            weight = answer.scale * answer.dim_mask[d]
            numerators[d] += weight * answer.vec[d]
            denominators[d] += weight

    vector = [
        numerator / denominator if denominator > 0 else 0.0
        for numerator, denominator in zip(numerators, denominators, strict=True)
    ]
    return vector if any(vector) else None


async def submit_survey(
    session: AsyncSession,
    user_id: int,
    answers: Sequence[tuple[str, float | None]],
    payload: dict[str, Any],
) -> SurveyResult:
    """RECO-03. `answers` are (option_code, scale_value); an empty list skips the survey.

    Raises 422 UNKNOWN_OPTION_CODE for a code missing from survey_option_vectors and 409
    SURVEY_ALREADY_SUBMITTED when the user already submitted or skipped (survey_at is set).
    """
    codes = {code for code, _ in answers}
    options: dict[str, SurveyOptionVector] = {}
    if codes:
        rows = await session.scalars(
            select(SurveyOptionVector).where(SurveyOptionVector.option_code.in_(codes))
        )
        options = {row.option_code: row for row in rows}
    unknown = sorted(codes - options.keys())
    if unknown:
        raise AppError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "UNKNOWN_OPTION_CODE",
            f"Unknown option_code: {', '.join(unknown)}.",
        )

    vector = build_user_vector(
        [
            WeightedOption(
                vec=options[code].vec,
                dim_mask=options[code].dim_mask,
                scale=DEFAULT_SCALE if scale is None else scale,
            )
            for code, scale in answers
        ]
    )

    values = {
        "initial_vec": vector,
        "vec": vector,
        "survey_answer_count": len(answers),
        "survey_payload": payload,
        "survey_at": func.now(),
    }
    # One statement, so two concurrent submissions cannot both pass: the row is written only while
    # survey_at is NULL, which also keeps feedback_count and total_shown of an existing row.
    statement = (
        insert(UserPreferenceVector)
        .values(user_id=user_id, **values)
        .on_conflict_do_update(
            index_elements=[UserPreferenceVector.user_id],
            set_=values,
            where=UserPreferenceVector.survey_at.is_(None),
        )
        .returning(UserPreferenceVector.survey_at)
    )
    survey_at = await session.scalar(statement)
    if survey_at is None:
        await session.rollback()
        raise AppError(
            status.HTTP_409_CONFLICT, "SURVEY_ALREADY_SUBMITTED", "Survey already submitted."
        )
    await session.commit()

    return SurveyResult(
        user_id=user_id,
        survey_answer_count=len(answers),
        has_vector=vector is not None,
        survey_at=survey_at,
    )


async def get_survey_status(session: AsyncSession, user_id: int) -> SurveyStatus:
    """RECO-09. No row or survey_at NULL means completed = false (API Design, RECO-09 note)."""
    row = (
        await session.execute(
            select(UserPreferenceVector.survey_at, UserPreferenceVector.survey_answer_count).where(
                UserPreferenceVector.user_id == user_id
            )
        )
    ).one_or_none()
    if row is None:
        return SurveyStatus(user_id=user_id, completed=False, survey_at=None, survey_answer_count=0)
    return SurveyStatus(
        user_id=user_id,
        completed=row.survey_at is not None,
        survey_at=row.survey_at,
        survey_answer_count=row.survey_answer_count,
    )
