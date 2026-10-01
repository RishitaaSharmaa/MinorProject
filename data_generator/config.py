"""Central configuration for the Sharma Industries simulation."""

from datetime import date

from decisionwatch.config import get_settings


RANDOM_SEED = 20260928
START_DATE = date(2025, 4, 1)
END_DATE = date(2025, 9, 30)

NUM_ITEMS = 50
NUM_SUPPLIERS = 10
OVERRIDE_RATE = 0.30
VIOLATION_INJECTION_RATE = 0.25
BACKGROUND_EVENTS_PER_MONTH = 6
#: Latest an injected assumption-breaking event can land after its decision.
#: Real operational surprises (a forecast revision, a lead-time slip) surface
#: within weeks, not randomly up to six months later -- capping this also
#: keeps a meaningful share of violations inside a decision's still-tight
#: cancellation window (below), instead of almost all of them landing long
#: after it's too late to act.
VIOLATION_EVENT_MAX_LAG_DAYS = 45

FORECAST_ERROR_MEAN = 0.0
FORECAST_ERROR_STD_DEV = 0.15
SALES_NOISE_STD_DEV_PCT = 0.22
DELIVERIES_LATE_RATE = 0.55
LATE_DAYS_MIN = 1
LATE_DAYS_MAX = 4
EARLY_DAYS_MIN = -2
EARLY_DAYS_MAX = 0

UNIT_COST_MIN = 35.0
UNIT_COST_MAX = 2400.0
HOLDING_COST_PCT_MIN = 0.12
HOLDING_COST_PCT_MAX = 0.30
MIN_ORDER_QTY_MIN = 10
MIN_ORDER_QTY_MAX = 100
AVG_DAILY_DEMAND_MIN = 12
AVG_DAILY_DEMAND_MAX = 75
SAFETY_STOCK_DAYS = 7
TARGET_STOCK_DAYS = 35

_SETTINGS = get_settings()
NOTE_LLM_PROVIDER = _SETTINGS.note_llm_provider.lower()
NOTE_LLM_MODEL = _SETTINGS.note_llm_model
NOTE_LLM_TEMPERATURE = 0.7
#: Cases per synthetic-notes LLM call. A six-month run produces ~150-200 cases;
#: sending them all in one request overruns Groq's free-tier tokens-per-minute
#: cap (a single ~19k-token request against an 8k TPM limit fails outright).
NOTES_BATCH_SIZE = 20

# TODO: use a different provider/model for extraction evaluation than above.
EXTRACTION_PROVIDER = _SETTINGS.llm_provider.lower()
EXTRACTION_MODEL = _SETTINGS.llm_model

WEEKDAY_DEMAND_MULTIPLIERS = (0.82, 1.03, 1.08, 1.06, 1.10, 1.18, 0.73)
FESTIVAL_SPIKES = (
    # month, day, duration, multiplier, label; intentionally includes a
    # Diwali-season build-up that starts near the end of this six-month window.
    (5, 1, 4, 1.30, "Akshaya Tritiya"),
    (8, 27, 5, 1.38, "Ganesh Chaturthi"),
    (9, 15, 16, 1.32, "Diwali season"),
)

OUTPUT_DIR_NAME = "output"