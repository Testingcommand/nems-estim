
import streamlit as st
import pandas as pd

from datetime import datetime
from streamlit_autorefresh import st_autorefresh

from config import (
    APP_NAME,
    TIMEZONE,
    REFRESH_SECONDS,
    STATUSES,
    NEXT_STEPS,
)

from storage import (
    load_patients,
    save_patients,
    reset_patients,
)

from scheduler import rebuild_schedule, format_time


st.set_page_config(
    page_title=APP_NAME,
    page_icon="🏥",
    layout="wide",
)

# Automatic refresh
st_autorefresh(
    interval=REFRESH_SECONDS * 1000,
    key="nems_refresh",
)

now = datetime.now(TIMEZONE)
today = now.strftime("%Y-%m-%d")


def get_time():
    return datetime.now(TIMEZONE).strftime("%H:%M")


def update_board():
    patients = load_patients()
    patients = rebuild_schedule(patients)
    save_patients(patients)
    return patients


# -------------------------------
# HEADER
# -------------------------------

st.title("🏥 NEMS Estim")
st.caption(
    f"Daily Patient Flow Dashboard · {today}"
)

col1, col2 = st.columns([4, 1])

with col1:
    st.caption(
        f"Last refreshed: {get_time()}"
    )

with col2:
    if st.button("🔄 Refresh Now", use_container_width=True):
        st.rerun()


# -------------------------------
# LOAD SHARED PATIENT DATA
# -------------------------------

try:
    patients = update_board()

except Exception as error:
    st.error(
        "Unable to connect to the temporary shared storage. "
        "Please check the application configuration."
    )
    st.stop()


# -------------------------------
# SUMMARY DASHBOARD
# -------------------------------

total = len([
    p for p in patients
    if p.get("Patient")
])

in_estim = len([
    p for p in patients
    if p.get("Estim Room")
])

ready = len([
    p for p in patients
    if p.get("Next Step") == "Ready to Leave"
    or str(p.get("Next Step", "")).startswith("Estim Done")
])

review = len([
    p for p in patients
    if "Review" in str(p.get("Next Step", ""))
    or "Delayed" in str(p.get("Next Step", ""))
])

a, b, c, d = st.columns(4)

a.metric("Patients", total)
b.metric("In Estim", in_estim)
c.metric("Completed / Leaving", ready)
d.metric("Needs Review", review)


st.divider()


# -------------------------------
# ADD PATIENT
# -------------------------------

st.subheader("Add Patient")

with st.form("add_patient", clear_on_submit=True):

    c1, c2, c3 = st.columns(3)

    with c1:
        name = st.text_input("Patient Last Name")

    with c2:
        provider = st.selectbox(
            "Provider",
            STATUSES[:-1],
        )

    with c3:
        appointment = st.text_input(
            "Appointment Time (HH:MM)",
            placeholder="09:30",
        )

    add = st.form_submit_button(
        "➕ Add Patient",
        use_container_width=True,
    )

    if add:
        if not name.strip():
            st.error("Enter a patient name.")

        else:
            try:
                if appointment.strip():
                    datetime.strptime(
                        appointment.strip(),
                        "%H:%M",
                    )

                patients.append({
                    "id": str(
                        datetime.now().timestamp()
                    ),
                    "Patient": name.strip(),
                    "Status": provider,
                    "Appt Time": appointment.strip(),
                    "Provider Room": "",
                    "Estim Room": "",
                    "Estim Start": "",
                    "Next Step": "",
                    "Estim Done": False,
                    "Arrival": get_time(),
                })

                save_patients(
                    rebuild_schedule(patients)
                )

                st.rerun()

            except ValueError:
                st.error(
                    "Appointment must use HH:MM format, "
                    "such as 09:30."
                )


st.divider()


# -------------------------------
# PATIENT TABLE
# -------------------------------

st.subheader("Patient Flow")

if patients:

    df = pd.DataFrame(patients)

    columns = [
        "id",
        "Patient",
        "Status",
        "Appt Time",
        "Provider Room",
        "Estim Room",
        "Estim Start",
        "Next Step",
        "Estim Done",
        "Arrival",
    ]

    for col in columns:
        if col not in df.columns:
            df[col] = ""

    edited = st.data_editor(
        df[columns],
        hide_index=True,
        use_container_width=True,
        num_rows="fixed",
        key=f"patient_editor_{today}",
        column_config={
            "id": None,
            "Patient": st.column_config.TextColumn(
                "Patient",
                required=True,
            ),
            "Status": st.column_config.SelectboxColumn(
                "Provider",
                options=STATUSES,
            ),
            "Appt Time": st.column_config.TextColumn(
                "Appointment",
                help="24-hour HH:MM",
            ),
            "Provider Room": st.column_config.NumberColumn(
                "Provider Room",
                disabled=True,
            ),
            "Estim Room": st.column_config.SelectboxColumn(
                "Estim Room",
                options=[1, 2, 5],
            ),
            "Estim Start": st.column_config.TextColumn(
                "Estim Start",
            ),
            "Next Step": st.column_config.SelectboxColumn(
                "Next Step",
                options=NEXT_STEPS + [
                    "Estim Room Delayed - Review",
                    "Review - Over 45 Min Early",
                ],
            ),
            "Estim Done": st.column_config.CheckboxColumn(
                "Estim Done",
            ),
            "Arrival": st.column_config.TextColumn(
                "Arrival",
                disabled=True,
            ),
        },
    )

    if st.button(
        "💾 Save Patient Changes",
        type="primary",
        use_container_width=True,
    ):
        try:
            updated = edited.to_dict("records")

            for patient in updated:
                if patient.get("Appt Time"):
                    datetime.strptime(
                        patient["Appt Time"],
                        "%H:%M",
                    )

                if patient.get("Estim Start"):
                    datetime.strptime(
                        patient["Estim Start"],
                        "%H:%M",
                    )

            save_patients(
                rebuild_schedule(updated)
            )

            st.success("Patient board updated.")
            st.rerun()

        except ValueError:
            st.error(
                "Check appointment and Estim times. "
                "Use HH:MM format."
            )

else:
    st.info("No patients have been added today.")


st.divider()


# -------------------------------
# DAILY RESET
# -------------------------------

st.subheader("Daily Controls")

with st.expander("Reset Daily Board"):

    st.warning(
        "This permanently removes the current day's "
        "temporary patient information."
    )

    confirm = st.checkbox(
        "I understand that this will clear today's board."
    )

    if st.button(
        "🗑️ Reset Today's Board",
        disabled=not confirm,
        type="primary",
    ):
        reset_patients()
        st.success("Daily board cleared.")
        st.rerun()


st.caption(
    "NEMS Estim · Temporary daily session · "
    "Automatic refresh every 20 seconds"
)
