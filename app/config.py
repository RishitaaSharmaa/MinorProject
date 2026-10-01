"""Environment and `.env` configuration for the backend."""

from functools import lru_cache

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated application settings loaded from environment or `.env`."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    database_url: str = "postgresql+psycopg://decisionwatch:decisionwatch_dev@localhost:5432/decisionwatch"
    erp_connector: str = "synthetic"
    groq_api_key: SecretStr = SecretStr("")
    llm_provider: str = "groq"
    llm_model: str = "openai/gpt-oss-20b"
    note_llm_provider: str = "groq"
    note_llm_model: str = "llama-3.3-70b-versatile"
    api_url: str = "http://localhost:8000"

    #: Fallback cost_keep, as a fraction of order value, when no condition-specific
    #: model can be grounded in connector data (marks the estimate for confidence scoring).
    scoring_default_exposure_pct: float = 0.05
    #: Multiplier applied to a stockout-risk shortfall (stock/forecast/lead-time breaks
    #: that leave a decision short), reflecting that being short costs more than excess.
    scoring_stockout_multiplier: float = 1.5
    #: Cost, as a fraction of the shortfall value, of a forced MOQ top-up purchase.
    scoring_topup_penalty_pct: float = 0.10
    #: Flat exposure, as a fraction of order value, for an open/resolved supplier-risk break.
    scoring_supplier_risk_exposure_pct: float = 0.08
    #: Flat exposure, as a fraction of order value, for a lost price-break assumption.
    scoring_price_break_loss_pct: float = 0.03
    #: Fraction of quantity/value a "reduce" action is assumed to cut; also the
    #: fraction of the cancellation fee and in-transit cost it incurs.
    scoring_reduce_fraction: float = 0.5
    #: Fraction of cost_keep exposure a "delay" action is assumed to remove.
    scoring_delay_mitigation: float = 0.3
    #: Fraction of the cancellation fee a "delay" action incurs as a rebooking/
    #: change-order cost, even though it does not stop or shrink the shipment.
    scoring_delay_fee_fraction: float = 0.1
    #: Cost, as a fraction of the affected order value, of touching a shipment already
    #: in transit (on or after its recorded po_date).
    scoring_in_transit_cost_pct: float = 0.15

    @model_validator(mode="after")
    def require_distinct_note_model(self) -> "Settings":
        """Keep extraction and synthetic-note generation on distinct model pairs."""
        if (
            self.llm_provider.lower() == self.note_llm_provider.lower()
            and self.llm_model == self.note_llm_model
        ):
            raise ValueError("Extraction and synthetic notes must use different provider/model pairs")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached process settings."""
    return Settings()