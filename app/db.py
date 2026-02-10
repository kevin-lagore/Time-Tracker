"""SQLite database access layer."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import load_config
from app.log_setup import get_logger
from app.models import LogEntry, LogEntryEdit, UserState

logger = get_logger("worklog.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS log_entries (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    audio_path TEXT,
    audio_sha256 TEXT,
    transcript_raw TEXT,
    transcript_confidence REAL,
    cleaned_note TEXT,
    tags_json TEXT DEFAULT '[]',
    is_private INTEGER DEFAULT 0,
    context_source TEXT DEFAULT 'none',
    toggl_time_entry_id TEXT,
    toggl_project_id TEXT,
    toggl_project_name TEXT,
    toggl_client_name TEXT,
    toggl_workspace_id TEXT,
    capture_context_json TEXT,
    error_json TEXT
);

CREATE TABLE IF NOT EXISTS toggl_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cached_at TEXT NOT NULL,
    workspaces_json TEXT,
    projects_json TEXT,
    clients_json TEXT
);

CREATE TABLE IF NOT EXISTS log_entry_edits (
    id TEXT PRIMARY KEY,
    log_entry_id TEXT NOT NULL,
    edited_at TEXT NOT NULL,
    field TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    FOREIGN KEY (log_entry_id) REFERENCES log_entries(id)
);

CREATE TABLE IF NOT EXISTS user_state (
    key TEXT PRIMARY KEY,
    value_json TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_log_entries_created ON log_entries(created_at);
CREATE INDEX IF NOT EXISTS idx_log_entries_client ON log_entries(toggl_client_name);
CREATE INDEX IF NOT EXISTS idx_log_entries_project ON log_entries(toggl_project_name);
CREATE INDEX IF NOT EXISTS idx_log_entry_edits_entry ON log_entry_edits(log_entry_id);
"""


def _db_path() -> Path:
    cfg = load_config()
    p = Path(cfg["database"]["path"])
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def init_db():
    """Initialize database schema."""
    with get_connection() as conn:
        conn.executescript(_SCHEMA)
    logger.info("Database initialized at %s", _db_path())


@contextmanager
def get_connection():
    """Yield a sqlite3 connection with WAL mode and row factory."""
    conn = sqlite3.connect(str(_db_path()), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _row_to_entry(row: sqlite3.Row) -> LogEntry:
    d = dict(row)
    d["is_private"] = bool(d.get("is_private", 0))
    return LogEntry(**d)


# --- Log Entries ---

def insert_entry(entry: LogEntry):
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO log_entries
            (id, created_at, updated_at, audio_path, audio_sha256,
             transcript_raw, transcript_confidence, cleaned_note, tags_json,
             is_private, context_source, toggl_time_entry_id, toggl_project_id,
             toggl_project_name, toggl_client_name, toggl_workspace_id,
             capture_context_json, error_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                entry.id,
                entry.created_at.isoformat(),
                entry.updated_at.isoformat(),
                entry.audio_path,
                entry.audio_sha256,
                entry.transcript_raw,
                entry.transcript_confidence,
                entry.cleaned_note,
                entry.tags_json,
                int(entry.is_private),
                entry.context_source,
                entry.toggl_time_entry_id,
                entry.toggl_project_id,
                entry.toggl_project_name,
                entry.toggl_client_name,
                entry.toggl_workspace_id,
                entry.capture_context_json,
                entry.error_json,
            ),
        )
    logger.info("Inserted log entry %s", entry.id)


def update_entry(entry: LogEntry):
    entry.updated_at = datetime.utcnow()
    with get_connection() as conn:
        conn.execute(
            """UPDATE log_entries SET
                updated_at=?, audio_path=?, audio_sha256=?,
                transcript_raw=?, transcript_confidence=?, cleaned_note=?,
                tags_json=?, is_private=?, context_source=?,
                toggl_time_entry_id=?, toggl_project_id=?, toggl_project_name=?,
                toggl_client_name=?, toggl_workspace_id=?,
                capture_context_json=?, error_json=?
            WHERE id=?""",
            (
                entry.updated_at.isoformat(),
                entry.audio_path,
                entry.audio_sha256,
                entry.transcript_raw,
                entry.transcript_confidence,
                entry.cleaned_note,
                entry.tags_json,
                int(entry.is_private),
                entry.context_source,
                entry.toggl_time_entry_id,
                entry.toggl_project_id,
                entry.toggl_project_name,
                entry.toggl_client_name,
                entry.toggl_workspace_id,
                entry.capture_context_json,
                entry.error_json,
                entry.id,
            ),
        )
    logger.info("Updated log entry %s", entry.id)


