import asyncio
import json
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
import os, shutil, uuid
from datetime import timezone, datetime
from typing import List, Optional

from core.extractor import Extractor
from core.transformer import Transformer
from core.loader import Loader
from utils.audit import AuditTrail
from models.schemas import (
    ConfigureRequest,
    ConfigureResponse,
    TransformResponse,
    LoadRequest,
    LoadResponse,
    StatsResponse,
    DDLUploadResponse,
    ApplyDDLRequest,
    ApplyDDLResponse,
    ApplyDDLTableResult,
    PreExtractResponse,
    PreExtractFileInfo,
    DB_TYPE_EXTENSIONS,
    EditDataRequest,
    EditDataResponse,
    CreateTemplateRequest,
    UpdateTemplateRequest,
    DDLTemplate,
    TemplateListResponse,
)
from db import (
    init_db,
    init_templates_table,
    create_project,
    list_projects,
    get_project,
    rename_project,
    delete_project,
    update_project_phase,
    create_pipeline_run,
    finish_pipeline_run,
    get_history as db_get_history,
    get_dashboard_stats as db_get_dashboard_stats,
    insert_audit_events_batch,
    backfill_pipeline_runs,
    _get_conn,
)
from project_state import (
    save_state,
    load_state,
    ensure_project_dirs,
    project_uploads_dir,
    project_outputs_dir,
    delete_project_files,
)
from models.project_schemas import (
    LoginRequest,
    AuthResponse,
    CreateProjectRequest,
    RenameProjectRequest,
    ProjectResponse,
    ProjectListResponse,
)

app = FastAPI(title="ETL Legacy", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "uploads"
OUTPUT_DIR = "outputs"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

GUEST_DIR = os.path.join(os.path.dirname(__file__), "data", "guest")
os.makedirs(GUEST_DIR, exist_ok=True)
init_db()
init_templates_table()
backfill_pipeline_runs()

# In-memory session store (keyed by session_id)
sessions: dict = {}


def _excluded_set(session: dict) -> set:
    """Excluded tables for a session, as a set. Stored as a list internally
    so it can round-trip through JSON state files."""
    return set(session.get("excluded_tables") or [])


def _visible_tables(session: dict) -> list[str]:
    """Names of tables not currently excluded, preserving raw order."""
    raw = session.get("raw", {})
    excluded = _excluded_set(session)
    return [t for t in raw.get("tables", {}).keys() if t not in excluded]


def _visible_raw(session: dict) -> dict:
    """A filtered view of session['raw'] containing only included tables.

    Returns a fresh dict — callers can mutate the outer container freely
    without affecting the underlying session. Inner row lists are NOT
    deep-copied; downstream code (Transformer) deep-copies as needed.
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
        "ddl_schema": raw.get("ddl_schema", {}),
    }


def _visible_session(session: dict) -> dict:
    """Shallow-copy of the session with raw replaced by its visible view."""
    s = dict(session)
    s["raw"] = _visible_raw(session)
    return s


def _auto_save(session_id: str, phase: str) -> None:
    """If the session is linked to a project, persist state and update phase."""
    s = sessions.get(session_id)
    if not s or not s.get("project_id"):
        return
    project_id = s["project_id"]
    s["phase"] = phase
    save_state(project_id, s)
    update_project_phase(project_id, phase)


def _flush_audit_events(
    project_id: str, audit_trail, run_id: str | None = None
) -> None:
    """Write in-memory audit trail events to the database and clear them."""
    if not audit_trail or not audit_trail.events:
        return
    from datetime import datetime as _dt

    now = _dt.now(timezone.utc).isoformat()
    batch = []
    for ev in audit_trail.events:
        batch.append(
            {
                "project_id": project_id,
                "run_id": run_id,
                "event_type": ev.get("type", "unknown"),
                "table_name": ev.get("table"),
                "column_name": ev.get("column"),
                "detail": ev.get("description", ""),
                "created_at": ev.get("timestamp", now),
            }
        )
    insert_audit_events_batch(batch)
    audit_trail.events.clear()


# ---------------------------------------------------------------------------
# Template CRUD helpers
# ---------------------------------------------------------------------------


def save_template(
    project_id: str, name: str, ddl_content: str, created_by: Optional[str] = None
) -> str:
    """Save a new DDL template. Returns template ID."""
    template_id = str(uuid.uuid4())
    created_at = datetime.utcnow().isoformat()

    try:
        with _get_conn() as conn:
            conn.execute(
                """
                INSERT INTO ddl_templates (id, project_id, name, ddl_content, created_at, created_by)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (template_id, project_id, name, ddl_content, created_at, created_by),
            )
            conn.commit()
        return template_id
    except Exception as e:
        raise ValueError(f"Failed to save template: {str(e)}")


