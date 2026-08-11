"""Lightweight chat-session metadata (titles, timestamps) for the sidebar.

The ADK ``SqliteSessionService`` persists the full event history, but listing it
for a sidebar would mean loading every session's events just to show a title. So
we keep a small side table: one row per chat session with a human title (the
first user message) and an updated-at timestamp. Scoped per user.

Stored in ``data/sessions_meta.db`` (separate from the ADK sessions db).
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_DB_PATH = os.path.join(_DATA_DIR, "sessions_meta.db")


def _conn() -> sqlite3.Connection:
    os.makedirs(_DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS chat_sessions (
                   session_id   TEXT PRIMARY KEY,
                   user         TEXT NOT NULL,
                   title        TEXT NOT NULL,
                   created_at   TEXT NOT NULL,
                   updated_at   TEXT NOT NULL,
                   message_count INTEGER NOT NULL DEFAULT 0
               )"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON chat_sessions(user, updated_at)")
        # A clean UI transcript (user + assistant text). The ADK session db holds
        # the agent's full event history for working memory; this is what the chat
        # panel rehydrates from — simple and display-ready.
        c.execute(
            """CREATE TABLE IF NOT EXISTS chat_messages (
                   id         INTEGER PRIMARY KEY AUTOINCREMENT,
                   session_id TEXT NOT NULL,
                   user       TEXT NOT NULL,
                   role       TEXT NOT NULL,
                   text       TEXT NOT NULL,
                   created_at TEXT NOT NULL
               )"""
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON chat_messages(session_id, id)")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def touch_session(session_id: str, user: str, message: str) -> None:
    """Record activity on a session: create it (titled by the first message) or
    bump its updated-at + message count."""
    now = _now()
    title = (message or "New chat").strip().replace("\n", " ")[:60] or "New chat"
    with _conn() as c:
        row = c.execute(
            "SELECT session_id FROM chat_sessions WHERE session_id=? AND user=?",
            (session_id, user),
        ).fetchone()
        if row is None:
            c.execute(
                "INSERT INTO chat_sessions (session_id, user, title, created_at, updated_at, message_count)"
                " VALUES (?,?,?,?,?,1)",
                (session_id, user, title, now, now),
            )
        else:
            c.execute(
                "UPDATE chat_sessions SET updated_at=?, message_count=message_count+1"
                " WHERE session_id=? AND user=?",
                (now, session_id, user),
            )


def list_sessions(user: str, limit: int = 50) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT session_id, title, updated_at, message_count FROM chat_sessions"
            " WHERE user=? ORDER BY updated_at DESC LIMIT ?",
            (user, int(limit)),
        ).fetchall()
    return [dict(r) for r in rows]


def rename_session(session_id: str, user: str, title: str) -> bool:
    title = (title or "").strip()[:60]
    if not title:
        return False
    with _conn() as c:
        cur = c.execute(
            "UPDATE chat_sessions SET title=? WHERE session_id=? AND user=?",
            (title, session_id, user),
        )
        return cur.rowcount > 0


def delete_session(session_id: str, user: str) -> bool:
    with _conn() as c:
        c.execute("DELETE FROM chat_messages WHERE session_id=? AND user=?", (session_id, user))
        cur = c.execute(
            "DELETE FROM chat_sessions WHERE session_id=? AND user=?", (session_id, user)
        )
        return cur.rowcount > 0


# --- transcript (for rehydration) -----------------------------------------

def add_message(session_id: str, user: str, role: str, text: str) -> None:
    if not (text or "").strip():
        return
    with _conn() as c:
        c.execute(
            "INSERT INTO chat_messages (session_id, user, role, text, created_at) VALUES (?,?,?,?,?)",
            (session_id, user, role, text, _now()),
        )


def get_messages(session_id: str, user: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT role, text FROM chat_messages WHERE session_id=? AND user=? ORDER BY id",
            (session_id, user),
        ).fetchall()
    return [dict(r) for r in rows]
