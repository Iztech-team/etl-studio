import asyncio
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.extract.extractor import Extractor
from core.load.loader import Loader
from core.transform.transformer import Transformer
from persistence.db import (
    _get_conn,
    create_pipeline_run,
    create_project,
    delete_project,
    finish_pipeline_run,
)
from persistence.db import get_dashboard_stats as db_get_dashboard_stats
from persistence.db import get_history as db_get_history
from persistence.db import (
    get_project,
    insert_audit_events_batch,
    list_projects,
    rename_project,
    update_project_phase,
)
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from models.project_schemas import (
    AuthResponse,
    CreateProjectRequest,
    LoginRequest,
    ProjectListResponse,
    ProjectResponse,
    RenameProjectRequest,
)
from models.schemas import (
    DB_TYPE_EXTENSIONS,
    ConfigureRequest,
    ConfigureResponse,
    EditDataRequest,
    EditDataResponse,
    LoadRequest,
    LoadResponse,
    PreExtractFileInfo,
    PreExtractResponse,
    StatsResponse,
    TableSelectionRequest,
    TransformResponse,
)
from persistence.project_state import (
    delete_project_files,
    ensure_project_dirs,
    load_state,
    project_dir,
    project_outputs_dir,
    project_uploads_dir,
    save_state,
)
from startup import GUEST_DIR, OUTPUT_DIR, UPLOAD_DIR, lifespan
from state import extraction_store, session_store
from utils import extract_cache
from utils.audit import AuditTrail

app = FastAPI(title="ETL Legacy", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    }


def _visible_session(session: dict) -> dict:
    """Shallow-copy of the session with raw replaced by its visible view."""
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
        sid for sid, s in (await session_store.all_sessions()).items() if s.get("project_id") == project_id
    ]
    for sid in to_remove:
        await session_store.remove(sid)
    delete_project_files(project_id)
    delete_project(project_id)
    return {"ok": True}


def _resume_payload(project: dict, session_id: str, session: dict) -> dict:
    raw = session.get("raw", {})
    # The transformed dict may carry the full row data — for a real
    # project that's gigabytes of JSON, blocks the asyncio loop during
    # encode, and starves every other request. Strip it down to the
    # metadata the frontend actually consumes (counts + warnings +
    # preview). If a downstream view needs the full rows it can re-fetch
    # via /api/transform.
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

    async def encode_async(obj: dict) -> bytes:
        """For payloads that may serialize to many MB (the final 'done'
        event carrying schema + preview + transform metadata), encode on
        a worker thread so the asyncio loop stays responsive — otherwise
        a single big json.dumps freezes every other request including
        client navigations."""
        return await asyncio.to_thread(encode, obj)

    async def stream():
        try:
            # Warm path: a session for this project already lives in memory.
            for sid, sess in (await session_store.all_sessions()).items():
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
                    await asyncio.sleep(0)
                    table_done_count_warm = 0
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
                        # Same pacing logic as the cold path: 2 ms every
                        # 4 events keeps the wire moving and React rendering.
                        table_done_count_warm += 1
                        if table_done_count_warm % 4 == 0:
                            await asyncio.sleep(0.002)
                        else:
                            await asyncio.sleep(0)
                    # The 'done' payload may contain ~MB of schema +
                    # preview metadata even after stripping the row data;
                    # encode it off-thread to keep the loop responsive
                    # while the client is downloading.
                    final_bytes = await encode_async(
                        {"event": "done", **_resume_payload(project, sid, sess)}
                    )
                    yield final_bytes
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

            # The iterator emits its own 'start' once listdir runs (with the
            # real table list). We used to emit an extra empty start here so
            # the client got an immediate event, but that confused progress
            # bars whose total briefly went 0 → N → 0 → N. The frontend
            # tolerates a slight delay before the first 'start'.
            project_emitted = False
            # Pacing: the cache fast-path produces events in microseconds.
            # Without a deliberate yield between them the OS coalesces all
            # chunks into a single TCP send and React batches every state
            # update into one render — the user sees no progress at all.
            # We track table_done events so the cold path (naturally slow
            # because of CSV parsing) doesn't pay any pacing cost.
            table_done_count = 0
            while True:
                event = await asyncio.to_thread(safe_next)
                if event is SENTINEL:
                    break
                event_type, payload = event
                if event_type == "done":
                    session = payload
                    continue
                # Tag the project onto the very first start so the splash
                # has the project name to display.
                if event_type == "start" and not project_emitted:
                    payload = {"project": project, **payload}
                    project_emitted = True
                yield encode({"event": event_type, **payload})
                # Cooperative yield so each chunk reaches the wire before
                # the next event is built. For the cache path, also pace
                # every few table_done events with a 2 ms sleep so the
                # client gets visible progress (135 tables × 2 ms ≈ 270 ms
                # — enough for animation, well under "annoying delay").
                if event_type == "table_done":
                    table_done_count += 1
                    if table_done_count % 4 == 0:
                        await asyncio.sleep(0.002)
                    else:
                        await asyncio.sleep(0)
                else:
                    await asyncio.sleep(0)

            session["project_id"] = project_id
            await session_store.put(session_id, session)
            final_bytes = await encode_async(
                {"event": "done", **_resume_payload(project, session_id, session)}
            )
            yield final_bytes
        except Exception as e:
            yield encode({"event": "error", "message": f"Failed to resume: {e}"})

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.post("/api/projects/{project_id}/save")
async def save_project(project_id: str):
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    session = None
    for s in (await session_store.all_sessions()).values():
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

    await session_store.put(session_id, {
        "project_id": project_id,
        "pending_db": {
            "file_path": dest,
            "session_dir": session_dir,
            "filename": file.filename,
            "size": file_size,
            "db_type": db_type,
        },
    })
    state = _new_extraction_state()
    state["filename"] = file.filename
    state["project_id"] = project_id
    await extraction_store.put(session_id, state)
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
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    s = (await session_store.require(session_id))
    pending = s.get("pending_db")
    if not pending and "raw" not in s:
        raise HTTPException(400, "No database file pending extraction for this session")

    state = await extraction_store.get(session_id)
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
    await extraction_store.put(session_id, new_state)
    asyncio.create_task(_run_extraction(session_id, password))
    return {"ok": True, "status": "extracting", "session_id": session_id}


