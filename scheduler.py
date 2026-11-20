from datetime import datetime, timedelta
from uuid import uuid4
import re

from config import (
    PROVIDERS, ESTIM_ROOMS, ESTIM_MINUTES, PROVIDER_MINUTES,
    EARLY_MINUTES, MAX_EARLY_MINUTES, TIMEZONE
)

STAGES = [
    "Waiting for Estim",
    "Estim in Progress",
    "Move to Provider",
    "Waiting for Provider",
    "Ready to Leave",
    "Completed",
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
    raw = re.sub(r"\s+", "", raw)
    day = day or now_local().date()
    suffix = ""
    if raw.endswith(("AM", "PM")):
        suffix, raw = raw[-2:], raw[:-2]
    elif raw.endswith(("A", "P")):
        suffix = "AM" if raw[-1] == "A" else "PM"
        raw = raw[:-1]
    try:
        if ":" in raw:
            if suffix:
                parsed = datetime.strptime(raw + suffix, "%I:%M%p")
            else:
                parsed = datetime.strptime(raw, "%H:%M")
        elif raw.isdigit() and len(raw) <= 2:
            hour = int(raw)
            if suffix:
                parsed = datetime.strptime(f"{hour}:00{suffix}", "%I:%M%p")
            elif hour == 12:
                parsed = datetime.strptime("12:00PM", "%I:%M%p")
            elif 0 <= hour <= 11:
                parsed = datetime.strptime(f"{hour}:00", "%H:%M")
            elif 13 <= hour <= 23:
                parsed = datetime.strptime(f"{hour}:00", "%H:%M")
            else:
                return None
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

def normalize_patient(patient):
    patient.setdefault("id", str(uuid4()))
    defaults = {
        "Patient": "",
        "Status": "",
        "Provider Room": "",
        "Appt Time": "",
        "Arrival": "",
        "Estim Needed": True,
        "Stage": "Waiting for Estim",
        "Estim Room": "",
        "Actual Estim Start": "",
        "Actual Estim End": "",
        "Provider Seen": False,
        "Provider Seen At": "",
        "Patient Moved": False,
        "Patient Moved At": "",
        "Estim Done": False,
        "Flow Suggestion": "Estim First",
        "Conflict": "",
        "Created At": now_local().strftime("%H:%M"),
    }
    for key, value in defaults.items():
        patient.setdefault(key, value)

    # Migrate older v4 records while preserving their current progress.
    # In v4.1, Estim-first patients were stored as "Waiting for Provider"
    # immediately after Estim finished. Promote those records to the explicit handoff stage.
    if (patient.get("Stage") == "Waiting for Provider"
            and patient.get("Estim Needed", True)
            and patient.get("Estim Done")
            and not patient.get("Provider Seen")):
        patient["Stage"] = "Move to Provider"
    if patient.get("Stage") not in STAGES:
        if patient.get("Estim Done"):
            patient["Stage"] = "Ready to Leave" if patient.get("Provider Seen") else "Move to Provider"
        elif patient.get("Actual Estim Start"):
            patient["Stage"] = "Estim in Progress"
        elif patient.get("Provider Seen"):
            patient["Stage"] = "Waiting for Estim" if patient.get("Estim Needed", True) else "Ready to Leave"
        else:
            patient["Stage"] = "Waiting for Estim" if patient.get("Estim Needed", True) else "Waiting for Provider"

    if patient.get("Status") in PROVIDERS:
        patient["Provider Room"] = PROVIDERS[patient["Status"]]
    if patient.get("Estim Done") and not patient.get("Actual Estim End"):
        patient["Actual Estim End"] = patient.get("Estim End", "")
    return patient

def suggest_appointment(patients, provider, now=None):
    now = now or now_local()
    times = [
        parse_time(p.get("Appt Time"), now.date())
        for p in patients
        if p.get("Status") == provider and p.get("Appt Time")
    ]
    times = [value for value in times if value]
    if times:
        candidate = max(times) + timedelta(minutes=PROVIDER_MINUTES)
    else:
        candidate = now.replace(second=0, microsecond=0)
        remainder = candidate.minute % 30
        if remainder:
            candidate += timedelta(minutes=30 - remainder)
    return format_time(candidate)

def suggest_flow(appt, arrival, now=None):
    now = now or now_local()
    appointment = parse_time(appt, now.date())
    arrived = parse_time(arrival, now.date())
    if not appointment or not arrived:
        return "Review timing"
    early_by = (appointment - arrived).total_seconds() / 60
    if early_by > MAX_EARLY_MINUTES:
        return "Review timing"
    if early_by >= EARLY_MINUTES:
        return "Estim First"
    return "Provider First"

def arrival_message(patient, now=None):
    now = now or now_local()
    appointment = parse_time(patient.get("Appt Time"), now.date())
    arrival = parse_time(patient.get("Arrival"), now.date())
    if not appointment or not arrival:
        return ""
    difference = (appointment - arrival).total_seconds() / 60
    if difference > MAX_EARLY_MINUTES:
        return f"Arrived {int(difference)} min early — review timing"
    if difference < 0:
        return f"Arrived {int(abs(difference))} min after appointment"
    if difference >= EARLY_MINUTES:
        return f"Arrived {int(difference)} min early"
    return "Arrived close to appointment time"

def assign_estim_room(patients, patient):
    occupied = {
        p.get("Estim Room")
        for p in patients
        if p.get("id") != patient.get("id") and p.get("Stage") == "Estim in Progress"
    }
    return next((room for room in ESTIM_ROOMS if room not in occupied), None)

def _overlap(start_a, end_a, start_b, end_b):
    return start_a < end_b and start_b < end_a

def get_estim_conflicts(patients, now=None):
    now = now or now_local()
    reservations = []
    for patient in patients:
        if patient.get("Stage") != "Estim in Progress":
            continue
        start = parse_time(patient.get("Actual Estim Start"), now.date())
        room = patient.get("Estim Room")
        if start and room in ESTIM_ROOMS:
            # Active sessions occupy their room until staff marks Estim complete.
            expected_end = max(start + timedelta(minutes=ESTIM_MINUTES), now)
            reservations.append((patient, room, start, expected_end))
    conflicts = {}
    for index, (p1, room1, start1, end1) in enumerate(reservations):
        for p2, room2, start2, end2 in reservations[index + 1:]:
            if room1 == room2 and _overlap(start1, end1, start2, end2):
                conflicts.setdefault(p1["id"], []).append(
                    f"Room {room1} also assigned to {p2.get('Patient', 'another patient')}"
                )
                conflicts.setdefault(p2["id"], []).append(
                    f"Room {room2} also assigned to {p1.get('Patient', 'another patient')}"
                )
    return conflicts

def rebuild_schedule(patients):
    for patient in patients:
        normalize_patient(patient)
        patient["Conflict"] = ""
    conflicts = get_estim_conflicts(patients)
    for patient in patients:
        patient["Conflict"] = "; ".join(conflicts.get(patient.get("id"), []))
    return patients

def start_estim(patients, patient):
    room = assign_estim_room(patients, patient)
    if room is None:
        raise ValueError("All Estim rooms are occupied. Complete an active session or check room assignments.")
    patient["Estim Room"] = room
    patient["Actual Estim Start"] = now_local().strftime("%H:%M")
    patient["Actual Estim End"] = ""
    patient["Estim Done"] = False
    patient["Stage"] = "Estim in Progress"
    return patient

def finish_estim(patient):
    patient["Estim Done"] = True
    patient["Actual Estim End"] = now_local().strftime("%H:%M")
    patient["Estim Room"] = ""
    patient["Stage"] = "Ready to Leave" if patient.get("Provider Seen") else "Move to Provider"
    return patient

def mark_patient_moved(patient):
    patient["Patient Moved"] = True
    patient["Patient Moved At"] = now_local().strftime("%H:%M")
    patient["Stage"] = "Waiting for Provider"
    return patient

def mark_provider_seen(patient):
    patient["Provider Seen"] = True
    patient["Provider Seen At"] = now_local().strftime("%H:%M")
    if not patient.get("Estim Needed", True) or patient.get("Estim Done"):
        patient["Stage"] = "Ready to Leave"
    elif patient.get("Stage") == "Estim in Progress":
        # Provider saw the patient while Estim was still in progress.
        patient["Stage"] = "Estim in Progress"
    else:
        patient["Stage"] = "Waiting for Estim"
    return patient

def mark_completed(patient):
    patient["Stage"] = "Completed"
    patient["Completed At"] = now_local().strftime("%H:%M")
    return patient

def reopen_patient(patient):
    patient["Stage"] = "Ready to Leave"
    patient.pop("Completed At", None)
    return patient

def room_status(patients):
    occupied = {}
    for patient in patients:
        if patient.get("Stage") == "Estim in Progress" and patient.get("Estim Room"):
            occupied[patient["Estim Room"]] = patient.get("Patient", "Occupied")
    return {room: occupied.get(room) for room in ESTIM_ROOMS}
