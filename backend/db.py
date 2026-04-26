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
            CREATE TABLE IF NOT EXISTS projects (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                username    TEXT NOT NULL DEFAULT 'admin',
                phase       TEXT NOT NULL DEFAULT 'upload',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                UNIQUE(name, username)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id          TEXT PRIMARY KEY,
                project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                phase       TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'running',
                rows_affected INTEGER NOT NULL DEFAULT 0,
                note        TEXT NOT NULL DEFAULT '',
                started_at  TEXT NOT NULL,
                finished_at TEXT,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id  TEXT NOT NULL,
                run_id      TEXT,
                event_type  TEXT NOT NULL,
                table_name  TEXT,
                column_name TEXT,
                detail      TEXT NOT NULL DEFAULT '',
                created_at  TEXT NOT NULL,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (run_id) REFERENCES pipeline_runs(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_pipeline_runs_project
            ON pipeline_runs(project_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_events_project
            ON audit_events(project_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_events_run
            ON audit_events(run_id)
        """)


def init_templates_table() -> None:
    """Initialize ddl_templates table if it doesn't exist."""
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ddl_templates (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                ddl_content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                created_by TEXT,
                UNIQUE(project_id, name)
            )
        """)


def backfill_pipeline_runs() -> int:
    """One-time migration: scan existing project states and insert historical pipeline_runs."""
    import json
    import os

    data_dir = Path(__file__).parent / "data" / "projects"
    if not data_dir.exists():
        return 0

    PHASE_ORDER = ["upload", "edit", "configure", "transform", "load", "stats"]
    backfilled = 0

    with _get_conn() as conn:
        projects = conn.execute(
            "SELECT id, phase, created_at, updated_at FROM projects"
        ).fetchall()
        for p in projects:
            pid = p["id"]
            # Skip if this project already has runs
            existing = conn.execute(
                "SELECT 1 FROM pipeline_runs WHERE project_id = ? LIMIT 1", (pid,)
            ).fetchone()
            if existing:
                continue

            state_file = data_dir / pid / "state.json"
            if not state_file.exists():
                continue

            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    state = json.load(f)
            except Exception:
                continue

            phase = state.get("phase", p["phase"])
            phase_idx = PHASE_ORDER.index(phase) if phase in PHASE_ORDER else 0
            created = p["created_at"]
            updated = p["updated_at"]

            # Extract run (if past upload)
            if phase_idx >= 1:
                run_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO pipeline_runs (id, project_id, phase, status, rows_affected, note, started_at, finished_at) VALUES (?, ?, 'extract', 'done', ?, ?, ?, ?)",
                    (run_id, pid, 0, "backfilled from state", created, created),
                )
                backfilled += 1

            # Transform run (if past configure)
            if phase_idx >= 3:
                run_id = str(uuid.uuid4())
                transformed = (
                    state.get("transformed")
                    if isinstance(state.get("transformed"), dict)
                    else {}
                )
                total_rows = transformed.get("total_rows", 0) if transformed else 0
                note_parts = []
                if transformed.get("encoding_conversions"):
                    note_parts.append(
                        f"{transformed['encoding_conversions']} enc fixes"
                    )
                if transformed.get("type_conversions"):
                    note_parts.append(f"{transformed['type_conversions']} type conv")
                conn.execute(
                    "INSERT INTO pipeline_runs (id, project_id, phase, status, rows_affected, note, started_at, finished_at) VALUES (?, ?, 'transform', 'done', ?, ?, ?, ?)",
                    (
                        run_id,
                        pid,
                        total_rows,
                        ", ".join(note_parts) or "backfilled",
                        updated,
                        updated,
                    ),
                )
                backfilled += 1

            # Load run (if past load)
            if phase_idx >= 4:
                run_id = str(uuid.uuid4())
                load_result = (
                    state.get("load_result")
                    if isinstance(state.get("load_result"), dict)
                    else {}
                )
                rows_written = 0
                if load_result and isinstance(load_result.get("rows_written"), dict):
                    rows_written = sum(load_result["rows_written"].values())
                errors = load_result.get("errors", []) if load_result else []
                status = "error" if errors else "done"
                note = "; ".join(errors[:2]) if errors else "backfilled"
                conn.execute(
                    "INSERT INTO pipeline_runs (id, project_id, phase, status, rows_affected, note, started_at, finished_at) VALUES (?, ?, 'load', ?, ?, ?, ?, ?)",
                    (run_id, pid, status, rows_written, note, updated, updated),
                )
                backfilled += 1

    return backfilled


# ── projects ──────────────────────────────────────────────


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


# ── pipeline runs ─────────────────────────────────────────


def create_pipeline_run(project_id: str, phase: str) -> dict:
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO pipeline_runs (id, project_id, phase, status, started_at) VALUES (?, ?, ?, 'running', ?)",
            (run_id, project_id, phase, now),
        )
        row = conn.execute(
            "SELECT * FROM pipeline_runs WHERE id = ?", (run_id,)
        ).fetchone()
        return dict(row)


def finish_pipeline_run(
    run_id: str,
    status: str = "done",
    rows_affected: int = 0,
    note: str = "",
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        conn.execute(
            "UPDATE pipeline_runs SET status = ?, rows_affected = ?, note = ?, finished_at = ? WHERE id = ?",
            (status, rows_affected, note, now, run_id),
        )


def list_pipeline_runs(project_id: str) -> list[dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM pipeline_runs WHERE project_id = ? ORDER BY started_at DESC",
            (project_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_history(username: str) -> list[dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT r.*, p.name AS project_name
            FROM pipeline_runs r
            JOIN projects p ON p.id = r.project_id
            WHERE p.username = ?
            ORDER BY r.started_at DESC
            """,
            (username,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_dashboard_stats(username: str) -> dict:
    with _get_conn() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(DISTINCT r.project_id) AS projects_with_data,
                COALESCE(SUM(r.rows_affected), 0) AS total_rows_migrated
            FROM pipeline_runs r
            JOIN projects p ON p.id = r.project_id
            WHERE p.username = ?
              AND r.phase = 'load'
              AND r.status = 'done'
            """,
            (username,),
        ).fetchone()
        return dict(row)


# ── audit events ──────────────────────────────────────────


def insert_audit_event(
    project_id: str,
    event_type: str,
    table_name: str | None = None,
    column_name: str | None = None,
    detail: str = "",
    run_id: str | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO audit_events (project_id, run_id, event_type, table_name, column_name, detail, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project_id, run_id, event_type, table_name, column_name, detail, now),
        )


def insert_audit_events_batch(events: list[dict]) -> None:
    if not events:
        return
    with _get_conn() as conn:
        conn.executemany(
            "INSERT INTO audit_events (project_id, run_id, event_type, table_name, column_name, detail, created_at) VALUES (:project_id, :run_id, :event_type, :table_name, :column_name, :detail, :created_at)",
            events,
        )


def list_audit_events(project_id: str, limit: int = 200) -> list[dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_events WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
            (project_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]