@app.get("/api/extract/{session_id}/status")
async def extract_status(session_id: str):
    """Lightweight status snapshot (no event log)."""
    state = await extraction_store.get(session_id)
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
    if not (await extraction_store.get(session_id)):
        raise HTTPException(404, "No extraction state for this session")

    async def gen():
        cursor = 0
        while True:
            state = await extraction_store.get(session_id)
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

    state = await extraction_store.get(session_id)
    if not state:
        raise HTTPException(404, "No extraction state for this session")

    if state["status"] in ("done", "error", "cancelled"):
        return {"ok": True, "status": state["status"], "session_id": session_id}

    state["status"] = "cancelled"
    state["events"].append({"event": "cancelled", "message": "Extraction cancelled"})
    state["finished_at"] = _dt.now(timezone.utc).isoformat()

    s = await session_store.get(session_id)
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
            await session_store.remove(session_id)

    return {"ok": True, "status": "cancelled", "session_id": session_id}


async def _run_extraction(session_id: str, password: str | None) -> None:
    """Background worker: drives the iter, writes events to state."""
    from datetime import datetime as _dt

    from core.extract.db_extractor import extract_db_to_csvs_iter

    state = (await extraction_store.get(session_id))
    s = (await session_store.require(session_id))
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

        (await session_store.require(session_id)).update(
            {
                "pre_extract": {
                    "file": file_info.dict(),
                    "password": password is not None,
                    "db_type": pending["db_type"],
                },
                "extractor": extractor,
                "raw": result,
                "files": saved_files,
                "audit_trail": audit_trail,
            }
        )
        (await session_store.require(session_id)).pop("pending_db", None)
        # Persist parsed extraction so next resume skips CSV parsing.
        project_id_for_cache = (await session_store.require(session_id)).get("project_id")
        if project_id_for_cache:
            try:
                from utils import extract_cache as _ec

                _ec.write(project_id_for_cache, result, pending["session_dir"])
            except Exception:
                pass
        await _auto_save(session_id, "pre-extract")

        done_payload = PreExtractResponse(
            ok=True,
            session_id=session_id,
            file=file_info,
            tables_extracted=list(result.get("tables", {}).keys()),
            csv_files=csv_files,
            preview=result.get("preview", {}),
            inferred_schema=result.get("schema", {}),
            stats=result.get("stats", {}),
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
async def pre_extract_select(session_id: str, body: TableSelectionRequest):
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
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    s = (await session_store.require(session_id))
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

    await _auto_save(session_id, "edit")
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
        from core.extract.db_extractor import extract_db_to_csvs

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
    await session_store.put(session_id, {
        "project_id": project_id,
        "extractor": extractor,
        "raw": result,
        "files": saved,
        "audit_trail": audit_trail,
    })

    # Persist the parsed extraction so the next resume skips CSV parsing.
    # Best-effort: if the cache write fails for any reason the request
    # still succeeds — resume just falls back to a fresh re-extract.
    if project_id:
        try:
            from utils import extract_cache as _ec

            _ec.write(project_id, result, session_dir)
        except Exception:
            pass

    await _auto_save(session_id, "edit")

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
    }


