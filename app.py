import streamlit as st
import pandas as pd
from datetime import datetime, time
from uuid import uuid4

from streamlit_autorefresh import st_autorefresh

from config import (
    APP_NAME, TIMEZONE, REFRESH_SECONDS, STATUSES,
    NEXT_STEPS, ESTIM_ROOMS,
)
from storage import load_patients, save_patients, reset_patients, get_revision
from scheduler import rebuild_schedule, new_patient

st.set_page_config(page_title=APP_NAME, page_icon="🏥", layout="wide")

# ----------------------------- Styling -----------------------------
st.markdown("""
<style>
    .block-container {padding-top: 1.6rem; padding-bottom: 2.5rem; max-width: 1500px;}
    [data-testid="stMetric"] {
        background: #f5f7fa; border: 1px solid #e6eaf0;
        padding: 14px 16px; border-radius: 12px;
    }
    [data-testid="stDataFrame"], [data-testid="stDataEditor"] {border-radius: 10px;}
    div.stButton > button {border-radius: 9px; min-height: 2.5rem;}
    h1 {letter-spacing: -0.035em;}
    .small-muted {color: #687386; font-size: .88rem;}
</style>
""", unsafe_allow_html=True)

# Keep the database values in 24-hour format. Only the interface uses AM/PM.
def to_display(value):
    if not value:
        return ""
    try:
        parsed = datetime.strptime(str(value).strip(), "%H:%M")
        return f"{parsed.strftime('%I:%M %p').lstrip('0')}"
    except ValueError:
        return str(value)

def to_storage(value):
    if value is None or str(value).strip() == "":
        return ""
    raw = str(value).strip().upper()
    for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M"):
        try:
            return datetime.strptime(raw, fmt).strftime("%H:%M")
        except ValueError:
            pass
    raise ValueError(f"Use a time such as 9:30 AM or 14:30 (received {value!r}).")

def now_time():
    return datetime.now(TIMEZONE).strftime("%H:%M")

def refresh_board():
    st.rerun()

# Refresh the shared board periodically so other staff can see updates.
st_autorefresh(interval=max(5, int(REFRESH_SECONDS)) * 1000, key="nems_refresh")

now = datetime.now(TIMEZONE)
today = now.strftime("%A, %B %-d, %Y")

# ----------------------------- Load -----------------------------
try:
    patients = load_patients()
    scheduled = rebuild_schedule([dict(p) for p in patients])
    # Persist scheduler-generated assignments only when they actually change.
    if scheduled != patients:
        save_patients(scheduled)
        patients = scheduled
    else:
        patients = scheduled
except Exception as exc:
    st.error("The patient board could not be loaded. Check the database configuration.")
    st.exception(exc)
    st.stop()

# ----------------------------- Header -----------------------------
header_left, header_right = st.columns([4, 1])
with header_left:
    st.title("NEMS Estim")
    st.caption(f"Daily Patient Flow  ·  {today}")
with header_right:
    st.write("")
    if st.button("↻ Refresh", use_container_width=True):
        st.rerun()

st.divider()

# ----------------------------- Summary -----------------------------
active_patients = [p for p in patients if p.get("Patient")]
total = len(active_patients)
in_estim = sum(bool(p.get("Estim Room")) for p in active_patients)
completed = sum(
    p.get("Next Step") == "Ready to Leave"
    or str(p.get("Next Step", "")).startswith("Estim Done")
    for p in active_patients
)
review = sum(
    "Review" in str(p.get("Next Step", ""))
    or "Delayed" in str(p.get("Next Step", ""))
    or bool(p.get("Conflict"))
    for p in active_patients
)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Patients", total)
m2.metric("In Estim", in_estim)
m3.metric("Completed / Leaving", completed)
m4.metric("Needs Review", review)

st.divider()