def list_templates(project_id: str) -> List[dict]:
    """List all templates for a project."""
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, project_id, name, ddl_content, created_at, created_by
            FROM ddl_templates
            WHERE project_id = ?
            ORDER BY created_at DESC
        """,
            (project_id,),
        ).fetchall()

        templates = []
        for row in rows:
            templates.append(
                {
                    "id": row[0],
                    "project_id": row[1],
                    "name": row[2],
                    "ddl_content": row[3],
                    "created_at": row[4],
                    "created_by": row[5],
                }
            )
        return templates


def get_template(template_id: str) -> dict:
    """Get a template by ID."""
    with _get_conn() as conn:
        row = conn.execute(
            """
            SELECT id, project_id, name, ddl_content, created_at, created_by
            FROM ddl_templates
            WHERE id = ?
        """,
            (template_id,),
        ).fetchone()

        if not row:
            raise ValueError("Template not found")

        return {
            "id": row[0],
            "project_id": row[1],
            "name": row[2],
            "ddl_content": row[3],
            "created_at": row[4],
            "created_by": row[5],
        }


def delete_template(template_id: str) -> bool:
    """Delete a template by ID."""
    with _get_conn() as conn:
        conn.execute("DELETE FROM ddl_templates WHERE id = ?", (template_id,))
        conn.commit()
    return True


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/dashboard-stats")
async def dashboard_stats(username: str):
    """Aggregate stats across all projects for a user.

    Only inspects projects already cached in memory. Loading state from
    disk for every project on every dashboard hit was blocking the event
    loop for ~100s with the AlArabi 257-table dataset, which froze the
    projects list and made open-project clicks appear to do nothing.
    Quality for a project becomes visible after it's been opened once
    (which populates the in-memory session cache).
    """
    db_stats = db_get_dashboard_stats(username)
    total_rows = db_stats.get("total_rows_migrated", 0)

    projects = list_projects(username)
    project_ids = {p["id"] for p in projects}
    quality_scores: list[float] = []
    for sess in sessions.values():
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


@app.get("/api/history")
async def history_endpoint(username: str):
    """Return pipeline run history from the database."""
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


ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"
ADMIN_DISPLAY_NAME = "Admin"


@app.post("/api/auth/login", response_model=AuthResponse)
async def login_endpoint(body: LoginRequest):
    if (
        body.username.strip().lower() == ADMIN_USERNAME
        and body.password == ADMIN_PASSWORD
    ):
        return AuthResponse(username=ADMIN_USERNAME, display_name=ADMIN_DISPLAY_NAME)
    raise HTTPException(401, "Invalid username or password")


@app.post("/api/projects", response_model=ProjectResponse)
async def create_project_endpoint(body: CreateProjectRequest):
    try:
        project = create_project(body.name, body.username)
    except ValueError as e:
        raise HTTPException(409, str(e))
    ensure_project_dirs(project["id"])
    return ProjectResponse(**project)


@app.get("/api/projects", response_model=ProjectListResponse)
async def list_projects_endpoint(username: str):
    projects = list_projects(username)
    return ProjectListResponse(projects=[ProjectResponse(**p) for p in projects])


@app.get("/api/projects/{project_id}", response_model=ProjectResponse)
async def get_project_endpoint(project_id: str):
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return ProjectResponse(**project)


@app.patch("/api/projects/{project_id}", response_model=ProjectResponse)
async def rename_project_endpoint(project_id: str, body: RenameProjectRequest):
    try:
        rename_project(project_id, body.name)
    except ValueError as e:
        raise HTTPException(409, str(e))
    project = get_project(project_id)
    return ProjectResponse(**project)


@app.delete("/api/projects/{project_id}")
async def delete_project_endpoint(project_id: str):
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    to_remove = [
        sid for sid, s in sessions.items() if s.get("project_id") == project_id
    ]
    for sid in to_remove:
        del sessions[sid]
    delete_project_files(project_id)
    delete_project(project_id)
    return {"ok": True}


def _resume_payload(project: dict, session_id: str, session: dict) -> dict:
    raw = session.get("raw", {})
    return {
        "session_id": session_id,
        "project": project,
        "phase": project["phase"],
        "files": session.get("files", []),
        "preview": raw.get("preview", {}),
        "inferred_schema": raw.get("schema", {}),
        "stats": raw.get("stats", {}),
        "ddl_schema": session.get("ddl_schema", {}),
        "config": session.get("config"),
        "transform": session.get("transformed"),
        "load_result": session.get("load_result"),
        "excluded_tables": list(_excluded_set(session)),
        "all_extracted_tables": list(raw.get("tables", {}).keys()),
    }


@app.post("/api/projects/{project_id}/resume")
async def resume_project(project_id: str):
    """Streaming NDJSON: emits per-table progress as CSVs are parsed.

    Events:
      {"event": "start", "project": {...}, "tables": [name, ...], "total": N}
      {"event": "table_done", "name": "T", "rowCount": 1234, "columns": [...]}
      ...
      {"event": "done", ...resume payload}
      OR {"event": "error", "message": "..."}

    The warm path (in-memory cache hit) emits all events at once so the
    client UI tick-tocks the same way regardless of cold/warm.
    """
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    from project_state import load_state_iter

    def encode(obj: dict) -> bytes:
        return (json.dumps(obj, ensure_ascii=False, default=str) + "\n").encode("utf-8")

    async def stream():
        try:
            # Warm path: a session for this project already lives in memory.
            for sid, sess in sessions.items():
                if sess.get("project_id") == project_id and sess.get("raw"):
                    tables = sess["raw"].get("tables", {})
                    table_names = list(tables.keys())
                    yield encode(
                        {
                            "event": "start",
                            "project": project,
                            "tables": table_names,
                            "total": len(table_names),
                            "warm": True,
                        }
                    )
                    for name in table_names:
                        rows = tables.get(name, [])
                        yield encode(
                            {
                                "event": "table_done",
                                "name": name,
                                "rowCount": len(rows),
                                "columns": list(rows[0].keys()) if rows else [],
                            }
                        )
                    yield encode(
                        {"event": "done", **_resume_payload(project, sid, sess)}
                    )
                    return

            # Cold path: drive load_state_iter on a worker thread and
            # forward events as they arrive. The sentinel pattern keeps
            # StopIteration from leaking through asyncio.to_thread.
            session_id = str(uuid.uuid4())
            session: dict = {}

            SENTINEL = object()
            it = load_state_iter(project_id)

            def safe_next():
                try:
                    return next(it)
                except StopIteration:
                    return SENTINEL

            yield encode(
                {"event": "start", "project": project, "tables": [], "total": 0}
            )

            # Note: we may emit a second 'start' from the iterator below
            # (with the actual table list once listdir runs). The frontend
            # treats 'start' as updating its known total, so that's fine.
            while True:
                event = await asyncio.to_thread(safe_next)
                if event is SENTINEL:
                    break
                event_type, payload = event
                if event_type == "done":
                    session = payload
                    continue
                yield encode({"event": event_type, **payload})

            session["project_id"] = project_id
            sessions[session_id] = session
            yield encode(
                {"event": "done", **_resume_payload(project, session_id, session)}
            )
        except Exception as e:
            yield encode({"event": "error", "message": f"Failed to resume: {e}"})

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.post("/api/projects/{project_id}/save")
async def save_project(project_id: str):
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    session = None
    for s in sessions.values():
        if s.get("project_id") == project_id:
            session = s
            break
    if not session:
        raise HTTPException(400, "No active session for this project")
    save_state(project_id, session)
    return {"ok": True}


def _detect_db_type(filename: str) -> str | None:
    ext = os.path.splitext(filename)[1].lower()
    for db_type, extensions in DB_TYPE_EXTENSIONS.items():
        if ext in extensions:
            return db_type
    return None


def _is_db_file(filename: str) -> bool:
    return _detect_db_type(filename) is not None


# ---------------------------------------------------------------------------
# DB upload + extraction (two-phase, with replayable progress stream)
#
# Flow:
#   POST /api/upload-db                  -> uploads file, returns session_id
#   POST /api/extract/{session_id}       -> kicks off extraction in background
#   GET  /api/extract/{session_id}/status -> snapshot (status, progress, result)
#   GET  /api/extract/{session_id}/stream -> NDJSON stream with full replay,
#                                            ends when extraction is done/error
#
# Extraction runs as an asyncio task and pushes events into extraction_states.
# Multiple clients can connect to the stream — each gets the full event log
# from index 0, then live updates until the terminal event. That's how the
# user can navigate away and reconnect without losing progress.
# ---------------------------------------------------------------------------

extraction_states: dict[str, dict] = {}


def _new_extraction_state() -> dict:
    return {
        "status": "pending",  # pending | extracting | done | error | cancelled
        "events": [],  # list of dicts (one per yielded event)
        "result": None,  # final PreExtractResponse-shaped dict
        "error": None,
        "started_at": None,
        "finished_at": None,
        "filename": None,
        "project_id": None,
        "current_table": None,
        "tables_done": 0,
        "tables_total": 0,
    }


def _safe_next_factory(sentinel: object):
    """Wrap next() so StopIteration becomes a sentinel return value.

    asyncio cannot let StopIteration propagate out of a coroutine — it
    has special meaning to the event loop and gets converted into a
    RuntimeError ("StopIteration interacts badly with generators..."),
    so we catch it inside the worker thread and signal end-of-stream
    via a unique sentinel instead.
    """

    def safe_next(gen):
        try:
            return next(gen)
        except StopIteration:
            return sentinel

    return safe_next


@app.post("/api/upload-db")
async def upload_db(
    file: UploadFile = File(...),
    project_id: str | None = Form(None),
):
    """Upload a database file. Does NOT extract — call /api/extract next.

    Returns session_id, file metadata. The session is created in a
    'pending_db' state with the on-disk path.
    """
    db_type = _detect_db_type(file.filename or "")
    if not db_type:
        raise HTTPException(
            400,
            f"Unsupported database file type. Supported: "
            + ", ".join(ext for exts in DB_TYPE_EXTENSIONS.values() for ext in exts),
        )

    session_id = str(uuid.uuid4())
    if project_id:
        session_dir = project_uploads_dir(project_id)
    else:
        session_dir = os.path.join(GUEST_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)

    dest = os.path.join(session_dir, file.filename)
    with open(dest, "wb") as out:
        while chunk := await file.read(8 * 1024 * 1024):
            out.write(chunk)

    file_size = os.path.getsize(dest)
    file_info = PreExtractFileInfo(
        name=file.filename,
        path=dest,
        size=file_size,
        db_type=db_type,
    )

    sessions[session_id] = {
        "project_id": project_id,
        "pending_db": {
            "file_path": dest,
            "session_dir": session_dir,
            "filename": file.filename,
            "size": file_size,
            "db_type": db_type,
        },
    }
    state = _new_extraction_state()
    state["filename"] = file.filename
    state["project_id"] = project_id
    extraction_states[session_id] = state

    return {
        "ok": True,
        "session_id": session_id,
        "file": file_info.dict(),
    }


@app.post("/api/extract/{session_id}")
async def start_extract(
    session_id: str,
    password: str | None = Form(None),
):
    """Kick off extraction for a previously uploaded DB. Returns immediately.

    Idempotent if extraction is already in flight or done — returns the
    current status without restarting. If a previous attempt errored,
    calling again resets state and tries again.
    """
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")
    s = sessions[session_id]
    pending = s.get("pending_db")
    if not pending and "raw" not in s:
        raise HTTPException(400, "No database file pending extraction for this session")

    state = extraction_states.get(session_id)
    if state and state["status"] == "extracting":
        return {"ok": True, "status": "extracting", "session_id": session_id}
    if state and state["status"] == "done":
        return {"ok": True, "status": "done", "session_id": session_id}

    from datetime import datetime as _dt

    new_state = _new_extraction_state()
    new_state["status"] = "extracting"
    new_state["started_at"] = _dt.now(timezone.utc).isoformat()
    new_state["filename"] = (pending or {}).get("filename") or (state or {}).get(
        "filename"
    )
    new_state["project_id"] = s.get("project_id")
    extraction_states[session_id] = new_state

    asyncio.create_task(_run_extraction(session_id, password))
    return {"ok": True, "status": "extracting", "session_id": session_id}


@app.get("/api/extract/{session_id}/status")
async def extract_status(session_id: str):
    """Lightweight status snapshot (no event log)."""
    state = extraction_states.get(session_id)
    if not state:
        raise HTTPException(404, "No extraction state for this session")
    return {
        "session_id": session_id,
        "status": state["status"],
        "filename": state["filename"],
        "project_id": state["project_id"],
        "tables_done": state["tables_done"],
        "tables_total": state["tables_total"],
        "current_table": state["current_table"],
        "events_count": len(state["events"]),
        "error": state["error"],
        "started_at": state["started_at"],
        "finished_at": state["finished_at"],
        "result": state["result"],
    }


@app.get("/api/extract/{session_id}/stream")
async def stream_extract(session_id: str):
    """NDJSON stream with full replay. Ends on done/error event.

    The cursor starts at 0 — every connecting client sees the entire
    event history followed by live updates. Late joiners see the same
    sequence, including the terminal event.
    """
    if session_id not in extraction_states:
        raise HTTPException(404, "No extraction state for this session")

    async def gen():
        cursor = 0
        while True:
            state = extraction_states.get(session_id)
            if state is None:
                break
            new_events = state["events"][cursor:]
            for ev in new_events:
                yield (json.dumps(ev, ensure_ascii=False) + "\n").encode("utf-8")
            cursor = len(state["events"])
            if state["status"] in ("done", "error", "cancelled"):
                break
            await asyncio.sleep(0.15)

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.post("/api/extract/{session_id}/cancel")
async def cancel_extract(session_id: str):
    """Cancel an in-flight extraction.

    Marks state as cancelled so the worker stops at its next checkpoint
    and any active /stream readers terminate. Removes the uploaded DB
    file and tears down the session if no extracted data has landed yet.
    """
    from datetime import datetime as _dt

    state = extraction_states.get(session_id)
    if not state:
        raise HTTPException(404, "No extraction state for this session")

    if state["status"] in ("done", "error", "cancelled"):
        return {"ok": True, "status": state["status"], "session_id": session_id}

    state["status"] = "cancelled"
    state["events"].append({"event": "cancelled", "message": "Extraction cancelled"})
    state["finished_at"] = _dt.now(timezone.utc).isoformat()

    s = sessions.get(session_id)
    if s:
        pending = s.get("pending_db")
        if pending:
            try:
                if os.path.exists(pending["file_path"]):
                    os.remove(pending["file_path"])
            except OSError:
                pass
        # Drop the whole session if extraction never produced data; keep
        # it otherwise so any rows already in `raw` survive.
        if "raw" not in s:
            sessions.pop(session_id, None)

    return {"ok": True, "status": "cancelled", "session_id": session_id}


async def _run_extraction(session_id: str, password: str | None) -> None:
    """Background worker: drives the iter, writes events to state."""
    from datetime import datetime as _dt
    from core.db_extractor import extract_db_to_csvs_iter

    state = extraction_states[session_id]
    s = sessions[session_id]
    pending = s.get("pending_db")
    if not pending:
        state["status"] = "error"
        state["error"] = "No database file pending extraction"
        state["events"].append({"event": "error", "message": state["error"]})
        state["finished_at"] = _dt.now(timezone.utc).isoformat()
        return

    audit_trail = AuditTrail(source_type="db", source_name=pending["filename"])
    audit_trail.log_extraction_started(pending["db_type"], 0)

    SENTINEL = object()
    safe_next = _safe_next_factory(SENTINEL)

    try:
        gen = extract_db_to_csvs_iter(
            pending["file_path"],
            pending["db_type"],
            pending["session_dir"],
            password,
        )
        csv_files: List[str] = []

        while True:
            if state["status"] == "cancelled":
                return
            event = await asyncio.to_thread(safe_next, gen)
            if event is SENTINEL:
                break
            if state["status"] == "cancelled":
                return
            event_type, payload = event
            if event_type == "done":
                csv_files = payload.get("csv_files", [])
                continue
            ev = {"event": event_type, **payload}
            state["events"].append(ev)
            if event_type == "start":
                state["tables_total"] = len(payload.get("tables", []))
            elif event_type == "table_done":
                state["tables_done"] = payload.get("index", state["tables_done"])
                state["current_table"] = payload.get("name")

        if not csv_files:
            msg = "No tables found in the database file"
            state["status"] = "error"
            state["error"] = msg
            state["events"].append({"event": "error", "message": msg})
            state["finished_at"] = _dt.now(timezone.utc).isoformat()
            audit_trail.log_extraction_error(msg)
            return

        # Original DB file is no longer needed once CSVs are written.
        try:
            os.remove(pending["file_path"])
        except OSError:
            pass

        extractor = Extractor(pending["session_dir"], audit_trail)
        result = await asyncio.to_thread(extractor.extract_all)

        audit_trail.log_extraction_completed(
            list(result.get("tables", {}).keys()),
            sum(len(rows) for rows in result.get("tables", {}).values()),
        )

        saved_files = [
            {
                "name": f,
                "path": os.path.join(pending["session_dir"], f),
                "size": os.path.getsize(os.path.join(pending["session_dir"], f)),
            }
            for f in csv_files
        ]

        file_info = PreExtractFileInfo(
            name=pending["filename"],
            path=pending["file_path"],
            size=pending["size"],
            db_type=pending["db_type"],
        )

        sessions[session_id].update(
            {
                "pre_extract": {
                    "file": file_info.dict(),
                    "password": password is not None,
                    "db_type": pending["db_type"],
                },
                "extractor": extractor,
                "raw": result,
                "files": saved_files,
                "ddl_schema": result.get("ddl_schema", {}),
                "applied_ddl": [],
                "audit_trail": audit_trail,
            }
        )
        sessions[session_id].pop("pending_db", None)
        _auto_save(session_id, "pre-extract")

        done_payload = PreExtractResponse(
            ok=True,
            session_id=session_id,
            file=file_info,
            tables_extracted=list(result.get("tables", {}).keys()),
            csv_files=csv_files,
            preview=result.get("preview", {}),
            inferred_schema=result.get("schema", {}),
            stats=result.get("stats", {}),
            ddl_schema=result.get("ddl_schema", {}),
        ).dict()

        state["result"] = done_payload
        state["events"].append({"event": "done", **done_payload})
        state["status"] = "done"
        state["finished_at"] = _dt.now(timezone.utc).isoformat()
    except Exception as e:
        msg = f"Failed to extract database: {e}"
        state["status"] = "error"
        state["error"] = msg
        state["events"].append({"event": "error", "message": msg})
        state["finished_at"] = _dt.now(timezone.utc).isoformat()
        try:
            audit_trail.log_extraction_error(msg)
        except Exception:
            pass


@app.post("/api/pre-extract-select/{session_id}")
async def pre_extract_select(session_id: str, body: ApplyDDLRequest):
    """Soft-exclude tables in the session.

    Raw extracted data stays put (CSVs and in-memory rows) so the user
    can re-include any table later by revisiting the extract stage. Only
    the `excluded_tables` set is updated; downstream consumers filter
    through `_visible_*` helpers.

    If the selection differs from the previous one, transform/load
    artefacts are dropped (they're stale) and configure entries for
    newly-excluded tables are trimmed. Configure entries for tables that
    survived the change are kept intact.
    """
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")
    s = sessions[session_id]
    raw = s.get("raw", {})
    all_tables = set(raw.get("tables", {}).keys())
    selected = set(body.tables) & all_tables
    new_excluded = all_tables - selected
    prev_excluded = _excluded_set(s)

    changed = new_excluded != prev_excluded
    s["excluded_tables"] = sorted(new_excluded)

    if changed:
        s.pop("transformed", None)
        s.pop("transformer", None)
        s.pop("load_result", None)
        s.pop("fk_edges", None)

        # Trim configure entries for tables that just got excluded; keep
        # entries for tables that remain selected so the user doesn't lose
        # column mapping work they've already done.
        config = s.get("config")
        if isinstance(config, dict):
            for key in ("columns", "transforms", "table_renames", "table_excludes"):
                section = config.get(key)
                if isinstance(section, dict):
                    for table in list(section.keys()):
                        if table in new_excluded:
                            section.pop(table, None)

        # Drop applied_ddl entries for excluded tables; their schema in
        # raw stays untouched so re-including them later restores DDL state.
        applied = s.get("applied_ddl") or []
        s["applied_ddl"] = [t for t in applied if t not in new_excluded]

        audit_trail = s.get("audit_trail")
        if audit_trail:
            try:
                audit_trail.events.append(
                    {
                        "type": "tables_reselected",
                        "table": None,
                        "column": None,
                        "description": (
                            f"included={sorted(selected)}, excluded={sorted(new_excluded)}"
                        ),
                        "timestamp": __import__("datetime")
                        .datetime.now(timezone.utc)
                        .isoformat(),
                    }
                )
            except Exception:
                pass

    _auto_save(session_id, "edit")
    return {
        "ok": True,
        "changed": changed,
        "kept": sorted(selected),
        "excluded": sorted(new_excluded),
    }


@app.post("/api/upload")
async def upload_files(
    files: List[UploadFile] = File(...),
    project_id: str | None = Form(None),
    password: str | None = Form(None),
):
    session_id = str(uuid.uuid4())
    if project_id:
        session_dir = project_uploads_dir(project_id)
    else:
        session_dir = os.path.join(GUEST_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)

    # Create audit trail for this session
    audit_trail = AuditTrail(source_type="upload")

    saved = []
    db_file_info = None
    for f in files:
        dest = os.path.join(session_dir, f.filename)
        with open(dest, "wb") as out:
            shutil.copyfileobj(f.file, out)
        file_info = {"name": f.filename, "path": dest, "size": os.path.getsize(dest)}
        saved.append(file_info)
        if not db_file_info and _is_db_file(f.filename):
            db_file_info = file_info

    if db_file_info:
        from core.db_extractor import extract_db_to_csvs

        db_type = _detect_db_type(db_file_info["name"])
        if db_type is None:
            raise HTTPException(400, "Unsupported database file type")

        # Update audit trail for DB extraction
        audit_trail.source_type = "db"
        audit_trail.source_name = db_file_info["name"]
        audit_trail.log_extraction_started(db_type, 0)

        try:
            csv_files = extract_db_to_csvs(
                db_file_info["path"], db_type, session_dir, password
            )
        except ImportError as e:
            audit_trail.log_extraction_error(str(e))
            raise HTTPException(400, str(e))
        except Exception as e:
            audit_trail.log_extraction_error(str(e))
            raise HTTPException(400, f"Failed to extract database: {e}")

        if not csv_files:
            audit_trail.log_extraction_error("No tables found in the database file")
            raise HTTPException(400, "No tables found in the database file")

        os.remove(db_file_info["path"])
        saved = [s for s in saved if s["path"] != db_file_info["path"]]
        for csv_name in csv_files:
            csv_path = os.path.join(session_dir, csv_name)
            saved.append(
                {"name": csv_name, "path": csv_path, "size": os.path.getsize(csv_path)}
            )

    extractor = Extractor(session_dir, audit_trail)
    result = extractor.extract_all()

    # Complete extraction logging if it was a DB extraction
    if db_file_info:
        audit_trail.log_extraction_completed(
            list(result.get("tables", {}).keys()),
            sum(len(rows) for rows in result.get("tables", {}).values()),
        )
    sessions[session_id] = {
        "project_id": project_id,
        "extractor": extractor,
        "raw": result,
        "files": saved,
        "ddl_schema": result.get("ddl_schema", {}),
        "applied_ddl": [],
        "audit_trail": audit_trail,
    }

    _auto_save(session_id, "edit")

    # Record upload/extract as a pipeline run
    if project_id:
        total_rows = sum(len(rows) for rows in result.get("tables", {}).values())
        table_count = len(result.get("tables", {}))
        run = create_pipeline_run(project_id, "extract")
        finish_pipeline_run(
            run["id"], "done", total_rows, f"{table_count} tables extracted"
        )
        _flush_audit_events(project_id, audit_trail, run["id"])

    return {
        "session_id": session_id,
        "files": saved,
        "preview": result.get("preview", {}),
        "inferred_schema": result.get("schema", {}),
        "stats": result.get("stats", {}),
        "ddl_schema": result.get("ddl_schema", {}),
    }


@app.get("/api/table-data/{session_id}")
async def get_table_data(session_id: str):
    """Return all rows for all tables in the session."""
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")
    s = sessions[session_id]
    raw = _visible_raw(s)
    return {
        "tables": raw.get("tables", {}),
        "schema": raw.get("schema", {}),
    }


@app.get("/api/table-data/{session_id}/{table_name}")
async def get_table_page(
    session_id: str,
    table_name: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
):
    """Return a single page of rows for a specific table."""
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")
    s = sessions[session_id]
    if table_name in _excluded_set(s):
        raise HTTPException(404, f"Table '{table_name}' is excluded")
    raw = s.get("raw", {})
    all_tables = raw.get("tables", {})
    if table_name not in all_tables:
        raise HTTPException(404, f"Table '{table_name}' not found")
    rows = all_tables[table_name]
    total = len(rows)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "table": table_name,
        "rows": rows[start:end],
        "columns": list(rows[0].keys()) if rows else [],
        "page": page,
        "page_size": page_size,
        "total_rows": total,
        "total_pages": max(1, (total + page_size - 1) // page_size),
    }


@app.post("/api/table-data/{session_id}")
async def save_table_data(session_id: str, body: EditDataRequest):
    """Replace table rows with edited data and recompute schema/stats."""
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")
    s = sessions[session_id]
    raw = s.get("raw", {})

    # Replace rows for each table
    for table, rows in body.tables.items():
        if table not in raw.get("tables", {}):
            continue
        raw["tables"][table] = rows

    # Recompute stats
    stats = {}
    for table, rows in raw.get("tables", {}).items():
        stats[table] = {"row_count": len(rows)}
    raw["stats"] = stats

    # Recompute preview
    raw["preview"] = {t: rows[:5] for t, rows in raw.get("tables", {}).items()}

    # Re-run schema inference on the extractor
    extractor: Extractor = s["extractor"]
    extractor._raw_tables = raw["tables"]
    extractor._infer_schema()
    raw["schema"] = extractor._schema

    _auto_save(session_id, "edit")
    return {
        "ok": True,
        "stats": stats,
        "preview": raw["preview"],
        "schema": raw["schema"],
    }


@app.get("/api/session/{session_id}/config")
async def get_session_config(session_id: str):
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")
    return sessions[session_id].get("config", {})


@app.post("/api/configure/{session_id}", response_model=ConfigureResponse)
async def configure(
    session_id: str,
    body: ConfigureRequest,
    phase: str = Query("configure"),
):
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")
    sessions[session_id]["config"] = body.dict()
    _auto_save(session_id, phase)
    return ConfigureResponse(ok=True, message="Configuration saved")


@app.post("/api/upload-ddl/{session_id}", response_model=DDLUploadResponse)
async def upload_ddl(session_id: str, files: List[UploadFile] = File(...)):
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")

    from utils.sql_parser import SQLParser

    s = sessions[session_id]
    ddl_schema = s.get("ddl_schema", {})
    data_tables = set(s["raw"].get("tables", {}).keys())

    all_foreign_keys = s.get("ddl_foreign_keys", [])
    all_constraints = s.get("ddl_constraints_raw", {})

    for f in files:
        content = (await f.read()).decode("utf-8", errors="replace")
        parser = SQLParser(content)
        parsed = parser.parse_ddl()
        ddl_schema.update(parsed)
        # Collect FK relationships and constraints from DDL
        all_foreign_keys.extend(getattr(parser, "foreign_keys", []))
        all_constraints.update(getattr(parser, "constraints", {}))

    s["ddl_schema"] = ddl_schema
    s["ddl_foreign_keys"] = all_foreign_keys
    s["ddl_constraints_raw"] = all_constraints
    matching = [t for t in ddl_schema if t in data_tables]

    return DDLUploadResponse(
        ok=True,
        ddl_schema=ddl_schema,
        matching_tables=matching,
    )


@app.post("/api/apply-ddl/{session_id}", response_model=ApplyDDLResponse)
async def apply_ddl(session_id: str, body: ApplyDDLRequest):
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")

    s = sessions[session_id]
    ddl_schema = s.get("ddl_schema", {})
    data_tables = s["raw"].get("tables", {})
    inferred_schema = s["raw"].get("schema", {})
    excluded = _excluded_set(s)
    results = []

    for table in body.tables:
        errors = []

        if table in excluded:
            errors.append(f"Table '{table}' is currently excluded")
            results.append(
                ApplyDDLTableResult(table=table, applied=False, errors=errors)
            )
            continue

        if table not in ddl_schema:
            errors.append(f"No DDL definition found for table '{table}'")
            results.append(
                ApplyDDLTableResult(table=table, applied=False, errors=errors)
            )
            continue

        if table not in data_tables or not data_tables[table]:
            errors.append(f"No data found for table '{table}'")
            results.append(
                ApplyDDLTableResult(table=table, applied=False, errors=errors)
            )
            continue

        # Strict column match (case-insensitive)
        ddl_cols = {c.lower() for c in ddl_schema[table]}
        data_cols = {c.lower() for c in data_tables[table][0].keys()}

        ddl_only = ddl_cols - data_cols
        data_only = data_cols - ddl_cols

        if ddl_only or data_only:
            if ddl_only:
                errors.append(
                    f"Columns in DDL but not in data: {', '.join(sorted(ddl_only))}"
                )
            if data_only:
                errors.append(
                    f"Columns in data but not in DDL: {', '.join(sorted(data_only))}"
                )
            results.append(
                ApplyDDLTableResult(table=table, applied=False, errors=errors)
            )
            continue

        # Apply DDL schema — overwrite inferred schema for this table
        inferred_schema[table] = ddl_schema[table]
        if table not in s.get("applied_ddl", []):
            s.setdefault("applied_ddl", []).append(table)

        results.append(ApplyDDLTableResult(table=table, applied=True, errors=[]))

    all_ok = all(r.applied for r in results)
    return ApplyDDLResponse(ok=all_ok, results=results)


@app.get("/api/transform/{session_id}", response_model=TransformResponse)
async def transform(session_id: str):
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")
    s = sessions[session_id]
    project_id = s.get("project_id")
    run = None
    if project_id:
        run = create_pipeline_run(project_id, "transform")
    audit_trail = s.get("audit_trail")

    # Inject DDL constraints (PK, UNIQUE) into config for dedup
    config = dict(s.get("config", {}))
    ddl_constraints_raw = s.get("ddl_constraints_raw", {})
    ddl_schema_raw = s.get("ddl_schema", {})
    if ddl_constraints_raw:
        # Use the full constraints parsed from DDL (includes multi-column UNIQUE)
        config["ddl_constraints"] = ddl_constraints_raw
    elif ddl_schema_raw:
        # Fall back to per-column flags from the schema
        ddl_constraints = {}
        for tbl, cols_info in ddl_schema_raw.items():
            pk_cols = [c for c, info in cols_info.items() if info.get("primary_key")]
            uq_cols = [
                [c]
                for c, info in cols_info.items()
                if info.get("unique") and not info.get("primary_key")
            ]
            if pk_cols or uq_cols:
                ddl_constraints[tbl] = {"primary_key": pk_cols, "unique": uq_cols}
        config["ddl_constraints"] = ddl_constraints

    transformer = Transformer(_visible_raw(s), config, audit_trail)
    result = transformer.run()
    sessions[session_id]["transformed"] = result
    sessions[session_id]["transformer"] = transformer
    # Merge FK edges from transform config and DDL foreign keys
    fk_edges = list(transformer.fk_edges)
    for fk in s.get("ddl_foreign_keys", []):
        edge = (fk["child_table"], fk["parent_table"])
        if edge not in fk_edges:
            fk_edges.append(edge)
    sessions[session_id]["fk_edges"] = fk_edges
    _auto_save(session_id, "transform")
    if run and project_id:
        total_rows = result.get("total_rows", 0)
        note_parts = []
        if result.get("encoding_conversions"):
            note_parts.append(f"{result['encoding_conversions']} enc fixes")
        if result.get("type_conversions"):
            note_parts.append(f"{result['type_conversions']} type conv")
        if result.get("dedup_removed"):
            note_parts.append(f"{result['dedup_removed']} dupes removed")
        finish_pipeline_run(run["id"], "done", total_rows, ", ".join(note_parts))
        _flush_audit_events(project_id, audit_trail, run["id"])
    return TransformResponse(**result)


# ---------------------------------------------------------------------------
# Transform presets — capture-and-replay of column edits/renames so the
# user doesn't reconfigure 100+ tables for every new client with the same
# legacy schema.
# ---------------------------------------------------------------------------

import presets as presets_store


@app.get("/api/transform-presets")
async def list_transform_presets():
    return {"presets": presets_store.list_presets()}


@app.get("/api/transform-presets/{preset_id}")
async def get_transform_preset(preset_id: str):
    preset = presets_store.get_preset(preset_id)
    if not preset:
        raise HTTPException(404, "Preset not found")
    return preset


@app.post("/api/transform-presets")
async def create_transform_preset(body: dict):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Preset name is required")
    table_names = body.get("table_names") or {}
    edits = body.get("edits") or {}
    if not isinstance(table_names, dict) or not isinstance(edits, dict):
        raise HTTPException(400, "table_names and edits must be objects")
    return presets_store.create_preset(name, table_names, edits)


@app.put("/api/transform-presets/{preset_id}")
async def update_transform_preset(preset_id: str, body: dict):
    name = body.get("name")
    table_names = body.get("table_names")
    edits = body.get("edits")
    updated = presets_store.update_preset(
        preset_id,
        name=name.strip() if isinstance(name, str) else None,
        table_names=table_names if isinstance(table_names, dict) else None,
        edits=edits if isinstance(edits, dict) else None,
    )
    if not updated:
        raise HTTPException(404, "Preset not found")
    return updated


@app.delete("/api/transform-presets/{preset_id}")
async def delete_transform_preset(preset_id: str):
    if not presets_store.delete_preset(preset_id):
        raise HTTPException(404, "Preset not found")
    return {"ok": True}


@app.post("/api/load/{session_id}", response_model=LoadResponse)
async def load(session_id: str, body: LoadRequest):
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")
    s = sessions[session_id]
    if "transformed" not in s:
        raise HTTPException(400, "Run transform first")

    project_id = s.get("project_id")
    run = None
    if project_id:
        run = create_pipeline_run(project_id, "load")

    if project_id:
        out_dir = project_outputs_dir(project_id)
    else:
        out_dir = os.path.join(OUTPUT_DIR, session_id)
    os.makedirs(out_dir, exist_ok=True)

    excluded = _excluded_set(s)
    ddl_schema = {
        t: s["raw"]["schema"].get(t, {})
        for t in s["raw"].get("tables", {})
        if t in s.get("applied_ddl", []) and t not in excluded
    }
    fk_edges = [
        edge
        for edge in s.get("fk_edges", [])
        if edge[0] not in excluded and edge[1] not in excluded
    ]
    # Also collect FK edges from DDL foreign keys parsed during apply-ddl
    ddl_fks = s.get("ddl_foreign_keys", [])
    for fk in ddl_fks:
        if fk["child_table"] in excluded or fk["parent_table"] in excluded:
            continue
        edge = (fk["child_table"], fk["parent_table"])
        if edge not in fk_edges:
            fk_edges.append(edge)

    loader = Loader(
        s["transformed"], body.dict(), out_dir, ddl_schema=ddl_schema, fk_edges=fk_edges
    )
    result = loader.run()
    sessions[session_id]["load_result"] = result
    _auto_save(session_id, "load")
    if run and project_id:
        total_rows = sum(result.get("rows_written", {}).values())
        status = "error" if result.get("errors") else "done"
        note = (
            "; ".join(result.get("errors", [])[:2])
            if result.get("errors")
            else f"format={body.output_format}"
        )
        finish_pipeline_run(run["id"], status, total_rows, note)
        audit_trail = s.get("audit_trail")
        if audit_trail:
            _flush_audit_events(project_id, audit_trail, run["id"])
    return LoadResponse(**result)


@app.get("/api/stats/{session_id}", response_model=StatsResponse)
async def stats(session_id: str):
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")
    s = sessions[session_id]
    from utils.stats import StatsEngine

    engine = StatsEngine(_visible_session(s))
    _auto_save(session_id, "stats")
    return StatsResponse(**engine.compute())


@app.get("/api/download/{session_id}/{filename}")
async def download(session_id: str, filename: str):
    s = sessions.get(session_id)
    if s and s.get("project_id"):
        base_dir = project_outputs_dir(s["project_id"])
    else:
        base_dir = os.path.join(OUTPUT_DIR, session_id)
    safe_dir = os.path.realpath(base_dir)
    path = os.path.realpath(os.path.join(safe_dir, filename))
    if not path.startswith(safe_dir + os.sep):
        raise HTTPException(400, "Invalid filename")
    if not os.path.exists(path):
        raise HTTPException(404, "File not found")
    return FileResponse(path, filename=os.path.basename(path))


@app.get("/api/projects/{project_id}/outputs")
async def list_project_outputs(project_id: str):
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    out_dir = project_outputs_dir(project_id)
    if not os.path.isdir(out_dir):
        return {"files": []}
    files = [f for f in os.listdir(out_dir) if os.path.isfile(os.path.join(out_dir, f))]
    return {"files": sorted(files)}


@app.get("/api/projects/{project_id}/download/{filename}")
async def download_project_file(project_id: str, filename: str):
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    base_dir = project_outputs_dir(project_id)
    safe_dir = os.path.realpath(base_dir)
    path = os.path.realpath(os.path.join(safe_dir, filename))
    if not path.startswith(safe_dir + os.sep):
        raise HTTPException(400, "Invalid filename")
    if not os.path.exists(path):
        raise HTTPException(404, "File not found")
    return FileResponse(path, filename=os.path.basename(path))


# ---------------------------------------------------------------------------
# Template API routes
# ---------------------------------------------------------------------------


@app.post("/api/projects/{project_id}/templates")
async def create_template(project_id: str, request: CreateTemplateRequest):
    """Save a new DDL template."""
    try:
        template_id = save_template(
            project_id=project_id,
            name=request.name,
            ddl_content=request.ddl_content,
            created_by=request.created_by,
        )
        return {"id": template_id, "message": "Template saved"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/projects/{project_id}/templates")
async def list_project_templates(project_id: str):
    """List all templates for a project."""
    templates = list_templates(project_id)
    return {"templates": templates, "total": len(templates)}


@app.get("/api/projects/{project_id}/templates/{template_id}")
async def get_single_template(project_id: str, template_id: str):
    """Get a specific template."""
    try:
        template = get_template(template_id)
        return template
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/api/projects/{project_id}/templates/{template_id}")
async def delete_single_template(project_id: str, template_id: str):
    """Delete a template."""
    delete_template(template_id)
    return {"message": "Template deleted"}