@app.get("/api/table-data/{session_id}")
async def get_table_data(session_id: str):
    """Return all rows for all tables in the session."""
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    s = (await session_store.require(session_id))
    _ensure_rows_loaded(s)  # lazy: rows aren't populated by resume
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
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    s = (await session_store.require(session_id))
    if table_name in _excluded_set(s):
        raise HTTPException(404, f"Table '{table_name}' is excluded")
    _ensure_rows_loaded(s, [table_name])  # lazy: per-table load is cheap
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
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    s = (await session_store.require(session_id))
    _ensure_rows_loaded(s)  # lazy: edits need the full row set in memory
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

    await _auto_save(session_id, "edit")
    return {
        "ok": True,
        "stats": stats,
        "preview": raw["preview"],
        "schema": raw["schema"],
    }


@app.get("/api/session/{session_id}/config")
async def get_session_config(session_id: str):
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    return (await session_store.require(session_id)).get("config", {})


@app.post("/api/configure/{session_id}", response_model=ConfigureResponse)
async def configure(
    session_id: str,
    body: ConfigureRequest,
    phase: str = Query("configure"),
):
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    (await session_store.require(session_id))["config"] = body.dict()
    await _auto_save(session_id, phase)
    return ConfigureResponse(ok=True, message="Configuration saved")



@app.get("/api/transform/{session_id}", response_model=TransformResponse)
async def transform(session_id: str):
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    s = (await session_store.require(session_id))
    project_id = s.get("project_id")
    run = None
    if project_id:
        run = create_pipeline_run(project_id, "transform")
    audit_trail = s.get("audit_trail")

    config = dict(s.get("config", {}))

    # Per-session progress dict polled by the navbar dock so the user can
    # see how far the transform has gotten while it runs.
    progress: Dict[str, Any] = {
        "status": "running",
        "tables_done": 0,
        "tables_total": 0,
        "current_table": None,
        "persisted_targets": [],
    }
    (await session_store.require(session_id))["transform_progress"] = progress

    def _on_progress(table_name: str, done: int, total: int) -> None:
        progress["tables_done"] = done
        progress["tables_total"] = total
        progress["current_table"] = table_name

    # Per-target persistence: write each completed target to disk the
    # moment every source feeding it has finished. If transform crashes,
    # users can still pick up the persisted targets from disk. The
    # directory is wiped at the start of every transform so stale outputs
    # from a previous (failed) run don't mix with the current one.
    partial_dir: Optional[str] = None
    if project_id:
        partial_dir = os.path.join(project_dir(project_id), "transform_partial")
        try:
            shutil.rmtree(partial_dir, ignore_errors=True)
            os.makedirs(partial_dir, exist_ok=True)
        except Exception:
            partial_dir = None

    def _persist_target(target: str, rows: List[Dict[str, Any]]) -> None:
        if not partial_dir:
            return
        # Sanitize the target name for use as a filename — ERPnext doctype
        # names with spaces would still work on Windows but are uglier.
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in target)
        path = os.path.join(partial_dir, f"{safe}.json")
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False, default=str)
            os.replace(tmp, path)
            progress.setdefault("persisted_targets", []).append(target)
        except Exception as e:
            s.setdefault("warnings", []).append(
                f"failed to persist target {target}: {e}"
            )

    # Lazy row loader: pulls one table's rows from the cache only when the
    # transformer needs them, and the transformer frees the rows after
    # processing. Avoids loading the entire 1 GB+ dataset into RAM upfront
    # and keeps the asyncio loop responsive (no big pickle.load on the
    # event loop or the worker thread).
    excluded = _excluded_set(s)

    def _row_loader(table_name: str) -> List[Dict[str, Any]]:
        if table_name in excluded:
            return []
        if not project_id:
            # No project context — fall back to whatever is already in
            # session memory (e.g. a freshly-uploaded session).
            return s.get("raw", {}).get("tables", {}).get(table_name, []) or []
        rows = extract_cache.read_table_rows(project_id, table_name)
        if rows is None:
            # Cache miss — fall back to in-memory (may have been edited)
            # then to a fresh extract.
            rows = s.get("raw", {}).get("tables", {}).get(table_name)
            if rows is None:
                _ensure_rows_loaded(s, [table_name])
                rows = s.get("raw", {}).get("tables", {}).get(table_name, [])
        return rows or []

    transformer = Transformer(
        _visible_raw(s),
        config,
        audit_trail,
        progress_cb=_on_progress,
        persist_target_cb=_persist_target,
        row_loader=_row_loader,
    )
    try:
        # Run synchronously off the event loop so the asyncio loop stays
        # free to serve /api/transform/{sid}/status polls from the dock.
        result = await asyncio.to_thread(transformer.run)
    except Exception as e:
        progress["status"] = "error"
        progress["error"] = str(e)
        if run and project_id:
            finish_pipeline_run(run["id"], "error", 0, str(e))
        raise
    progress["status"] = "done"
    progress["tables_done"] = progress.get("tables_total", 0)
    (await session_store.require(session_id))["transformed"] = result
    (await session_store.require(session_id))["transformer"] = transformer
    (await session_store.require(session_id))["fk_edges"] = list(transformer.fk_edges)
    await _auto_save(session_id, "transform")
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