# ----------------------------- Add patient -----------------------------
with st.expander("＋ Add patient", expanded=False):
    with st.form("add_patient_form", clear_on_submit=True):
        c1, c2, c3 = st.columns([2, 1, 1])
        name = c1.text_input("Patient last name")
        provider = c2.selectbox("Provider", STATUSES[:-1])
        appt = c3.text_input("Appointment time", placeholder="9:30 AM")
        submitted = st.form_submit_button("Add patient", type="primary", use_container_width=True)
    if submitted:
        if not name.strip():
            st.error("Enter a patient last name.")
        else:
            try:
                appt_24 = to_storage(appt)
                patient = new_patient(name.strip(), provider, appt_24)
                patient["Arrival"] = now_time()
                updated = rebuild_schedule(patients + [patient])
                save_patients(updated)
                st.success("Patient added.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

# ----------------------------- Patient board -----------------------------
st.subheader("Patient flow")
st.caption("Changes to the table save automatically. Times are displayed in 12-hour format.")

if patients:
    # Keep the original records so manual edits can set the correct AUTO/MANUAL flags.
    original_by_id = {str(p.get("id")): dict(p) for p in patients}
    display_rows = []
    for p in patients:
        display_rows.append({
            "id": str(p.get("id", "")),
            "Patient": p.get("Patient", ""),
            "Provider": p.get("Status", ""),
            "Appointment": to_display(p.get("Appt Time", "")),
            "Appt Control": p.get("Appt Mode", "AUTO"),
            "Provider Room": p.get("Provider Room", ""),
            "Estim Room": p.get("Estim Room", ""),
            "Estim Start": to_display(p.get("Estim Start", "")),
            "Room Control": p.get("Estim Room Mode", "AUTO"),
            "Estim Time Control": p.get("Estim Start Mode", "AUTO"),
            "Next Step": p.get("Next Step", ""),
            "Next Step Control": p.get("Next Step Mode", "AUTO"),
            "Estim Done": bool(p.get("Estim Done", False)),
            "Arrival": to_display(p.get("Arrival", "")),
            "Conflict": p.get("Conflict", ""),
        })

    display_df = pd.DataFrame(display_rows)
    editor_key = f"patient_editor_{today}_{get_revision()}_{st.session_state.get('editor_version', 0)}"
    edited_df = st.data_editor(
        display_df,
        key=editor_key,
        hide_index=True,
        use_container_width=True,
        num_rows="fixed",
        disabled=["id", "Provider Room", "Arrival", "Conflict"],
        column_config={
            "id": None,
            "Patient": st.column_config.TextColumn("Patient", required=True, width="medium"),
            "Provider": st.column_config.SelectboxColumn("Provider", options=STATUSES, width="small"),
            "Appointment": st.column_config.TextColumn("Appointment", help="Example: 9:30 AM", width="small"),
            "Appt Control": st.column_config.SelectboxColumn("Appt", options=["AUTO", "MANUAL"], width="small"),
            "Provider Room": st.column_config.NumberColumn("Provider room", width="small"),
            "Estim Room": st.column_config.SelectboxColumn("Estim room", options=["", *ESTIM_ROOMS], width="small"),
            "Estim Start": st.column_config.TextColumn("Estim start", help="Example: 9:45 AM", width="small"),
            "Room Control": st.column_config.SelectboxColumn("Room", options=["AUTO", "MANUAL"], width="small"),
            "Estim Time Control": st.column_config.SelectboxColumn("Estim time", options=["AUTO", "MANUAL"], width="small"),
            "Next Step": st.column_config.SelectboxColumn(
                "Next step",
                options=NEXT_STEPS + ["Estim Done - Move to Provider Room",
                                      "Estim Done - Ready to leave",
                                      "Estim Room Delayed - Review",
                                      "Review - Over 45 Min Early"],
                width="medium",
            ),
            "Next Step Control": st.column_config.SelectboxColumn("Flow", options=["AUTO", "MANUAL"], width="small"),
            "Estim Done": st.column_config.CheckboxColumn("Estim done", width="small"),
            "Arrival": st.column_config.TextColumn("Arrival", width="small"),
            "Conflict": st.column_config.TextColumn("Conflict", width="medium"),
        },
    )

    edited_rows = edited_df.to_dict("records")
    changed = edited_rows != display_rows

    if changed:
        try:
            updated = []
            for row in edited_rows:
                pid = str(row.get("id", ""))
                old = original_by_id.get(pid)
                if old is None:
                    continue
                p = dict(old)
                p["Patient"] = str(row.get("Patient", "")).strip()
                if not p["Patient"]:
                    raise ValueError("Patient names cannot be blank.")
                p["Status"] = row.get("Provider", p.get("Status", ""))
                p["Appt Time"] = to_storage(row.get("Appointment", ""))
                p["Estim Start"] = to_storage(row.get("Estim Start", ""))
                p["Estim Room"] = row.get("Estim Room", "")
                p["Next Step"] = row.get("Next Step", "")
                p["Estim Done"] = bool(row.get("Estim Done", False))

                # Editing a value automatically switches that field to manual.
                if row.get("Appointment") != to_display(old.get("Appt Time", "")):
                    p["Appt Mode"] = "MANUAL"
                else:
                    p["Appt Mode"] = row.get("Appt Control", old.get("Appt Mode", "AUTO"))

                if row.get("Estim Room") != old.get("Estim Room", ""):
                    p["Estim Room Mode"] = "MANUAL" if row.get("Estim Room") not in ("", None) else "AUTO"
                else:
                    p["Estim Room Mode"] = row.get("Room Control", old.get("Estim Room Mode", "AUTO"))

                if row.get("Estim Start") != to_display(old.get("Estim Start", "")):
                    p["Estim Start Mode"] = "MANUAL" if row.get("Estim Start") else "AUTO"
                else:
                    p["Estim Start Mode"] = row.get("Estim Time Control", old.get("Estim Start Mode", "AUTO"))

                if row.get("Next Step") != old.get("Next Step", ""):
                    p["Next Step Mode"] = "MANUAL"
                else:
                    p["Next Step Mode"] = row.get("Next Step Control", old.get("Next Step Mode", "AUTO"))

                updated.append(p)

            updated = rebuild_schedule(updated)
            save_patients(updated)
            st.session_state.editor_version = st.session_state.get("editor_version", 0) + 1
            st.toast("Changes saved", icon="✓")
            st.rerun()
        except ValueError as exc:
            st.error(f"Changes not saved: {exc}")

    # A simple per-patient quick editor provides a clearer override path on smaller screens.
    with st.expander("Manual override help"):
        st.markdown(
            "- Edit **Appointment**, **Estim room**, **Estim start**, or **Next step** directly in the table.\n"
            "- The edited field automatically switches to **MANUAL** control.\n"
            "- Change its control selector back to **AUTO** to let the scheduler manage it again.\n"
            "- A conflict is shown in the Conflict column. Check the room and time before proceeding."
        )
else:
    st.info("No patients have been added today. Use **Add patient** to get started.")

# ----------------------------- Daily controls -----------------------------
st.divider()
with st.expander("Daily administration"):
    st.warning("Resetting clears the current day's patient board for everyone using this database.")
    confirm = st.checkbox("I understand that this will clear today's board.")
    if st.button("Reset today's board", disabled=not confirm, type="secondary"):
        reset_patients()
        st.session_state.editor_version = st.session_state.get("editor_version", 0) + 1
        st.success("Today's board has been cleared.")
        st.rerun()

st.caption(f"NEMS Estim · Shared database · Refreshes every {REFRESH_SECONDS} seconds")
