"""Simple username/password auth with bcrypt hashing + JWT sessions.

Scope is a personal tool for the owner and a few friends, so this is deliberately
minimal: a single SQLite users table, bcrypt password hashing, and short-lived
HS256 JWTs. No password reset, email verification, or role hierarchy (every
logged-in user can use every feature — RBAC is a documented future extension).
"""
from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timezone

import bcrypt
import jwt

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_DB_PATH = os.path.join(_DATA_DIR, "users.db")


def _conn() -> sqlite3.Connection:
    os.makedirs(_DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as c:
        c.execute(
            """CREATE TABLE IF NOT EXISTS users (
                   username   TEXT PRIMARY KEY,
                   pw_hash    BLOB NOT NULL,
                   role       TEXT NOT NULL DEFAULT 'user',
                   created_at TEXT NOT NULL
               )"""
        )


# --- password hashing -----------------------------------------------------

def hash_password(password: str) -> bytes:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())


def verify_password(password: str, pw_hash: bytes) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), pw_hash)
    except (ValueError, TypeError):
        return False


# --- user management ------------------------------------------------------

def create_user(username: str, password: str, role: str = "user") -> bool:
    """Create a user. Returns False if the username already exists."""
    username = username.strip()
    if not username or not password:
        return False
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO users (username, pw_hash, role, created_at) VALUES (?,?,?,?)",
                (username, hash_password(password), role, datetime.now(timezone.utc).isoformat()),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def authenticate(username: str, password: str) -> dict | None:
    """Return {username, role} if credentials are valid, else None."""
    with _conn() as c:
        row = c.execute(
            "SELECT username, pw_hash, role FROM users WHERE username = ?", (username.strip(),)
        ).fetchone()
    if row and verify_password(password, row["pw_hash"]):
        return {"username": row["username"], "role": row["role"]}
    return None


def seed_default_user() -> None:
    """Create the seed account from APP_USERNAME / APP_PASSWORD if it's missing."""
    init_db()
    username = os.getenv("APP_USERNAME", "").strip()
    password = os.getenv("APP_PASSWORD", "")
    if not username or not password:
        return
    if create_user(username, password, role="admin"):
        print(f"[auth] Seeded login account '{username}'. Change APP_PASSWORD in .env to rotate it.")


# --- JWT sessions ---------------------------------------------------------

def _secret() -> str:
    return os.getenv("JWT_SECRET", "dev-insecure-secret")


def make_token(username: str, role: str = "user") -> str:
    hours = int(os.getenv("JWT_EXPIRY_HOURS", "8"))
    payload = {
        "sub": username,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + hours * 3600,
    }
    return jwt.encode(payload, _secret(), algorithm="HS256")


def decode_token(token: str) -> dict | None:
    """Return the token payload if valid & unexpired, else None."""
    try:
        return jwt.decode(token, _secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
