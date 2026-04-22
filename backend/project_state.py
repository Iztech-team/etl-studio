import json
import os
import shutil
from pathlib import Path

from core.extractor import Extractor
from core.transformer import Transformer

DATA_DIR = Path(__file__).parent / "data"

PERSIST_KEYS = [
    "phase",
    "ddl_schema",
    "applied_ddl",
    "config",
    "validation",
    "load_result",
    "pre_extract",
]

PHASE_ORDER = ["upload", "edit", "configure", "validate", "transform", "load", "stats"]


def project_dir(project_id: str) -> str:
    return str(DATA_DIR / "projects" / project_id)


def project_uploads_dir(project_id: str) -> str:
    return str(DATA_DIR / "projects" / project_id / "uploads")


def project_outputs_dir(project_id: str) -> str:
    return str(DATA_DIR / "projects" / project_id / "outputs")


def state_path(project_id: str) -> str:
    return str(DATA_DIR / "projects" / project_id / "state.json")


def ensure_project_dirs(project_id: str) -> None:
    os.makedirs(project_uploads_dir(project_id), exist_ok=True)
    os.makedirs(project_outputs_dir(project_id), exist_ok=True)


def save_state(project_id: str, session: dict) -> None:
    state = {key: session[key] for key in PERSIST_KEYS if key in session}
    with open(state_path(project_id), "w", encoding="utf-8") as f:
        json.dump(state, f, default=str)


def load_state(project_id: str) -> dict:
    uploads_dir = project_uploads_dir(project_id)

    extractor = Extractor(uploads_dir)
    raw = extractor.extract_all()

    with open(state_path(project_id), "r", encoding="utf-8") as f:
        saved = json.load(f)

    session: dict = {"raw": raw, "extractor": extractor, "project_id": project_id}

    for key in PERSIST_KEYS:
        if key in saved:
            session[key] = saved[key]

    applied_ddl = session.get("applied_ddl")
    ddl_schema = session.get("ddl_schema")
    if applied_ddl and ddl_schema:
        for table in applied_ddl:
            if table in ddl_schema:
                raw["schema"][table] = ddl_schema[table]

    files = [
        fname
        for fname in os.listdir(uploads_dir)
        if os.path.isfile(os.path.join(uploads_dir, fname))
    ]
    session["files"] = files

    phase = session.get("phase", "upload")
    phase_index = PHASE_ORDER.index(phase) if phase in PHASE_ORDER else 0
    transform_index = PHASE_ORDER.index("transform")

    if phase_index >= transform_index:
        config = session.get("config", {})
        transformer = Transformer(raw, config)
        session["transformed"] = transformer.run()
        session["transformer"] = transformer

    return session


def delete_project_files(project_id: str) -> None:
    shutil.rmtree(project_dir(project_id), ignore_errors=True)
