import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from api.tables import _ensure_rows_loaded
from core.load.loader import Loader
from core.strategies import (
    StrategyResult,
    default_strategy_name,
    get_strategy,
)
from core.strategies.erpnext.writer import write_frappe_csvs
from helpers import (
    _auto_save,
    _excluded_set,
    _flush_audit_events,
    _visible_raw,
    _visible_session,
)
from models.schemas import (
    LoadRequest,
    LoadResponse,
    StatsResponse,
    TransformResponse,
)
from persistence.db import create_pipeline_run, finish_pipeline_run
from persistence.project_state import project_outputs_dir
from startup import OUTPUT_DIR
from state import session_store

router = APIRouter()


def _legacy_tables(s: Dict[str, Any]) -> Dict[str, List[dict]]:
    raw = _visible_raw(s)
    return raw.get("tables", {}) or {}


def _passthrough_result(legacy: Dict[str, List[dict]]) -> Dict[str, Any]:
    """Identity transform — used while the strategy is still being wired.

    Each domain slice incrementally adds doctypes to the strategy's output;
    until those cover all source data, falling back here keeps `/api/load`
    and `/api/stats` operational.
    """
    total = sum(len(rows or []) for rows in legacy.values())
    return _result_shape(
        tables=legacy,
        total_rows=total,
        warnings=[],
        note="passthrough",
    )


def _strategy_result(
    legacy: Dict[str, List[dict]],
    strategy_name: str,
    config: Dict[str, Any],
    staging_dir: Optional[str] = None,
) -> Dict[str, Any]:
    if staging_dir:
        _clear_dir(staging_dir)
    strategy = get_strategy(strategy_name)
    out: StrategyResult = strategy.transform(legacy, config, staging_dir=staging_dir)
    out.close_files()
    counts = out.doctype_counts()
    if not counts:
        return _passthrough_result(legacy)
    total = sum(counts.values())
    audit_rows = out.output_tables.get("__audit_report__") or []
    checklist_rows = out.output_tables.get("__migration_setup_checklist__") or []
    # In disk mode we don't surface real doctype data through `tables`
    # (it lives on disk via staging_dir); pass an empty dict but keep
    # output_doctypes and the staging_dir on the result so the writer
    # can find the JSONL files later.
    return _result_shape(
        tables={} if staging_dir else {
            k: v for k, v in out.output_tables.items() if not k.startswith("__")
        },
        total_rows=total,
        warnings=[w.get("message", "") for w in out.warnings],
        note=f"strategy={strategy_name}",
        stats=out.stats,
        errors=out.errors,
        strategy_name=strategy_name,
        strategy_label=getattr(strategy, "label", strategy_name),
        audit_report=audit_rows[0] if audit_rows else None,
        setup_checklist_md=(checklist_rows[0] or {}).get("content")
                           if checklist_rows else None,
        output_doctypes=counts,
        staging_dir=staging_dir,
    )


def _result_shape(
    tables: Dict[str, List[dict]],
    total_rows: int,
    warnings: List[str],
    note: str,
    stats: Optional[Dict[str, int]] = None,
    errors: Optional[List[dict]] = None,
    strategy_name: Optional[str] = None,
    strategy_label: Optional[str] = None,
    audit_report: Optional[Dict[str, Any]] = None,
    setup_checklist_md: Optional[str] = None,
    output_doctypes: Optional[Dict[str, int]] = None,
    staging_dir: Optional[str] = None,
) -> Dict[str, Any]:
    counts = output_doctypes or {t: len(rows) for t, rows in tables.items()}
    return {
        "ok": True,
        "tables": tables,
        "tables_transformed": len(counts) or len(tables),
        "total_rows": total_rows,
        "encoding_conversions": 0,
        "type_conversions": 0,
        "reference_mappings": 0,
        "null_normalizations": 0,
        "dedup_removed": 0,
        "warnings": warnings,
        "exceptions": {},
        "preview": {t: (rows or [])[:5] for t, rows in tables.items()},
        "strategy_note": note,
        "strategy_name": strategy_name,
        "strategy_label": strategy_label,
        "strategy_stats": stats or {},
        "strategy_errors": errors or [],
        "output_doctypes": counts,
        "audit_report": audit_report,
        "setup_checklist_md": setup_checklist_md,
        "staging_dir": staging_dir,
    }


