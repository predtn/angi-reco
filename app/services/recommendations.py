"""RECO-05 (POST /recommendations) and RECO-06 (POST /impressions).

RECO-05 ranks the candidates the backend already filtered and sorted (restaurant rating, then
like_count) with the scores of Design §3, and logs every candidate for evaluation. It never
counts impressions: N_i and N_total grow only through RECO-06, when the app really showed a dish.
"""

import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from fastapi import status
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import (
    AlgorithmConfig,
    DishStats,
    DishVector,
    RecommendationItem,
    RecommendationLog,
    UserDishScore,
    UserPreferenceVector,
)
from app.models.enums import DishVectorStatus
from app.services.scoring import Candidate, Params, ScoredCandidate, UserState, rank_candidates


@dataclass(frozen=True)
class RecommendationResult:
    request_id: uuid.UUID | None
    config_version: int
    items: list[ScoredCandidate]
    ignored_dish_ids: list[int]


@dataclass(frozen=True)
class ImpressionResult:
    request_id: uuid.UUID
    counted: list[int]
    ignored: list[int]


async def recommend(
    session: AsyncSession,
    user_id: int | None,
    candidate_dish_ids: Sequence[int],
    top_k: int,
    context: str,
) -> RecommendationResult:
    """RECO-05. `user_id` None = Guest: ranked by Wilson, nothing logged, request_id None.

    Dishes reco never received or that are inactive go to ignored_dish_ids. A repeated id is
    scored once, at its first position.
    """
    started = time.perf_counter()
    config = await session.scalar(select(AlgorithmConfig).where(AlgorithmConfig.is_active))
    if config is None:
        # /health reports the same problem; the backend falls back on any 5xx.
        raise RuntimeError("No active row in algorithm_configs; run the migrations")
    params = Params(
        k=float(config.params["k"]),
        k_prime=float(config.params["k_prime"]),
        z=float(config.params["z"]),
        gamma=float(config.params["gamma"]),
    )

    ordered_ids = list(dict.fromkeys(candidate_dish_ids))
    dishes = {
        row.dish_id: row
        for row in await session.execute(
            select(
                DishVector.dish_id,
                DishVector.vec,
                DishVector.status,
                func.coalesce(DishStats.like_count, 0).label("like_count"),
                func.coalesce(DishStats.dislike_count, 0).label("dislike_count"),
            )
            .outerjoin(DishStats, DishStats.dish_id == DishVector.dish_id)
            .where(DishVector.dish_id.in_(ordered_ids), DishVector.is_active)
        )
    }
    ignored = [dish_id for dish_id in ordered_ids if dish_id not in dishes]

    user = None
    scores: dict[int, UserDishScore] = {}
    if user_id is not None:
        preference = await session.get(UserPreferenceVector, user_id)
        user = UserState(
            vector=None if preference is None else preference.vec,
            m=0 if preference is None else (preference.total_interactions or 0),
            n_total=0 if preference is None else preference.total_shown,
        )
        scores = {
            row.dish_id: row
            for row in await session.scalars(
                select(UserDishScore).where(
                    UserDishScore.user_id == user_id, UserDishScore.dish_id.in_(list(dishes))
                )
            )
        }

    candidates = []
    for dish_id in ordered_ids:
        dish = dishes.get(dish_id)
        if dish is None:
            continue
        score = scores.get(dish_id)
        candidates.append(
            Candidate(
                dish_id=dish_id,
                vector=dish.vec if dish.status == DishVectorStatus.READY else None,
                like_count=dish.like_count,
                dislike_count=dish.dislike_count,
                implicit=0.5 if score is None else score.implicit_score,
                interaction_count=0 if score is None else score.interaction_count,
                shown_count=0 if score is None else score.shown_count,
            )
        )

    ranked = rank_candidates(candidates, user, params)
    if user_id is None or user is None or not ranked:
        return RecommendationResult(None, config.config_version, ranked[:top_k], ignored)

    delta = user.m / (user.m + params.k_prime)
    request_id = await session.scalar(
        insert(RecommendationLog)
        .values(
            user_id=user_id,
            config_version=config.config_version,
            context=context,
            m=user.m,
            n_total=user.n_total,
            delta=delta,
            candidate_count=len(ordered_ids),
            top_k=top_k,
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
        .returning(RecommendationLog.request_id)
    )
    # Every candidate is logged with all its scores, returned or not (evaluation plan, §6).
    await session.execute(
        insert(RecommendationItem),
        [
            {
                "request_id": request_id,
                "dish_id": item.dish_id,
                "rank": item.rank,
                "is_returned": item.rank <= top_k,
                "cosine_sim": item.cosine,
                "explicit_score": item.explicit,
                "implicit_score": item.implicit,
                "alpha": item.alpha,
                "personalized": item.personalized,
                "wilson": item.wilson,
                "final_score": item.final,
                "exploration": item.exploration,
                "recommend_score": item.recommend,
            }
            for item in ranked
        ],
    )
    await session.commit()
    return RecommendationResult(request_id, config.config_version, ranked[:top_k], ignored)


async def record_impressions(
    session: AsyncSession,
    user_id: int,
    request_id: uuid.UUID,
    dish_ids: Sequence[int],
    shown_at: datetime | None,
) -> ImpressionResult:
    """RECO-06: marks the dishes of a request as shown and adds 1 to N_i of each and to N_total.

    A dish counts once per request (shown_at IS NULL in the UPDATE), so a resent batch only
    returns it as ignored, as does a dish that is not part of the request.
    """
    owner = await session.scalar(
        select(RecommendationLog.user_id).where(RecommendationLog.request_id == request_id)
    )
    if owner is None:
        raise AppError(status.HTTP_404_NOT_FOUND, "REQUEST_NOT_FOUND", "Request not found.")
    if owner != user_id:
        raise AppError(
            status.HTTP_403_FORBIDDEN, "FORBIDDEN", "The request belongs to another user."
        )

    requested = list(dict.fromkeys(dish_ids))
    counted_rows = await session.scalars(
        update(RecommendationItem)
        .where(
            RecommendationItem.request_id == request_id,
            RecommendationItem.dish_id.in_(requested),
            RecommendationItem.shown_at.is_(None),
        )
        .values(shown_at=func.now() if shown_at is None else shown_at)
        .returning(RecommendationItem.dish_id)
    )
    counted_set = set(counted_rows)
    counted = [dish_id for dish_id in requested if dish_id in counted_set]

    if counted:
        await session.execute(
            insert(UserDishScore)
            .values(
                [{"user_id": user_id, "dish_id": dish_id, "shown_count": 1} for dish_id in counted]
            )
            .on_conflict_do_update(
                index_elements=[UserDishScore.user_id, UserDishScore.dish_id],
                set_={"shown_count": UserDishScore.shown_count + 1},
            )
        )
        await session.execute(
            insert(UserPreferenceVector)
            .values(user_id=user_id, total_shown=len(counted))
            .on_conflict_do_update(
                index_elements=[UserPreferenceVector.user_id],
                set_={"total_shown": UserPreferenceVector.total_shown + len(counted)},
            )
        )
    await session.commit()
    return ImpressionResult(
        request_id=request_id,
        counted=counted,
        ignored=[dish_id for dish_id in requested if dish_id not in counted_set],
    )
