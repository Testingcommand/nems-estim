
from datetime import datetime, timedelta
from uuid import uuid4

from config import (
    PROVIDERS,
    ESTIM_ROOMS,
    ESTIM_MINUTES,
    PROVIDER_MINUTES,
    SLOT_MINUTES,
    EARLY_MINUTES,
    MAX_EARLY_MINUTES,
    TIMEZONE,
)


# ---------------------------------------
# PATIENT DEFAULTS
# ---------------------------------------

def new_patient(name, provider, appointment=""):
    now = datetime.now(TIMEZONE)

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
    }


def normalize_patient(patient):
    defaults = new_patient("", "")

    for key, value in defaults.items():
        patient.setdefault(key, value)

    return patient


# ---------------------------------------
# TIME HELPERS
# ---------------------------------------

def parse_time(value, today):
    if isinstance(value, datetime):
        return value.replace(
            year=today.year,
            month=today.month,
            day=today.day,
            tzinfo=TIMEZONE,
        )

    if not value:
        return None

    try:
        parsed = datetime.strptime(
            str(value).strip(),
            "%H:%M",
        )

        return datetime.combine(
            today,
            parsed.time(),
            tzinfo=TIMEZONE,
        )

    except ValueError:
        return None


def format_time(value):
    if not value:
        return ""

    return value.strftime("%H:%M")


def round_slot(value):
    minutes = (
        value.hour * 60
        + value.minute
        + (1 if value.second or value.microsecond else 0)
    )

    rounded = (
        (minutes + SLOT_MINUTES - 1)
        // SLOT_MINUTES
    ) * SLOT_MINUTES

    return (
        value.replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        + timedelta(minutes=rounded)
    )


# ---------------------------------------
# PROVIDER CONFLICT DETECTION
# ---------------------------------------

def has_provider_conflict(
    patients,
    provider,
    candidate,
    exclude_id=None,
):
    candidate_end = candidate + timedelta(
        minutes=PROVIDER_MINUTES
    )

    for patient in patients:

        if patient.get("id") == exclude_id:
            continue

        if patient.get("Status") != provider:
            continue

        existing = parse_time(
            patient.get("Appt Time"),
            candidate.date(),
        )

        if not existing:
            continue

        existing_end = existing + timedelta(
            minutes=PROVIDER_MINUTES
        )

        if (
            candidate < existing_end
            and existing < candidate_end
        ):
            return True

    return False


def next_provider_slot(
    patients,
    provider,
    start,
    exclude_id=None,
):
    candidate = round_slot(start)

    while has_provider_conflict(
        patients,
        provider,
        candidate,
        exclude_id,
    ):
        candidate += timedelta(
            minutes=SLOT_MINUTES
        )

    return candidate


# ---------------------------------------
# PROVIDER SCHEDULING
# ---------------------------------------

def assign_provider_appointments(patients, now):

    today = now.date()

    # Clear invalid provider room assignments.
    for patient in patients:

        provider = patient.get("Status")

        if provider == "RTL":
            continue

        if provider not in PROVIDERS:
            patient["Provider Room"] = ""
            continue

        patient["Provider Room"] = PROVIDERS[provider]

    # Preserve valid manual appointments.
    for patient in patients:

        provider = patient.get("Status")

        if provider not in PROVIDERS:
            continue

        if patient.get("Appt Mode") != "MANUAL":
            continue

        appointment = parse_time(
            patient.get("Appt Time"),
            today,
        )

        if not appointment:
            patient["Appt Mode"] = "AUTO"
            patient["Appt Time"] = ""

    # Assign automatic appointments in arrival order.
    automatic = [
        p for p in patients
        if p.get("Status") in PROVIDERS
        and p.get("Appt Mode") != "MANUAL"
    ]

    automatic.sort(
        key=lambda p: (
            parse_time(p.get("Arrival"), today)
            or now
        )
    )

    for patient in automatic:

        arrival = parse_time(
            patient.get("Arrival"),
            today,
        ) or now

        candidate = next_provider_slot(
            patients,
            patient["Status"],
            max(now, arrival),
            exclude_id=patient["id"],
        )

        patient["Appt Time"] = format_time(candidate)
        patient["Appt Mode"] = "AUTO"


