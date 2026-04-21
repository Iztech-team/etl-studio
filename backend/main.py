from fastapi import FastAPI, UploadFile, File, HTTPException
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
    ValidateResponse,
    TransformResponse,
    LoadRequest,
    LoadResponse,
    StatsResponse,
    DDLUploadResponse,
    ApplyDDLRequest,
    ApplyDDLResponse,
    ApplyDDLTableResult,
)

app = FastAPI(title="ETL Studio", version="1.0.0")

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

# In-memory session store (keyed by session_id)
sessions: dict = {}


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/upload")
async def upload_files(files: List[UploadFile] = File(...)):
    session_id = str(uuid.uuid4())
    session_dir = os.path.join(UPLOAD_DIR, session_id)
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
        "extractor": extractor,
        "raw": result,
        "files": saved,
        "ddl_schema": result.get("ddl_schema", {}),
        "applied_ddl": [],
    }

    return {
        "session_id": session_id,
        "files": saved,
        "preview": result.get("preview", {}),
        "inferred_schema": result.get("schema", {}),
        "stats": result.get("stats", {}),
        "ddl_schema": result.get("ddl_schema", {}),
    }


@app.post("/api/configure/{session_id}", response_model=ConfigureResponse)
async def configure(session_id: str, body: ConfigureRequest):
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")
    sessions[session_id]["config"] = body.dict()
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


@app.get("/api/validate/{session_id}", response_model=ValidateResponse)
async def validate(session_id: str):
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")
    s = sessions[session_id]
    extractor: Extractor = s["extractor"]
    config = s.get("config", {})
    result = extractor.validate(config)
    sessions[session_id]["validation"] = result
    return ValidateResponse(**result)


@app.get("/api/transform/{session_id}", response_model=TransformResponse)
async def transform(session_id: str):
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")
    s = sessions[session_id]
    transformer = Transformer(s["raw"], s.get("config", {}))
    result = transformer.run()
    sessions[session_id]["transformed"] = result
    sessions[session_id]["transformer"] = transformer
    return TransformResponse(**result)


@app.post("/api/load/{session_id}", response_model=LoadResponse)
async def load(session_id: str, body: LoadRequest):
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")
    s = sessions[session_id]
    if "transformed" not in s:
        raise HTTPException(400, "Run transform first")

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
    safe_dir = os.path.realpath(os.path.join(OUTPUT_DIR, session_id))
    path = os.path.realpath(os.path.join(safe_dir, filename))
    if not path.startswith(safe_dir + os.sep):
        raise HTTPException(400, "Invalid filename")
    if not os.path.exists(path):
        raise HTTPException(404, "File not found")
    return FileResponse(path, filename=os.path.basename(path))
