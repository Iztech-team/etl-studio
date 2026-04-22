from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import os, shutil, uuid
from typing import List

from core.extractor import Extractor
from core.transformer import Transformer
from core.loader import Loader
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
)
from db import (
    init_db,
    create_project,
    list_projects,
    get_project,
    rename_project,
    delete_project,
    update_project_phase,
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

# In-memory session store (keyed by session_id)
sessions: dict = {}


def _auto_save(session_id: str, phase: str) -> None:
    """If the session is linked to a project, persist state and update phase."""
    s = sessions.get(session_id)
    if not s or not s.get("project_id"):
        return
    project_id = s["project_id"]
    s["phase"] = phase
    save_state(project_id, s)
    update_project_phase(project_id, phase)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


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


@app.post("/api/projects/{project_id}/resume")
async def resume_project(project_id: str):
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    session_id = str(uuid.uuid4())
    session = load_state(project_id)
    session["project_id"] = project_id
    sessions[session_id] = session
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
    }


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


@app.post("/api/pre-extract", response_model=PreExtractResponse)
async def pre_extract(
    file: UploadFile = File(...),
    password: str | None = Form(None),
    project_id: str | None = Form(None),
):
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
        while chunk := await file.read(8 * 1024 * 1024):  # 8 MB chunks
            out.write(chunk)

    file_size = os.path.getsize(dest)
    file_info = PreExtractFileInfo(
        name=file.filename,
        path=dest,
        size=file_size,
        db_type=db_type,
    )

    # Extract tables from DB into CSVs
    from core.db_extractor import extract_db_to_csvs

    try:
        csv_files = extract_db_to_csvs(dest, db_type, session_dir, password)
    except ImportError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"Failed to extract database: {e}")

    if not csv_files:
        raise HTTPException(400, "No tables found in the database file")

    # Remove the original DB file so Extractor only sees CSVs
    os.remove(dest)

    # Run the standard Extractor on the generated CSVs
    extractor = Extractor(session_dir)
    result = extractor.extract_all()

    saved_files = [
        {
            "name": f,
            "path": os.path.join(session_dir, f),
            "size": os.path.getsize(os.path.join(session_dir, f)),
        }
        for f in csv_files
    ]

    sessions[session_id] = {
        "project_id": project_id,
        "pre_extract": {
            "file": file_info.dict(),
            "password": password is not None,
            "db_type": db_type,
        },
        "extractor": extractor,
        "raw": result,
        "files": saved_files,
        "ddl_schema": result.get("ddl_schema", {}),
        "applied_ddl": [],
    }

    _auto_save(session_id, "pre-extract")
    return PreExtractResponse(
        ok=True,
        session_id=session_id,
        file=file_info,
        tables_extracted=list(result.get("tables", {}).keys()),
        csv_files=csv_files,
        preview=result.get("preview", {}),
        inferred_schema=result.get("schema", {}),
        stats=result.get("stats", {}),
        ddl_schema=result.get("ddl_schema", {}),
    )


@app.post("/api/pre-extract-select/{session_id}")
async def pre_extract_select(session_id: str, body: ApplyDDLRequest):
    """Keep only selected tables in the session, remove the rest."""
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")
    s = sessions[session_id]
    raw = s.get("raw", {})
    selected = set(body.tables)
    all_tables = set(raw.get("tables", {}).keys())
    removed = all_tables - selected

    # Remove from raw tables, schema, stats, preview
    for table in removed:
        raw.get("tables", {}).pop(table, None)
        raw.get("schema", {}).pop(table, None)
        raw.get("stats", {}).pop(table, None)
        raw.get("preview", {}).pop(table, None)

    # Remove CSV files for deselected tables
    if s.get("project_id"):
        session_dir = project_uploads_dir(s["project_id"])
    else:
        session_dir = os.path.join(GUEST_DIR, session_id)
    s["files"] = [
        f for f in s.get("files", []) if f["name"].rsplit(".", 1)[0] in selected
    ]
    for table in removed:
        csv_path = os.path.join(session_dir, f"{table}.csv")
        if os.path.exists(csv_path):
            os.remove(csv_path)

    _auto_save(session_id, "edit")
    return {
        "ok": True,
        "kept": sorted(selected & all_tables),
        "removed": sorted(removed),
    }


