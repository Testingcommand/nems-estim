import streamlit as st
from datetime import timedelta
from streamlit_autorefresh import st_autorefresh

from config import APP_NAME, REFRESH_SECONDS, PROVIDERS, ESTIM_ROOMS
from storage import load_board, save_patients, reset_patients, ConcurrentUpdateError
from scheduler import (
    now_local, parse_time, format_time, display_time, normalize_patient,
    rebuild_schedule, suggest_appointment, suggest_flow, arrival_message,
    start_estim, finish_estim, mark_patient_moved, mark_provider_seen,
    mark_completed, reopen_patient, room_status, STAGES
)

st.set_page_config(page_title=APP_NAME, page_icon="🏥", layout="wide")
st.markdown("""
<style>
.block-container {max-width: 1500px; padding-top: 1rem; padding-bottom: 2rem;}
div[data-testid="stMetric"] {
  border: 1px solid var(--secondary-background-color);
  border-radius: 12px; padding: 10px; background: var(--secondary-background-color);
}
div.stButton > button {border-radius: 9px; min-height: 2.45rem;}
.small-muted {color: var(--secondary-text-color); font-size: .88rem;}
.patient-row {padding: .25rem 0;}
</style>
""", unsafe_allow_html=True)

st_autorefresh(interval=max(10, int(REFRESH_SECONDS)) * 1000, key="nems_auto_refresh")
now = now_local()
st.title("NEMS Estim")
st.caption(f"Daily patient flow · {now.strftime('%A, %B %d, %Y')} · Updated {now.strftime('%I:%M:%S %p').lstrip('0')}")

def load_data():
    items, rev = load_board()
    return rebuild_schedule(items), rev

try:
    patients, revision = load_data()
except Exception as exc:
    st.error("Unable to load the patient board. Check the database and hosting configuration.")
    st.exception(exc)
    st.stop()

def commit(updated):
    try:
        cleaned = rebuild_schedule(updated)
        save_patients(cleaned, expected_revision=revision)
        st.rerun()
    except ConcurrentUpdateError as exc:
        st.warning(str(exc))
        st.info("Use Refresh before retrying so you do not overwrite another staff member's update.")
        st.stop()

def copy_patients():
    return [dict(patient) for patient in patients]

def find_patient(items, patient_id):
    return next(patient for patient in items if str(patient.get("id")) == str(patient_id))

def patient_sort_key(patient):
    value = parse_time(patient.get("Appt Time"), now.date())
    return (value is None, value or now, patient.get("Patient", "").casefold())

def stage_badge(stage):
    return {
        "Waiting for Estim": "🟡 Waiting for Estim",
        "Estim in Progress": "🔵 Estim in Progress",
        "Move to Provider": "🟠 Move to Provider",
        "Waiting for Provider": "🟣 Waiting for Provider",
        "Ready to Leave": "🟢 Ready to Leave",
        "Completed": "⚪ Completed",
    }.get(stage, stage)

# Sidebar controls
with st.sidebar:
    st.subheader("Board controls")
    if st.button("↻ Refresh now", use_container_width=True):
        st.rerun()
    st.caption(f"Auto-refresh: every {REFRESH_SECONDS} seconds")
    st.caption(f"Board revision: {revision}")
    st.divider()
    search_text = st.text_input("Search patient", placeholder="Last name / identifier")
    provider_filter = st.multiselect("Filter providers", list(PROVIDERS.keys()), default=list(PROVIDERS.keys()))
    stage_filter = st.multiselect(
        "Show stages",
        STAGES,
        default=["Waiting for Estim", "Estim in Progress", "Move to Provider", "Waiting for Provider", "Ready to Leave"]
    )
    show_completed = st.checkbox("Include completed patients", value=False)