def get_entry(entry_id: str) -> Optional[LogEntry]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM log_entries WHERE id=?", (entry_id,)
        ).fetchone()
    if row:
        return _row_to_entry(row)
    return None


def delete_entry(entry_id: str):
    with get_connection() as conn:
        conn.execute("DELETE FROM log_entries WHERE id=?", (entry_id,))
        conn.execute("DELETE FROM log_entry_edits WHERE log_entry_id=?", (entry_id,))
    logger.info("Deleted log entry %s", entry_id)


def find_by_sha256(sha256: str) -> Optional[LogEntry]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM log_entries WHERE audio_sha256=?", (sha256,)
        ).fetchone()
    if row:
        return _row_to_entry(row)
    return None


def list_entries(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    client: Optional[str] = None,
    project: Optional[str] = None,
    tag: Optional[str] = None,
    keyword: Optional[str] = None,
    context_source: Optional[str] = None,
    has_errors: Optional[bool] = None,
    include_private: bool = True,
    limit: int = 200,
    offset: int = 0,
) -> list[LogEntry]:
    clauses = []
    params: list = []

    if date_from:
        clauses.append("created_at >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("created_at <= ?")
        params.append(date_to + "T23:59:59")
    if client:
        clauses.append("toggl_client_name = ?")
        params.append(client)
    if project:
        clauses.append("toggl_project_name = ?")
        params.append(project)
    if tag:
        clauses.append("tags_json LIKE ?")
        params.append(f'%"{tag}"%')
    if keyword:
        clauses.append(
            "(transcript_raw LIKE ? OR cleaned_note LIKE ?)"
        )
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    if context_source:
        clauses.append("context_source = ?")
        params.append(context_source)
    if has_errors is True:
        clauses.append("error_json IS NOT NULL AND error_json != 'null'")
    elif has_errors is False:
        clauses.append("(error_json IS NULL OR error_json = 'null')")
    if not include_private:
        clauses.append("is_private = 0")

    where = " AND ".join(clauses) if clauses else "1=1"
    sql = f"SELECT * FROM log_entries WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_entry(r) for r in rows]


def count_entries(**kwargs) -> int:
    """Count entries matching filters (same kwargs as list_entries minus limit/offset)."""
    clauses = []
    params: list = []
    if kwargs.get("date_from"):
        clauses.append("created_at >= ?")
        params.append(kwargs["date_from"])
    if kwargs.get("date_to"):
        clauses.append("created_at <= ?")
        params.append(kwargs["date_to"] + "T23:59:59")
    if kwargs.get("client"):
        clauses.append("toggl_client_name = ?")
        params.append(kwargs["client"])
    if not kwargs.get("include_private", True):
        clauses.append("is_private = 0")
    where = " AND ".join(clauses) if clauses else "1=1"
    with get_connection() as conn:
        row = conn.execute(f"SELECT COUNT(*) as cnt FROM log_entries WHERE {where}", params).fetchone()
    return row["cnt"]


# --- Edits (audit) ---

def insert_edit(edit: LogEntryEdit):
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO log_entry_edits (id, log_entry_id, edited_at, field, old_value, new_value)
            VALUES (?,?,?,?,?,?)""",
            (edit.id, edit.log_entry_id, edit.edited_at.isoformat(), edit.field, edit.old_value, edit.new_value),
        )


def get_edits_for_entry(entry_id: str) -> list[LogEntryEdit]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM log_entry_edits WHERE log_entry_id=? ORDER BY edited_at DESC",
            (entry_id,),
        ).fetchall()
    return [LogEntryEdit(**dict(r)) for r in rows]


# --- Toggl Cache ---

def save_toggl_cache(workspaces: list, projects: list, clients: list):
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO toggl_cache (cached_at, workspaces_json, projects_json, clients_json)
            VALUES (?, ?, ?, ?)""",
            (
                datetime.utcnow().isoformat(),
                json.dumps(workspaces),
                json.dumps(projects),
                json.dumps(clients),
            ),
        )
    logger.info("Saved Toggl cache")


def get_toggl_cache() -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM toggl_cache ORDER BY cached_at DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    return {
        "cached_at": row["cached_at"],
        "workspaces": json.loads(row["workspaces_json"] or "[]"),
        "projects": json.loads(row["projects_json"] or "[]"),
        "clients": json.loads(row["clients_json"] or "[]"),
    }


# --- User State ---

def get_user_state(key: str) -> Optional[str]:
    with get_connection() as conn:
        row = conn.execute("SELECT value_json FROM user_state WHERE key=?", (key,)).fetchone()
    if row:
        return row["value_json"]
    return None


def set_user_state(key: str, value_json: str):
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO user_state (key, value_json, updated_at) VALUES (?,?,?)
            ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at""",
            (key, value_json, datetime.utcnow().isoformat()),
        )
