from datetime import datetime, timedelta
from uuid import uuid4

from config import (
    PROVIDERS, ESTIM_ROOMS, ESTIM_MINUTES, PROVIDER_MINUTES,
    SLOT_MINUTES, EARLY_MINUTES, MAX_EARLY_MINUTES, TIMEZONE
)


def now_local():
    return datetime.now(TIMEZONE)


def parse_time(value, day=None):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    day = day or now_local().date()
    raw = str(value).strip().upper()
    for fmt in ("%H:%M", "%I:%M %p", "%I:%M%p"):
        try:
            parsed = datetime.strptime(raw, fmt)
            return datetime.combine(day, parsed.time()).replace(tzinfo=TIMEZONE)
        except ValueError:
            pass
    return None


def format_time(value):
    return value.strftime("%H:%M") if value else ""


def display_time(value):
    parsed = parse_time(value)
    return parsed.strftime("%I:%M %p").lstrip("0") if parsed else (value or "")


def new_patient(name, provider, appointment=""):
    now = now_local()
    return {
        "id": str(uuid4()),
        "Patient": name,
        "Status": provider,
        "Appt Time": appointment,
        "Provider Room": PROVIDERS.get(provider, ""),
        "Appt Mode": "MANUAL" if appointment else "AUTO",
        "Arrival": now.strftime("%H:%M"),
        "Estim Room": "",
        "Estim Start": "",
        "Estim Room Mode": "AUTO",
        "Estim Start Mode": "AUTO",
        "Next Step": "",
        "Next Step Mode": "AUTO",
        "Flow Order": "",
        "Estim Done": False,
        "Conflict": "",
        "Provider Start": "",
        "Provider Start Mode": "AUTO",
        "Notes": "",
    }


def normalize_patient(patient):
    defaults = new_patient("", "")
    for key, value in defaults.items():
        patient.setdefault(key, value)
    if patient.get("Status") in PROVIDERS:
        patient["Provider Room"] = PROVIDERS[patient["Status"]]
    return patient


def _overlap(start_a, end_a, start_b, end_b):
    return start_a < end_b and start_b < end_a


def get_estim_conflicts(patients):
    reservations = []
    day = now_local().date()
    for p in patients:
        if p.get("Estim Done") or p.get("Status") == "RTL":
            continue
        room = p.get("Estim Room")
        start = parse_time(p.get("Estim Start"), day)
        if room not in ESTIM_ROOMS or not start:
            continue
        reservations.append({
            "id": p.get("id"), "name": p.get("Patient", "Patient"),
            "room": room, "start": start,
            "end": start + timedelta(minutes=ESTIM_MINUTES),
        })
    conflicts = {}
    for i, a in enumerate(reservations):
        for b in reservations[i+1:]:
            if a["room"] == b["room"] and _overlap(a["start"], a["end"], b["start"], b["end"]):
                msg = f"Room {a['room']} overlaps with {b['name']} ({b['start'].strftime('%I:%M %p').lstrip('0')})"
                conflicts.setdefault(a["id"], []).append(msg)
                msg2 = f"Room {b['room']} overlaps with {a['name']} ({a['start'].strftime('%I:%M %p').lstrip('0')})"
                conflicts.setdefault(b["id"], []).append(msg2)
    return conflicts


def _auto_estim_assignment(patients, patient, now):
    """Find earliest available room slot at/after now; preserve all manual assignments."""
    day = now.date()
    busy = []
    for p in patients:
        if p["id"] == patient["id"] or p.get("Estim Done") or p.get("Status") == "RTL":
            continue
        if p.get("Estim Room") not in ESTIM_ROOMS:
            continue
        start = parse_time(p.get("Estim Start"), day)
        if start:
            busy.append((p["Estim Room"], start, start + timedelta(minutes=ESTIM_MINUTES)))
    candidate_slots = []
    for room in ESTIM_ROOMS:
        candidate = now.replace(second=0, microsecond=0)
        remainder = candidate.minute % SLOT_MINUTES
        if remainder:
            candidate += timedelta(minutes=SLOT_MINUTES-remainder)
        for _ in range(288):
            end = candidate + timedelta(minutes=ESTIM_MINUTES)
            if not any(r == room and _overlap(candidate, end, s, e) for r, s, e in busy):
                candidate_slots.append((candidate, room))
                break
            candidate += timedelta(minutes=SLOT_MINUTES)
    if not candidate_slots:
        return None, None
    start, room = min(candidate_slots, key=lambda x: (x[0], x[1]))
    return room, start