@app.post("/api/reconcile/{session_id}")
async def reconcile_endpoint(session_id: str, body: dict | None = None):
    """Run the reconciliation pass over the transformed data and return a
    structured report. Body is optional and may carry per-project tolerances
    or invoice-table specs:

      {
        "voucher_tolerance": 0.01,
        "account_tolerance": 0.01,
        "invoice_tolerance": 0.05,
        "gl_table": "gl_entry",
        "invoice_specs": [
          {"invoice_table": "sales_invoice",
           "line_table": "sales_invoice_item", "label": "sales"},
          ...
        ],
        "fk_specs": [
          {"child": "sales_invoice_item", "parent": "sales_invoice",
           "child_field": "parent", "parent_field": "name"},
          ...
        ]
      }

    Legacy balances for the per-account tie-out are pulled from the
    session's raw extraction (`ACCOUNTT.MBALANCE`-style) when the GL
    output uses the legacy ACCOUNTID as `account`. If you renamed the
    account identifier, pass `legacy_account_balances` in the body
    explicitly.
    """
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    s = (await session_store.require(session_id))
    if "transformed" not in s or not s["transformed"]:
        await _ensure_transformed(session_id)
    transformed = s["transformed"]
    target_tables = transformed.get("tables", {})

    body = body or {}

    # If the caller didn't pass legacy balances, derive them from the
    # session's raw ACCOUNTT (best-effort — lets you run the check on
    # any AlArabi-shaped project without extra config).
    legacy_balances = body.get("legacy_account_balances")
    if not legacy_balances:
        legacy_balances = {}
        accountt_rows = (s.get("raw") or {}).get("tables", {}).get("ACCOUNTT") or []
        for r in accountt_rows:
            aid = r.get("ACCOUNTID")
            mbal = r.get("MBALANCE")
            if aid is not None and mbal not in (None, "", "0"):
                try:
                    legacy_balances[aid] = float(mbal)
                except (TypeError, ValueError):
                    continue

    from utils import reconcile as _rec

    report = _rec.reconcile(
        target_tables,
        legacy_account_balances=legacy_balances or None,
        invoice_specs=body.get("invoice_specs"),
        fk_specs=body.get("fk_specs"),
        gl_table=body.get("gl_table", "gl_entry"),
        voucher_tolerance=body.get("voucher_tolerance", 0.01),
        account_tolerance=body.get("account_tolerance", 0.01),
        invoice_tolerance=body.get("invoice_tolerance", 0.05),
    )
    (await session_store.require(session_id))["reconcile_report"] = report
    return report


@app.get("/api/transform/{session_id}/status")
async def transform_status(session_id: str):
    """Lightweight progress endpoint polled by the navbar dock.

    Returns the same shape as /api/extract/{sid}/status so the dock view
    can stay symmetrical:
      {status: "running"|"done"|"error"|"unknown",
       tables_done, tables_total, current_table}
    """
    if not await session_store.exists(session_id):
        return {"status": "unknown"}
    s = (await session_store.require(session_id))
    progress = s.get("transform_progress")
    if not progress:
        return {"status": "unknown"}
    return progress


