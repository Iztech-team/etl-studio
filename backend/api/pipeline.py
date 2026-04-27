import asyncio
import json
import os
import shutil
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from api.tables import _ensure_rows_loaded
from core.load.loader import Loader
from core.transform.transformer import Transformer
from helpers import (
    _auto_save,
    _excluded_set,
    _flush_audit_events,
    _visible_raw,
    _visible_session,
)
from models.schemas import (
    ConfigureRequest,
    ConfigureResponse,
    LoadRequest,
    LoadResponse,
    StatsResponse,
    TransformResponse,
)
from persistence.db import create_pipeline_run, finish_pipeline_run
from persistence.project_state import project_dir, project_outputs_dir
from startup import OUTPUT_DIR
from state import session_store
from utils import extract_cache

router = APIRouter()


async def _ensure_transformed(session_id: str) -> None:
    """Run the transformer on demand if the session doesn't have its result.

    Resume no longer pre-runs the transformer (it cost 10–30s per page open
    for big schemas). Endpoints that need s['transformed'] call this helper.
    """
    s = await session_store.require(session_id)
    if "transformed" in s and s["transformed"]:
        return
    _ensure_rows_loaded(s)
    audit_trail = s.get("audit_trail")
    config = dict(s.get("config", {}))
    transformer = Transformer(_visible_raw(s), config, audit_trail)
    s["transformed"] = transformer.run()
    s["transformer"] = transformer


@router.post("/configure/{session_id}", response_model=ConfigureResponse)
async def configure(
    session_id: str, body: ConfigureRequest,
    phase: str = Query("configure"),
):
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    s = await session_store.require(session_id)
    s["config"] = body.dict()
    await _auto_save(session_id, phase)
    return ConfigureResponse(ok=True, message="Configuration saved")


@router.get("/transform/{session_id}", response_model=TransformResponse)
async def transform(session_id: str):
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    s = await session_store.require(session_id)
    project_id = s.get("project_id")
    run = None
    if project_id:
        run = create_pipeline_run(project_id, "transform")
    audit_trail = s.get("audit_trail")
    config = dict(s.get("config", {}))

    progress: Dict[str, Any] = {
        "status": "running",
        "tables_done": 0, "tables_total": 0,
        "current_table": None, "persisted_targets": [],
    }
    s["transform_progress"] = progress

    def _on_progress(table_name: str, done: int, total: int) -> None:
        progress["tables_done"] = done
        progress["tables_total"] = total
        progress["current_table"] = table_name

    # Per-target persistence: write each completed target to disk so a
    # transform crash doesn't lose finished tables. Wipe stale outputs
    # at the start of every run.
    partial_dir: Optional[str] = None
    if project_id:
        partial_dir = os.path.join(project_dir(project_id), "transform_partial")
        try:
            shutil.rmtree(partial_dir, ignore_errors=True)
            os.makedirs(partial_dir, exist_ok=True)
        except Exception:
            partial_dir = None

    def _persist_target(target: str, rows: List[Dict[str, Any]]) -> None:
        if not partial_dir:
            return
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in target)
        path = os.path.join(partial_dir, f"{safe}.json")
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False, default=str)
            os.replace(tmp, path)
            progress.setdefault("persisted_targets", []).append(target)
        except Exception as e:
            s.setdefault("warnings", []).append(
                f"failed to persist target {target}: {e}"
            )

    excluded = _excluded_set(s)

    def _row_loader(table_name: str) -> List[Dict[str, Any]]:
        # Lazy: fetch one table's rows on demand and let the transformer
        # release them after. Avoids loading the whole 1 GB+ dataset upfront
        # and keeps the asyncio loop responsive.
        if table_name in excluded:
            return []
        if not project_id:
            return s.get("raw", {}).get("tables", {}).get(table_name, []) or []
        rows = extract_cache.read_table_rows(project_id, table_name)
        if rows is None:
            rows = s.get("raw", {}).get("tables", {}).get(table_name)
            if rows is None:
                _ensure_rows_loaded(s, [table_name])
                rows = s.get("raw", {}).get("tables", {}).get(table_name, [])
        return rows or []

    transformer = Transformer(
        _visible_raw(s), config, audit_trail,
        progress_cb=_on_progress,
        persist_target_cb=_persist_target,
        row_loader=_row_loader,
    )
    try:
        # Run on a worker thread so the asyncio loop stays free for status polls.
        result = await asyncio.to_thread(transformer.run)
    except Exception as e:
        progress["status"] = "error"
        progress["error"] = str(e)
        if run and project_id:
            finish_pipeline_run(run["id"], "error", 0, str(e))
        raise
    progress["status"] = "done"
    progress["tables_done"] = progress.get("tables_total", 0)
    s["transformed"] = result
    s["transformer"] = transformer
    s["fk_edges"] = list(transformer.fk_edges)
    await _auto_save(session_id, "transform")
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


