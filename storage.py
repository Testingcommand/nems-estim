"""Daily SQLite board. Use one persistent shared database for all staff sessions."""
import json, os, sqlite3
from pathlib import Path
from datetime import datetime
from config import TIMEZONE

DB_PATH = Path(os.environ.get("NEMS_ESTIM_DB", "data/nems_estim.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

class ConcurrentUpdateError(Exception):
    pass

ALLOWED_FIELDS = {
    "id", "Patient", "Status", "Provider Room", "Appt Time", "Appt Mode",
    "Arrival", "Estim Needed", "Stage", "Estim Room", "Actual Estim Start",
    "Actual Estim End", "Provider Seen", "Provider Seen At", "Flow Suggestion",
    "Conflict", "Estim Done", "Next Step", "Estim End",
}

def _today():
    return datetime.now(TIMEZONE).strftime("%Y-%m-%d")

def _connect():
    conn = sqlite3.connect(str(DB_PATH), timeout=20)
    conn.execute("PRAGMA busy_timeout=20000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def _initialize():
    today = _today()
    with _connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS daily_board (
            board_date TEXT PRIMARY KEY, patients_json TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL)""")
        conn.execute("DELETE FROM daily_board WHERE board_date < ?", (today,))
        conn.execute("""INSERT OR IGNORE INTO daily_board
            (board_date, patients_json, revision, updated_at) VALUES (?, '[]', 0, ?)""",
            (today, datetime.now(TIMEZONE).isoformat()))

def _clean(records):
    return [{k:v for k,v in p.items() if k in ALLOWED_FIELDS}
            for p in records if isinstance(p, dict)]

def load_board():
    _initialize()
    with _connect() as conn:
        row = conn.execute("SELECT patients_json, revision FROM daily_board WHERE board_date=?",
                           (_today(),)).fetchone()
    if not row:
        return [], 0
    return _clean(json.loads(row[0])), int(row[1])

def save_patients(patients, expected_revision=None):
    _initialize()
    payload = json.dumps(_clean(patients), ensure_ascii=False)
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT revision FROM daily_board WHERE board_date=?",
                           (_today(),)).fetchone()
        current = int(row[0]) if row else 0
        if expected_revision is not None and current != expected_revision:
            conn.rollback()
            raise ConcurrentUpdateError("The board changed in another browser. Refresh and try again.")
        revision = current + 1
        conn.execute("""INSERT INTO daily_board
            (board_date, patients_json, revision, updated_at) VALUES (?, ?, ?, ?)
            ON CONFLICT(board_date) DO UPDATE SET patients_json=excluded.patients_json,
            revision=excluded.revision, updated_at=excluded.updated_at""",
            (_today(), payload, revision, datetime.now(TIMEZONE).isoformat()))
        conn.commit()
    return revision

def reset_patients(expected_revision=None):
    return save_patients([], expected_revision)
