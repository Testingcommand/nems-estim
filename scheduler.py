from datetime import datetime, timedelta
from uuid import uuid4
import re

from config import (
    PROVIDERS, ESTIM_ROOMS, ESTIM_MINUTES, PROVIDER_MINUTES,
    EARLY_MINUTES, MAX_EARLY_MINUTES, TIMEZONE
)

FLOW_STAGES = [
    "Waiting for Estim",
    "Estim in Progress",
    "Waiting for Provider",
    "Ready to Leave",
]

def now_local():
    return datetime.now(TIMEZONE)

def parse_time(value, day=None):
    """Accept 9, 930, 930a, 230p, 2:30pm, 14:30 and standard AM/PM."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    raw = str(value).strip().upper().replace(".", "")
    if not raw:
        return None
    day = day or now_local().date()
    raw = re.sub(r"\s+", "", raw)
    suffix = ""
    if raw.endswith(("AM", "PM")):
        suffix, raw = raw[-2:], raw[:-2]
    elif raw.endswith(("A", "P")):
        suffix = "AM" if raw[-1] == "A" else "PM"
        raw = raw[:-1]
    try:
        if ":" in raw:
            fmt = "%H:%M" if not suffix else "%I:%M%p"
            parsed = datetime.strptime(raw + suffix, fmt)
        elif raw.isdigit() and len(raw) <= 2:
            hour = int(raw)
            if not 0 <= hour <= 23:
                return None
            if suffix:
                parsed = datetime.strptime(f"{hour}{suffix}", "%I%p")
            elif hour == 12:
                parsed = datetime.strptime("12:00PM", "%I:%M%p")
            elif hour <= 11:
                parsed = datetime.strptime(f"{hour}:00", "%I:%M")
            else:
                parsed = datetime.strptime(f"{hour}:00", "%H:%M")
        elif raw.isdigit() and len(raw) in (3, 4):
            digits = raw.zfill(4)
            hour, minute = int(digits[:-2]), int(digits[-2:])
            if minute > 59:
                return None
            if suffix:
                if not 1 <= hour <= 12:
                    return None
                parsed = datetime.strptime(f"{hour}:{minute:02d}{suffix}", "%I:%M%p")
            else:
                if not 0 <= hour <= 23:
                    return None
                parsed = datetime.strptime(f"{hour}:{minute:02d}", "%H:%M")
        else:
            return None
        return datetime.combine(day, parsed.time()).replace(tzinfo=TIMEZONE)
    except ValueError:
        return None

def format_time(value):
    return value.strftime("%H:%M") if value else ""

def display_time(value):
    parsed = parse_time(value)
    return parsed.strftime("%I:%M %p").lstrip("0") if parsed else (value or "")

def normalize_patient(p):
    legacy_stage = p.get("Stage")
    legacy_next_step = p.get("Next Step", "")
    legacy_estim_done = p.get("Estim Done", False)
    defaults = {
        "id": str(uuid4()), "Patient": "", "Status": "", "Provider Room": "",
        "Appt Time": "", "Appt Mode": "AUTO", "Arrival": "",
        "Estim Needed": True, "Stage": "Waiting for Estim",
        "Estim Room": "", "Actual Estim Start": "", "Actual Estim End": "",
        "Provider Seen": False, "Provider Seen At": "",
        "Flow Suggestion": "Estim First", "Conflict": "",
    }
    for k, v in defaults.items():
        p.setdefault(k, v)
    if p.get("Status") in PROVIDERS:
        p["Provider Room"] = PROVIDERS[p["Status"]]
    # Migrate v3 records without losing the patient's current progress.
    if not legacy_stage:
        if legacy_estim_done:
            p["Stage"] = "Ready to Leave" if p.get("Provider Seen") else "Waiting for Provider"
        elif legacy_next_step == "Estim in Progress":
            p["Stage"] = "Estim in Progress"
        elif legacy_next_step == "Provider First":
            p["Stage"] = "Waiting for Provider"
        elif legacy_next_step == "Ready to Leave":
            p["Stage"] = "Ready to Leave"
        else:
            p["Stage"] = "Waiting for Estim"
    if p.get("Estim Done") and not p.get("Actual Estim End"):
        p["Actual Estim End"] = p.get("Estim End", "")
    return p

def suggest_appointment(patients, provider, now=None):
    """Suggest the next 30-minute slot after the latest appointment for this provider."""
    now = now or now_local()
    times = [parse_time(p.get("Appt Time"), now.date()) for p in patients
             if p.get("Status") == provider and p.get("Appt Time")]
    times = [t for t in times if t]
    if times:
        candidate = max(times) + timedelta(minutes=PROVIDER_MINUTES)
    else:
        candidate = now.replace(second=0, microsecond=0)
        remainder = candidate.minute % 30
        if remainder:
            candidate += timedelta(minutes=30-remainder)
    return format_time(candidate)

def suggest_flow(appt, arrival, now=None):
    now = now or now_local()
    a, b = parse_time(appt, now.date()), parse_time(arrival, now.date())
    if not a or not b:
        return "Provider First"
    early = (a-b).total_seconds()/60
    if early > MAX_EARLY_MINUTES:
        return "Review timing"
    return "Estim First" if early >= EARLY_MINUTES else "Provider First"

def _overlap(a, b, c, d):
    return a < d and c < b

def get_estim_conflicts(patients):
    reservations = []
    day = now_local().date()
    for p in patients:
        if p.get("Stage") != "Estim in Progress":
            continue
        start = parse_time(p.get("Actual Estim Start"), day)
        room = p.get("Estim Room")
        if start and room in ESTIM_ROOMS:
            reservations.append((p, room, start, start + timedelta(minutes=ESTIM_MINUTES)))
    conflicts = {}
    for i, (p1, r1, s1, e1) in enumerate(reservations):
        for p2, r2, s2, e2 in reservations[i+1:]:
            if r1 == r2 and _overlap(s1, e1, s2, e2):
                conflicts.setdefault(p1["id"], []).append(
                    f"Room {r1} overlaps with {p2.get('Patient','another patient')} ({display_time(format_time(s2))})")
                conflicts.setdefault(p2["id"], []).append(
                    f"Room {r2} overlaps with {p1.get('Patient','another patient')} ({display_time(format_time(s1))})")
    return conflicts

def assign_estim_room(patients, patient):
    """Choose a room not currently occupied by another Estim-in-progress patient."""
    occupied = {p.get("Estim Room") for p in patients
                if p.get("id") != patient.get("id") and p.get("Stage") == "Estim in Progress"}
    return next((room for room in ESTIM_ROOMS if room not in occupied), None)

def rebuild_schedule(patients):
    for p in patients:
        normalize_patient(p)
        if p.get("Status") in PROVIDERS:
            p["Provider Room"] = PROVIDERS[p["Status"]]
        if not p.get("Arrival"):
            p["Arrival"] = now_local().strftime("%H:%M")
        p["Conflict"] = ""
    conflicts = get_estim_conflicts(patients)
    for p in patients:
        p["Conflict"] = "; ".join(conflicts.get(p.get("id"), []))
    return patients

def start_estim(patients, patient):
    room = assign_estim_room(patients, patient)
    if room is None:
        raise ValueError("All Estim rooms are currently occupied. Finish or release a room first.")
    now = now_local()
    patient["Estim Room"] = room
    patient["Actual Estim Start"] = now.strftime("%H:%M")
    patient["Actual Estim End"] = ""
    patient["Estim Done"] = False
    patient["Stage"] = "Estim in Progress"
    return patient

def finish_estim(patient):
    patient["Estim Done"] = True
    patient["Actual Estim End"] = now_local().strftime("%H:%M")
    patient["Estim Room"] = ""
    patient["Stage"] = "Ready to Leave" if patient.get("Provider Seen") or not patient.get("Estim Needed", True) else "Waiting for Provider"
    return patient

def mark_provider_seen(patient):
    patient["Provider Seen"] = True
    patient["Provider Seen At"] = now_local().strftime("%H:%M")
    if not patient.get("Estim Needed", True) or patient.get("Estim Done"):
        patient["Stage"] = "Ready to Leave"
    elif patient.get("Stage") != "Estim in Progress":
        patient["Stage"] = "Waiting for Estim"
    return patient
