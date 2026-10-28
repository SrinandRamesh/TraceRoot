"""SQLite persistence for dataset investigations, recommendations, fix validations and activity."""

import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

DB_PATH = os.environ.get("TRACEROOT_DB_PATH") or str(Path(__file__).with_name("traceroot.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS investigations (
    id TEXT PRIMARY KEY,
    workspace TEXT NOT NULL,
    title TEXT NOT NULL,
    dataset_name TEXT NOT NULL,
    source TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    signature TEXT,
    status TEXT NOT NULL,
    outcome TEXT NOT NULL,
    severity TEXT NOT NULL,
    primary_service TEXT,
    received_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    result TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    investigation_id TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    category TEXT NOT NULL, priority TEXT NOT NULL, problem TEXT NOT NULL, why TEXT NOT NULL,
    evidence TEXT NOT NULL, action TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS fix_validations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    investigation_id TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL, fix_description TEXT NOT NULL, dataset_name TEXT NOT NULL,
    result TEXT NOT NULL, details TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS investigation_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    investigation_id TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    timestamp TEXT NOT NULL, kind TEXT NOT NULL, message TEXT NOT NULL
);
"""
LEGACY_TABLES = ["telemetry", "activity", "validations", "metric_samples", "incidents"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create tables. Drops the old demo-incident tables from earlier versions; nothing is seeded."""
    with connect() as conn:
        for table in LEGACY_TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.executescript(SCHEMA)


def new_id() -> str:
    return f"INV-{datetime.now(timezone.utc):%Y%m%d}-{secrets.token_hex(3).upper()}"


def _activity(conn, inv_id: str, kind: str, message: str) -> None:
    conn.execute("INSERT INTO investigation_activity (investigation_id, timestamp, kind, message) VALUES (?,?,?,?)",
                 (inv_id, utc_now(), kind, message))


def _replace_recs(conn, inv_id: str, recs: list[dict[str, Any]]) -> None:
    conn.execute("DELETE FROM recommendations WHERE investigation_id = ?", (inv_id,))
    for r in recs:
        conn.execute("INSERT INTO recommendations (investigation_id, category, priority, problem, why, evidence, action) "
                     "VALUES (?,?,?,?,?,?,?)", (inv_id, r["category"], r["priority"], r["problem"], r["why"], r["evidence"], r["action"]))


def save_investigation(record: dict[str, Any], activity: str) -> str:
    inv_id = new_id()
    now = utc_now()
    with connect() as conn:
        conn.execute(
            "INSERT INTO investigations (id, workspace, title, dataset_name, source, content_hash, signature, status, outcome, "
            "severity, primary_service, received_at, updated_at, result) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (inv_id, record["workspace"], record["title"], record["dataset_name"], record["source"], record["content_hash"],
             record["signature"], record["status"], record["outcome"], record["severity"], record["primary_service"],
             now, now, json.dumps(record["result"], default=str)))
        _replace_recs(conn, inv_id, record["result"]["recommendations"])
        _activity(conn, inv_id, "analysed", activity)
    return inv_id


def update_with_new_data(inv_id: str, record: dict[str, Any], message: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE investigations SET title=?, dataset_name=?, content_hash=?, outcome=?, severity=?, result=?, "
                     "updated_at=? WHERE id=?", (record["title"], record["dataset_name"], record["content_hash"],
                                                 record["outcome"], record["severity"],
                                                 json.dumps(record["result"], default=str), utc_now(), inv_id))
        _replace_recs(conn, inv_id, record["result"]["recommendations"])
        _activity(conn, inv_id, "new_data", message)


def _summary(row: sqlite3.Row, full: bool) -> dict[str, Any]:
    item = dict(row)
    result = json.loads(item.pop("result"))
    if full:
        item["result"] = result
    else:
        item["problem_statement"] = (result.get("problem") or {}).get("statement")
        item["affected_components"] = (result.get("problem") or {}).get("affected_components", [])
        item["severity_rationale"] = result.get("severity_rationale")
    return item


def list_investigations(workspace: str | None = None) -> list[dict[str, Any]]:
    with connect() as conn:
        q = "SELECT * FROM investigations" + (" WHERE workspace = ?" if workspace else "") + " ORDER BY received_at DESC"
        return [_summary(r, False) for r in conn.execute(q, (workspace,) if workspace else ()).fetchall()]


def get_investigation(inv_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM investigations WHERE id = ?", (inv_id,)).fetchone()
        if not row:
            return None
        item = _summary(row, True)
        item["activity"] = [dict(r) for r in conn.execute(
            "SELECT timestamp, kind, message FROM investigation_activity WHERE investigation_id = ? ORDER BY id", (inv_id,))]
        item["recommendations"] = [dict(r) for r in conn.execute(
            "SELECT * FROM recommendations WHERE investigation_id = ? ORDER BY id", (inv_id,))]
        item["validations"] = get_validations(inv_id, conn)
        return item


def find_by_hash(workspace: str, content_hash: str) -> str | None:
    with connect() as conn:
        row = conn.execute("SELECT id FROM investigations WHERE workspace=? AND content_hash=?", (workspace, content_hash)).fetchone()
        return row["id"] if row else None


def find_active_by_signature(workspace: str, signature: str) -> str | None:
    with connect() as conn:
        row = conn.execute("SELECT id FROM investigations WHERE workspace=? AND signature=? AND status IN ('Open','Investigating') "
                           "ORDER BY updated_at DESC", (workspace, signature)).fetchone()
        return row["id"] if row else None


def set_status(inv_id: str, status: str, message: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE investigations SET status=?, updated_at=? WHERE id=?", (status, utc_now(), inv_id))
        _activity(conn, inv_id, "status", message)


def delete_investigation(inv_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM investigations WHERE id = ?", (inv_id,))


def add_validation(inv_id: str, description: str, dataset_name: str, outcome: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute("INSERT INTO fix_validations (investigation_id, created_at, fix_description, dataset_name, result, details) "
                     "VALUES (?,?,?,?,?,?)", (inv_id, utc_now(), description, dataset_name, outcome["result"],
                                              json.dumps(outcome, default=str)))
        _activity(conn, inv_id, "validation", f"Fix validation '{description}' with {dataset_name}: {outcome['result']}.")


def get_validations(inv_id: str, conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    def run(c):
        rows = c.execute("SELECT * FROM fix_validations WHERE investigation_id = ? ORDER BY id DESC", (inv_id,)).fetchall()
        return [{**dict(r), "details": json.loads(r["details"])} for r in rows]
    if conn:
        return run(conn)
    with connect() as c:
        return run(c)


def list_recommendations(workspace: str) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("SELECT r.*, i.title AS investigation_title, i.dataset_name FROM recommendations r "
                            "JOIN investigations i ON i.id = r.investigation_id WHERE i.workspace = ? ORDER BY r.id DESC",
                            (workspace,)).fetchall()
        return [dict(r) for r in rows]


def set_recommendation_status(rec_id: int, status: str) -> bool:
    with connect() as conn:
        return conn.execute("UPDATE recommendations SET status=? WHERE id=?", (status, rec_id)).rowcount > 0
