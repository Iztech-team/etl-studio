import hashlib
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

_DB_PATH = Path(__file__).parent / "data" / "etl_studio.db"


def _get_conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                username      TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                salt          TEXT NOT NULL,
                display_name  TEXT NOT NULL,
                created_at    TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                username    TEXT NOT NULL,
                phase       TEXT NOT NULL DEFAULT 'upload',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                UNIQUE(name, username)
            )
        """)


def create_project(name: str, username: str) -> dict:
    project_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO projects (id, name, username, phase, created_at, updated_at) VALUES (?, ?, ?, 'upload', ?, ?)",
                (project_id, name, username, now, now),
            )
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            return dict(row)
    except sqlite3.IntegrityError:
        raise ValueError(f"Project '{name}' already exists for user '{username}'")


def list_projects(username: str) -> list[dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM projects WHERE username = ? ORDER BY updated_at DESC",
            (username,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_project(project_id: str) -> dict | None:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        return dict(row) if row else None


def update_project_phase(project_id: str, phase: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        conn.execute(
            "UPDATE projects SET phase = ?, updated_at = ? WHERE id = ?",
            (phase, now, project_id),
        )


def rename_project(project_id: str, new_name: str) -> None:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT username FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Project '{project_id}' not found")
        username = row["username"]
        now = datetime.now(timezone.utc).isoformat()
        try:
            conn.execute(
                "UPDATE projects SET name = ?, updated_at = ? WHERE id = ?",
                (new_name, now, project_id),
            )
        except sqlite3.IntegrityError:
            raise ValueError(
                f"Project '{new_name}' already exists for user '{username}'"
            )


def delete_project(project_id: str) -> None:
    with _get_conn() as conn:
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))


def check_username_exists(username: str) -> bool:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM projects WHERE username = ? LIMIT 1", (username,)
        ).fetchone()
        return row is not None


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), iterations=100_000
    ).hex()


def register_user(username: str, password: str, display_name: str) -> dict:
    salt = secrets.token_hex(16)
    password_hash = _hash_password(password, salt)
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, salt, display_name, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (username, password_hash, salt, display_name, now),
            )
            return {"username": username, "display_name": display_name}
    except sqlite3.IntegrityError:
        raise ValueError(f"Username '{username}' is already taken")


def login_user(username: str, password: str) -> dict:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
    if not row:
        raise ValueError("Invalid username or password")
    if _hash_password(password, row["salt"]) != row["password_hash"]:
        raise ValueError("Invalid username or password")
    return {"username": row["username"], "display_name": row["display_name"]}
