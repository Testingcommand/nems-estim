
from zoneinfo import ZoneInfo

APP_NAME = "NEMS Estim"

TIMEZONE = ZoneInfo("America/Los_Angeles")

PROVIDERS = {
    "Deng": 3,
    "Qian": 6,
    "Wang": 7,
}

ESTIM_ROOMS = [1, 2, 5]

ESTIM_MINUTES = 10
PROVIDER_MINUTES = 35
SLOT_MINUTES = 30

EARLY_MINUTES = 12
MAX_EARLY_MINUTES = 45

REFRESH_SECONDS = 20

# Expire temporary daily data after 36 hours.
DATA_TTL_SECONDS = 36 * 60 * 60

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

PATIENT_COLUMNS = [
    "Patient",
    "Status",
    "Appt Time",
    "Provider Room",
    "Estim Room",
    "Estim Start",
    "Next Step",
    "Estim Done",
    "Arrival",
]
