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
    #: Shared secret for the event-ingest endpoints (`X-API-Key`). Ingest is
    #: disabled (503) while this is empty so it is never open by accident.
    ingest_api_key: SecretStr = SecretStr("")
    #: Optional URL that receives a JSON POST whenever an ingested event breaks
    #: an assumption (works with Slack/Teams incoming webhooks or any receiver).
    alert_webhook_url: str = ""
    #: When true, every tenant endpoint needs a bearer token or tenant API key. When false
    #: (the demo default) unauthenticated requests use the shared demo workspace.
    auth_required: bool = False
    trial_days: int = 30
    #: Self-hosted "agent" mode: the customer runs this backend inside their own network, so
    #: their data never reaches the hosted site. Single tenant; every request needs `AGENT_TOKEN`.
    agent_mode: bool = False
    #: Browser-only mode: the whole backend runs inside the user's browser (Pyodide) against a
    #: private SQLite file, so nothing is uploaded. Implies agent mode without a token, and is
    #: refused anywhere except a browser (see `app.main`).
    local_mode: bool = False
    agent_token: SecretStr = SecretStr("")
    #: Comma-separated browser origins allowed to call the API (the hosted site, for agent mode).
    cors_origins: str = ""
    #: Trust `X-Real-IP` (set by the bundled nginx) as the caller address for rate limits.
    trust_proxy_headers: bool = False
    session_ttl_days: int = 7
    #: Which ERP the agent reads (`sap_b1` or `netsuite`); empty means data comes from CSV imports and
    #: pushed events only. Credentials below should belong to a read-only ERP user.
    erp_source: str = ""
    #: Minutes between automatic syncs; 0 disables the schedule (a sync can still be run on demand).
    sync_interval_minutes: int = 0
    #: How far back purchase orders are read, in days.
    sync_lookback_days: int = 180
    #: Used for suppliers whose ERP has no lead-time field configured.
    default_lead_time_days: int = 14
    sap_b1_url: str = ""
    sap_b1_company_db: str = ""
    sap_b1_username: str = ""
    sap_b1_password: SecretStr = SecretStr("")
    sap_b1_verify_tls: bool = True
    sap_b1_ca_bundle: str = ""
    sap_b1_lead_time_field: str = ""
    sap_b1_strike_field: str = ""
    netsuite_account_id: str = ""
    netsuite_consumer_key: SecretStr = SecretStr("")
    netsuite_consumer_secret: SecretStr = SecretStr("")
    netsuite_token_id: SecretStr = SecretStr("")
    netsuite_token_secret: SecretStr = SecretStr("")
    netsuite_query_suppliers: str = ""
    netsuite_query_items: str = ""
    netsuite_query_purchase_orders: str = ""
    netsuite_query_stock_levels: str = ""
    #: Days without a state event for an assumption's watched entity/field before the
    #: assumption is reported as stale (its "live" status is unverified, not confirmed).
    stale_after_days: int = 14

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
    def local_mode_is_agent_mode(self) -> "Settings":
        if self.local_mode:
            self.agent_mode = True
        return self

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