import asyncio
import json
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from helpers import _resume_payload
from models.project_schemas import (
    CreateProjectRequest,
    ProjectListResponse,
    ProjectResponse,
    RenameProjectRequest,
)
from persistence.db import (
    create_project,
    delete_project,
    get_project,
    list_projects,
    rename_project,
)
from persistence.project_state import (
    delete_project_files,
    ensure_project_dirs,
    save_state,
)
from state import session_store

router = APIRouter()


@router.post("/projects", response_model=ProjectResponse)
async def create_project_endpoint(body: CreateProjectRequest):
    try:
        project = create_project(body.name, body.username)
    except ValueError as e:
        raise HTTPException(409, str(e))
    ensure_project_dirs(project["id"])
    return ProjectResponse(**project)


@router.get("/projects", response_model=ProjectListResponse)
async def list_projects_endpoint(username: str):
    projects = list_projects(username)
    return ProjectListResponse(projects=[ProjectResponse(**p) for p in projects])


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project_endpoint(project_id: str):
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return ProjectResponse(**project)


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
async def rename_project_endpoint(project_id: str, body: RenameProjectRequest):
    try:
        rename_project(project_id, body.name)
    except ValueError as e:
        raise HTTPException(409, str(e))
    project = get_project(project_id)
    return ProjectResponse(**project)


@router.delete("/projects/{project_id}")
async def delete_project_endpoint(project_id: str):
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    to_remove = [
        sid for sid, s in (await session_store.all_sessions()).items()
        if s.get("project_id") == project_id
    ]
    for sid in to_remove:
        await session_store.remove(sid)
    delete_project_files(project_id)
    delete_project(project_id)
    return {"ok": True}


@router.post("/projects/{project_id}/resume")
async def resume_project(project_id: str):
    """Streaming NDJSON: per-table progress while CSVs parse.

    Events:
      {"event": "start", "project": {...}, "tables": [name, ...], "total": N}
      {"event": "table_done", "name": "T", "rowCount": 1234, "columns": [...]}
      ...
      {"event": "done", ...resume payload}
      OR {"event": "error", "message": "..."}

    Warm path emits everything at once so the UI ticks the same regardless.
    """
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    from persistence.project_state import load_state_iter

    def encode(obj: dict) -> bytes:
        return (json.dumps(obj, ensure_ascii=False, default=str) + "\n").encode("utf-8")

    async def encode_async(obj: dict) -> bytes:
        # Big payloads (final 'done' carrying schema/preview) get encoded on
        # a worker thread so json.dumps doesn't freeze the event loop.
        return await asyncio.to_thread(encode, obj)

    async def stream():
        try:
            for sid, sess in (await session_store.all_sessions()).items():
                if sess.get("project_id") == project_id and sess.get("raw"):
                    tables = sess["raw"].get("tables", {})
                    table_names = list(tables.keys())
                    yield encode({
                        "event": "start", "project": project,
                        "tables": table_names, "total": len(table_names), "warm": True,
                    })
                    await asyncio.sleep(0)
                    table_done_count_warm = 0
                    for name in table_names:
                        rows = tables.get(name, [])
                        yield encode({
                            "event": "table_done", "name": name,
                            "rowCount": len(rows),
                            "columns": list(rows[0].keys()) if rows else [],
                        })
                        # Pace every 4 events by 2ms so the wire/UI advances
                        # visibly instead of TCP-coalescing into one chunk.
                        table_done_count_warm += 1
                        if table_done_count_warm % 4 == 0:
                            await asyncio.sleep(0.002)
                        else:
                            await asyncio.sleep(0)
                    final_bytes = await encode_async(
                        {"event": "done", **_resume_payload(project, sid, sess)}
                    )
                    yield final_bytes
                    return

            # Cold path: drive load_state_iter on a worker thread.
            session_id = str(uuid.uuid4())
            session: dict = {}

            SENTINEL = object()
            it = load_state_iter(project_id)

            def safe_next():
                try:
                    return next(it)
                except StopIteration:
                    return SENTINEL

            project_emitted = False
            table_done_count = 0
            while True:
                event = await asyncio.to_thread(safe_next)
                if event is SENTINEL:
                    break
                event_type, payload = event
                if event_type == "done":
                    session = payload
                    continue
                if event_type == "start" and not project_emitted:
                    payload = {"project": project, **payload}
                    project_emitted = True
                yield encode({"event": event_type, **payload})
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


@router.post("/projects/{project_id}/save")
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
