from zoneinfo import ZoneInfo

APP_NAME = "NEMS Estim"
TIMEZONE = ZoneInfo("America/Los_Angeles")

PROVIDERS = {
    "Deng": 3,
    "Qian": 6,
    "Wang": 7,
}
ESTIM_ROOMS = [1, 2, 5]

# Scheduling durations
ESTIM_MINUTES = 10
PROVIDER_MINUTES = 30
SLOT_MINUTES = 5

# Arrival guidance. These are defaults, not hard rules.
EARLY_MINUTES = 12
MAX_EARLY_MINUTES = 60

REFRESH_SECONDS = 20

STATUSES = ["Deng", "Qian", "Wang", "RTL"]
NEXT_STEPS = [
    "Estim First",
    "Provider First",
    "Estim in Progress",
    "Estim Done - Move to Provider Room",
    "Estim Done - Ready to Leave",
    "Ready to Leave",
    "Review - Provider Discretion",
    "Estim Room Delayed - Review",
    "Review - Over 60 Min Early",
]
