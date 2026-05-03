import json
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.tables import _ensure_rows_loaded
from core.load.erpnext_client import ErpnextClient, ErpnextError
from core.load.erpnext_loader import run_live_import
from core.load.loader import Loader
from core.strategies import (
    StrategyResult,
    default_strategy_name,
    get_strategy,
)
from core.strategies.erpnext_shared.writer import write_frappe_csvs
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
from persistence.db import (
    clear_erpnext_imports,
    create_pipeline_run,
    finish_pipeline_run,
    get_erpnext_credentials,
    list_erpnext_imports,
    record_erpnext_import,
    save_erpnext_credentials,
)
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
    table_loader=None,
) -> Dict[str, Any]:
    if staging_dir:
        _clear_dir(staging_dir)
    strategy = get_strategy(strategy_name)
    out: StrategyResult = strategy.transform(
        legacy, config,
        staging_dir=staging_dir,
        table_loader=table_loader,
    )
    out.close_files()
    counts = out.doctype_counts()
    if not counts:
        return _passthrough_result(legacy)
    total = sum(counts.values())
    audit_rows = out.output_tables.get("__audit_report__") or []
    checklist_rows = out.output_tables.get("__migration_setup_checklist__") or []
    coverage_rows = out.output_tables.get("__native_bucket_coverage__") or []
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
        bucket_coverage_md=(coverage_rows[0] or {}).get("content")
                           if coverage_rows else None,
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
    bucket_coverage_md: Optional[str] = None,
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
        "bucket_coverage_md": bucket_coverage_md,
        "staging_dir": staging_dir,
    }