def _resolve_strategy(s: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    name = s.get("strategy_name") or default_strategy_name()
    config = s.get("strategy_config") or {}
    return name, config


def _run_transform(s: Dict[str, Any]) -> Dict[str, Any]:
    legacy = _legacy_tables(s)
    name, config = _resolve_strategy(s)
    staging_dir = _transform_staging_dir(s)
    result = _strategy_result(legacy, name, config, staging_dir=staging_dir)
    # Source tables can be freed now that the strategy has consumed them
    # — they're still on disk via the JSONL extract cache and lazy-load
    # if the user re-runs transform. Frees ~1-3GB of RSS for big imports.
    raw = s.get("raw") or {}
    if isinstance(raw.get("tables"), dict):
        for tname in list(raw["tables"].keys()):
            raw["tables"][tname] = []
    return result


def _transform_staging_dir(s: Dict[str, Any]) -> Optional[str]:
    """Per-session/project dir where strategy emits stream as JSONL."""
    project_id = s.get("project_id")
    if project_id:
        from persistence.project_state import project_dir
        return os.path.join(project_dir(project_id), "_transform_out")
    return None


def _clear_dir(path: str) -> None:
    if not os.path.isdir(path):
        return
    for entry in os.listdir(path):
        full = os.path.join(path, entry)
        if os.path.isfile(full):
            try:
                os.remove(full)
            except OSError:
                pass


async def _ensure_transformed(session_id: str) -> None:
    s = await session_store.require(session_id)
    if "transformed" in s and s["transformed"]:
        return
    _ensure_rows_loaded(s)
    s["transformed"] = _run_transform(s)


@router.get("/transform/{session_id}", response_model=TransformResponse)
async def transform(session_id: str):
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    s = await session_store.require(session_id)
    project_id = s.get("project_id")
    run = create_pipeline_run(project_id, "transform") if project_id else None
    audit_trail = s.get("audit_trail")

    _ensure_rows_loaded(s)
    result = _run_transform(s)
    s["transformed"] = result
    s["fk_edges"] = []
    await _auto_save(session_id, "transform")
    if run and project_id:
        finish_pipeline_run(
            run["id"],
            "done",
            result["total_rows"],
            result.get("strategy_note", ""),
        )
        if audit_trail:
            _flush_audit_events(project_id, audit_trail, run["id"])
    return TransformResponse(**_response_payload(result))


def _response_payload(result: Dict[str, Any]) -> Dict[str, Any]:
    """Trim session-only keys from the public response.

    The session keeps `tables` (heavy) and `strategy_errors` (internal).
    The wire response carries summaries and the audit/checklist artifacts.
    """
    keep = {
        "ok", "tables_transformed", "total_rows",
        "encoding_conversions", "type_conversions", "reference_mappings",
        "null_normalizations", "dedup_removed",
        "warnings", "preview",
        "strategy_name", "strategy_label", "strategy_stats",
        "output_doctypes", "audit_report", "setup_checklist_md",
    }
    return {k: v for k, v in result.items() if k in keep}


@router.post("/load/{session_id}", response_model=LoadResponse)
async def load(session_id: str, body: LoadRequest):
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    s = await session_store.require(session_id)
    if "transformed" not in s or not s["transformed"]:
        await _ensure_transformed(session_id)

    project_id = s.get("project_id")
    run = create_pipeline_run(project_id, "load") if project_id else None

    out_dir = (
        project_outputs_dir(project_id)
        if project_id
        else os.path.join(OUTPUT_DIR, session_id)
    )
    os.makedirs(out_dir, exist_ok=True)
    _clean_output_dir(out_dir)

    excluded = _excluded_set(s)
    fk_edges: List[tuple] = [
        edge for edge in s.get("fk_edges", [])
        if edge[0] not in excluded and edge[1] not in excluded
    ]

    if body.output_format == "frappe":
        result = _run_frappe_writer(s, out_dir)
    else:
        loader = Loader(s["transformed"], body.dict(), out_dir, fk_edges=fk_edges)
        result = loader.run()
    s["load_result"] = result
    await _auto_save(session_id, "load")
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


def _clean_output_dir(out_dir: str) -> None:
    """Remove any files left from a previous load run.

    Each /api/load call produces a fresh, self-contained set of files;
    leaving stragglers from a prior format (json/csv/sql/frappe) would
    leak into the download zip. We only remove files at the top level —
    subdirs like `transform_partial/` live under `project_dir`, not
    `outputs/`, so they are never touched here.
    """
    if not os.path.isdir(out_dir):
        return
    for entry in os.listdir(out_dir):
        path = os.path.join(out_dir, entry)
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass


def _run_frappe_writer(session: Dict[str, Any], out_dir: str) -> Dict[str, Any]:
    """Format strategy output as Frappe Data Import CSVs.

    Reads the strategy's output_tables (already shaped per ERPnext doctype
    with nested children) plus the audit report + checklist artifacts the
    strategy emitted, and produces dependency-ordered, chunked CSV files
    that ERPnext's Data Import UI can consume directly. Honors the
    session's strategy_config.include_legacy_fields toggle.
    """
    transformed = session.get("transformed") or {}
    tables = transformed.get("tables") or {}
    audit_report = transformed.get("audit_report")
    checklist_md = transformed.get("setup_checklist_md")
    staging_dir = transformed.get("staging_dir")
    config = session.get("strategy_config") or {}
    include_legacy = bool(config.get("include_legacy_fields", True))
    files = write_frappe_csvs(
        tables, out_dir,
        audit_report=audit_report,
        checklist_md=checklist_md,
        include_legacy_fields=include_legacy,
        staging_dir=staging_dir,
    )
    rows_written = transformed.get("output_doctypes") or {
        dt: len(rows) for dt, rows in tables.items()
        if not dt.startswith("__") and rows
    }
    return {
        "ok": True,
        "output_files": files,
        "rows_written": rows_written,
        "staging_used": False,
        "transaction_wrapped": False,
        "errors": [],
        "exceptions_written": [],
    }


@router.get("/stats/{session_id}", response_model=StatsResponse)
async def stats(session_id: str):
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    s = await session_store.require(session_id)
    from utils.stats import StatsEngine

    engine = StatsEngine(_visible_session(s))
    await _auto_save(session_id, "stats")
    return StatsResponse(**engine.compute())
