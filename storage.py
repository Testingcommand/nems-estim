
import streamlit as st

from datetime import datetime
from config import TIMEZONE


def get_daily_key():
    return datetime.now(TIMEZONE).strftime(
        "%Y-%m-%d"
    )


def load_patients():
    today = get_daily_key()

    if st.session_state.get("board_date") != today:
        st.session_state.board_date = today
        st.session_state.patients = []
        st.session_state.revision = 0

    if "patients" not in st.session_state:
        st.session_state.patients = []

    return st.session_state.patients


def save_patients(patients):
    st.session_state.patients = patients
    st.session_state.revision = (
        st.session_state.get("revision", 0) + 1
    )


def reset_patients():
    st.session_state.patients = []
    st.session_state.board_date = get_daily_key()
    st.session_state.revision = 0


def get_revision():
    return st.session_state.get("revision", 0)