# Add patient
with st.expander("＋ Add patient", expanded=(len(patients) == 0)):
    provider = st.radio("Provider", list(PROVIDERS.keys()), horizontal=True, key="add_provider")
    suggested_appt = suggest_appointment(patients, provider, now)
    suggested_flow = suggest_flow(suggested_appt, now.strftime("%H:%M"), now)
    with st.form("add_patient_form", clear_on_submit=True):
        patient_name = st.text_input("Patient last name / identifier")
        appointment_raw = st.text_input(
            "Appointment time",
            value=display_time(suggested_appt),
            help="Suggested as the next 30-minute slot for this provider. You can override it. Examples: 9, 930a, 2:30pm, 1430."
        )
        arrival_raw = st.text_input(
            "Arrival time",
            value=now.strftime("%I:%M %p").lstrip("0"),
            help="Examples: 9, 930a, 2:30pm, 1430."
        )
        estim_needed = st.checkbox("Estim needed", value=True)
        initial_order = st.radio(
            "Initial order",
            ["Estim first", "Provider first"],
            index=0 if suggested_flow == "Estim First" else 1,
            horizontal=True,
            help="This is a suggestion based on arrival time. Follow provider direction if different."
        )
        add_patient = st.form_submit_button("Add to board", type="primary", use_container_width=True)

    if add_patient:
        if not patient_name.strip():
            st.error("Enter a patient last name or approved identifier.")
        else:
            appointment = parse_time(appointment_raw, now.date())
            arrival = parse_time(arrival_raw, now.date())
            if appointment is None or arrival is None:
                st.error("Time not recognized. Try 9, 930a, 2:30pm, or 14:30.")
            else:
                stage = "Waiting for Estim" if estim_needed and initial_order == "Estim first" else "Waiting for Provider"
                new_patient = normalize_patient({
                    "Patient": patient_name.strip(),
                    "Status": provider,
                    "Provider Room": PROVIDERS[provider],
                    "Appt Time": format_time(appointment),
                    "Arrival": format_time(arrival),
                    "Estim Needed": estim_needed,
                    "Stage": stage,
                    "Flow Suggestion": suggest_flow(format_time(appointment), format_time(arrival), now),
                })
                try:
                    commit(patients + [new_patient])
                except ConcurrentUpdateError as exc:
                    st.warning(str(exc))

# Derived lists and dashboard
active_patients = [p for p in patients if p.get("Stage") != "Completed"]
visible_completed = [p for p in patients if p.get("Stage") == "Completed"]
rooms = room_status(patients)
room_busy = sum(value is not None for value in rooms.values())
ready_count = sum(p.get("Stage") == "Ready to Leave" for p in patients)
in_estim_count = sum(p.get("Stage") == "Estim in Progress" for p in patients)
move_count = sum(p.get("Stage") == "Move to Provider" for p in patients)

st.subheader("Clinic overview")
metric_cols = st.columns(4)
metric_cols[0].metric("Active patients", len(active_patients))
metric_cols[1].metric("Estim in progress", in_estim_count)
metric_cols[2].metric("Move to provider", move_count)
metric_cols[3].metric("Ready to leave", ready_count)

with st.container(border=True):
    st.markdown("**Provider queues**")
    queue_cols = st.columns(len(PROVIDERS))
    for col, provider_name in zip(queue_cols, PROVIDERS):
        queue = [p for p in active_patients if p.get("Status") == provider_name]
        waiting = sum(p.get("Stage") in ("Waiting for Provider", "Move to Provider") for p in queue)
        next_appt = min(
            [parse_time(p.get("Appt Time"), now.date()) for p in queue if parse_time(p.get("Appt Time"), now.date())],
            default=None
        )
        with col:
            st.metric(provider_name, f"{len(queue)} active", f"{waiting} awaiting provider")
            st.caption(f"Next appointment: {display_time(format_time(next_appt)) if next_appt else '—'}")

with st.container(border=True):
    st.markdown("**Estim room status**")
    room_cols = st.columns(len(ESTIM_ROOMS))
    for col, room in zip(room_cols, ESTIM_ROOMS):
        occupant = rooms.get(room)
        with col:
            if occupant:
                st.warning(f"Room {room} · Occupied")
                st.caption(occupant)
            else:
                st.success(f"Room {room} · Available")

st.divider()
st.subheader("Patient board")
st.caption("Compact list first. Expand a patient for one-click workflow actions and details.")

