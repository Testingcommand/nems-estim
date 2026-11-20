import streamlit as st
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

from config import APP_NAME, TIMEZONE, REFRESH_SECONDS, PROVIDERS, ESTIM_ROOMS
from storage import load_board, save_patients, reset_patients, ConcurrentUpdateError
from scheduler import (
    now_local, parse_time, format_time, display_time, normalize_patient,
    rebuild_schedule, suggest_appointment, suggest_flow, start_estim,
    finish_estim, mark_provider_seen
)

st.set_page_config(page_title=APP_NAME, page_icon="🏥", layout="wide")
st.markdown("""
<style>
.block-container {max-width: 1450px; padding-top: 1.2rem; padding-bottom: 2rem;}
div[data-testid="stMetric"] {border:1px solid var(--secondary-background-color);
 border-radius:12px;padding:12px;background:var(--secondary-background-color);}
div.stButton > button {border-radius:9px; min-height:2.5rem;}
</style>
""", unsafe_allow_html=True)
st_autorefresh(interval=max(10, int(REFRESH_SECONDS))*1000, key="nems_auto_refresh")
now = now_local()
st.title("NEMS Estim")
st.caption("Daily patient flow · " + now.strftime("%A, %B %d, %Y"))

def commit(updated, revision):
    updated = rebuild_schedule(updated)
    st.session_state.board_revision = save_patients(updated, expected_revision=revision)
    st.rerun()

def get_copy():
    return [dict(p) for p in patients]

def patient_by_id(items, pid):
    return next(p for p in items if str(p.get("id")) == str(pid))

try:
    patients, revision = load_board()
    patients = rebuild_schedule(patients)
except Exception as exc:
    st.error("Unable to load the patient board. Check the database and hosting configuration.")
    st.exception(exc)
    st.stop()

with st.sidebar:
    st.subheader("Board")
    if st.button("↻ Refresh", use_container_width=True):
        st.rerun()
    st.caption(f"Auto-refresh every {REFRESH_SECONDS} seconds")
    st.caption(f"Revision {revision}")

# Add patient form
with st.expander("＋ Add patient", expanded=True):
    with st.form("add_patient", clear_on_submit=True):
        name = st.text_input("Patient last name / identifier")
        provider = st.radio("Provider", list(PROVIDERS.keys()), horizontal=True)
        default_appt = suggest_appointment(patients, provider, now)
        appt_raw = st.text_input("Appointment time", value=display_time(default_appt),
                                 help="Suggested as the next 30-minute slot for this provider. You can change it.")
        arrival_raw = st.text_input("Arrival time", value=now.strftime("%I:%M %p").lstrip("0"),
                                    help="Examples: 9, 930a, 2:30pm, 1430")
        estim_needed = st.checkbox("Estim needed", value=True)
        add = st.form_submit_button("Add patient", type="primary", use_container_width=True)
    if add:
        if not name.strip():
            st.error("Enter a patient last name or identifier.")
        else:
            appt = parse_time(appt_raw)
            arrival = parse_time(arrival_raw)
            if appt is None:
                st.error("Appointment time not recognized. Try 9, 930a, 2:30pm, or 14:30.")
            elif arrival is None:
                st.error("Arrival time not recognized. Try 9, 930a, 2:30pm, or 14:30.")
            else:
                p = normalize_patient({
                    "Patient": name.strip(), "Status": provider,
                    "Appt Time": format_time(appt), "Arrival": format_time(arrival),
                    "Estim Needed": estim_needed,
                    "Stage": "Waiting for Estim" if estim_needed else "Waiting for Provider",
                })
                p["Flow Suggestion"] = suggest_flow(p["Appt Time"], p["Arrival"])
                if p["Flow Suggestion"] == "Provider First":
                    p["Stage"] = "Waiting for Provider" if estim_needed else "Waiting for Provider"
                if not estim_needed:
                    p["Stage"] = "Waiting for Provider"
                try:
                    commit(patients + [p], revision)
                except ConcurrentUpdateError as exc:
                    st.warning(str(exc))

# counts
active = [p for p in patients if p.get("Patient") and p.get("Stage") != "Ready to Leave"]
in_estim = sum(p.get("Stage") == "Estim in Progress" for p in active)
ready = sum(p.get("Stage") == "Ready to Leave" for p in patients)
conflicts = sum(bool(p.get("Conflict")) for p in patients)
m1,m2,m3,m4 = st.columns(4)
m1.metric("Active patients", len(active))
m2.metric("Estim in progress", in_estim)
m3.metric("Ready to leave", ready)
m4.metric("Room conflicts", conflicts)

st.divider()
st.subheader("Patient flow")
st.caption("Use the action buttons to move each patient through the visit. Provider discretion always takes priority.")