# ---------------------------------------
# ESTIM ROOM AVAILABILITY
# ---------------------------------------

def get_room_availability(patients, today):

    reservations = {
        room: [] for room in ESTIM_ROOMS
    }

    for patient in patients:

        if patient.get("Estim Done"):
            continue

        if patient.get("Status") == "RTL":
            continue

        room = patient.get("Estim Room")

        if room not in ESTIM_ROOMS:
            continue

        start = parse_time(
            patient.get("Estim Start"),
            today,
        )

        if not start:
            continue

        end = start + timedelta(
            minutes=ESTIM_MINUTES
        )

        reservations[room].append({
            "patient": patient.get("Patient"),
            "patient_id": patient.get("id"),
            "start": start,
            "end": end,
            "mode": patient.get("Estim Room Mode"),
        })

    for room in reservations:
        reservations[room].sort(
            key=lambda x: x["start"]
        )

    return reservations


# ---------------------------------------
# ESTIM ROOM CONFLICTS
# ---------------------------------------

def find_room_conflicts(reservations):

    conflicts = []

    for room, appointments in reservations.items():

        for i in range(len(appointments)):

            for j in range(i + 1, len(appointments)):

                first = appointments[i]
                second = appointments[j]

                if second["start"] < first["end"]:

                    conflicts.append({
                        "room": room,
                        "patient1": first["patient"],
                        "patient2": second["patient"],
                        "start1": first["start"],
                        "start2": second["start"],
                    })

    return conflicts


# ---------------------------------------
# ROOM AVAILABILITY
# ---------------------------------------

def find_available_room(
    reservations,
    now,
    preferred_room=None,
    preferred_start=None,
):

    candidates = []

    for room in ESTIM_ROOMS:

        if (
            preferred_room is not None
            and room != preferred_room
        ):
            continue

        occupied = reservations[room]

        candidate = (
            preferred_start
            if preferred_start is not None
            else now
        )

        # Find the earliest non-overlapping interval.
        for reservation in occupied:

            end = candidate + timedelta(
                minutes=ESTIM_MINUTES
            )

            if (
                candidate < reservation["end"]
                and reservation["start"] < end
            ):
                candidate = reservation["end"]

        candidates.append((candidate, room))

    if not candidates:
        return None, None

    candidates.sort(
        key=lambda x: (x[0], x[1])
    )

    return candidates[0][1], candidates[0][0]


# ---------------------------------------
# WORKFLOW DETERMINATION
# ---------------------------------------

def determine_next_step(patient, now):

    if patient.get("Status") == "RTL":
        return "Ready to Leave"

    if patient.get("Estim Done"):
        if patient.get("Next Step Mode") == "MANUAL":
            return patient.get("Next Step", "")

        if patient.get("Flow Order") == "ESTIM_FIRST":
            return (
                "Estim Done - Move to Provider Room"
            )

        return "Estim Done - Ready to leave"

    if patient.get("Next Step Mode") == "MANUAL":
        return patient.get("Next Step", "")

    today = now.date()

    appointment = parse_time(
        patient.get("Appt Time"),
        today,
    )

    arrival = parse_time(
        patient.get("Arrival"),
        today,
    )

    if not appointment or not arrival:
        return "Provider First"

    minutes_early = (
        appointment - arrival
    ).total_seconds() / 60

    if minutes_early > MAX_EARLY_MINUTES:
        return "Review - Over 45 Min Early"

    if minutes_early >= EARLY_MINUTES:
        return "Estim First"

    return "Provider First"


# ---------------------------------------
# MAIN SCHEDULING ENGINE
# ---------------------------------------

