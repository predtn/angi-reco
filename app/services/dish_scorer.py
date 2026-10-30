"""Scores a dish on the 12 ontology dimensions with an OpenAI model (Design §2.4).

The model answers against a strict JSON schema of the 12 dimensions; the caller still validates
the scores with `vector_from_scores`, so a schema slip only marks the dish failed.
"""

import json
from dataclasses import dataclass
from typing import Any, Protocol

from openai import AsyncOpenAI, OpenAIError

from app.core.config import Settings
from app.core.ontology import DIMENSIONS, SCALE, describe_dimensions

_SYSTEM_PROMPT = f"""You score Vietnamese dishes for a food recommendation system.
Rate how strongly the dish shows each dimension below, from its name and description.
Use only these values: {", ".join(f"{value:g}" for value in SCALE)}
(0 = absent, 0.25 = slight, 0.5 = moderate, 0.75 = strong, 1 = dominant).
Judge the dish as it is usually served in Vietnam; do not invent toppings it does not have.

Dimensions (key, group, meaning):
{describe_dimensions()}

Answer with a JSON object holding exactly these {len(DIMENSIONS)} keys."""

_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "dish_vector",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {name: {"type": "number", "enum": list(SCALE)} for name in DIMENSIONS},
            "required": list(DIMENSIONS),
            "additionalProperties": False,
        },
    },
}


class ScoringError(Exception):
    """The model could not be reached or gave no usable answer; the dish becomes failed."""

    def __init__(self, message: str, raw_output: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.raw_output = raw_output


@dataclass(frozen=True)
class ScoredDish:
    # {dimension: score} as the model returned it, validated later by vector_from_scores
    scores: dict[str, Any]
    # stored in dish_vectors.raw_ai_output
    raw_output: dict[str, Any]


class DishScorer(Protocol):
    model_name: str

    async def score(self, name: str, description: str | None) -> ScoredDish: ...


class OpenAIDishScorer:
    def __init__(
        self, api_key: str, model: str, timeout_seconds: float, base_url: str | None = None
    ) -> None:
        self.model_name = model
        self._client = AsyncOpenAI(
            api_key=api_key, base_url=base_url, timeout=timeout_seconds, max_retries=1
        )

    async def score(self, name: str, description: str | None) -> ScoredDish:
        dish = f"Name: {name}\nDescription: {description or '(none)'}"
        try:
            response = await self._client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": dish},
                ],
                response_format=_RESPONSE_FORMAT,
            )
        except OpenAIError as exc:
            raise ScoringError(f"OpenAI request failed: {type(exc).__name__}: {exc}") from exc

        content = response.choices[0].message.content if response.choices else None
        if not content:
            raise ScoringError("OpenAI returned no content.")
        try:
            raw = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ScoringError(f"OpenAI returned invalid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise ScoringError("OpenAI returned JSON that is not an object.", {"output": raw})
        return ScoredDish(scores=raw, raw_output=raw)


def create_scorer(settings: Settings) -> DishScorer | None:
    """None until both LLM_API_KEY and LLM_MODEL are set."""
    if settings.llm_api_key is None or not settings.llm_model:
        return None
    return OpenAIDishScorer(
        settings.llm_api_key.get_secret_value(),
        settings.llm_model,
        settings.llm_timeout_seconds,
        settings.llm_base_url,
    )
