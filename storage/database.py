"""SQLite history of analysis runs (local file, parameterized queries, compressed and redacted payloads)."""
from __future__ import annotations

import json
import os
import sqlite3
import zlib
from contextlib import closing
from datetime import datetime
from pathlib import Path

from ai.redaction import redact

SCHEMA_VERSION = 1
MAX_PAYLOAD_BYTES = 50 * 1024 * 1024


def redact_obj(obj, redact_emails: bool = True):
    """Return a copy of a JSON-like structure with every string value passed through secret redaction."""
    if isinstance(obj, str):
        return redact(obj, redact_emails=redact_emails).text
    if isinstance(obj, list):
        return [redact_obj(x, redact_emails) for x in obj]
    if isinstance(obj, dict):
        return {k: redact_obj(v, redact_emails) for k, v in obj.items()}
    return obj


class HistoryDB:
    def __init__(self, path, max_runs: int = 50):
        self.path = Path(path)
        self.max_runs = max_runs
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as con, con:
            con.execute("""CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, log_name TEXT NOT NULL,
                total_events INTEGER, error_groups INTEGER, critical_errors INTEGER, recurring_errors INTEGER,
                files_analyzed INTEGER, seconds REAL, ai_provider TEXT, payload BLOB NOT NULL)""")
            con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        try:
            os.chmod(self.path, 0o600)   # history may hold log excerpts: owner-only on POSIX
        except OSError:
            pass

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def save(self, run_dict: dict, tickets: dict | None = None, *, redact_payload: bool = True,
             redact_emails: bool = True) -> int:
        payload = {"run": run_dict, "tickets": tickets or {}}
        if redact_payload:
            payload = redact_obj(payload, redact_emails)
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if len(raw) > MAX_PAYLOAD_BYTES:
            raise ValueError("Analysis result is too large to store")
        d = run_dict.get("dashboard", {})
        with closing(self._connect()) as con, con:
            cur = con.execute(
                "INSERT INTO runs (created_at, log_name, total_events, error_groups, critical_errors, recurring_errors,"
                " files_analyzed, seconds, ai_provider, payload) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"), str(run_dict.get("log_name", "unknown"))[:200],
                 d.get("total_events"), d.get("unique_errors"), d.get("critical_errors"), d.get("recurring_errors"),
                 d.get("files_analyzed"), d.get("analysis_seconds"), str(run_dict.get("ai_provider", ""))[:100],
                 zlib.compress(raw, 6)))
            run_id = cur.lastrowid
            con.execute("DELETE FROM runs WHERE id NOT IN (SELECT id FROM runs ORDER BY id DESC LIMIT ?)", (self.max_runs,))
        return run_id

    def list(self, limit: int = 50) -> list[dict]:
        cols = ("id", "created_at", "log_name", "total_events", "error_groups", "critical_errors", "recurring_errors",
                "files_analyzed", "seconds", "ai_provider")
        with closing(self._connect()) as con:
            rows = con.execute(f"SELECT {', '.join(cols)} FROM runs ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
        return [dict(zip(cols, r)) for r in rows]

    def load(self, run_id: int) -> dict | None:
        with closing(self._connect()) as con:
            row = con.execute("SELECT payload FROM runs WHERE id = ?", (int(run_id),)).fetchone()
        if row is None:
            return None
        try:
            return json.loads(zlib.decompress(row[0]).decode("utf-8"))
        except (zlib.error, ValueError):
            return None

    def delete(self, run_id: int) -> bool:
        with closing(self._connect()) as con, con:
            return con.execute("DELETE FROM runs WHERE id = ?", (int(run_id),)).rowcount > 0

    def clear(self) -> int:
        with closing(self._connect()) as con, con:
            return con.execute("DELETE FROM runs").rowcount

    def count(self) -> int:
        with closing(self._connect()) as con:
            return con.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
