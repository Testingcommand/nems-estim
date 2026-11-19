import streamlit as st
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

from config import APP_NAME, TIMEZONE, REFRESH_SECONDS, STATUSES, NEXT_STEPS, ESTIM_ROOMS, PROVIDERS
from storage import load_board, save_patients, reset_patients, ConcurrentUpdateError
from scheduler import (
    new_patient, rebuild_schedule, parse_time, display_time,
    get_estim_conflicts, mark_estim_done
)

st.set_page_config(page_title=APP_NAME, page_icon="🏥", layout="wide")

# Theme-aware colors: use Streamlit variables so both light and dark themes remain legible.
st.markdown("""
<style>
.block-container {max-width: 1450px; padding-top: 1.4rem; padding-bottom: 2rem;}
div[data-testid="stMetric"] {border:1px solid var(--secondary-background-color);
  border-radius:14px; padding:14px 16px; background:var(--secondary-background-color);}
.patient-card {border:1px solid var(--secondary-background-color); border-radius:14px;
  padding:16px; margin:8px 0 14px 0; background:var(--background-color);}
.muted {color:var(--text-color); opacity:.72; font-size:.88rem;}
div.stButton > button {border-radius:9px;}
</style>
""", unsafe_allow_html=True)

st_autorefresh(interval=max(10, int(REFRESH_SECONDS))*1000, key="nems_auto_refresh")
now = datetime.now(TIMEZONE)
today_label = now.strftime("%A, %B %d, %Y").replace(" 0", " ")

def commit(updated, revision):
    updated = rebuild_schedule(updated)
    new_revision = save_patients(updated, expected_revision=revision)
    st.session_state.board_revision = new_revision
    st.rerun()

def time_input(label, value, key):
    # Text input accepts familiar AM/PM notation; convert to internal HH:MM.
    return st.text_input(label, value=display_time(value), placeholder="9:30 AM", key=key)

try:
    patients, revision = load_board()
    patients = rebuild_schedule(patients)
except Exception:
    st.error("Unable to load the patient board. Check the database and hosting configuration.")
    st.stop()

st.title("NEMS Estim")
st.caption(f"Daily Patient Flow · {today_label}")
top_a, top_b = st.columns([5,1])
with top_b:
    if st.button("↻ Refresh", use_container_width=True):
        st.rerun()

active = [p for p in patients if p.get("Patient") and p.get("Status") != "RTL"]
in_estim = sum(1 for p in active if p.get("Estim Room") and not p.get("Estim Done"))
done = sum(1 for p in patients if p.get("Estim Done") or p.get("Status") == "RTL")
conflict_count = sum(1 for p in patients if p.get("Conflict"))
m1,m2,m3,m4 = st.columns(4)
m1.metric("Patients", len(active))
m2.metric("In / Assigned to Estim", in_estim)
m3.metric("Estim completed / leaving", done)
m4.metric("Room conflicts", conflict_count)

st.divider()
with st.expander("＋ Add patient", expanded=False):
    with st.form("add_patient", clear_on_submit=True):
        c1,c2,c3 = st.columns([2,1,1])
        name = c1.text_input("Patient identifier / last name")
        provider = c2.selectbox("Provider", STATUSES[:-1])
        appt = c3.text_input("Appointment time", placeholder="10:30 AM")
        arrival = st.text_input("Arrival time (leave blank for now)", placeholder="10:15 AM")
        add = st.form_submit_button("Add patient", type="primary", use_container_width=True)
    if add:
        if not name.strip():
            st.error("Enter a patient identifier.")
        else:
            try:
                appt_dt = parse_time(appt) if appt.strip() else None
                arrival_dt = parse_time(arrival) if arrival.strip() else now
                if appt.strip() and not appt_dt:
                    raise ValueError("Appointment time must look like 10:30 AM.")
                if arrival.strip() and not arrival_dt:
                    raise ValueError("Arrival time must look like 10:15 AM.")
                patient = new_patient(name.strip(), provider, appt_dt.strftime("%H:%M") if appt_dt else "")
                patient["Arrival"] = arrival_dt.strftime("%H:%M")
                commit(patients + [patient], revision)
            except ValueError as e:
                st.error(str(e))
            except ConcurrentUpdateError as e:
                st.warning(str(e))

# Main board grouped by suggested/current patient flow.
st.subheader("Patient flow")
st.caption("The suggested flow is a starting point. Provider discretion takes priority; use Edit to override any patient.")