# ---------------------------------------------------------------------------
# Transform presets — capture-and-replay of column edits/renames so the
# user doesn't reconfigure 100+ tables for every new client with the same
# legacy schema.
# ---------------------------------------------------------------------------

import persistence.presets as presets_store


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
    return presets_store.create_preset(
        name,
        table_names,
        edits,
        dropped_tables=body.get("dropped_tables") or [],
        table_options=body.get("table_options") or {},
        extra_configs=body.get("extra_configs") or [],
    )


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
        dropped_tables=body.get("dropped_tables"),
        table_options=body.get("table_options"),
        extra_configs=body.get("extra_configs"),
    )
    if not updated:
        raise HTTPException(404, "Preset not found")
    return updated


@app.delete("/api/transform-presets/{preset_id}")
async def delete_transform_preset(preset_id: str):
    if not presets_store.delete_preset(preset_id):
        raise HTTPException(404, "Preset not found")
    return {"ok": True}


def _ensure_rows_loaded(
    session: Dict[str, Any], tables: Optional[List[str]] = None
) -> None:
    """Lazy-load CSV rows from the extract cache (or re-parse from disk
    if the cache is missing/stale).

    Resume populates the session with metadata only — schema, stats,
    preview, table names — so opening a project is fast even on a 5 GB
    dataset. Any endpoint that actually needs the rows (transform,
    table-data viewer, edit, etc.) calls this helper before reading
    `session['raw']['tables']`.

    `tables`: optional whitelist of source-table names to load. None means
    load every table. The per-table cache layout means partial loads cost
    only the requested tables' pickle files."""
    raw = session.setdefault("raw", {"tables": {}})
    raw_tables = raw.setdefault("tables", {})

    project_id = session.get("project_id")
    if not project_id:
        return  # nothing we can do without a project

    uploads_dir = project_uploads_dir(project_id)

    # Decide which tables we still need.
    if tables is None:
        wanted = list(raw.get("schema", {}).keys()) or _list_cached_tables(project_id)
    else:
        wanted = list(tables)
    needed = [t for t in wanted if t not in raw_tables]
    if not needed:
        return

    # Try the cache first.
    if extract_cache.is_fresh(project_id, uploads_dir):
        loaded_any = False
        for name in needed:
            rows = extract_cache.read_table_rows(project_id, name)
            if rows is not None:
                raw_tables[name] = rows
                loaded_any = True
        # If every requested table loaded from cache, we're done.
        if all(t in raw_tables for t in needed):
            extractor = session.get("extractor")
            if extractor is not None:
                extractor._raw_tables = raw_tables
            return
        # Otherwise fall through to a full re-parse — something's missing
        # from the cache and we need to repopulate.
        if loaded_any:
            pass

    # Fallback: re-parse the CSVs from disk and rewrite the cache. This
    # is the slow path; users hit it only when the cache is genuinely
    # stale or missing.
    audit_trail = session.get("audit_trail")
    extractor = session.get("extractor") or Extractor(uploads_dir, audit_trail)
    result = extractor.extract_all()
    raw["tables"] = result.get("tables", {}) or {}
    raw["schema"] = result.get("schema", raw.get("schema", {}))
    raw["stats"] = result.get("stats", raw.get("stats", {}))
    raw["preview"] = result.get("preview", raw.get("preview", {}))
    session["extractor"] = extractor
    try:
        extract_cache.write(project_id, raw, uploads_dir)
    except Exception:
        pass


def _list_cached_tables(project_id: str) -> List[str]:
    """Return the table names recorded in the cache metadata, or [] if
    the cache isn't there."""
    try:
        meta = extract_cache.read_meta(project_id)
        return list(meta.get("all_table_names", []) or [])
    except Exception:
        return []


async def _ensure_transformed(session_id: str) -> None:
    """Run the transformer on demand if the session doesn't have its result.

    On project resume we no longer pre-run the transformer (it was costing
    10–30s per page open for big schemas). Instead any endpoint that needs
    `s['transformed']` calls this helper, which mirrors what /api/transform
    does but without the per-step audit-trail bookkeeping.
    """
    s = (await session_store.require(session_id))
    if "transformed" in s and s["transformed"]:
        return
    # Lazy load: rows aren't populated by resume.
    _ensure_rows_loaded(s)
    audit_trail = s.get("audit_trail")
    config = dict(s.get("config", {}))
    transformer = Transformer(_visible_raw(s), config, audit_trail)
    s["transformed"] = transformer.run()
    s["transformer"] = transformer


