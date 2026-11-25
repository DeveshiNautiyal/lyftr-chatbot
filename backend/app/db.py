"""SQLite storage. Schema is created on startup."""
import json
import os
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  metadata TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY,
  system_prompt TEXT,
  created_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str):
        self.path = path
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        with self._conn() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def ping(self) -> bool:
        with self._conn() as c:
            c.execute("SELECT 1").fetchone()
        return True

    def get_system_prompt(self, session_id: str):
        with self._conn() as c:
            row = c.execute("SELECT system_prompt FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        return row["system_prompt"] if row else None

    def history(self, session_id: str) -> list:
        with self._conn() as c:
            rows = c.execute(
                "SELECT role, content, metadata FROM messages WHERE session_id=? ORDER BY id", (session_id,)
            ).fetchall()
        out = []
        for r in rows:
            item = {"role": r["role"], "content": r["content"]}
            if r["metadata"]:
                item["metadata"] = json.loads(r["metadata"])
            out.append(item)
        return out

    def session_exists(self, session_id: str) -> bool:
        with self._conn() as c:
            return c.execute("SELECT 1 FROM messages WHERE session_id=? LIMIT 1", (session_id,)).fetchone() is not None

    def save_exchange(self, session_id, system_prompt, user_msg, reply, metadata):
        """Atomically store the user message and assistant reply (only called on success)."""
        ts = now()
        with self._conn() as c:
            c.execute(
                "INSERT INTO sessions(session_id, system_prompt, created_at) VALUES(?,?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET system_prompt=COALESCE(excluded.system_prompt, sessions.system_prompt)",
                (session_id, system_prompt, ts),
            )
            c.execute(
                "INSERT INTO messages(session_id, role, content, metadata, created_at) VALUES(?,?,?,?,?)",
                (session_id, "user", user_msg, None, ts),
            )
            c.execute(
                "INSERT INTO messages(session_id, role, content, metadata, created_at) VALUES(?,?,?,?,?)",
                (session_id, "assistant", reply, json.dumps(metadata), now()),
            )
