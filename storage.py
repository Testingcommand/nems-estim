"""
Daily, minimal SQLite storage for the NEMS Estim operational tracker.

The board is keyed by the clinic-local date. On each load/save, records from
prior dates are deleted. All staff must connect to the same running app server
and persistent database. For multiple app replicas, use shared PostgreSQL.
"""
import json
import os
import sqlite3
from pathlib import Path
from datetime import datetime

from config import TIMEZONE

DB_PATH = Path(os.environ.get("NEMS_ESTIM_DB", "data/nems_estim.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


class ConcurrentUpdateError(Exception):
    """Another browser session saved a newer version of the board."""


# Explicit allowlist: keep only fields needed for patient-flow coordination.
ALLOWED_FIELDS = {
    "id", "Patient", "Status", "Appt Time", "Provider Room", "Appt Mode",
    "Arrival", "Estim Room", "Estim Start", "Estim Room Mode",
    "Estim Start Mode", "Next Step", "Next Step Mode", "Flow Order",
    "Estim Done", "Conflict", "Provider Start", "Provider Start Mode",
}


def _connect():
    conn = sqlite3.connect(str(DB_PATH), timeout=20)
    conn.execute("PRAGMA busy_timeout=20000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _today():
    return datetime.now(TIMEZONE).strftime("%Y-%m-%d")


def _initialize():
    today = _today()
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_board (
                board_date TEXT PRIMARY KEY,
                patients_json TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
        """)
        # Automatic daily expiration: remove all earlier clinic-day boards.
        conn.execute("DELETE FROM daily_board WHERE board_date < ?", (today,))
        conn.execute("""
            INSERT OR IGNORE INTO daily_board
            (board_date, patients_json, revision, updated_at)
            VALUES (?, '[]', 0, ?)
        """, (today, datetime.now(TIMEZONE).isoformat()))


def _minimal_records(records):
    cleaned = []
    for patient in records:
        if not isinstance(patient, dict):
            continue
        # Discard legacy or unexpected fields, including optional notes.
        cleaned.append({k: v for k, v in patient.items() if k in ALLOWED_FIELDS})
    return cleaned


def load_board():
    _initialize()
    with _connect() as conn:
        row = conn.execute(
            "SELECT patients_json, revision FROM daily_board WHERE board_date=?",
            (_today(),)
        ).fetchone()
    if row is None:
        return [], 0
    records = _minimal_records(json.loads(row[0]))
    # Rewrite same-day legacy rows once to remove fields no longer retained.
    if records != json.loads(row[0]):
        save_patients(records, expected_revision=int(row[1]))
        return load_board()
    return records, int(row[1])


def load_patients():
    patients, _ = load_board()
    return patients


def get_revision():
    _, revision = load_board()
    return revision


def save_patients(patients, expected_revision=None):
    _initialize()
    payload = json.dumps(_minimal_records(patients), ensure_ascii=False, default=str)
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT revision FROM daily_board WHERE board_date=?",
            (_today(),)
        ).fetchone()
        current = int(row[0]) if row else 0
        if expected_revision is not None and current != expected_revision:
            conn.rollback()
            raise ConcurrentUpdateError(
                "The board changed in another browser. Refresh and reapply your edit."
            )
        new_revision = current + 1
        conn.execute("""
            INSERT INTO daily_board
            (board_date, patients_json, revision, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(board_date) DO UPDATE SET
                patients_json=excluded.patients_json,
                revision=excluded.revision,
                updated_at=excluded.updated_at
        """, (_today(), payload, new_revision, datetime.now(TIMEZONE).isoformat()))
        conn.commit()
    return new_revision


def reset_patients(expected_revision=None):
    return save_patients([], expected_revision=expected_revision)
