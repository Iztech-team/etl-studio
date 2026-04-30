import asyncio
import json
import os
import shutil
import uuid
from datetime import timezone
from typing import List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from core.extract.extractor import Extractor
from core.strategies.erpnext_shared.entities import (
    descriptors as entity_descriptors,
    resolve_dependencies,
)
from helpers import _auto_save, _excluded_set, _flush_audit_events
from models.schemas import (
    DB_TYPE_EXTENSIONS,
    EntitySelectionRequest,
    PreExtractFileInfo,
    PreExtractResponse,
    TableSelectionRequest,
)
from persistence.db import create_pipeline_run, finish_pipeline_run
from persistence.project_state import project_uploads_dir
from startup import GUEST_DIR
from state import extraction_store, session_store
from utils import extract_cache
from utils.audit import AuditTrail

router = APIRouter()


def _detect_db_type(filename: str) -> str | None:
    ext = os.path.splitext(filename)[1].lower()
    for db_type, extensions in DB_TYPE_EXTENSIONS.items():
        if ext in extensions:
            return db_type
    return None


def _is_db_file(filename: str) -> bool:
    return _detect_db_type(filename) is not None


def _new_extraction_state() -> dict:
    return {
        "status": "pending",  # pending | extracting | done | error | cancelled
        "events": [],
        "result": None,
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
    RuntimeError, so we catch inside the worker thread and signal
    end-of-stream via a unique sentinel.
    """
    def safe_next(gen):
        try:
            return next(gen)
        except StopIteration:
            return sentinel
    return safe_next


@router.post("/upload-db")
async def upload_db(
    file: UploadFile = File(...),
    project_id: str | None = Form(None),
):
    """Upload a database file. Does NOT extract — call /api/extract next."""
    db_type = _detect_db_type(file.filename or "")
    if not db_type:
        raise HTTPException(
            400,
            "Unsupported database file type. Supported: "
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
        name=file.filename, path=dest, size=file_size, db_type=db_type,
    )

    await session_store.put(session_id, {
        "project_id": project_id,
        "pending_db": {
            "file_path": dest, "session_dir": session_dir,
            "filename": file.filename, "size": file_size, "db_type": db_type,
        },
    })
    state = _new_extraction_state()
    state["filename"] = file.filename
    state["project_id"] = project_id
    await extraction_store.put(session_id, state)
    return {"ok": True, "session_id": session_id, "file": file_info.dict()}


@router.post("/extract/{session_id}")
async def start_extract(
    session_id: str, password: str | None = Form(None),
):
    """Kick off extraction. Idempotent — returns current status if already running."""
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    s = await session_store.require(session_id)
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
    new_state["filename"] = (pending or {}).get("filename") or (state or {}).get("filename")
    new_state["project_id"] = s.get("project_id")
    await extraction_store.put(session_id, new_state)
    asyncio.create_task(_run_extraction(session_id, password))
    return {"ok": True, "status": "extracting", "session_id": session_id}


@router.get("/extract/{session_id}/status")
async def extract_status(session_id: str):
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


@router.get("/extract/{session_id}/stream")
async def stream_extract(session_id: str):
    """NDJSON stream with full replay. Every connecting client sees the
    entire history followed by live updates. Ends on done/error event."""
    if not await extraction_store.get(session_id):
        raise HTTPException(404, "No extraction state for this session")

    async def gen():
        cursor = 0
        while True:
            state = await extraction_store.get(session_id)
            if state is None:
                break
            for ev in state["events"][cursor:]:
                yield (json.dumps(ev, ensure_ascii=False) + "\n").encode("utf-8")
            cursor = len(state["events"])
            if state["status"] in ("done", "error", "cancelled"):
                break
            await asyncio.sleep(0.15)

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@router.post("/extract/{session_id}/cancel")
async def cancel_extract(session_id: str):
    """Cancel an in-flight extraction.

    Marks state cancelled so the worker stops at next checkpoint and any
    /stream readers terminate. Removes the uploaded DB file and tears down
    the session if no extracted data has landed yet.
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
        if "raw" not in s:
            await session_store.remove(session_id)

    return {"ok": True, "status": "cancelled", "session_id": session_id}


async def _run_extraction(session_id: str, password: str | None) -> None:
    """Background worker: drives the iter, writes events to state."""
    from datetime import datetime as _dt

    from core.extract.db_extractor import extract_db_to_csvs_iter

    state = await extraction_store.get(session_id)
    s = await session_store.require(session_id)
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
            pending["file_path"], pending["db_type"],
            pending["session_dir"], password,
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
            name=pending["filename"], path=pending["file_path"],
            size=pending["size"], db_type=pending["db_type"],
        )

        sess = await session_store.require(session_id)
        sess.update({
            "pre_extract": {
                "file": file_info.dict(),
                "password": password is not None,
                "db_type": pending["db_type"],
            },
            "extractor": extractor,
            "raw": result,
            "files": saved_files,
            "audit_trail": audit_trail,
        })
        sess.pop("pending_db", None)
        project_id_for_cache = sess.get("project_id")
        if project_id_for_cache:
            try:
                from utils import extract_cache as _ec
                _ec.write(project_id_for_cache, result, pending["session_dir"])
            except Exception:
                pass
        await _auto_save(session_id, "pre-extract")

        done_payload = PreExtractResponse(
            ok=True, session_id=session_id, file=file_info,
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


@router.post("/pre-extract-select/{session_id}")
async def pre_extract_select(session_id: str, body: TableSelectionRequest):
    """Soft-exclude tables in the session.

    Raw extracted data stays put so the user can re-include any table
    later. If the selection differs, transform/load artefacts are dropped
    (stale) and configure entries for newly-excluded tables are trimmed.
    """
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    s = await session_store.require(session_id)
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
                from datetime import datetime as _dt
                audit_trail.events.append({
                    "type": "tables_reselected",
                    "table": None, "column": None,
                    "description": f"included={sorted(selected)}, excluded={sorted(new_excluded)}",
                    "timestamp": _dt.now(timezone.utc).isoformat(),
                })
            except Exception:
                pass

    await _auto_save(session_id, "edit")
    return {
        "ok": True, "changed": changed,
        "kept": sorted(selected), "excluded": sorted(new_excluded),
    }


@router.get("/entities")
async def list_entities():
    """Return the entity menu the extract UI renders."""
    return {"entities": entity_descriptors()}


@router.post("/select-entities/{session_id}")
async def select_entities(session_id: str, body: EntitySelectionRequest):
    """Persist the user's entity selection on the session.

    Stale transform / load artefacts are dropped if the selection
    changed so the next /api/transform run respects the new scope.
    """
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    s = await session_store.require(session_id)
    resolved = sorted(resolve_dependencies(body.entities))
    prev = sorted(s.get("selected_entities") or [])
    changed = resolved != prev
    s["selected_entities"] = resolved
    if changed:
        s.pop("transformed", None)
        s.pop("transformer", None)
        s.pop("load_result", None)
    await _auto_save(session_id, "edit")
    return {"ok": True, "changed": changed, "selected": resolved}


@router.post("/upload")
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
            saved.append({"name": csv_name, "path": csv_path, "size": os.path.getsize(csv_path)})

    extractor = Extractor(session_dir, audit_trail)
    result = extractor.extract_all()

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

    if project_id:
        try:
            from utils import extract_cache as _ec
            _ec.write(project_id, result, session_dir)
        except Exception:
            pass

    await _auto_save(session_id, "edit")

    if project_id:
        total_rows = sum(len(rows) for rows in result.get("tables", {}).values())
        table_count = len(result.get("tables", {}))
        run = create_pipeline_run(project_id, "extract")
        finish_pipeline_run(run["id"], "done", total_rows, f"{table_count} tables extracted")
        _flush_audit_events(project_id, audit_trail, run["id"])

    return {
        "session_id": session_id,
        "files": saved,
        "preview": result.get("preview", {}),
        "inferred_schema": result.get("schema", {}),
        "stats": result.get("stats", {}),
    }
