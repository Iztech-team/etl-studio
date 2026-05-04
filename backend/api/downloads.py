import io
import os
import zipfile

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from persistence.db import get_project
from persistence.project_state import project_dir, project_outputs_dir
from startup import OUTPUT_DIR
from state import session_store

router = APIRouter()


def _safe_path(base_dir: str, filename: str) -> str:
    """Resolve filename under base_dir; raise if it escapes the directory."""
    safe_dir = os.path.realpath(base_dir)
    path = os.path.realpath(os.path.join(safe_dir, filename))
    if not path.startswith(safe_dir + os.sep):
        raise HTTPException(400, "Invalid filename")
    if not os.path.exists(path):
        raise HTTPException(404, "File not found")
    return path


def _zip_dir(dir_path: str, zip_filename: str) -> StreamingResponse:
    files = sorted(
        f for f in os.listdir(dir_path) if os.path.isfile(os.path.join(dir_path, f))
    )
    if not files:
        raise HTTPException(404, "No outputs to bundle")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in files:
            zf.write(os.path.join(dir_path, name), arcname=name)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
    )


@router.get("/download/{session_id}/{filename}")
async def download(session_id: str, filename: str):
    s = await session_store.get(session_id)
    if s and s.get("project_id"):
        base_dir = project_outputs_dir(s["project_id"])
    else:
        base_dir = os.path.join(OUTPUT_DIR, session_id)
    path = _safe_path(base_dir, filename)
    return FileResponse(path, filename=os.path.basename(path))


@router.get("/projects/{project_id}/outputs")
async def list_project_outputs(project_id: str):
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    out_dir = project_outputs_dir(project_id)
    if not os.path.isdir(out_dir):
        return {"files": []}
    files = [f for f in os.listdir(out_dir) if os.path.isfile(os.path.join(out_dir, f))]
    return {"files": sorted(files)}


@router.get("/projects/{project_id}/download/{filename}")
async def download_project_file(project_id: str, filename: str):
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    path = _safe_path(project_outputs_dir(project_id), filename)
    return FileResponse(path, filename=os.path.basename(path))


@router.get("/projects/{project_id}/download-all")
async def download_all_project_files(project_id: str):
    """Bundle every file in the project's outputs/ into a single .zip."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    out_dir = project_outputs_dir(project_id)
    if not os.path.isdir(out_dir):
        raise HTTPException(404, "No outputs to bundle")
    project_name = project.get("name") or project_id
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in project_name)
    return _zip_dir(out_dir, f"{safe_name}_outputs.zip")


@router.get("/download-all/{session_id}")
async def download_all_session_files(session_id: str):
    """Same as the project variant but for guest sessions without a project_id."""
    s = await session_store.get(session_id)
    if s and s.get("project_id"):
        base_dir = project_outputs_dir(s["project_id"])
    else:
        base_dir = os.path.join(OUTPUT_DIR, session_id)
    if not os.path.isdir(base_dir):
        raise HTTPException(404, "No outputs to bundle")
    return _zip_dir(base_dir, f"session_{session_id[:8]}_outputs.zip")


@router.get("/projects/{project_id}/transform-partial")
async def list_transform_partial(project_id: str):
    """List per-target JSON files persisted incrementally during transform.
    Useful for picking up partial work when transform crashed mid-run."""
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


@router.get("/projects/{project_id}/transform-partial/{filename}")
async def download_transform_partial(project_id: str, filename: str):
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    path = _safe_path(
        os.path.join(project_dir(project_id), "transform_partial"), filename
    )
    return FileResponse(path, filename=os.path.basename(path))
