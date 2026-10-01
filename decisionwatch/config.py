"""Environment-backed settings for DecisionWatch."""

from functools import lru_cache

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and `.env`."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    database_url: str = "postgresql+psycopg://localhost/decisionwatch"
    groq_api_key: SecretStr = SecretStr("")
    llm_provider: str = "groq"
    llm_model: str = "llama-3.1-8b-instant"
    note_llm_provider: str = "groq"
    note_llm_model: str = "llama-3.3-70b-versatile"
    api_url: str = "http://localhost:8000"

    @model_validator(mode="after")
    def ensure_distinct_llm_models(self) -> "Settings":
        """Prevent synthetic note generation and extraction sharing a model."""
        if (
            self.llm_provider.lower() == self.note_llm_provider.lower()
            and self.llm_model == self.note_llm_model
        ):
            raise ValueError("Extraction and synthetic notes must use different provider/model pairs")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide validated settings instance."""
    return Settings()