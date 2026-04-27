"""Shared private helpers used by route modules.

These started life inside main.py; extracted so api/* router files can
import them without circular dependencies.
"""

from datetime import timezone
from typing import Any, Dict, List, Optional

from persistence.db import insert_audit_events_batch, update_project_phase
from persistence.project_state import save_state
from state import session_store


def _excluded_set(session: dict) -> set:
    return set(session.get("excluded_tables") or [])


def _visible_tables(session: dict) -> List[str]:
    raw = session.get("raw", {})
    excluded = _excluded_set(session)
    return [t for t in raw.get("tables", {}).keys() if t not in excluded]


def _visible_raw(session: dict) -> dict:
    """Filtered view of session['raw'] containing only included tables.

    Returns a fresh outer dict so callers can mutate it freely. Inner row
    lists are NOT deep-copied; downstream code (Transformer) deep-copies
    as needed.
    """
    raw = session.get("raw", {})
    excluded = _excluded_set(session)
    if not excluded:
        return raw
    keep = [t for t in raw.get("tables", {}).keys() if t not in excluded]
    keep_set = set(keep)
    return {
        "tables": {t: raw["tables"][t] for t in keep if t in raw.get("tables", {})},
        "schema": {t: v for t, v in raw.get("schema", {}).items() if t in keep_set},
        "stats": {t: v for t, v in raw.get("stats", {}).items() if t in keep_set},
        "preview": {t: v for t, v in raw.get("preview", {}).items() if t in keep_set},
    }


def _visible_session(session: dict) -> dict:
    s = dict(session)
    s["raw"] = _visible_raw(session)
    return s


async def _auto_save(session_id: str, phase: str) -> None:
    """If the session is linked to a project, persist state and update phase."""
    s = await session_store.get(session_id)
    if not s or not s.get("project_id"):
        return
    project_id = s["project_id"]
    s["phase"] = phase
    save_state(project_id, s)
    update_project_phase(project_id, phase)


def _flush_audit_events(
    project_id: str, audit_trail, run_id: Optional[str] = None
) -> None:
    """Write in-memory audit trail events to the database and clear them."""
    if not audit_trail or not audit_trail.events:
        return
    from datetime import datetime as _dt

    now = _dt.now(timezone.utc).isoformat()
    batch = [
        {
            "project_id": project_id,
            "run_id": run_id,
            "event_type": ev.get("type", "unknown"),
            "table_name": ev.get("table"),
            "column_name": ev.get("column"),
            "detail": ev.get("description", ""),
            "created_at": ev.get("timestamp", now),
        }
        for ev in audit_trail.events
    ]
    insert_audit_events_batch(batch)
    audit_trail.events.clear()


def _resume_payload(project: dict, session_id: str, session: dict) -> dict:
    raw = session.get("raw", {})
    # Strip transformed.tables — it's gigabytes for real projects and would
    # block the asyncio loop during encode. Keep counts/warnings/preview only.
    transformed = session.get("transformed")
    transform_summary = None
    if isinstance(transformed, dict):
        transform_summary = {
            k: v for k, v in transformed.items() if k not in ("tables", "exceptions")
        }
    return {
        "session_id": session_id,
        "project": project,
        "phase": project["phase"],
        "files": session.get("files", []),
        "preview": raw.get("preview", {}),
        "inferred_schema": raw.get("schema", {}),
        "stats": raw.get("stats", {}),
        "config": session.get("config"),
        "transform": transform_summary,
        "load_result": session.get("load_result"),
        "excluded_tables": list(_excluded_set(session)),
        "all_extracted_tables": list(raw.get("tables", {}).keys()),
    }


# Auth constants (small enough to live alongside helpers).
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"
ADMIN_DISPLAY_NAME = "Admin"