groups = [
    ("Estim First", "Estim first", "Patients assigned to Estim before seeing the provider."),
    ("Provider First", "Provider first", "Patients waiting to see their provider first."),
    ("Estim in Progress", "Estim in progress", "Patients currently using an Estim room."),
    ("Estim Done - Move to Provider Room", "Estim completed", "Patients who finished Estim and should move to the provider."),
    ("Review - Provider Discretion", "Needs provider review", "Cases where staff should decide the next step."),
    ("Review - Over 60 Min Early", "Arrived very early", "Review timing with the provider."),
    ("Estim Room Delayed - Review", "Estim delayed", "Estim timing needs attention."),
    ("Ready to Leave", "Ready to leave", "Patients marked as finished."),
]
# Include any additional manual next-step labels under an Other group.
known = {g[0] for g in groups}
for title, heading, description in groups:
    members = [p for p in patients if p.get("Patient") and p.get("Next Step") == title]
    if not members:
        continue
    with st.expander(f"{heading} · {len(members)}", expanded=True):
        st.caption(description)
        for p in members:
            pid = str(p.get("id"))
            with st.container(border=True):
                left, right = st.columns([4,1])
                with left:
                    st.markdown(f"**{p.get('Patient','')}**")
                    st.caption(
                        f"{p.get('Status','')} · Provider room {p.get('Provider Room') or '—'} · "
                        f"Appointment {display_time(p.get('Appt Time')) or '—'} · "
                        f"Arrived {display_time(p.get('Arrival')) or '—'}"
                    )
                    estim_text = (
                        f"Estim room {p.get('Estim Room')} · {display_time(p.get('Estim Start'))}"
                        if p.get("Estim Room") else "No Estim room assigned"
                    )
                    st.write(estim_text)
                    if p.get("Conflict"):
                        st.error(p["Conflict"])
                with right:
                    if p.get("Estim Done"):
                        st.success("Estim done")
                    elif p.get("Estim Room"):
                        st.info("Estim assigned")
                    else:
                        st.caption("Not in Estim")
                with st.expander("Edit patient / manual override"):
                    with st.form(f"edit_{pid}"):
                        e1,e2 = st.columns(2)
                        e_name = e1.text_input("Patient", value=p.get("Patient",""))
                        e_provider = e2.selectbox("Provider", STATUSES, index=STATUSES.index(p.get("Status")) if p.get("Status") in STATUSES else 0)
                        e_appt = time_input("Appointment time", p.get("Appt Time"), f"appt_{pid}")
                        e_arrival = time_input("Arrival time", p.get("Arrival"), f"arrival_{pid}")
                        e_room = e1.selectbox("Estim room", ["Auto", *ESTIM_ROOMS], index=(["Auto", *ESTIM_ROOMS].index(p.get("Estim Room")) if p.get("Estim Room") in ESTIM_ROOMS else 0))
                        e_estim_start = time_input("Estim start time", p.get("Estim Start"), f"estim_{pid}")
                        current_step = p.get("Next Step") or "Provider First"
                        step_options = list(dict.fromkeys(NEXT_STEPS + [current_step]))
                        e_step = e2.selectbox("Next step (provider discretion)", step_options, index=step_options.index(current_step))
                        e_step_auto = st.checkbox("Let system suggest next step again", value=p.get("Next Step Mode") != "MANUAL")
                        e_estim_done = st.checkbox("Estim completed", value=bool(p.get("Estim Done")))
                        save = st.form_submit_button("Save patient", type="primary", use_container_width=True)
                    if save:
                        try:
                            updated = [dict(x) for x in patients]
                            target = next(x for x in updated if str(x.get("id")) == pid)
                            if not e_name.strip():
                                raise ValueError("Patient identifier cannot be blank.")
                            target["Patient"] = e_name.strip()
                            target["Status"] = e_provider
                            for field, raw in [("Appt Time", e_appt), ("Arrival", e_arrival), ("Estim Start", e_estim_start)]:
                                parsed = parse_time(raw) if raw.strip() else None
                                if raw.strip() and not parsed:
                                    raise ValueError(f"Invalid time for {field}. Use 9:30 AM.")
                                target[field] = parsed.strftime("%H:%M") if parsed else ""
                            target["Appt Mode"] = "MANUAL" if target["Appt Time"] else "AUTO"
                            if e_room == "Auto":
                                target["Estim Room"] = ""
                                target["Estim Room Mode"] = "AUTO"
                            else:
                                target["Estim Room"] = int(e_room)
                                target["Estim Room Mode"] = "MANUAL"
                            target["Estim Start Mode"] = "MANUAL" if target["Estim Start"] else "AUTO"
                            target["Next Step"] = e_step
                            target["Next Step Mode"] = "AUTO" if e_step_auto else "MANUAL"
                            target["Estim Done"] = e_estim_done
                            if e_estim_done:
                                mark_estim_done(target)
                            commit(updated, revision)
                        except (ValueError, StopIteration) as e:
                            st.error(str(e))
                        except ConcurrentUpdateError as e:
                            st.warning(str(e))
                if p.get("Estim Room") and not p.get("Estim Done"):
                    if st.button("✓ Mark Estim done", key=f"done_{pid}"):
                        updated = [dict(x) for x in patients]
                        target = next(x for x in updated if str(x.get("id")) == pid)
                        mark_estim_done(target)
                        try:
                            commit(updated, revision)
                        except ConcurrentUpdateError as e:
                            st.warning(str(e))

other = [p for p in patients if p.get("Patient") and p.get("Next Step") not in known]
if other:
    with st.expander(f"Other / unclassified · {len(other)}", expanded=True):
        for p in other:
            st.write(f"**{p.get('Patient')}** — {p.get('Next Step') or 'No next step'}")

st.divider()
with st.expander("Daily administration"):
    st.warning("Reset clears the shared board for all staff using this database.")
    confirm = st.checkbox("I understand this clears today's patient board.")
    if st.button("Reset today's board", disabled=not confirm):
        try:
            reset_patients(expected_revision=revision)
            st.rerun()
        except ConcurrentUpdateError as e:
            st.warning(str(e))

st.caption(f"Shared board · Refreshes every {REFRESH_SECONDS} seconds · Database revision {revision}")