def _resolve_strategy(s: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    name = s.get("strategy_name") or default_strategy_name()
    config = dict(s.get("strategy_config") or {})
    selected = s.get("selected_entities")
    if selected is not None:
        config["selected_entities"] = selected
    return name, config


def _run_transform(s: Dict[str, Any], session_id: Optional[str] = None) -> Dict[str, Any]:
    legacy = _legacy_tables(s)
    name, config = _resolve_strategy(s)
    staging_dir = _transform_staging_dir(s, session_id)
    loader = _make_table_loader(s)
    result = _strategy_result(
        legacy, name, config,
        staging_dir=staging_dir,
        table_loader=loader,
    )
    # Source tables can be freed now that the strategy has consumed them
    # — they're still on disk and lazy-load if the user re-runs transform.
    # Frees ~1-3GB of RSS for big imports.
    raw = s.get("raw") or {}
    if isinstance(raw.get("tables"), dict):
        for tname in list(raw["tables"].keys()):
            raw["tables"][tname] = []
    return result


def _transform_staging_dir(s: Dict[str, Any], session_id: Optional[str] = None) -> Optional[str]:
    """Per-session/project dir where strategy emits stream as JSONL.

    Uses disk-streaming mode for large datasets to avoid memory exhaustion.
    For project sessions: {project_dir}/_transform_out
    For guest sessions: {OUTPUT_DIR}/{session_id}/_transform_out
    """
    project_id = s.get("project_id")

    if project_id:
        from persistence.project_state import project_dir
        staging_dir = os.path.join(project_dir(project_id), "_transform_out")
    elif session_id:
        staging_dir = os.path.join(OUTPUT_DIR, session_id, "_transform_out")
    else:
        return None

    os.makedirs(staging_dir, exist_ok=True)
    return staging_dir


def _make_table_loader(s: Dict[str, Any]):
    """Return a callable(name) → iterator-of-rows that streams a legacy
    table from the JSONL extract cache. Used for tables in
    SKIP_EAGER_LOAD that the strategy reads via Context.iter_streamed().
    """
    project_id = s.get("project_id")
    if not project_id:
        return None
    from utils import extract_cache

    def loader(name: str):
        yield from extract_cache.stream_table_rows(project_id, name)

    return loader


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
    s["transformed"] = _run_transform(s, session_id)


@router.get("/transform/{session_id}", response_model=TransformResponse)
async def transform(session_id: str):
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    s = await session_store.require(session_id)
    project_id = s.get("project_id")
    run = create_pipeline_run(project_id, "transform") if project_id else None
    audit_trail = s.get("audit_trail")

    _ensure_rows_loaded(s)
    result = _run_transform(s, session_id)
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
        "bucket_coverage_md",
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


class ErpnextLoadRequest(BaseModel):
    url: str
    api_key: str
    api_secret: str
    company: Optional[str] = None
    company_abbr: Optional[str] = None
    force_reupload: bool = False
    halt_on_failure: bool = True
    selected_doctypes: Optional[List[str]] = None
    skip_files: Optional[List[str]] = None


@router.get("/erpnext-credentials/{project_id}")
async def get_erpnext_creds(project_id: str):
    return {"credentials": get_erpnext_credentials(project_id)}


@router.get("/erpnext-imports/{project_id}")
async def get_erpnext_imports(project_id: str):
    """Return per-file records of previously successful imports.

    Frontend uses this to mark doctype cards with an 'already imported'
    badge so the user knows which files would be auto-skipped on the
    next run (unless they tick `Re-upload everything`).
    """
    return {"imports": list_erpnext_imports(project_id)}


@router.post("/load-erpnext/{session_id}")
async def load_erpnext(session_id: str, body: ErpnextLoadRequest):
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    s = await session_store.require(session_id)
    # Apply any company / abbr override from the load form. If the user
    # picks different values than what transform last ran with, drop the
    # cached output and let _ensure_transformed re-run with the new
    # values — otherwise the CSVs still have the old company baked in.
    # Also wipe the import history: previously-imported records still
    # carry the OLD abbr suffix in their autonamed `name`, so the new
    # CSVs (which reference the new abbr) won't link up. A full
    # re-upload after a company change keeps everything consistent.
    cfg = s.get("strategy_config") or {}
    config_changed = False
    if body.company and body.company != cfg.get("company_name"):
        cfg["company_name"] = body.company
        s["transformed"] = None
        config_changed = True
    if body.company_abbr and body.company_abbr != cfg.get("company_abbr"):
        cfg["company_abbr"] = body.company_abbr
        s["transformed"] = None
        config_changed = True
    s["strategy_config"] = cfg
    if config_changed and s.get("project_id"):
        clear_erpnext_imports(s["project_id"])

    # Lazy re-transform on resume / after a config override: project
    # state intentionally doesn't persist the heavy `transformed` dict.
    if "transformed" not in s or not s["transformed"]:
        await _ensure_transformed(session_id)
    project_id = s.get("project_id")
    if project_id:
        save_erpnext_credentials(
            project_id, body.url, body.api_key, body.api_secret,
            body.company, body.company_abbr,
        )

    out_dir = (
        project_outputs_dir(project_id)
        if project_id
        else os.path.join(OUTPUT_DIR, session_id)
    )
    os.makedirs(out_dir, exist_ok=True)
    _clean_output_dir(out_dir)

    transformed = s.get("transformed") or {}
    write_frappe_csvs(
        transformed.get("tables") or {},
        out_dir,
        audit_report=transformed.get("audit_report"),
        checklist_md=transformed.get("setup_checklist_md"),
        bucket_coverage_md=transformed.get("bucket_coverage_md"),
        # API path skips legacy_* per the user's spec — they need
        # custom-field registration that we deliberately don't automate.
        include_legacy_fields=False,
        staging_dir=transformed.get("staging_dir"),
    )

    company = body.company or (s.get("strategy_config") or {}).get("company_name")
    company_abbr = body.company_abbr or (s.get("strategy_config") or {}).get("company_abbr") or ""
    opening_date = (s.get("strategy_config") or {}).get("opening_date") or ""
    client = ErpnextClient(body.url, body.api_key, body.api_secret)
    run = create_pipeline_run(project_id, "load") if project_id else None

    if project_id and body.force_reupload:
        clear_erpnext_imports(project_id)
    already = list_erpnext_imports(project_id) if project_id else {}

    def on_done(file_name: str, doctype: str, imported: int) -> None:
        if project_id:
            record_erpnext_import(project_id, file_name, doctype, imported)

    def stream():
        # Some intermediaries (nginx, vite proxy) hold ~4KB of bytes
        # before flushing. Send a comment line of padding plus the
        # X-Accel-Buffering header so the first real events reach the
        # browser as soon as we yield them.
        yield ":" + (" " * 2048) + "\n\n"
        yield _sse({"event": "begin", "company": company,
                    "skipping": sorted(already.keys()) if already else []})
        last_event: Dict[str, Any] = {}
        try:
            for ev in run_live_import(
                out_dir, client, company or "",
                opening_date=opening_date,
                company_abbr=company_abbr,
                already_imported=already,
                on_file_imported=on_done,
                selected_doctypes=body.selected_doctypes,
                halt_on_failure=body.halt_on_failure,
                skip_files=body.skip_files,
            ):
                last_event = ev
                yield _sse(ev)
        except ErpnextError as e:
            yield _sse({"event": "error", "message": str(e), "payload": e.payload})
        except Exception as e:
            yield _sse({"event": "error", "message": str(e)})
        finally:
            if run and project_id:
                status = "done" if last_event.get("event") == "complete" else "error"
                note = "via live api" if status == "done" else str(last_event.get("message", ""))[:200]
                rows = 0
                summary = last_event.get("summary") or []
                if isinstance(summary, list):
                    rows = sum(int(e.get("imported") or 0) for e in summary)
                finish_pipeline_run(run["id"], status, rows, note)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _sse(event: Dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


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
    bucket_coverage_md = transformed.get("bucket_coverage_md")
    staging_dir = transformed.get("staging_dir")
    config = session.get("strategy_config") or {}
    include_legacy = bool(config.get("include_legacy_fields", True))
    files = write_frappe_csvs(
        tables, out_dir,
        audit_report=audit_report,
        checklist_md=checklist_md,
        bucket_coverage_md=bucket_coverage_md,
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
