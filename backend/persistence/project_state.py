import json
import os
import shutil
from pathlib import Path

from core.extract.extractor import Extractor
from utils.audit import AuditTrail
from utils import extract_cache

DATA_DIR = Path(__file__).parent / "data"

PERSIST_KEYS = [
    "phase",
    "config",
    "load_result",
    "pre_extract",
    "audit_trail",
    "excluded_tables",
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
        yield (
            "done",
            {
                "raw": {"tables": {}, "preview": {}, "schema": {}, "stats": {}},
                "extractor": None,
                "project_id": project_id,
                "audit_trail": AuditTrail(),
                "files": [],
            },
        )
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

    # Fast path: extract metadata from the cache and leave row data
    # UNLOADED. The frontend never needs row data on resume — it only
    # uses schema, stats, preview, and table-name lists. Endpoints that
    # actually need rows (transform, table-data) call the lazy
    # `_ensure_rows_loaded` helper in main.py to populate them on demand.
    if extract_cache.is_fresh(project_id, uploads_dir):
        try:
            meta = extract_cache.read_meta(project_id)
            schema = meta.get("schema", {}) or {}
            stats = meta.get("stats", {}) or {}
            preview = meta.get("preview", {}) or {}
            table_names = list(meta.get("all_table_names", []) or [])
            yield "start", {"tables": table_names, "total": len(table_names)}
            for name in table_names:
                cols = list(schema.get(name, {}).keys())
                # Fall back to first preview row's columns if schema entry
                # is empty (some sources only populate one of these).
                if not cols:
                    pv = preview.get(name) or []
                    if pv:
                        cols = list(pv[0].keys())
                rowcount = (stats.get(name) or {}).get("row_count", 0)
                yield "table_done", {
                    "name": name,
                    "rowCount": rowcount,
                    "columns": cols,
                }
            # Empty `tables` dict signals "rows not loaded yet". The lazy
            # loader fills it from disk on demand.
            raw = {
                "tables": {},
                "schema": schema,
                "stats": stats,
                "preview": preview,
            }
            # Hydrate extractor metadata so /api/table-data's edit endpoint
            # (which re-uses extractor._infer_schema) keeps working.
            extractor._raw_tables = {}
            extractor._schema = schema
            extractor._stats = stats
        except Exception:
            # Corrupt cache — fall through to a full re-extract that
            # rewrites the cache in the new format.
            raw = {}

    if not raw:
        for event_type, payload in extractor.extract_all_iter():
            if event_type == "done":
                raw = {
                    "tables": payload["tables"],
                    "schema": payload["schema"],
                    "stats": payload["stats"],
                    "preview": payload["preview"],
                }
            else:
                # Forward 'start' / 'table_done' so the caller can stream them.
                yield event_type, payload
        # Write cache for next resume. Best-effort.
        try:
            extract_cache.write(project_id, raw, uploads_dir)
        except Exception:
            pass

    session: dict = {
        "raw": raw,
        "extractor": extractor,
        "project_id": project_id,
        "audit_trail": audit_trail,
    }

    for key in PERSIST_KEYS:
        if key == "audit_trail":
            # We already reconstructed the live AuditTrail object above
            # from saved["audit_trail"]. Don't overwrite it with the raw
            # dict — Transformer.run() calls .log_*() methods on it.
            continue
        if key in saved:
            session[key] = saved[key]

    session["files"] = [
        {
            "name": fname,
            "path": os.path.join(uploads_dir, fname),
            "size": os.path.getsize(os.path.join(uploads_dir, fname)),
        }
        for fname in os.listdir(uploads_dir)
        if os.path.isfile(os.path.join(uploads_dir, fname))
    ]

    # NOTE: we used to re-run the full transformer here when resuming a
    # project on the transform/load phase. For a 100+-table project that's
    # 10–30 seconds wasted on every page open. The transformed dataset is
    # easy to recompute from saved config + raw, so we defer it: the
    # frontend's transform stage will trigger /api/transform if it needs
    # the data, and /api/load lazily reruns the transformer when it sees
    # `transformed` is missing. See _ensure_transformed in main.py.

    yield "done", session


def delete_project_files(project_id: str) -> None:
    shutil.rmtree(project_dir(project_id), ignore_errors=True)
