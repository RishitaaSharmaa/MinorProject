"""Central configuration for the Sharma Industries simulation."""

from datetime import date
import os


RANDOM_SEED = 20260928
START_DATE = date(2025, 4, 1)
END_DATE = date(2025, 9, 30)

NUM_ITEMS = 50
NUM_SUPPLIERS = 10
OVERRIDE_RATE = 0.30
VIOLATION_INJECTION_RATE = 0.25
BACKGROUND_EVENTS_PER_MONTH = 6

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

# Set NOTE_LLM_PROVIDER to "template" to generate notes without API credentials.
NOTE_LLM_PROVIDER = os.getenv("NOTE_LLM_PROVIDER", "groq").lower()
_DEFAULT_NOTE_MODELS = {"groq": "llama-3.3-70b-versatile"}
NOTE_LLM_MODEL = os.getenv("NOTE_LLM_MODEL", _DEFAULT_NOTE_MODELS.get(NOTE_LLM_PROVIDER, "template"))
NOTE_LLM_TEMPERATURE = 0.7

# TODO: use a different provider/model for extraction evaluation than above.
EXTRACTION_PROVIDER = "groq"
EXTRACTION_MODEL = "llama-3.1-8b-instant"

WEEKDAY_DEMAND_MULTIPLIERS = (0.82, 1.03, 1.08, 1.06, 1.10, 1.18, 0.73)
FESTIVAL_SPIKES = (
    # month, day, duration, multiplier, label; intentionally includes a
    # Diwali-season build-up that starts near the end of this six-month window.
    (5, 1, 4, 1.30, "Akshaya Tritiya"),
    (8, 27, 5, 1.38, "Ganesh Chaturthi"),
    (9, 15, 16, 1.32, "Diwali season"),
)

OUTPUT_DIR_NAME = "output"