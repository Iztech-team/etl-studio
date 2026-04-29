from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from core.extract.extractor import Extractor
from helpers import _auto_save, _excluded_set, _visible_raw
from models.schemas import EditDataRequest
from persistence.project_state import project_uploads_dir
from state import session_store
from utils import extract_cache

router = APIRouter()


def _list_cached_tables(project_id: str) -> List[str]:
    """Return the table names recorded in the cache metadata, or [] if missing."""
    try:
        meta = extract_cache.read_meta(project_id)
        return list(meta.get("all_table_names", []) or [])
    except Exception:
        return []


def _ensure_rows_loaded(
    session: Dict[str, Any], tables: Optional[List[str]] = None
) -> None:
    """Lazy-load CSV rows from the extract cache (or re-parse from disk).

    Resume populates the session with metadata only, so opening a project
    is fast even on a 5 GB dataset. Endpoints that need the rows call this
    helper before reading session['raw']['tables'].

    `tables`: optional whitelist of source-table names to load. None means
    load every table.
    """
    raw = session.setdefault("raw", {"tables": {}})
    raw_tables = raw.setdefault("tables", {})

    project_id = session.get("project_id")
    if not project_id:
        return

    uploads_dir = project_uploads_dir(project_id)

    if tables is None:
        wanted = list(raw.get("schema", {}).keys()) or _list_cached_tables(project_id)
    else:
        wanted = list(tables)
    # Treat both 'missing key' and 'present-but-empty' as needs-loading.
    # The streaming CSV extract path puts an empty-list placeholder in
    # raw["tables"][name] (rows live on disk in JSONL), so checking
    # `t not in raw_tables` would skip the lazy-load entirely.
    needed = [t for t in wanted if not raw_tables.get(t)]
    if not needed:
        return

    if extract_cache.is_fresh(project_id, uploads_dir):
        for name in needed:
            rows = extract_cache.read_table_rows(project_id, name)
            if rows is not None:
                raw_tables[name] = rows
        if all(t in raw_tables for t in needed):
            extractor = session.get("extractor")
            if extractor is not None:
                extractor._raw_tables = raw_tables
            return

    # Fallback: re-parse the CSVs from disk and rewrite the cache.
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


@router.get("/table-data/{session_id}")
async def get_table_data(session_id: str):
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    s = await session_store.require(session_id)
    _ensure_rows_loaded(s)
    raw = _visible_raw(s)
    return {"tables": raw.get("tables", {}), "schema": raw.get("schema", {})}


@router.get("/table-data/{session_id}/{table_name}")
async def get_table_page(
    session_id: str, table_name: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
):
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    s = await session_store.require(session_id)
    if table_name in _excluded_set(s):
        raise HTTPException(404, f"Table '{table_name}' is excluded")
    _ensure_rows_loaded(s, [table_name])
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
        "page": page, "page_size": page_size,
        "total_rows": total,
        "total_pages": max(1, (total + page_size - 1) // page_size),
    }


@router.post("/table-data/{session_id}")
async def save_table_data(session_id: str, body: EditDataRequest):
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    s = await session_store.require(session_id)
    _ensure_rows_loaded(s)
    raw = s.get("raw", {})

    for table, rows in body.tables.items():
        if table not in raw.get("tables", {}):
            continue
        raw["tables"][table] = rows

    stats = {table: {"row_count": len(rows)} for table, rows in raw.get("tables", {}).items()}
    raw["stats"] = stats
    raw["preview"] = {t: rows[:5] for t, rows in raw.get("tables", {}).items()}

    extractor: Extractor = s["extractor"]
    extractor._raw_tables = raw["tables"]
    extractor._infer_schema()
    raw["schema"] = extractor._schema

    await _auto_save(session_id, "edit")
    return {"ok": True, "stats": stats, "preview": raw["preview"], "schema": raw["schema"]}


@router.get("/session/{session_id}/config")
async def get_session_config(session_id: str):
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    return (await session_store.require(session_id)).get("config", {})
