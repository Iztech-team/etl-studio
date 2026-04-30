import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from definitions import (
    CHECK_PIPELINE_RUN_EXISTS,
    CREATE_AUDIT_EVENTS_TABLE,
    CREATE_ERPNEXT_CREDS_TABLE,
    CREATE_INDEX_AUDIT_EVENTS_PROJECT,
    CREATE_INDEX_AUDIT_EVENTS_RUN,
    CREATE_INDEX_PIPELINE_RUNS_PROJECT,
    CREATE_PIPELINE_RUNS_TABLE,
    CREATE_PROJECTS_TABLE,
    DELETE_PROJECT,
    FINISH_PIPELINE_RUN,
    GET_DASHBOARD_STATS,
    GET_ERPNEXT_CREDS,
    GET_PIPELINE_RUN,
    GET_PROJECT,
    GET_PROJECT_USERNAME,
    INSERT_AUDIT_EVENT,
    INSERT_AUDIT_EVENT_BATCH,
    INSERT_BACKFILLED_EXTRACT_RUN,
    INSERT_BACKFILLED_LOAD_RUN,
    INSERT_BACKFILLED_TRANSFORM_RUN,
    INSERT_PIPELINE_RUN,
    INSERT_PROJECT,
    LIST_AUDIT_EVENTS,
    LIST_PIPELINE_RUNS,
    LIST_PROJECTS_BY_USER,
    LIST_PROJECTS_FOR_BACKFILL,
    PRAGMA_FOREIGN_KEYS_ON,
    PRAGMA_JOURNAL_MODE_WAL,
    RENAME_PROJECT,
    UPDATE_PROJECT_PHASE,
    UPSERT_ERPNEXT_CREDS,
)

_DB_PATH = Path(__file__).parent.parent / "data" / "etl_studio.db"


def _get_conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(PRAGMA_JOURNAL_MODE_WAL)
    conn.execute(PRAGMA_FOREIGN_KEYS_ON)
    return conn


def init_db() -> None:
    with _get_conn() as conn:
        conn.execute(CREATE_PROJECTS_TABLE)
        conn.execute(CREATE_PIPELINE_RUNS_TABLE)
        conn.execute(CREATE_AUDIT_EVENTS_TABLE)
        conn.execute(CREATE_ERPNEXT_CREDS_TABLE)
        conn.execute(CREATE_INDEX_PIPELINE_RUNS_PROJECT)
        conn.execute(CREATE_INDEX_AUDIT_EVENTS_PROJECT)
        conn.execute(CREATE_INDEX_AUDIT_EVENTS_RUN)


