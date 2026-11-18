
from zoneinfo import ZoneInfo

APP_NAME = "NEMS Estim"

TIMEZONE = ZoneInfo("America/Los_Angeles")

# Providers and their assigned rooms
PROVIDERS = {
    "Deng": 3,
    "Qian": 6,
    "Wang": 7,
}

# Shared Estim rooms
ESTIM_ROOMS = [1, 2, 5]

# Scheduling durations
ESTIM_MINUTES = 10
PROVIDER_MINUTES = 35
SLOT_MINUTES = 30

# Arrival rules
EARLY_MINUTES = 12
MAX_EARLY_MINUTES = 45

# Dashboard
REFRESH_SECONDS = 20

STATUSES = [
    "Deng",
    "Qian",
    "Wang",
    "RTL",
]

NEXT_STEPS = [
    "Estim First",
    "Provider First",
    "Ready to Leave",
]

REVIEW_STEPS = [
    "Review - Over 45 Min Early",
    "Estim Room Delayed - Review",
]

ALL_NEXT_STEPS = (
    NEXT_STEPS + REVIEW_STEPS
)