@app.post("/api/load/{session_id}", response_model=LoadResponse)
async def load(session_id: str, body: LoadRequest):
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    s = (await session_store.require(session_id))
    if "transformed" not in s or not s["transformed"]:
        # Lazy: resume no longer pre-runs the transformer, so do it now.
        if not s.get("config"):
            raise HTTPException(400, "Run transform first")
        await _ensure_transformed(session_id)

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
    fk_edges = [
        edge
        for edge in s.get("fk_edges", [])
        if edge[0] not in excluded and edge[1] not in excluded
    ]

    # The transformer (if it ran in this session) populated self_refs for
    # any target whose parent column points back at the same target — used
    # by the loader to sort within tabAccount and friends.
    self_refs: Dict[str, str] = {}
    transformer = s.get("transformer")
    if transformer is not None:
        self_refs = getattr(transformer, "self_refs", {}) or {}
    loader = Loader(
        s["transformed"],
        body.dict(),
        out_dir,
        fk_edges=fk_edges,
        self_refs=self_refs,
    )
    result = loader.run()
    (await session_store.require(session_id))["load_result"] = result
    await _auto_save(session_id, "load")
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
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    s = (await session_store.require(session_id))
    from utils.stats import StatsEngine

    engine = StatsEngine(_visible_session(s))
    await _auto_save(session_id, "stats")
    return StatsResponse(**engine.compute())


@app.get("/api/download/{session_id}/{filename}")
async def download(session_id: str, filename: str):
    s = await session_store.get(session_id)
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


@app.get("/api/projects/{project_id}/download-all")
async def download_all_project_files(project_id: str):
    """Bundle every file in the project's outputs/ directory into a single
    .zip and stream it back. Used by the Export step's "download all"
    action so users don't have to grab files one by one."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    out_dir = project_outputs_dir(project_id)
    if not os.path.isdir(out_dir):
        raise HTTPException(404, "No outputs to bundle")
    files = sorted(
        f for f in os.listdir(out_dir) if os.path.isfile(os.path.join(out_dir, f))
    )
    if not files:
        raise HTTPException(404, "No outputs to bundle")

    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in files:
            zf.write(os.path.join(out_dir, name), arcname=name)
    buf.seek(0)

    project_name = project.get("name") or project_id
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in project_name)
    filename = f"{safe_name}_outputs.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/download-all/{session_id}")
async def download_all_session_files(session_id: str):
    """Same as the project variant but for guest sessions that don't have
    a project_id yet."""
    s = await session_store.get(session_id)
    if s and s.get("project_id"):
        base_dir = project_outputs_dir(s["project_id"])
    else:
        base_dir = os.path.join(OUTPUT_DIR, session_id)
    if not os.path.isdir(base_dir):
        raise HTTPException(404, "No outputs to bundle")
    files = sorted(
        f for f in os.listdir(base_dir) if os.path.isfile(os.path.join(base_dir, f))
    )
    if not files:
        raise HTTPException(404, "No outputs to bundle")

    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in files:
            zf.write(os.path.join(base_dir, name), arcname=name)
    buf.seek(0)

    filename = f"session_{session_id[:8]}_outputs.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/projects/{project_id}/transform-partial")
async def list_transform_partial(project_id: str):
    """List the per-target JSON files persisted incrementally during the
    last (or in-progress) transform. Useful for picking up partial work
    when transform crashed mid-run — every file here represents a target
    table that completed end-to-end before the failure."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    partial = os.path.join(project_dir(project_id), "transform_partial")
    if not os.path.isdir(partial):
        return {"files": []}
    files = []
    for f in sorted(os.listdir(partial)):
        full = os.path.join(partial, f)
        if os.path.isfile(full) and f.endswith(".json"):
            files.append({"name": f, "size": os.path.getsize(full)})
    return {"files": files}


@app.get("/api/projects/{project_id}/transform-partial/{filename}")
async def download_transform_partial(project_id: str, filename: str):
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    base_dir = os.path.join(project_dir(project_id), "transform_partial")
    safe_dir = os.path.realpath(base_dir)
    path = os.path.realpath(os.path.join(safe_dir, filename))
    if not path.startswith(safe_dir + os.sep):
        raise HTTPException(400, "Invalid filename")
    if not os.path.exists(path):
        raise HTTPException(404, "File not found")
    return FileResponse(path, filename=os.path.basename(path))