def save_erpnext_credentials(
    project_id: str, url: str, api_key: str, api_secret: str, company: str | None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        conn.execute(UPSERT_ERPNEXT_CREDS, (project_id, url, api_key, api_secret, company, now))


def get_erpnext_credentials(project_id: str) -> dict | None:
    with _get_conn() as conn:
        row = conn.execute(GET_ERPNEXT_CREDS, (project_id,)).fetchone()
        return dict(row) if row else None


def backfill_pipeline_runs() -> int:
    """One-time migration: scan project state files and insert historical pipeline_runs."""
    import json

    data_dir = Path(__file__).parent.parent / "data" / "projects"
    if not data_dir.exists():
        return 0

    PHASE_ORDER = ["upload", "edit", "configure", "transform", "load", "stats"]
    backfilled = 0

    with _get_conn() as conn:
        projects = conn.execute(LIST_PROJECTS_FOR_BACKFILL).fetchall()
        for p in projects:
            pid = p["id"]
            if conn.execute(CHECK_PIPELINE_RUN_EXISTS, (pid,)).fetchone():
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

            if phase_idx >= 1:
                conn.execute(
                    INSERT_BACKFILLED_EXTRACT_RUN,
                    (str(uuid.uuid4()), pid, 0, "backfilled from state", created, created),
                )
                backfilled += 1

            if phase_idx >= 3:
                transformed = state.get("transformed") if isinstance(state.get("transformed"), dict) else {}
                total_rows = transformed.get("total_rows", 0) if transformed else 0
                note_parts = []
                if transformed.get("encoding_conversions"):
                    note_parts.append(f"{transformed['encoding_conversions']} enc fixes")
                if transformed.get("type_conversions"):
                    note_parts.append(f"{transformed['type_conversions']} type conv")
                conn.execute(
                    INSERT_BACKFILLED_TRANSFORM_RUN,
                    (str(uuid.uuid4()), pid, total_rows,
                     ", ".join(note_parts) or "backfilled", updated, updated),
                )
                backfilled += 1

            if phase_idx >= 4:
                load_result = state.get("load_result") if isinstance(state.get("load_result"), dict) else {}
                rows_written = 0
                if load_result and isinstance(load_result.get("rows_written"), dict):
                    rows_written = sum(load_result["rows_written"].values())
                errors = load_result.get("errors", []) if load_result else []
                status = "error" if errors else "done"
                note = "; ".join(errors[:2]) if errors else "backfilled"
                conn.execute(
                    INSERT_BACKFILLED_LOAD_RUN,
                    (str(uuid.uuid4()), pid, status, rows_written, note, updated, updated),
                )
                backfilled += 1

    return backfilled


def create_project(name: str, username: str) -> dict:
    project_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _get_conn() as conn:
            conn.execute(INSERT_PROJECT, (project_id, name, username, now, now))
            return dict(conn.execute(GET_PROJECT, (project_id,)).fetchone())
    except sqlite3.IntegrityError:
        raise ValueError(f"Project '{name}' already exists for user '{username}'")


def list_projects(username: str) -> list[dict]:
    with _get_conn() as conn:
        return [dict(r) for r in conn.execute(LIST_PROJECTS_BY_USER, (username,)).fetchall()]


def get_project(project_id: str) -> dict | None:
    with _get_conn() as conn:
        row = conn.execute(GET_PROJECT, (project_id,)).fetchone()
        return dict(row) if row else None


def update_project_phase(project_id: str, phase: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        conn.execute(UPDATE_PROJECT_PHASE, (phase, now, project_id))


def rename_project(project_id: str, new_name: str) -> None:
    with _get_conn() as conn:
        row = conn.execute(GET_PROJECT_USERNAME, (project_id,)).fetchone()
        if row is None:
            raise ValueError(f"Project '{project_id}' not found")
        username = row["username"]
        now = datetime.now(timezone.utc).isoformat()
        try:
            conn.execute(RENAME_PROJECT, (new_name, now, project_id))
        except sqlite3.IntegrityError:
            raise ValueError(
                f"Project '{new_name}' already exists for user '{username}'"
            )


def delete_project(project_id: str) -> None:
    with _get_conn() as conn:
        conn.execute(DELETE_PROJECT, (project_id,))


def create_pipeline_run(project_id: str, phase: str) -> dict:
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        conn.execute(INSERT_PIPELINE_RUN, (run_id, project_id, phase, now))
        return dict(conn.execute(GET_PIPELINE_RUN, (run_id,)).fetchone())


def finish_pipeline_run(
    run_id: str, status: str = "done", rows_affected: int = 0, note: str = "",
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        conn.execute(FINISH_PIPELINE_RUN, (status, rows_affected, note, now, run_id))


def list_pipeline_runs(project_id: str) -> list[dict]:
    with _get_conn() as conn:
        return [dict(r) for r in conn.execute(LIST_PIPELINE_RUNS, (project_id,)).fetchall()]


def get_dashboard_stats(username: str) -> dict:
    with _get_conn() as conn:
        return dict(conn.execute(GET_DASHBOARD_STATS, (username,)).fetchone())


def insert_audit_event(
    project_id: str, event_type: str,
    table_name: str | None = None, column_name: str | None = None,
    detail: str = "", run_id: str | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        conn.execute(
            INSERT_AUDIT_EVENT,
            (project_id, run_id, event_type, table_name, column_name, detail, now),
        )


def insert_audit_events_batch(events: list[dict]) -> None:
    if not events:
        return
    with _get_conn() as conn:
        conn.executemany(INSERT_AUDIT_EVENT_BATCH, events)


def list_audit_events(project_id: str, limit: int = 200) -> list[dict]:
    with _get_conn() as conn:
        return [dict(r) for r in conn.execute(LIST_AUDIT_EVENTS, (project_id, limit)).fetchall()]