@app.post("/api/upload")
async def upload_files(
    files: List[UploadFile] = File(...),
    project_id: str | None = Form(None),
):
    session_id = str(uuid.uuid4())
    if project_id:
        session_dir = project_uploads_dir(project_id)
    else:
        session_dir = os.path.join(GUEST_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)

    saved = []
    for f in files:
        dest = os.path.join(session_dir, f.filename)
        with open(dest, "wb") as out:
            shutil.copyfileobj(f.file, out)
        saved.append({"name": f.filename, "path": dest, "size": os.path.getsize(dest)})

    extractor = Extractor(session_dir)
    result = extractor.extract_all()
    sessions[session_id] = {
        "project_id": project_id,
        "extractor": extractor,
        "raw": result,
        "files": saved,
        "ddl_schema": result.get("ddl_schema", {}),
        "applied_ddl": [],
    }

    _auto_save(session_id, "edit")
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
    raw = s.get("raw", {})
    return {
        "tables": raw.get("tables", {}),
        "schema": raw.get("schema", {}),
    }


@app.post("/api/table-data/{session_id}", response_model=EditDataResponse)
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
    return EditDataResponse(ok=True, stats=stats)


@app.post("/api/configure/{session_id}", response_model=ConfigureResponse)
async def configure(session_id: str, body: ConfigureRequest):
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")
    sessions[session_id]["config"] = body.dict()
    _auto_save(session_id, "configure")
    return ConfigureResponse(ok=True, message="Configuration saved")


@app.post("/api/upload-ddl/{session_id}", response_model=DDLUploadResponse)
async def upload_ddl(session_id: str, files: List[UploadFile] = File(...)):
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")

    from utils.sql_parser import SQLParser

    s = sessions[session_id]
    ddl_schema = s.get("ddl_schema", {})
    data_tables = set(s["raw"].get("tables", {}).keys())

    for f in files:
        content = (await f.read()).decode("utf-8", errors="replace")
        parser = SQLParser(content)
        parsed = parser.parse_ddl()
        ddl_schema.update(parsed)

    s["ddl_schema"] = ddl_schema
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
    results = []

    for table in body.tables:
        errors = []

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
    transformer = Transformer(s["raw"], s.get("config", {}))
    result = transformer.run()
    sessions[session_id]["transformed"] = result
    sessions[session_id]["transformer"] = transformer
    _auto_save(session_id, "transform")
    return TransformResponse(**result)


@app.post("/api/load/{session_id}", response_model=LoadResponse)
async def load(session_id: str, body: LoadRequest):
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")
    s = sessions[session_id]
    if "transformed" not in s:
        raise HTTPException(400, "Run transform first")

    if s.get("project_id"):
        out_dir = project_outputs_dir(s["project_id"])
    else:
        out_dir = os.path.join(OUTPUT_DIR, session_id)
    os.makedirs(out_dir, exist_ok=True)

    ddl_schema = {
        t: s["raw"]["schema"].get(t, {})
        for t in s["raw"].get("tables", {})
        if t in s.get("applied_ddl", [])
    }
    loader = Loader(s["transformed"], body.dict(), out_dir, ddl_schema=ddl_schema)
    result = loader.run()
    sessions[session_id]["load_result"] = result
    _auto_save(session_id, "load")
    return LoadResponse(**result)


@app.get("/api/stats/{session_id}", response_model=StatsResponse)
async def stats(session_id: str):
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")
    s = sessions[session_id]
    from utils.stats import StatsEngine

    engine = StatsEngine(s)
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
