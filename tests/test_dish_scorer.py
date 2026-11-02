"""OpenAI dish scoring without calling OpenAI: the request it sends and how it reads the answer."""

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import APITimeoutError

from app.core.config import Settings
from app.core.ontology import DIMENSIONS
from app.services import dish_scorer
from app.services.dish_scorer import OpenAIDishScorer, ScoringError, create_scorer
from scripts.backfill_dishes import to_payload


class _FakeCompletions:
    def __init__(self, content: str | None = None, error: Exception | None = None) -> None:
        self._content = content
        self._error = error
        self.kwargs: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if self._error is not None:
            raise self._error
        message = SimpleNamespace(content=self._content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _scorer(completions: _FakeCompletions) -> OpenAIDishScorer:
    scorer = OpenAIDishScorer("test-key", "test-model", 30)
    scorer._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))  # type: ignore[assignment]
    return scorer


def test_sends_the_dish_with_a_strict_schema_of_the_12_dimensions() -> None:
    answer = {name: 0.5 for name in DIMENSIONS}
    completions = _FakeCompletions(json.dumps(answer))

    scored = asyncio.run(_scorer(completions).score("Bún bò Huế", "Nước dùng hầm xương, sả"))

    assert scored.scores == answer
    assert scored.raw_output == answer
    kwargs = completions.kwargs
    assert kwargs["model"] == "test-model"
    assert "Bún bò Huế" in kwargs["messages"][1]["content"]
    assert "0. sweet (food_tastes): Vị ngọt" in kwargs["messages"][0]["content"]
    schema = kwargs["response_format"]["json_schema"]
    assert schema["strict"] is True
    assert schema["schema"]["required"] == list(DIMENSIONS)
    assert schema["schema"]["additionalProperties"] is False


@pytest.mark.parametrize(
    "completions",
    [
        _FakeCompletions(error=APITimeoutError(httpx.Request("POST", "https://api.openai.com"))),
        _FakeCompletions(None),
        _FakeCompletions("not json"),
        _FakeCompletions("[0.5, 0.5]"),
    ],
    ids=["timeout", "no-content", "invalid-json", "not-an-object"],
)
def test_unusable_answers_raise_scoring_error(completions: _FakeCompletions) -> None:
    with pytest.raises(ScoringError):
        asyncio.run(_scorer(completions).score("Phở", None))


def test_scorer_needs_both_key_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    # Only the values given here count, not a developer's .env or environment.
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    base: dict[str, Any] = {
        "_env_file": None,
        "database_url": "postgresql://x@localhost/x",
        "reco_api_key": "k" * 32,
    }

    assert create_scorer(Settings(**base)) is None
    assert create_scorer(Settings(**base, llm_api_key="sk-test")) is None
    assert create_scorer(Settings(**base, llm_model="test-model")) is None
    scorer = create_scorer(Settings(**base, llm_api_key="sk-test", llm_model="test-model"))
    assert isinstance(scorer, dish_scorer.OpenAIDishScorer)
    assert scorer.model_name == "test-model"


@pytest.mark.parametrize(
    "endpoint",
    [None, "https://generativelanguage.googleapis.com/v1beta/openai/"],
    ids=["default-openai", "configured-provider"],
)
def test_scorer_passes_configured_provider_to_client(
    monkeypatch: pytest.MonkeyPatch, endpoint: str | None
) -> None:
    captured: dict[str, Any] = {}

    def client(**kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(dish_scorer, "AsyncOpenAI", client)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    if endpoint is not None:
        monkeypatch.setenv("LLM_BASE_URL", endpoint)
    settings = Settings(
        _env_file=None,
        database_url="postgresql://x@localhost/x",
        reco_api_key="k" * 32,
        llm_api_key="test-only-key",
        llm_model="test-model",
        llm_timeout_seconds=17,
    )

    scorer = create_scorer(settings)

    assert isinstance(scorer, OpenAIDishScorer)
    assert scorer.model_name == "test-model"
    assert captured == {
        "api_key": "test-only-key",
        "base_url": endpoint or "https://api.openai.com/v1/",
        "timeout": 17,
        "max_retries": 1,
    }


def test_backfill_payload_matches_reco_01() -> None:
    row = {
        "id": 105,
        "name": "Bún bò Huế",
        "description": None,
        "dish_form": "soup",
        "restaurant_id": 7,
        "updated_at": datetime(2026, 10, 2, 2, 0, tzinfo=UTC),
    }

    assert to_payload(row) == {
        "dish_id": 105,
        "name": "Bún bò Huế",
        "description": None,
        "dish_form": "soup",
        "occurred_at": "2026-10-02T02:00:00+00:00",
        "restaurant_id": 7,
    }
