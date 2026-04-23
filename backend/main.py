from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import os, shutil, uuid
from datetime import timezone
from typing import List

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
)
from db import (
    init_db,
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
backfill_pipeline_runs()

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
    """Aggregate stats across all projects for a user."""
    db_stats = db_get_dashboard_stats(username)
    total_rows = db_stats.get("total_rows_migrated", 0)

    # Quality score still needs state files (computed from raw data)
    projects = list_projects(username)
    quality_scores: list[float] = []
    for p in projects:
        try:
            state = load_state(p["id"])
            raw = state.get("raw", {})
            if raw.get("tables"):
                from utils.stats import StatsEngine

                engine = StatsEngine(state)
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


def _is_db_file(filename: str) -> bool:
    return _detect_db_type(filename) is not None


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

    # Create audit trail for DB extraction
    audit_trail = AuditTrail(source_type="db", source_name=file.filename)
    audit_trail.log_extraction_started(db_type, 0)

    try:
        csv_files = extract_db_to_csvs(dest, db_type, session_dir, password)
    except ImportError as e:
        audit_trail.log_extraction_error(str(e))
        raise HTTPException(400, str(e))
    except Exception as e:
        audit_trail.log_extraction_error(str(e))
        raise HTTPException(400, f"Failed to extract database: {e}")

    if not csv_files:
        audit_trail.log_extraction_error("No tables found in the database file")
        raise HTTPException(400, "No tables found in the database file")

    # Remove the original DB file so Extractor only sees CSVs
    os.remove(dest)

    # Run the standard Extractor on the generated CSVs with audit trail
    extractor = Extractor(session_dir, audit_trail)
    result = extractor.extract_all()

    audit_trail.log_extraction_completed(
        list(result.get("tables", {}).keys()),
        sum(len(rows) for rows in result.get("tables", {}).values()),
    )

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
        "audit_trail": audit_trail,
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
    raw = s.get("raw", {})
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

    transformer = Transformer(s["raw"], config, audit_trail)
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

    ddl_schema = {
        t: s["raw"]["schema"].get(t, {})
        for t in s["raw"].get("tables", {})
        if t in s.get("applied_ddl", [])
    }
    fk_edges = s.get("fk_edges", [])
    # Also collect FK edges from DDL foreign keys parsed during apply-ddl
    ddl_fks = s.get("ddl_foreign_keys", [])
    for fk in ddl_fks:
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

    engine = StatsEngine(s)
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
