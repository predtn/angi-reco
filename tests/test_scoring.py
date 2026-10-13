"""Scores of Design §3 without a database, with the examples of the design where it gives them."""

import math

import pytest

from app.services.scoring import (
    Candidate,
    Params,
    UserState,
    cosine,
    exploration_score,
    minmax_explicit,
    rank_candidates,
    wilson_lower_bound,
)

PARAMS = Params(k=5, k_prime=5, z=1.96, gamma=0)


def _vector(**scores: float) -> list[float]:
    names = ("sweet", "sour", "salty", "bitter", "umami", "spicy", "cooling", "astringent",
             "fatty", "fresh", "rich", "aromatic")  # fmt: skip
    return [scores.get(name, 0.0) for name in names]


def _candidate(dish_id: int, vector: list[float] | None = None, **kwargs: int | float) -> Candidate:
    return Candidate(
        dish_id=dish_id,
        vector=vector,
        like_count=int(kwargs.pop("likes", 0)),
        dislike_count=int(kwargs.pop("dislikes", 0)),
        **kwargs,  # type: ignore[arg-type]
    )


def test_wilson_is_zero_without_votes_and_cautious_with_few() -> None:
    assert wilson_lower_bound(0, 0, 1.96) == 0
    # 8 likes out of 10: the 95% lower bound, not 0.8
    assert wilson_lower_bound(8, 2, 1.96) == pytest.approx(0.4902, abs=1e-4)
    # same ratio with more votes is trusted more
    assert wilson_lower_bound(80, 20, 1.96) > wilson_lower_bound(8, 2, 1.96)


def test_exploration_is_zero_before_anything_was_shown() -> None:
    assert exploration_score(0, 0) == 0
    raw = math.sqrt(math.log(11) / 1)
    assert exploration_score(10, 0) == pytest.approx(raw / (1 + raw))
    assert exploration_score(10, 5) < exploration_score(10, 0)


def test_minmax_explicit() -> None:
    assert minmax_explicit([0.2, 0.6, None, 1.0]) == pytest.approx([0, 0.5, 0, 1])
    assert minmax_explicit([0.7, 0.7, None]) == [0.5, 0.5, 0.0]
    assert minmax_explicit([None, None]) == [0.0, 0.0]


def test_cosine_is_undefined_for_a_zero_vector() -> None:
    assert cosine(_vector(spicy=1), _vector(spicy=0.5)) == pytest.approx(1)
    assert cosine(_vector(spicy=1), _vector()) is None


def test_design_examples_for_delta_and_alpha() -> None:
    # m = 2 survey answers + 6 likes/dislikes -> Δ = 8 / 13 ≈ 0.615 (§3.3)
    # n = 3 likes of this dish -> α = 3 / 8 = 0.375 (§3.2)
    user = UserState(vector=_vector(umami=1), m=8, n_total=0)
    dish = _candidate(1, _vector(umami=1), likes=3, interaction_count=3, implicit=0.541)

    [scored] = rank_candidates([dish], user, PARAMS)

    assert scored.alpha == pytest.approx(0.375)
    assert scored.personalized == pytest.approx(0.625 * scored.explicit + 0.375 * 0.541)
    delta = 8 / 13
    assert scored.final == pytest.approx(delta * scored.personalized + (1 - delta) * scored.wilson)
    assert scored.recommend == scored.final  # γ = 0 until phase 3


def test_new_user_without_signals_is_ranked_by_wilson() -> None:
    # m = 0 -> Δ = 0 -> Final = Wilson (cold start, §3.3)
    user = UserState(vector=None, m=0, n_total=0)
    candidates = [_candidate(1, likes=1), _candidate(2, likes=9, dislikes=1), _candidate(3)]

    ranked = rank_candidates(candidates, user, PARAMS)

    assert [item.dish_id for item in ranked] == [2, 1, 3]
    assert all(item.final == item.wilson for item in ranked)


def test_ties_keep_the_order_the_backend_sent() -> None:
    # At launch every dish has Wilson = 0 (§3.6)
    candidates = [_candidate(dish_id) for dish_id in (40, 10, 30, 20)]

    ranked = rank_candidates(candidates, None, PARAMS)

    assert [item.dish_id for item in ranked] == [40, 10, 30, 20]
    assert [item.rank for item in ranked] == [1, 2, 3, 4]


def test_guest_has_no_explicit_and_no_exploration() -> None:
    candidates = [_candidate(1, _vector(spicy=1)), _candidate(2, _vector(sweet=1), likes=5)]

    ranked = rank_candidates(candidates, None, Params(k=5, k_prime=5, z=1.96, gamma=0.1))

    assert [item.dish_id for item in ranked] == [2, 1]
    assert all(item.explicit == 0 and item.exploration == 0 for item in ranked)
    assert all(item.cosine is None for item in ranked)


def test_surveyed_user_gets_the_dishes_close_to_their_taste_first() -> None:
    user = UserState(vector=_vector(spicy=1, umami=0.5), m=6, n_total=0)
    candidates = [
        _candidate(1, _vector(sweet=1)),
        _candidate(2, _vector(spicy=1, umami=0.75)),
        _candidate(3, None),  # vector still pending: Explicit = 0
    ]

    ranked = rank_candidates(candidates, user, PARAMS)

    assert [item.dish_id for item in ranked] == [2, 1, 3]
    assert ranked[0].explicit == 1
    assert ranked[2].explicit == 0 and ranked[2].cosine is None


def test_gamma_mixes_in_exploration() -> None:
    user = UserState(vector=None, m=0, n_total=20)
    candidates = [_candidate(1, shown_count=10), _candidate(2, shown_count=0)]

    ranked = rank_candidates(candidates, user, Params(k=5, k_prime=5, z=1.96, gamma=0.1))

    # Both have Final 0; the dish never shown explores more and moves up.
    assert [item.dish_id for item in ranked] == [2, 1]
    assert ranked[0].recommend == pytest.approx(0.1 * exploration_score(20, 0))
