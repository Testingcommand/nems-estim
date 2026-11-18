
import streamlit as st
from datetime import datetime
from config import TIMEZONE


def get_daily_key():
    return datetime.now(TIMEZONE).strftime("%Y-%m-%d")


def load_patients():
    today = get_daily_key()

    if st.session_state.get("board_date") != today:
        st.session_state.board_date = today
        st.session_state.patients = []

    return st.session_state.patients


def save_patients(patients):
    st.session_state.patients = patients


def reset_patients():
    st.session_state.patients = []
    st.session_state.board_date = get_daily_key()