def rebuild_schedule(patients):

    now = datetime.now(TIMEZONE)
    today = now.date()

    # Normalize all patient records.
    for patient in patients:
        normalize_patient(patient)

    # STEP 1: RTL and invalid-provider cleanup.
    for patient in patients:

        provider = patient.get("Status")

        if provider == "RTL":
            patient.update({
                "Appt Time": "",
                "Provider Room": "",
                "Estim Room": "",
                "Estim Start": "",
                "Estim Room Mode": "AUTO",
                "Estim Start Mode": "AUTO",
                "Next Step": "Ready to Leave",
                "Next Step Mode": "AUTO",
                "Estim Done": False,
                "Conflict": "",
            })

        elif provider not in PROVIDERS:
            patient["Provider Room"] = ""

    active = [
        p for p in patients
        if p.get("Status") in PROVIDERS
    ]

    # STEP 2: Provider appointments.
    assign_provider_appointments(active, now)

    # STEP 3: Determine workflow.
    for patient in active:

        if not patient.get("Arrival"):
            patient["Arrival"] = format_time(now)

        patient["Next Step"] = determine_next_step(
            patient,
            now,
        )

        if (
            patient["Next Step"] == "Estim First"
            and not patient.get("Flow Order")
        ):
            patient["Flow Order"] = "ESTIM_FIRST"

        if (
            patient["Next Step"] == "Provider First"
            and not patient.get("Flow Order")
        ):
            patient["Flow Order"] = "PROVIDER_FIRST"

    # STEP 4: Clear completed assignments.
    for patient in active:

        if patient.get("Estim Done"):
            patient["Estim Room"] = ""
            patient["Estim Start"] = ""
            patient["Estim Room Mode"] = "AUTO"
            patient["Estim Start Mode"] = "AUTO"

        if patient.get("Next Step") == "Ready to Leave":
            patient["Estim Room"] = ""
            patient["Estim Start"] = ""
            patient["Estim Room Mode"] = "AUTO"
            patient["Estim Start Mode"] = "AUTO"

    # STEP 5: Assign manual room with missing start.
    for patient in active:

        if patient.get("Next Step") not in (
            "Estim First",
            "Estim Room Delayed - Review",
        ):
            continue

        room = patient.get("Estim Room")

        if room in ESTIM_ROOMS and not patient.get("Estim Start"):
            patient["Estim Start"] = format_time(now)
            patient["Estim Start Mode"] = "MANUAL"

    # STEP 6: Preserve existing valid room reservations.
    reservations = get_room_availability(
        active,
        today,
    )

    # STEP 7: Auto-assign patients without rooms.
    new_estim = [
        p for p in active
        if p.get("Next Step") == "Estim First"
        and not p.get("Estim Done")
        and not p.get("Estim Room")
    ]

    new_estim.sort(
        key=lambda p: (
            parse_time(p.get("Arrival"), today)
            or now
        )
    )

    for patient in new_estim:

        room, start = find_available_room(
            reservations,
            now,
        )

        if room is None:
            continue

        patient["Estim Room"] = room
        patient["Estim Start"] = format_time(start)
        patient["Estim Room Mode"] = "AUTO"
        patient["Estim Start Mode"] = "AUTO"

        reservations[room].append({
            "patient": patient.get("Patient"),
            "patient_id": patient.get("id"),
            "start": start,
            "end": start + timedelta(
                minutes=ESTIM_MINUTES
            ),
            "mode": "AUTO",
        })

        reservations[room].sort(
            key=lambda x: x["start"]
        )

    # STEP 8: Detect delayed Estim rooms.
    for patient in active:

        if patient.get("Next Step Mode") == "MANUAL":
            continue

        if patient.get("Next Step") != "Estim First":
            continue

        start = parse_time(
            patient.get("Estim Start"),
            today,
        )

        appointment = parse_time(
            patient.get("Appt Time"),
            today,
        )

        if (
            start
            and appointment
            and start + timedelta(
                minutes=ESTIM_MINUTES
            ) > appointment
        ):
            patient["Next Step"] = (
                "Estim Room Delayed - Review"
            )

    # STEP 9: Detect conflicts without changing
    # manually assigned appointments.
    reservations = get_room_availability(
        active,
        today,
    )

    conflicts = find_room_conflicts(
        reservations
    )

    for patient in patients:
        patient["Conflict"] = ""

    for conflict in conflicts:

        for patient in active:

            if patient.get("Patient") in (
                conflict["patient1"],
                conflict["patient2"],
            ):
                warning = (
                    f"Estim Room {conflict['room']} overlap"
                )

                patient["Conflict"] = warning

    return patients
