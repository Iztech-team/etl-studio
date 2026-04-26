import json
import os
import shutil
from pathlib import Path

from core.extractor import Extractor
from core.transformer import Transformer
from utils.audit import AuditTrail

DATA_DIR = Path(__file__).parent / "data"

PERSIST_KEYS = [
    "phase",
    "ddl_schema",
    "applied_ddl",
    "config",
    "load_result",
    "pre_extract",
    "audit_trail",
]

PHASE_ORDER = ["upload", "edit", "configure", "transform", "load", "stats"]


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
    # AuditTrail is not directly JSON-serialisable. json.dump's default=str
    # would otherwise turn it into its repr ("<utils.audit.AuditTrail ...>"),
    # which load_state can't read back. Convert to a plain dict here.
    if "audit_trail" in state and isinstance(state["audit_trail"], AuditTrail):
        state["audit_trail"] = state["audit_trail"].to_dict()
    with open(state_path(project_id), "w", encoding="utf-8") as f:
        json.dump(state, f, default=str)


def load_state(project_id: str) -> dict:
    """Synchronous wrapper around load_state_iter — drains the generator
    and returns just the final session. Use load_state_iter directly when
    you want to surface per-table progress."""
    session: dict = {}
    for event_type, payload in load_state_iter(project_id):
        if event_type == "done":
            session = payload
    return session


def load_state_iter(project_id: str):
    """Generator version. Yields ('start', ...), ('table_done', ...) for
    each CSV/sheet/SQL relation parsed, then ('done', session) with the
    fully assembled session dict (matching the old load_state return
    shape)."""
    uploads_dir = project_uploads_dir(project_id)
    state_file = state_path(project_id)

    if not os.path.exists(state_file):
        # Brand-new project with no upload yet — emit a single empty
        # 'done' so the streaming endpoint has the same protocol shape.
        yield "start", {"tables": [], "total": 0}
        yield "done", {
            "raw": {"tables": {}, "preview": {}, "schema": {}, "stats": {}},
            "extractor": None,
            "project_id": project_id,
            "audit_trail": AuditTrail(),
            "files": [],
        }
        return

    with open(state_file, "r", encoding="utf-8") as f:
        saved = json.load(f)

    audit_trail = AuditTrail()
    audit_data = saved.get("audit_trail")
    if isinstance(audit_data, dict):
        audit_trail.source_type = audit_data.get("source_type", "upload")
        audit_trail.source_name = audit_data.get("source_name", "")
        audit_trail.created_at = audit_data.get("created_at", "")
        audit_trail.events = audit_data.get("events", [])
        audit_trail.stats = audit_data.get("stats", {})

    extractor = Extractor(uploads_dir, audit_trail)
    raw: dict = {}
    for event_type, payload in extractor.extract_all_iter():
        if event_type == "done":
            raw = {
                "tables": payload["tables"],
                "schema": payload["schema"],
                "stats": payload["stats"],
                "preview": payload["preview"],
                "ddl_schema": payload["ddl_schema"],
            }
        else:
            # Forward 'start' / 'table_done' so the caller can stream them.
            yield event_type, payload

    session: dict = {
        "raw": raw,
        "extractor": extractor,
        "project_id": project_id,
        "audit_trail": audit_trail,
    }

    for key in PERSIST_KEYS:
        if key in saved:
            session[key] = saved[key]

    applied_ddl = session.get("applied_ddl")
    ddl_schema = session.get("ddl_schema")
    if applied_ddl and ddl_schema:
        for table in applied_ddl:
            if table in ddl_schema:
                raw["schema"][table] = ddl_schema[table]

    session["files"] = [
        {
            "name": fname,
            "path": os.path.join(uploads_dir, fname),
            "size": os.path.getsize(os.path.join(uploads_dir, fname)),
        }
        for fname in os.listdir(uploads_dir)
        if os.path.isfile(os.path.join(uploads_dir, fname))
    ]

    phase = session.get("phase", "upload")
    phase_index = PHASE_ORDER.index(phase) if phase in PHASE_ORDER else 0
    transform_index = PHASE_ORDER.index("transform")

    if phase_index >= transform_index:
        config = session.get("config", {})
        transformer = Transformer(raw, config, audit_trail)
        session["transformed"] = transformer.run()
        session["transformer"] = transformer

    yield "done", session


def delete_project_files(project_id: str) -> None:
    shutil.rmtree(project_dir(project_id), ignore_errors=True)