# Patient list ordered by appointment time, then filtered.
filtered = []
for patient in patients:
    if patient.get("Status") not in provider_filter:
        continue
    if patient.get("Stage") == "Completed" and not show_completed:
        continue
    if patient.get("Stage") not in stage_filter and not (patient.get("Stage") == "Completed" and show_completed):
        continue
    if search_text.strip() and search_text.strip().casefold() not in patient.get("Patient", "").casefold():
        continue
    filtered.append(patient)
filtered.sort(key=patient_sort_key)

if not filtered:
    st.info("No patients match the current filters.")
else:
    for patient in filtered:
        pid = patient["id"]
        stage = patient.get("Stage", "")
        appt = display_time(patient.get("Appt Time")) or "—"
        arrival = display_time(patient.get("Arrival")) or "—"
        title = f"{patient.get('Patient', 'Unknown')}  ·  {appt}  ·  {patient.get('Status', '—')}  ·  {stage_badge(stage)}"
        with st.expander(title, expanded=(stage == "Move to Provider")):
            top_left, top_right = st.columns([3, 1])
            with top_left:
                st.markdown(f"**Provider room {patient.get('Provider Room') or '—'}**")
                st.caption(f"Appointment {appt} · Arrival {arrival}")
                timing = arrival_message(patient, now)
                if timing:
                    if "review timing" in timing.lower() or "after appointment" in timing.lower():
                        st.warning(timing)
                    else:
                        st.caption(timing)
            with top_right:
                st.metric("Status", stage)

            if stage == "Move to Provider":
                room = patient.get("Provider Room") or "unassigned"
                st.success(f"➡️ MOVE TO PROVIDER ROOM {room}")
                st.caption("Estim is complete. Confirm when the patient has physically moved to the provider room.")
            elif stage == "Ready to Leave":
                st.success("Visit steps complete — patient is ready to leave.")
            elif stage == "Completed":
                st.caption(f"Completed at {display_time(patient.get('Completed At')) or '—'}")

            detail_cols = st.columns(3)
            detail_cols[0].write(f"**Estim:** {'Needed' if patient.get('Estim Needed') else 'Not needed'}")
            detail_cols[1].write(f"**Estim room:** {patient.get('Estim Room') or '—'}")
            detail_cols[2].write(f"**Provider seen:** {'Yes' if patient.get('Provider Seen') else 'No'}")
            if patient.get("Actual Estim Start"):
                st.caption(f"Estim started {display_time(patient.get('Actual Estim Start'))}")
            if patient.get("Actual Estim End"):
                st.caption(f"Estim completed {display_time(patient.get('Actual Estim End'))}")
            if patient.get("Patient Moved"):
                st.caption(f"Patient moved at {display_time(patient.get('Patient Moved At')) or '—'}")
            if patient.get("Provider Seen"):
                st.caption(f"Provider seen at {display_time(patient.get('Provider Seen At')) or '—'}")
            if patient.get("Conflict"):
                st.error("Room conflict: " + patient["Conflict"])

            st.markdown("**Actions**")
            action_cols = st.columns(3)
            if stage == "Waiting for Estim":
                if action_cols[0].button("▶ Start Estim", key=f"start_{pid}", type="primary", use_container_width=True):
                    updated = [dict(p) for p in patients]
                    try:
                        start_estim(updated, find_patient(updated, pid))
                        commit(updated)
                    except ValueError as exc:
                        st.warning(str(exc))
            elif stage == "Estim in Progress":
                if action_cols[0].button("✓ Estim complete", key=f"finish_{pid}", type="primary", use_container_width=True):
                    updated = [dict(p) for p in patients]
                    finish_estim(find_patient(updated, pid))
                    commit(updated)
            elif stage == "Move to Provider":
                if action_cols[0].button("↗ Patient moved", key=f"moved_{pid}", type="primary", use_container_width=True):
                    updated = [dict(p) for p in patients]
                    mark_patient_moved(find_patient(updated, pid))
                    commit(updated)
            elif stage == "Waiting for Provider":
                if action_cols[0].button("✓ Provider seen", key=f"provider_seen_{pid}", type="primary", use_container_width=True):
                    updated = [dict(p) for p in patients]
                    mark_provider_seen(find_patient(updated, pid))
                    commit(updated)
            elif stage == "Ready to Leave":
                if action_cols[0].button("✓ Complete visit", key=f"complete_{pid}", type="primary", use_container_width=True):
                    updated = [dict(p) for p in patients]
                    mark_completed(find_patient(updated, pid))
                    commit(updated)
            elif stage == "Completed":
                if action_cols[0].button("Reopen visit", key=f"reopen_{pid}", use_container_width=True):
                    updated = [dict(p) for p in patients]
                    reopen_patient(find_patient(updated, pid))
                    commit(updated)

            # Secondary actions and edit panel
            with st.expander("Edit / override", expanded=False):
                current_provider_index = list(PROVIDERS).index(patient["Status"]) if patient.get("Status") in PROVIDERS else 0
                with st.form(f"edit_{pid}"):
                    edit_name = st.text_input("Patient last name / identifier", value=patient.get("Patient", ""))
                    edit_provider = st.radio(
                        "Provider", list(PROVIDERS.keys()),
                        index=current_provider_index, horizontal=True, key=f"edit_provider_{pid}"
                    )
                    edit_appt = st.text_input("Appointment time", value=display_time(patient.get("Appt Time")))
                    edit_arrival = st.text_input("Arrival time", value=display_time(patient.get("Arrival")))
                    edit_estim = st.checkbox("Estim needed", value=bool(patient.get("Estim Needed", True)))
                    edit_stage = st.selectbox("Current stage", STAGES, index=STAGES.index(stage), key=f"edit_stage_{pid}")
                    edit_room = st.selectbox(
                        "Estim room", ["Auto"] + ESTIM_ROOMS,
                        index=(["Auto"] + ESTIM_ROOMS).index(patient.get("Estim Room"))
                        if patient.get("Estim Room") in ESTIM_ROOMS else 0,
                        key=f"edit_room_{pid}"
                    )
                    save_edit = st.form_submit_button("Save changes", type="primary", use_container_width=True)
                if save_edit:
                    new_appt = parse_time(edit_appt, now.date())
                    new_arrival = parse_time(edit_arrival, now.date())
                    if not edit_name.strip() or not new_appt or not new_arrival:
                        st.error("Enter a patient identifier and valid appointment and arrival times.")
                    else:
                        updated = [dict(p) for p in patients]
                        target = find_patient(updated, pid)
                        target.update({
                            "Patient": edit_name.strip(),
                            "Status": edit_provider,
                            "Provider Room": PROVIDERS[edit_provider],
                            "Appt Time": format_time(new_appt),
                            "Arrival": format_time(new_arrival),
                            "Estim Needed": edit_estim,
                            "Stage": edit_stage,
                            "Estim Room": "" if edit_room == "Auto" else edit_room,
                        })
                        if not edit_estim:
                            target["Estim Room"] = ""
                            target["Estim Done"] = True
                            target["Actual Estim Start"] = ""
                            target["Actual Estim End"] = ""
                            target["Stage"] = "Ready to Leave" if target.get("Provider Seen") else "Waiting for Provider"
                        if edit_stage == "Estim in Progress" and not target.get("Actual Estim Start"):
                            target["Actual Estim Start"] = now.strftime("%H:%M")
                            if edit_room == "Auto":
                                from scheduler import assign_estim_room
                                target["Estim Room"] = assign_estim_room(updated, target) or ""
                        if edit_stage == "Ready to Leave":
                            target["Provider Seen"] = True
                        commit(updated)

# Daily administration
st.divider()
with st.expander("Daily administration"):
    st.warning("Reset clears the shared board for everyone using this database.")
    reset_confirm = st.checkbox("I understand this clears today's board.")
    if st.button("Reset today's board", disabled=not reset_confirm):
        try:
            reset_patients(expected_revision=revision)
            st.rerun()
        except ConcurrentUpdateError as exc:
            st.warning(str(exc))

st.caption(
    "Operational workflow tracker only. Do not enter diagnoses, symptoms, medications, or clinical notes. "
    "Use only an organization-approved environment for any real patient information."
)
