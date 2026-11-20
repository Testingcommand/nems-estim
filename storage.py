"""Daily SQLite board. All staff must use the same persistent app/database."""
import json
import os
import sqlite3
from pathlib import Path
from datetime import datetime
from config import TIMEZONE

DB_PATH = Path(os.environ.get("NEMS_ESTIM_DB", "data/nems_estim.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

class ConcurrentUpdateError(Exception):
    pass

ALLOWED_FIELDS = {
    "id", "Patient", "Status", "Provider Room", "Appt Time", "Arrival",
    "Estim Needed", "Stage", "Estim Room", "Actual Estim Start",
    "Actual Estim End", "Provider Seen", "Provider Seen At",
    "Patient Moved", "Patient Moved At", "Estim Done", "Flow Suggestion",
    "Conflict", "Created At", "Completed At", "Estim End",
}

def _today():
    return datetime.now(TIMEZONE).strftime("%Y-%m-%d")

def _connect():
    connection = sqlite3.connect(str(DB_PATH), timeout=20)
    connection.execute("PRAGMA busy_timeout=20000")
    connection.execute("PRAGMA journal_mode=WAL")
    return connection

def _initialize():
    today = _today()
    with _connect() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS daily_board (
                board_date TEXT PRIMARY KEY,
                patients_json TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
        """)
        connection.execute("DELETE FROM daily_board WHERE board_date < ?", (today,))
        connection.execute("""
            INSERT OR IGNORE INTO daily_board
            (board_date, patients_json, revision, updated_at)
            VALUES (?, '[]', 0, ?)
        """, (today, datetime.now(TIMEZONE).isoformat()))

def _clean(records):
    return [
        {key: value for key, value in patient.items() if key in ALLOWED_FIELDS}
        for patient in records if isinstance(patient, dict)
    ]

def load_board():
    _initialize()
    with _connect() as connection:
        row = connection.execute(
            "SELECT patients_json, revision FROM daily_board WHERE board_date=?",
            (_today(),)
        ).fetchone()
    if not row:
        return [], 0
    return _clean(json.loads(row[0])), int(row[1])

def save_patients(patients, expected_revision=None):
    _initialize()
    payload = json.dumps(_clean(patients), ensure_ascii=False)
    with _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT revision FROM daily_board WHERE board_date=?",
            (_today(),)
        ).fetchone()
        current_revision = int(row[0]) if row else 0
        if expected_revision is not None and current_revision != expected_revision:
            connection.rollback()
            raise ConcurrentUpdateError(
                "The board changed in another browser. Refresh the board and retry your action."
            )
        new_revision = current_revision + 1
        connection.execute("""
            INSERT INTO daily_board
            (board_date, patients_json, revision, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(board_date) DO UPDATE SET
                patients_json=excluded.patients_json,
                revision=excluded.revision,
                updated_at=excluded.updated_at
        """, (_today(), payload, new_revision, datetime.now(TIMEZONE).isoformat()))
        connection.commit()
    return new_revision

def reset_patients(expected_revision=None):
    return save_patients([], expected_revision)