# Ready to leave is deliberately shown first so finished patients do not disappear at the bottom.
sections = [
    ("Ready to Leave", "Ready to leave"),
    ("Estim in Progress", "Estim in progress"),
    ("Waiting for Estim", "Waiting for Estim"),
    ("Waiting for Provider", "Waiting for Provider"),
]
for stage, heading in sections:
    members = [p for p in patients if p.get("Patient") and p.get("Stage") == stage]
    if not members:
        continue
    with st.container():
        st.markdown(f"### {heading} · {len(members)}")
        for p in members:
            pid = p["id"]
            with st.container(border=True):
                c1,c2 = st.columns([4,2])
                with c1:
                    st.markdown(f"**{p.get('Patient')}**")
                    st.caption(
                        f"{p.get('Status')} · Provider room {p.get('Provider Room') or '—'} · "
                        f"Appt {display_time(p.get('Appt Time')) or '—'} · "
                        f"Arrived {display_time(p.get('Arrival')) or '—'}"
                    )
                    details = []
                    if p.get("Estim Needed"):
                        details.append("Estim room " + (str(p.get("Estim Room")) if p.get("Estim Room") else "—"))
                        if p.get("Actual Estim Start"):
                            details.append("Started " + display_time(p["Actual Estim Start"]))
                        if p.get("Actual Estim End"):
                            details.append("Ended " + display_time(p["Actual Estim End"]))
                    else:
                        details.append("Provider-only visit")
                    if p.get("Provider Seen"):
                        details.append("Provider seen " + (display_time(p.get("Provider Seen At")) or ""))
                    st.caption(" · ".join(details))
                    if p.get("Conflict"):
                        st.error("Room conflict: " + p["Conflict"])
                with c2:
                    if stage == "Waiting for Estim":
                        if st.button("▶ Start Estim", key=f"start_{pid}", type="primary", use_container_width=True):
                            updated = get_copy()
                            target = patient_by_id(updated, pid)
                            try:
                                start_estim(updated, target)
                                commit(updated, revision)
                            except ValueError as exc:
                                st.warning(str(exc))
                    elif stage == "Estim in Progress":
                        if st.button("✓ Mark Estim complete", key=f"finish_{pid}", type="primary", use_container_width=True):
                            updated = get_copy()
                            finish_estim(patient_by_id(updated, pid))
                            try:
                                commit(updated, revision)
                            except ConcurrentUpdateError as exc:
                                st.warning(str(exc))
                    elif stage == "Waiting for Provider":
                        if st.button("✓ Provider seen", key=f"provider_{pid}", type="primary", use_container_width=True):
                            updated = get_copy()
                            mark_provider_seen(patient_by_id(updated, pid))
                            try:
                                commit(updated, revision)
                            except ConcurrentUpdateError as exc:
                                st.warning(str(exc))
                    else:
                        st.success("Visit steps complete")
                with st.expander("Edit / override"):
                    with st.form(f"edit_{pid}"):
                        e_name = st.text_input("Patient identifier", value=p.get("Patient",""))
                        e_provider = st.radio("Provider", list(PROVIDERS.keys()),
                                              index=list(PROVIDERS).index(p["Status"]) if p.get("Status") in PROVIDERS else 0,
                                              horizontal=True, key=f"provider_edit_{pid}")
                        e_appt = st.text_input("Appointment time", value=display_time(p.get("Appt Time")))
                        e_arrival = st.text_input("Arrival time", value=display_time(p.get("Arrival")))
                        e_estim = st.checkbox("Estim needed", value=bool(p.get("Estim Needed", True)))
                        stage_options = ["Waiting for Estim","Estim in Progress","Waiting for Provider","Ready to Leave"]
                        e_stage = st.radio("Current stage", stage_options,
                                           index=stage_options.index(stage) if stage in stage_options else 0,
                                           horizontal=False, key=f"stage_{pid}")
                        e_room = st.selectbox("Estim room (for active Estim)", ["Auto", *ESTIM_ROOMS],
                                              index=(["Auto", *ESTIM_ROOMS].index(p.get("Estim Room"))
                                                     if p.get("Estim Room") in ESTIM_ROOMS else 0),
                                              key=f"room_{pid}")
                        save = st.form_submit_button("Save changes", type="primary", use_container_width=True)
                    if save:
                        ap = parse_time(e_appt); ar = parse_time(e_arrival)
                        if not e_name.strip() or ap is None or ar is None:
                            st.error("Enter a patient identifier and valid appointment and arrival times.")
                        else:
                            updated = get_copy()
                            target = patient_by_id(updated, pid)
                            target.update({
                                "Patient": e_name.strip(), "Status": e_provider,
                                "Provider Room": PROVIDERS[e_provider],
                                "Appt Time": format_time(ap), "Arrival": format_time(ar),
                                "Estim Needed": e_estim, "Stage": e_stage,
                                "Estim Room": "" if e_room == "Auto" else e_room,
                            })
                            if not e_estim:
                                target["Estim Room"] = ""
                                target["Estim Done"] = True
                                target["Stage"] = "Ready to Leave" if target.get("Provider Seen") else "Waiting for Provider"
                            if e_stage == "Estim in Progress" and not target.get("Actual Estim Start"):
                                target["Actual Estim Start"] = now_local().strftime("%H:%M")
                                if e_room == "Auto":
                                    occupied = {x.get("Estim Room") for x in updated if x.get("id") != pid and x.get("Stage") == "Estim in Progress"}
                                    target["Estim Room"] = next((r for r in ESTIM_ROOMS if r not in occupied), "")
                            if e_stage == "Ready to Leave":
                                target["Provider Seen"] = True
                            try:
                                commit(updated, revision)
                            except ConcurrentUpdateError as exc:
                                st.warning(str(exc))

# Provider-only and post-Estim actions: when a patient is waiting for provider, staff can also start Estim
# after marking provider seen. This is how Provider First visits proceed.
st.divider()
with st.expander("Daily administration"):
    st.warning("Reset clears the shared board for everyone using this database.")
    confirm = st.checkbox("I understand this clears today's board.")
    if st.button("Reset today's board", disabled=not confirm):
        try:
            reset_patients(expected_revision=revision)
            st.rerun()
        except ConcurrentUpdateError as exc:
            st.warning(str(exc))

st.caption("Operational workflow tracker only. Use approved systems for clinical documentation.")
