"""
Persistent SQLite storage for the NEMS Estim board.

For multiple staff members to share one board, all browser sessions must connect
to this same running app server and this database file must live on persistent
storage. Do not run separate app instances with separate local database files.
"""
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from config import TIMEZONE

# Set NEMS_ESTIM_DB to a persistent mounted path in your hosting environment.
DB_PATH = Path(os.environ.get("NEMS_ESTIM_DB", "data/nems_estim.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _connect():
    conn = sqlite3.connect(str(DB_PATH), timeout=20, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=20000")
    return conn


def _today():
    return datetime.now(TIMEZONE).strftime("%Y-%m-%d")


def _initialize():
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS patient_boards (
                board_date TEXT PRIMARY KEY,
                patients_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute(
            """INSERT OR IGNORE INTO patient_boards
               (board_date, patients_json, updated_at)
               VALUES (?, '[]', ?)""",
            (_today(), datetime.now(TIMEZONE).isoformat()),
        )


def load_patients():
    _initialize()
    with _connect() as conn:
        row = conn.execute(
            "SELECT patients_json FROM patient_boards WHERE board_date = ?",
            (_today(),),
        ).fetchone()
    if not row:
        return []
    return json.loads(row[0])


def save_patients(patients):
    _initialize()
    payload = json.dumps(patients, ensure_ascii=False, default=str)
    with _connect() as conn:
        conn.execute(
            """INSERT INTO patient_boards (board_date, patients_json, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(board_date) DO UPDATE SET
                   patients_json = excluded.patients_json,
                   updated_at = excluded.updated_at""",
            (_today(), payload, datetime.now(TIMEZONE).isoformat()),
        )


def reset_patients():
    save_patients([])


def get_revision():
    # Kept for compatibility with any existing code that imports this helper.
    _initialize()
    with _connect() as conn:
        row = conn.execute(
            "SELECT updated_at FROM patient_boards WHERE board_date = ?",
            (_today(),),
        ).fetchone()
    return row[0] if row else None
