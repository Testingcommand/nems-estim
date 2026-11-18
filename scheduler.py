
from datetime import datetime, timedelta

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


def parse_time(value, today):
    if not value:
        return None

    try:
        parsed = datetime.strptime(
            str(value), "%H:%M"
        ).time()

        return datetime.combine(
            today, parsed, tzinfo=TIMEZONE
        )
    except ValueError:
        return None


def format_time(value):
    if not value:
        return ""

    return value.strftime("%H:%M")


def round_slot(value):
    minutes = value.hour * 60 + value.minute

    rounded = (
        (minutes + SLOT_MINUTES - 1)
        // SLOT_MINUTES
    ) * SLOT_MINUTES

    return value.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    ) + timedelta(minutes=rounded)


def next_provider_slot(patients, provider, start):
    candidate = round_slot(start)

    while True:
        conflict = False

        for patient in patients:
            if patient.get("Status") != provider:
                continue

            existing = parse_time(
                patient.get("Appt Time"),
                start.date(),
            )

            if not existing:
                continue

            end = existing + timedelta(
                minutes=SLOT_MINUTES
            )

            candidate_end = candidate + timedelta(
                minutes=SLOT_MINUTES
            )

            if (
                candidate < end
                and existing < candidate_end
            ):
                conflict = True
                break

        if not conflict:
            return candidate

        candidate += timedelta(
            minutes=SLOT_MINUTES
        )


def rebuild_schedule(patients):
    now = datetime.now(TIMEZONE)
    today = now.date()

    room_available = {
        room: now for room in ESTIM_ROOMS
    }

    # STEP 1: Provider scheduling and workflow

    for patient in patients:
        provider = patient.get("Status")

        if not patient.get("Patient"):
            continue

        if provider == "RTL":
            patient.update({
                "Appt Time": "",
                "Provider Room": "",
                "Estim Room": "",
                "Estim Start": "",
                "Next Step": "Ready to Leave",
                "Estim Done": False,
            })
            continue

        if provider not in PROVIDERS:
            continue

        arrival = parse_time(
            patient.get("Arrival"),
            today,
        )

        if not arrival:
            arrival = now
            patient["Arrival"] = format_time(now)

        appt = parse_time(
            patient.get("Appt Time"),
            today,
        )

        if not appt:
            appt = next_provider_slot(
                patients,
                provider,
                now,
            )
            patient["Appt Time"] = format_time(appt)

        patient["Provider Room"] = PROVIDERS[provider]

        minutes_early = (
            appt - arrival
        ).total_seconds() / 60

        done = patient.get("Estim Done", False)
        step = patient.get("Next Step", "")

        if done:
            patient["Estim Room"] = ""
            patient["Estim Start"] = ""

            if step != "Ready to Leave":
                patient["Next Step"] = (
                    "Estim Done - Move to Provider Room"
                    if minutes_early >= EARLY_MINUTES
                    else "Estim Done - Ready to leave"
                )

        elif step not in ("", "Estim First", "Provider First"):
            pass

        elif step == "Estim First":
            pass

        elif step == "Provider First":
            pass

        elif EARLY_MINUTES <= minutes_early <= MAX_EARLY_MINUTES:
            patient["Next Step"] = "Estim First"

        elif minutes_early > MAX_EARLY_MINUTES:
            patient["Next Step"] = "Review - Over 45 Min Early"

        else:
            patient["Next Step"] = "Provider First"

    # STEP 2: Reserve existing Estim assignments

    for patient in patients:
        if patient.get("Estim Done"):
            continue

        if patient.get("Next Step") == "Ready to Leave":
            continue

        room = patient.get("Estim Room")
        start = parse_time(
            patient.get("Estim Start"),
            today,
        )

        if room in room_available and start:
            room_available[room] = max(
                room_available[room],
                start + timedelta(minutes=ESTIM_MINUTES),
            )

    # STEP 3: Assign new Estim patients

    estim_patients = [
        p for p in patients
        if p.get("Next Step") == "Estim First"
        and not p.get("Estim Done")
        and not p.get("Estim Room")
    ]

    estim_patients.sort(
        key=lambda p: parse_time(
            p.get("Arrival"), today
        ) or now
    )

    for patient in estim_patients:
        room = min(
            room_available,
            key=lambda r: room_available[r],
        )

        start = max(now, room_available[room])

        patient["Estim Room"] = room
        patient["Estim Start"] = format_time(start)

        room_available[room] = (
            start + timedelta(minutes=ESTIM_MINUTES)
        )

        appt = parse_time(
            patient.get("Appt Time"),
            today,
        )

        if (
            appt
            and start + timedelta(minutes=ESTIM_MINUTES) > appt
        ):
            patient["Next Step"] = (
                "Estim Room Delayed - Review"
            )

    # STEP 4: Clear completed or inactive assignments

    for patient in patients:
        if (
            patient.get("Estim Done")
            or patient.get("Next Step") == "Ready to Leave"
        ):
            patient["Estim Room"] = ""
            patient["Estim Start"] = ""

        elif patient.get("Next Step") not in (
            "Estim First",
            "Estim Room Delayed - Review",
        ):
            patient["Estim Room"] = ""
            patient["Estim Start"] = ""

    return patients
