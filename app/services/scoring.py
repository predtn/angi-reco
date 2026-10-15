"""Scores of Recommendation_System_Design_Ver1.1 §3, as pure functions.

Personalized = (1 − α)·Explicit + α·Implicit                      (§3.2)
Final        = Δ·Personalized + (1 − Δ)·Pooled_Wilson              (§3.3)
Recommend    = (1 − γ)·Final + γ·Exploration                       (§3.4)

Ranking is a stable sort on Recommend, so ties keep the order the backend sent (restaurant rating,
then like_count; §3.6).

RECO-04 updates the inputs after each like / dislike with implicit_score and move_user_vector.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Params:
    """algorithm_configs.params of the active config_version (§3.5)."""

    k: float
    k_prime: float
    z: float
    gamma: float


@dataclass(frozen=True)
class UserState:
    """None vector = no Explicit; m = survey answers + likes/dislikes; n_total = N_total."""

    vector: Sequence[float] | None
    m: int
    n_total: int


@dataclass(frozen=True)
class Candidate:
    """One candidate dish known to reco, in the order the backend sent it."""

    dish_id: int
    # None while the vector is pending or failed: Explicit = 0 (§3.6)
    vector: Sequence[float] | None
    like_count: int
    dislike_count: int
    # From user_dish_scores; a missing row means Implicit 0.5, n = 0, N_i = 0
    implicit: float = 0.5
    interaction_count: int = 0
    shown_count: int = 0


@dataclass(frozen=True)
class ScoredCandidate:
    dish_id: int
    rank: int
    cosine: float | None
    explicit: float
    implicit: float
    alpha: float
    personalized: float
    wilson: float
    final: float
    exploration: float
    recommend: float


def wilson_lower_bound(likes: int, dislikes: int, z: float) -> float:
    """Pooled Wilson Score (§3.3); 0 for a dish without votes."""
    n = likes + dislikes
    if n == 0:
        return 0.0
    p = likes / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / (1 + z * z / n)


def exploration_score(n_total: int, n_i: int) -> float:
    """UCB with ln(N_total + 1), squashed by SoftSign+ (§3.4)."""
    raw = math.sqrt(math.log(n_total + 1) / (n_i + 1))
    return raw / (1 + raw)


def cosine(a: Sequence[float], b: Sequence[float]) -> float | None:
    """None when either vector is zero (cosine is undefined; stored vectors are never zero)."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return None if norm == 0 else dot / norm


def minmax_explicit(cosines: Sequence[float | None]) -> list[float]:
    """Explicit = MinMax of the cosines over this candidate set (§3.2).

    A dish without cosine gets 0; when every cosine is equal there is no relative difference, so
    each gets 0.5."""
    known = [value for value in cosines if value is not None]
    if not known:
        return [0.0] * len(cosines)
    low, high = min(known), max(known)
    if high == low:
        return [0.0 if value is None else 0.5 for value in cosines]
    return [0.0 if value is None else (value - low) / (high - low) for value in cosines]


def rank_candidates(
    candidates: Sequence[Candidate], user: UserState | None, params: Params
) -> list[ScoredCandidate]:
    """Scores and ranks the candidates. `user` None = Guest: Explicit 0, Δ 0, no exploration, so the
    order is Wilson, then the order sent (§3.6)."""
    if user is not None and user.vector is not None:
        cosines = [
            None if candidate.vector is None else cosine(user.vector, candidate.vector)
            for candidate in candidates
        ]
    else:
        cosines = [None] * len(candidates)
    explicits = minmax_explicit(cosines)

    delta = 0.0 if user is None else user.m / (user.m + params.k_prime)
    scored = []
    for candidate, cos, explicit in zip(candidates, cosines, explicits, strict=True):
        n = candidate.interaction_count if user is not None else 0
        implicit = candidate.implicit if user is not None else 0.5
        alpha = n / (n + params.k)
        personalized = (1 - alpha) * explicit + alpha * implicit
        wilson = wilson_lower_bound(candidate.like_count, candidate.dislike_count, params.z)
        final = delta * personalized + (1 - delta) * wilson
        exploration = (
            0.0 if user is None else exploration_score(user.n_total, candidate.shown_count)
        )
        recommend = (1 - params.gamma) * final + params.gamma * exploration
        scored.append(
            ScoredCandidate(
                dish_id=candidate.dish_id,
                rank=0,
                cosine=cos,
                explicit=explicit,
                implicit=implicit,
                alpha=alpha,
                personalized=personalized,
                wilson=wilson,
                final=final,
                exploration=exploration,
                recommend=recommend,
            )
        )

    # sorted() is stable: equal scores keep the backend's order.
    ordered = sorted(scored, key=lambda item: item.recommend, reverse=True)
    return [
        ScoredCandidate(**{**item.__dict__, "rank": position})
        for position, item in enumerate(ordered, start=1)
    ]


# Online updates after a like / dislike (§3.2, §5.2; RECO-04).


def implicit_score(raw: float) -> float:
    """Implicit = SoftSign01(r) = 0.5 + 0.5·r / (1 + |r|), always from the raw sum r (§3.2)."""
    return 0.5 + 0.5 * raw / (1 + abs(raw))


def move_user_vector(
    user: Sequence[float] | None, dish: Sequence[float], beta_u: float, w: int
) -> list[float] | None:
    """User_new = User_old + β_u·w·(Dish − User_old), with User_old = 0 when the user has no vector
    yet, so a first like gives β_u·Dish and a first dislike −β_u·Dish (§3.2).

    Returns None instead of the zero vector, which is never stored (cosine is undefined for it).
    """
    old = [0.0] * len(dish) if user is None else [float(value) for value in user]
    new = [
        value + beta_u * w * (float(target) - value)
        for value, target in zip(old, dish, strict=True)
    ]
    return new if any(new) else None