def determine_default_next_step(patient, now=None):
    """Suggest a flow; staff may override at any time at provider discretion."""
    now = now or now_local()
    appt = parse_time(patient.get("Appt Time"), now.date())
    arrival = parse_time(patient.get("Arrival"), now.date())
    if patient.get("Status") == "RTL":
        return "Ready to Leave"
    if patient.get("Estim Done"):
        return "Estim Done - Move to Provider Room"
    if not appt or not arrival:
        return "Provider First"
    early_by = (appt - arrival).total_seconds() / 60
    if early_by > MAX_EARLY_MINUTES:
        return "Review - Over 60 Min Early"
    if early_by >= EARLY_MINUTES:
        return "Estim First"
    return "Provider First"


def rebuild_schedule(patients):
    """
    Recalculate provider rooms, default next steps, Estim room conflicts.
    Provider discretion is preserved: a manual Next Step is never overwritten.
    Manual room/time assignments are preserved and flagged, not silently moved.
    """
    now = now_local()
    for p in patients:
        normalize_patient(p)
        if p.get("Status") == "RTL":
            p.update({
                "Provider Room": "", "Estim Room": "", "Estim Start": "",
                "Next Step": "Ready to Leave", "Next Step Mode": "AUTO",
                "Estim Done": False, "Conflict": ""
            })
            continue
        if p.get("Next Step Mode") != "MANUAL":
            p["Next Step"] = determine_default_next_step(p, now)

    # Assign Estim only to patients whose flow calls for it and who have no room.
    for p in patients:
        if p.get("Status") not in PROVIDERS or p.get("Estim Done"):
            continue
        if p.get("Next Step") not in ("Estim First", "Estim in Progress"):
            continue
        if p.get("Estim Room") in ESTIM_ROOMS and parse_time(p.get("Estim Start")):
            continue
        if p.get("Estim Room Mode") == "MANUAL" and p.get("Estim Room") in ESTIM_ROOMS:
            # Manual room with no start: assign current time, preserving the room.
            p["Estim Start"] = now.strftime("%H:%M")
            p["Estim Start Mode"] = "MANUAL"
            continue
        room, start = _auto_estim_assignment(patients, p, now)
        if room is not None:
            p["Estim Room"] = room
            p["Estim Start"] = format_time(start)
            p["Estim Room Mode"] = "AUTO"
            p["Estim Start Mode"] = "AUTO"

    conflicts = get_estim_conflicts(patients)
    for p in patients:
        p["Conflict"] = "; ".join(conflicts.get(p.get("id"), []))
    return patients


def set_manual_next_step(patient, next_step):
    patient["Next Step"] = next_step
    patient["Next Step Mode"] = "MANUAL"
    if next_step == "Estim Done - Move to Provider Room":
        patient["Estim Done"] = True
    elif next_step == "Ready to Leave":
        patient["Estim Done"] = True
        patient["Status"] = "RTL"
    return patient


def mark_estim_done(patient):
    patient["Estim Done"] = True
    patient["Estim Room"] = ""
    patient["Estim Start"] = ""
    patient["Estim Room Mode"] = "AUTO"
    patient["Estim Start Mode"] = "AUTO"
    if patient.get("Next Step Mode") != "MANUAL":
        patient["Next Step"] = "Estim Done - Move to Provider Room"
    return patient
