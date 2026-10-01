"""The only module that communicates with configured LLM providers."""

import time
from typing import Literal

from decisionwatch.config import get_settings

LLMTask = Literal["extraction", "explanation", "synthetic_notes"]

#: Retries for a rate-limited request before giving up, and the fallback wait
#: (seconds) when Groq's response carries no usable Retry-After header.
_MAX_RATE_LIMIT_RETRIES = 5
_DEFAULT_RETRY_SECONDS = 20.0


class LLMClient:
    """Route extraction, explanation, and note-generation calls by settings."""

    def complete(self, task: LLMTask, system_prompt: str, user_prompt: str) -> str:
        """Return a provider completion for the requested application task."""
        settings = get_settings()
        if task == "synthetic_notes":
            provider = settings.note_llm_provider
            model = settings.note_llm_model
        else:
            provider = settings.llm_provider
            model = settings.llm_model

        if provider != "groq":
            raise ValueError(f"Unsupported LLM provider: {provider}")
        api_key = settings.groq_api_key.get_secret_value()
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is required for LLM requests")

        from groq import Groq, RateLimitError

        client = Groq(api_key=api_key)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        for attempt in range(_MAX_RATE_LIMIT_RETRIES + 1):
            try:
                response = client.chat.completions.create(
                    model=model,
                    temperature=0.2 if task != "synthetic_notes" else 0.7,
                    messages=messages,
                )
                return response.choices[0].message.content or ""
            except RateLimitError as exc:
                if attempt == _MAX_RATE_LIMIT_RETRIES:
                    raise
                time.sleep(_retry_after_seconds(exc))
        raise AssertionError("Unreachable rate-limit retry state")


def _retry_after_seconds(exc: Exception) -> float:
    """Read Groq's suggested wait, falling back to a fixed delay if absent."""
    header = exc.response.headers.get("retry-after") if exc.response is not None else None
    try:
        return max(1.0, float(header))
    except (TypeError, ValueError):
        return _DEFAULT_RETRY_SECONDS