"""Stock Reconciliation (Opening Stock) from CATSTORET + CATEGORYT.

Uses CATSTORET.STARTQTY (true opening) — NOT QTYBALANCE which is the
in-period delta. Valuation rate comes from CATEGORYT.COSTPRICE (99.9%
of items have it). Negative opening rows are emitted as-is and require
Stock Settings → Allow Negative Stock to be enabled before import.

One Stock Reconciliation per warehouse — small store count (1 warehouse
in our data) keeps this simple.
"""
from typing import Iterable

from core.strategies.erpnext.common import (
    clean_str,
    index_by,
    item_id,
    parse_decimal,
)
from core.strategies.erpnext.context import Context
from core.strategies.erpnext.masters import warehouse_for_store


def emit_stock_opening(ctx: Context) -> None:
    cost_by_catid = _cost_lookup(ctx)
    by_warehouse = _group_stock_by_warehouse(ctx)
    for store_id, items in by_warehouse.items():
        warehouse = warehouse_for_store(ctx, store_id)
        if not warehouse:
            ctx.result.warn("StockOpening", f"unknown STOREID={store_id}")
            continue
        rows = _stock_reco_lines(items, warehouse, cost_by_catid, ctx)
        if not rows:
            ctx.result.bump("stock_recos_skipped_empty")
            continue
        ctx.result.emit("Stock Reconciliation", _stock_reco_payload(
            ctx, store_id, warehouse, rows,
        ))
        ctx.result.bump("stock_recos_emitted")
        ctx.result.bump("stock_lines_emitted", len(rows))
        _count_negatives(rows, ctx)


# -- Per-warehouse grouping ---------------------------------------------------

def _group_stock_by_warehouse(
    ctx: Context,
) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for row in ctx.table("CATSTORET"):
        store_id = clean_str(row.get("STOREID"))
        if not store_id:
            continue
        out.setdefault(store_id, []).append(row)
    return out


# -- Reco payload + lines -----------------------------------------------------

def _stock_reco_payload(
    ctx: Context,
    store_id: str,
    warehouse: str,
    items: list[dict],
) -> dict:
    return {
        "name": f"STR-OPN-LEG-{store_id}",
        "naming_series": "MAT-RECO-.YYYY.-",
        "purpose": "Opening Stock",
        "posting_date": ctx.config.opening_date,
        "posting_time": "00:00:00",
        "set_posting_time": 1,
        "company": ctx.config.company_name,
        "set_warehouse": warehouse,
        "expense_account": ctx.with_abbr("Stock Adjustment"),
        "docstatus": 1,
        "items": items,
        "legacy_storeid": store_id,
    }


def _stock_reco_lines(
    rows: Iterable[dict],
    warehouse: str,
    cost_by_catid: dict[str, float],
    ctx: Context,
) -> list[dict]:
    out: list[dict] = []
    for r in rows or []:
        line = _stock_line(r, warehouse, cost_by_catid)
        if line is not None:
            out.append(line)
        else:
            ctx.result.bump("stock_lines_skipped_zero")
    return out


def _stock_line(
    row: dict,
    warehouse: str,
    cost_by_catid: dict[str, float],
) -> dict | None:
    catid = clean_str(row.get("CATID"))
    if not catid:
        return None
    qty = parse_decimal(row.get("STARTQTY"))
    if qty == 0:
        return None
    rate = cost_by_catid.get(catid, 0.0)
    return {
        "item_code": item_id(catid),
        "warehouse": warehouse,
        "qty": qty,
        "valuation_rate": rate,
    }


# -- Cost / valuation rate ----------------------------------------------------

def _cost_lookup(ctx: Context) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in ctx.iter_streamed("CATEGORYT"):
        catid = clean_str(row.get("CATID"))
        if not catid:
            continue
        cost = parse_decimal(row.get("COSTPRICE"))
        if cost <= 0:
            cost = parse_decimal(row.get("PURCHPRICE"))
        if cost <= 0:
            cost = parse_decimal(row.get("LASTPURCHPRICE"))
        out[catid] = cost
    return out


def _count_negatives(rows: list[dict], ctx: Context) -> None:
    neg = sum(1 for r in rows if r.get("qty", 0) < 0)
    if neg:
        ctx.result.bump("stock_lines_negative", neg)
        ctx.result.warn(
            "StockOpening",
            f"{neg} item lines have negative opening qty — requires "
            "Stock Settings → Allow Negative Stock = ON",
        )