@router.post("/reconcile/{session_id}")
async def reconcile_endpoint(session_id: str, body: dict | None = None):
    """Run reconciliation pass over transformed data; return structured report.

    Body may carry per-project tolerances or invoice-table specs. Legacy
    balances for the per-account tie-out are pulled from the session's raw
    extraction (ACCOUNTT.MBALANCE) when the GL output uses ACCOUNTID as
    `account`. Pass legacy_account_balances explicitly to override.
    """
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    s = await session_store.require(session_id)
    if "transformed" not in s or not s["transformed"]:
        await _ensure_transformed(session_id)
    transformed = s["transformed"]
    target_tables = transformed.get("tables", {})

    body = body or {}

    legacy_balances = body.get("legacy_account_balances")
    if not legacy_balances:
        legacy_balances = {}
        accountt_rows = (s.get("raw") or {}).get("tables", {}).get("ACCOUNTT") or []
        for r in accountt_rows:
            aid = r.get("ACCOUNTID")
            mbal = r.get("MBALANCE")
            if aid is not None and mbal not in (None, "", "0"):
                try:
                    legacy_balances[aid] = float(mbal)
                except (TypeError, ValueError):
                    continue

    from utils import reconcile as _rec

    report = _rec.reconcile(
        target_tables,
        legacy_account_balances=legacy_balances or None,
        invoice_specs=body.get("invoice_specs"),
        fk_specs=body.get("fk_specs"),
        gl_table=body.get("gl_table", "gl_entry"),
        voucher_tolerance=body.get("voucher_tolerance", 0.01),
        account_tolerance=body.get("account_tolerance", 0.01),
        invoice_tolerance=body.get("invoice_tolerance", 0.05),
    )
    s["reconcile_report"] = report
    return report


@router.get("/transform/{session_id}/status")
async def transform_status(session_id: str):
    """Lightweight progress endpoint polled by the navbar dock."""
    if not await session_store.exists(session_id):
        return {"status": "unknown"}
    s = await session_store.require(session_id)
    progress = s.get("transform_progress")
    if not progress:
        return {"status": "unknown"}
    return progress


@router.post("/load/{session_id}", response_model=LoadResponse)
async def load(session_id: str, body: LoadRequest):
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    s = await session_store.require(session_id)
    if "transformed" not in s or not s["transformed"]:
        if not s.get("config"):
            raise HTTPException(400, "Run transform first")
        await _ensure_transformed(session_id)

    project_id = s.get("project_id")
    run = create_pipeline_run(project_id, "load") if project_id else None

    out_dir = project_outputs_dir(project_id) if project_id else os.path.join(OUTPUT_DIR, session_id)
    os.makedirs(out_dir, exist_ok=True)

    excluded = _excluded_set(s)
    fk_edges = [
        edge for edge in s.get("fk_edges", [])
        if edge[0] not in excluded and edge[1] not in excluded
    ]

    self_refs: Dict[str, str] = {}
    transformer = s.get("transformer")
    if transformer is not None:
        self_refs = getattr(transformer, "self_refs", {}) or {}
    loader = Loader(
        s["transformed"], body.dict(), out_dir,
        fk_edges=fk_edges, self_refs=self_refs,
    )
    result = loader.run()
    s["load_result"] = result
    await _auto_save(session_id, "load")
    if run and project_id:
        total_rows = sum(result.get("rows_written", {}).values())
        status = "error" if result.get("errors") else "done"
        note = ("; ".join(result.get("errors", [])[:2])
                if result.get("errors") else f"format={body.output_format}")
        finish_pipeline_run(run["id"], status, total_rows, note)
        audit_trail = s.get("audit_trail")
        if audit_trail:
            _flush_audit_events(project_id, audit_trail, run["id"])
    return LoadResponse(**result)


@router.get("/stats/{session_id}", response_model=StatsResponse)
async def stats(session_id: str):
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    s = await session_store.require(session_id)
    from utils.stats import StatsEngine

    engine = StatsEngine(_visible_session(s))
    await _auto_save(session_id, "stats")
    return StatsResponse(**engine.compute())
