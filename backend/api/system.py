from fastapi import APIRouter, HTTPException

from helpers import (
    ADMIN_DISPLAY_NAME,
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    _visible_session,
)
from models.project_schemas import AuthResponse, LoginRequest
from persistence.db import (
    get_dashboard_stats as db_get_dashboard_stats,
    get_history as db_get_history,
    list_projects,
)
from state import session_store

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/dashboard-stats")
async def dashboard_stats(username: str):
    """Aggregate stats across all projects for a user.

    Only inspects in-memory cached sessions to avoid blocking the event
    loop on a per-request disk scan. Quality scores become visible after
    a project has been opened at least once.
    """
    db_stats = db_get_dashboard_stats(username)
    total_rows = db_stats.get("total_rows_migrated", 0)

    projects = list_projects(username)
    project_ids = {p["id"] for p in projects}
    quality_scores: list[float] = []
    for sess in (await session_store.all_sessions()).values():
        pid = sess.get("project_id")
        if not pid or pid not in project_ids:
            continue
        if not sess.get("raw", {}).get("tables"):
            continue
        from utils.stats import StatsEngine

        try:
            engine = StatsEngine(_visible_session(sess))
            stats = engine.compute()
            quality_scores.append(stats["quality_score"])
        except Exception:
            pass
    avg_quality = (
        round(sum(quality_scores) / len(quality_scores), 1) if quality_scores else 0
    )
    return {
        "total_rows_migrated": total_rows,
        "avg_quality_score": avg_quality,
        "projects_with_data": db_stats.get("projects_with_data", 0),
    }


@router.get("/history")
async def history_endpoint(username: str):
    from datetime import datetime as _dt

    runs = db_get_history(username)
    rows = []
    for r in runs:
        try:
            dt = _dt.fromisoformat(r["started_at"])
            time_str = dt.strftime("%H:%M")
            date_str = dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            time_str = "—"
            date_str = "—"
        rows.append(
            {
                "t": time_str,
                "d": date_str,
                "project": r["project_name"],
                "stage": r["phase"].upper(),
                "status": r["status"],
                "rows": r["rows_affected"],
                "note": r["note"],
            }
        )
    return {"history": rows}


@router.post("/auth/login", response_model=AuthResponse)
async def login_endpoint(body: LoginRequest):
    if (
        body.username.strip().lower() == ADMIN_USERNAME
        and body.password == ADMIN_PASSWORD
    ):
        return AuthResponse(username=ADMIN_USERNAME, display_name=ADMIN_DISPLAY_NAME)
    raise HTTPException(401, "Invalid username or password")
