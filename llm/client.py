"""Provider-swappable, schema-validated JSON completions."""

import json
import logging
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.config import get_settings

logger = logging.getLogger(__name__)
SchemaModel = TypeVar("SchemaModel", bound=BaseModel)


def complete_json(system: str, user: str, schema: type[SchemaModel]) -> SchemaModel:
    """Return validated JSON, retrying once when parsing or schema validation fails."""
    settings = get_settings()
    provider = settings.llm_provider.lower()
    model = settings.llm_model
    if provider != "groq":
        raise ValueError(f"Unsupported LLM provider: {provider}")
    api_key = settings.groq_api_key.get_secret_value()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is required for LLM requests")

    from groq import Groq

    client = Groq(api_key=api_key)
    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=True)
    system_with_schema = f"{system}\nReturn only JSON matching this schema:\n{schema_json}"
    retry_note = ""
    for attempt in range(2):
        response = client.chat.completions.create(
            model=model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_with_schema + retry_note},
                {"role": "user", "content": user},
            ],
        )
        _log_usage(response, provider, model)
        content = response.choices[0].message.content or ""
        try:
            return schema.model_validate(json.loads(content))
        except (json.JSONDecodeError, ValidationError) as exc:
            if attempt == 1:
                raise ValueError("LLM response did not match the required JSON schema") from exc
            retry_note = (
                "\nYour previous response could not be parsed or validated. Return corrected JSON only, "
                "matching the schema exactly."
            )
    raise AssertionError("Unreachable JSON completion retry state")


def _log_usage(response: object, provider: str, model: str) -> None:
    """Log token counts without logging prompts, response text, or credentials."""
    usage = getattr(response, "usage", None)
    logger.info(
        "llm_usage provider=%s model=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s",
        provider,
        model,
        getattr(usage, "prompt_tokens", None),
        getattr(usage, "completion_tokens", None),
        getattr(usage, "total_tokens", None),
    )