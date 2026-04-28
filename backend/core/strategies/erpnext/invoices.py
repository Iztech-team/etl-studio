"""Sales Invoice + Purchase Invoice (with returns).

Header → detail join key: (DOCNO, INVTYPE). Returns reference the
original through INDOCNO; we resolve those to our generated invoice
names via a DOCNO→DOCSERIAL index built once per stream.

Walk-in (ACCOUNTID=0) sales are optionally summarized per date×terminal
to keep import volume manageable — see `_emit_walkin_summaries`. Named
(B2B + loyalty POS) sales emit per-invoice with full line detail.
"""
from typing import Iterable

from core.strategies.erpnext.accounts import account_full_name
from core.strategies.erpnext.common import (
    WALKIN_CUSTOMER_ID,
    clean_str,
    customer_id,
    group_by,
    normalize_uom,
    parse_date,
    parse_decimal,
    parse_time,
    pick,
    supplier_id,
)
from core.strategies.erpnext.context import Context
from core.strategies.erpnext.masters import (
    PRICE_LIST_FALLBACK_NAMES,
    warehouse_for_store,
)

# Source-document statuses we accept. POSTFLAG=9 is cancelled — skipped.
ACCEPT_POSTFLAGS = {"1", "2"}

# Frappe convention for receivable / payable / cash / sales / cogs
# accounts. The strategy assumes ERPnext has either auto-created these
# (typical) or the admin pre-creates them via the setup checklist.
def _debtors(ctx: Context) -> str:
    return ctx.with_abbr("Debtors")


def _creditors(ctx: Context) -> str:
    return ctx.with_abbr("Creditors")


def _cash(ctx: Context) -> str:
    return ctx.with_abbr("Cash")


# -- Top-level orchestration --------------------------------------------------

def emit_invoices(ctx: Context) -> None:
    emit_sales_invoices(ctx)
    emit_purchase_invoices(ctx)
    emit_sales_returns(ctx)
    emit_purchase_returns(ctx)


# -- Sales Invoice ------------------------------------------------------------

def emit_sales_invoices(ctx: Context) -> None:
    lines_by_key = group_by(ctx.table("CATESINVDOCDETT"), "DOCNO")
    # group_by indexes single-column; refine to (DOCNO, INVTYPE) below.
    lines_by_pair = _group_invoice_lines(ctx.table("CATESINVDOCDETT"))
    for row in ctx.table("CATESINVDOCT"):
        if not _accept_invoice(ctx, row, "SalesInvoice"):
            continue
        if _is_walkin_row(row) and ctx.config.summarize_walkin_sales:
            continue  # handled by _emit_walkin_summaries below
        _emit_sales_invoice(ctx, row, lines_by_pair)
    if ctx.config.summarize_walkin_sales:
        _emit_walkin_summaries(ctx, lines_by_pair)


def _emit_sales_invoice(
    ctx: Context,
    header: dict,
    lines_by_pair: dict[tuple[str, str], list[dict]],
) -> None:
    docserial = clean_str(header.get("DOCSERIAL"))
    items = _sales_items(ctx, _lines_for(header, lines_by_pair))
    if not items:
        ctx.result.bump("sales_invoices_skipped_no_lines")
        return
    is_pos = _is_pos(header)
    payload = {
        "name": f"SINV-LEG-{docserial}",
        "customer": _customer_for_invoice(header),
        "posting_date": parse_date(header.get("DOCDATE")),
        "posting_time": parse_time(header.get("DOCTIME")),
        "due_date": _sales_due_date(header, is_pos),
        "company": ctx.config.company_name,
        "currency": ctx.config.default_currency,
        "conversion_rate": 1.0,
        "selling_price_list": _default_selling_price_list(ctx),
        "debit_to": _debtors(ctx),
        "is_pos": 1 if is_pos else 0,
        "update_stock": 1,
        "docstatus": _docstatus(header),
        "discount_amount": parse_decimal(header.get("DISCOUNTV")),
        "remarks": clean_str(header.get("NOTES")),
        "items": items,
        "payments": _pos_payments(ctx, header, is_pos),
        "legacy_docno": clean_str(header.get("DOCNO")),
        "legacy_docserial": docserial,
        "legacy_kind": "named",
    }
    ctx.result.emit("Sales Invoice", payload)
    ctx.result.bump("sales_invoices_emitted")


def _emit_walkin_summaries(
    ctx: Context,
    lines_by_pair: dict[tuple[str, str], list[dict]],
) -> None:
    """Group anonymous walk-in invoices per (DOCDATE, SALEPOINT) into one
    summarized Sales Invoice each. Lines are aggregated per (item, uom)."""
    groups = _group_walkin_headers(ctx)
    for (date, salepoint), headers in groups.items():
        items = _summarize_lines(ctx, headers, lines_by_pair)
        if not items:
            ctx.result.bump("walkin_summaries_skipped_empty")
            continue
        ctx.result.emit("Sales Invoice", _walkin_summary_payload(
            ctx, date, salepoint, headers, items,
        ))
        ctx.result.bump("walkin_summaries_emitted")


def _walkin_summary_payload(
    ctx: Context,
    date: str,
    salepoint: str,
    headers: list[dict],
    items: list[dict],
) -> dict:
    total = sum(parse_decimal(h.get("DOCVALUE")) for h in headers)
    return {
        "name": f"SINV-LEG-WALKIN-{date}-{salepoint or 'NA'}",
        "customer": WALKIN_CUSTOMER_ID,
        "posting_date": date,
        "due_date": date,
        "company": ctx.config.company_name,
        "currency": ctx.config.default_currency,
        "conversion_rate": 1.0,
        "selling_price_list": _default_selling_price_list(ctx),
        "debit_to": _debtors(ctx),
        "is_pos": 1,
        "update_stock": 1,
        "docstatus": 1,
        "items": items,
        "payments": [{
            "mode_of_payment": "Cash",
            "account": _cash(ctx),
            "amount": total,
        }],
        "remarks": f"Walk-in summary — terminal {salepoint or 'NA'}, "
                   f"{len(headers)} legacy invoices",
        "legacy_summary": 1,
        "legacy_summary_count": len(headers),
        "legacy_summary_terminal": salepoint,
        "legacy_kind": "walkin_summary",
    }


def _group_walkin_headers(
    ctx: Context,
) -> dict[tuple[str, str], list[dict]]:
    out: dict[tuple[str, str], list[dict]] = {}
    for row in ctx.table("CATESINVDOCT"):
        if not _accept_invoice(ctx, row, "SalesInvoice", silent=True):
            continue
        if not _is_walkin_row(row):
            continue
        date = parse_date(row.get("DOCDATE")) or ""
        salepoint = clean_str(row.get("SALEPOINT"))
        out.setdefault((date, salepoint), []).append(row)
    return out


def _summarize_lines(
    ctx: Context,
    headers: list[dict],
    lines_by_pair: dict[tuple[str, str], list[dict]],
) -> list[dict]:
    """Aggregate (item, uom) across all line-rows under the given headers."""
    bucket: dict[tuple[str, str], dict] = {}
    for h in headers:
        for line in _lines_for(h, lines_by_pair):
            _accumulate_line(bucket, ctx, line)
    return [_finalize_line(b) for b in bucket.values() if b["qty"] > 0]


def _accumulate_line(bucket: dict, ctx: Context, line: dict) -> None:
    catid = clean_str(line.get("CATID"))
    if not catid:
        return
    uom = normalize_uom(line.get("CATUNIT"))
    qty = parse_decimal(line.get("CATQTY"))
    rate = parse_decimal(line.get("CATPRICEWOV"))
    key = (catid, uom)
    cell = bucket.setdefault(key, {
        "item_code": f"ALA-{catid}",
        "uom": uom,
        "qty": 0.0,
        "amount": 0.0,
        "warehouse": _warehouse_for_line(ctx, line),
    })
    cell["qty"] += qty
    cell["amount"] += qty * rate


def _finalize_line(cell: dict) -> dict:
    qty = cell["qty"] or 1.0
    rate = cell["amount"] / qty if qty else 0.0
    return {
        "item_code": cell["item_code"],
        "qty": cell["qty"],
        "rate": rate,
        "uom": cell["uom"],
        "warehouse": cell["warehouse"],
        "allow_zero_valuation_rate": 1,
    }


# -- Sales Invoice — common bits ---------------------------------------------

def _customer_for_invoice(header: dict) -> str:
    if _is_walkin_row(header):
        return WALKIN_CUSTOMER_ID
    return customer_id(header.get("ACCOUNTID"))


def _is_walkin_row(header: dict) -> bool:
    return clean_str(header.get("ACCOUNTID")) == "0"


def _is_pos(header: dict) -> bool:
    return bool(clean_str(header.get("SALEPOINT")))


def _sales_due_date(header: dict, is_pos: bool) -> str:
    posting = parse_date(header.get("DOCDATE"))
    if is_pos:
        return posting or ""
    due = parse_date(header.get("DUEDATE"))
    return due or posting or ""


def _docstatus(header: dict) -> int:
    """POSTFLAG=2 → submitted; POSTFLAG=1 → draft."""
    return 1 if clean_str(header.get("POSTFLAG")) == "2" else 0


def _pos_payments(ctx: Context, header: dict, is_pos: bool) -> list[dict]:
    if not is_pos:
        return []
    return [{
        "mode_of_payment": "Cash",
        "account": _cash(ctx),
        "amount": parse_decimal(header.get("DOCVALUE")),
    }]


def _accept_invoice(
    ctx: Context,
    header: dict,
    source: str,
    silent: bool = False,
) -> bool:
    flag = clean_str(header.get("POSTFLAG"))
    if flag in ACCEPT_POSTFLAGS:
        return True
    if flag == "9":
        if not silent:
            ctx.result.bump(f"{source.lower()}_skipped_cancelled")
        return False
    if not silent:
        ctx.result.warn(
            source,
            f"unknown POSTFLAG={flag} — emitting anyway",
            legacy_docno=clean_str(header.get("DOCNO")),
        )
    return True


def _default_selling_price_list(ctx: Context) -> str:
    rows = ctx.table("PRICETYPET")
    if rows:
        chosen = pick(rows[0], "PRICENAME")
        if chosen:
            return chosen
    return PRICE_LIST_FALLBACK_NAMES["1"]


# -- Sales Invoice line items -------------------------------------------------

def _sales_items(ctx: Context, line_rows: Iterable[dict]) -> list[dict]:
    items: list[dict] = []
    for line in line_rows:
        item = _sales_item_row(ctx, line)
        if item:
            items.append(item)
    return items


def _sales_item_row(ctx: Context, line: dict) -> dict | None:
    catid = clean_str(line.get("CATID"))
    if not catid:
        return None
    qty = parse_decimal(line.get("CATQTY"))
    if qty == 0:
        return None
    return {
        "item_code": f"ALA-{catid}",
        "qty": qty,
        "rate": parse_decimal(line.get("CATPRICEWOV")),
        "uom": normalize_uom(line.get("CATUNIT")),
        "warehouse": _warehouse_for_line(ctx, line),
        "income_account": account_full_name(ctx, line.get("SALEACCID")),
        "discount_amount": parse_decimal(line.get("CATDISCOUNT")),
        "allow_zero_valuation_rate": 1,
    }


def _warehouse_for_line(ctx: Context, line: dict) -> str:
    return warehouse_for_store(ctx, line.get("STOREID"))


# -- Purchase Invoice ---------------------------------------------------------

def emit_purchase_invoices(ctx: Context) -> None:
    lines_by_pair = _group_invoice_lines(ctx.table("CATEPINVDOCDETT"))
    for row in ctx.table("CATEPINVDOCT"):
        if not _accept_invoice(ctx, row, "PurchaseInvoice"):
            continue
        _emit_purchase_invoice(ctx, row, lines_by_pair)


def _emit_purchase_invoice(
    ctx: Context,
    header: dict,
    lines_by_pair: dict[tuple[str, str], list[dict]],
) -> None:
    docserial = clean_str(header.get("DOCSERIAL"))
    items = _purchase_items(ctx, _lines_for(header, lines_by_pair))
    if not items:
        ctx.result.bump("purchase_invoices_skipped_no_lines")
        return
    payload = {
        "name": f"PINV-LEG-{docserial}",
        "supplier": _supplier_for_purchase(ctx, header),
        "posting_date": parse_date(header.get("DOCDATE")),
        "posting_time": parse_time(header.get("DOCTIME")),
        "due_date": parse_date(header.get("DUEDATE"))
                    or parse_date(header.get("DOCDATE")) or "",
        "bill_no": clean_str(header.get("MANUALNO")),
        "bill_date": parse_date(header.get("DOCDATE")),
        "company": ctx.config.company_name,
        "currency": ctx.config.default_currency,
        "conversion_rate": 1.0,
        "credit_to": _creditors(ctx),
        "update_stock": 1,
        "docstatus": _docstatus(header),
        "remarks": clean_str(header.get("NOTES")),
        "items": items,
        "legacy_docno": clean_str(header.get("DOCNO")),
        "legacy_docserial": docserial,
    }
    ctx.result.emit("Purchase Invoice", payload)
    ctx.result.bump("purchase_invoices_emitted")


def _supplier_for_purchase(ctx: Context, header: dict) -> str:
    aid = clean_str(header.get("ACCOUNTID"))
    if not aid or aid == "0":
        # Anonymous purchase — extremely rare; fall back to a placeholder.
        return supplier_id("UNKNOWN")
    kind = ctx.party_kind(aid)
    if kind == "customer":
        return customer_id(aid)  # legacy data quirk: 14 cases referenced
    return supplier_id(aid)


def _purchase_items(ctx: Context, line_rows: Iterable[dict]) -> list[dict]:
    rows: list[dict] = []
    for line in line_rows:
        catid = clean_str(line.get("CATID"))
        if not catid:
            continue
        qty = parse_decimal(line.get("CATQTY"))
        if qty == 0:
            continue
        rows.append({
            "item_code": f"ALA-{catid}",
            "qty": qty,
            "rate": parse_decimal(line.get("CATPRICEWOV")),
            "uom": normalize_uom(line.get("CATUNIT")),
            "warehouse": _warehouse_for_line(ctx, line),
            "expense_account": account_full_name(ctx, line.get("PURCHACCID")),
            "allow_zero_valuation_rate": 1,
        })
    return rows


# -- Sales Return -------------------------------------------------------------

def emit_sales_returns(ctx: Context) -> None:
    lines_by_pair = _group_invoice_lines(ctx.table("CATESRETINVDOCDETT"))
    docno_to_serial = _docno_index(ctx.table("CATESINVDOCT"))
    for row in ctx.table("CATESRETINVDOCT"):
        if not _accept_invoice(ctx, row, "SalesReturn"):
            continue
        _emit_sales_return(ctx, row, lines_by_pair, docno_to_serial)


def _emit_sales_return(
    ctx: Context,
    header: dict,
    lines_by_pair: dict[tuple[str, str], list[dict]],
    docno_to_serial: dict[str, str],
) -> None:
    docserial = clean_str(header.get("DOCSERIAL"))
    line_rows = _lines_for(header, lines_by_pair)
    items = _return_sales_items(ctx, line_rows)
    if not items:
        ctx.result.bump("sales_returns_skipped_no_lines")
        return
    payload = {
        "name": f"SINV-LEG-RET-{docserial}",
        "customer": _customer_for_invoice(header),
        "posting_date": parse_date(header.get("DOCDATE")),
        "due_date": parse_date(header.get("DOCDATE")),
        "company": ctx.config.company_name,
        "currency": ctx.config.default_currency,
        "conversion_rate": 1.0,
        "debit_to": _debtors(ctx),
        "is_return": 1,
        "is_pos": 1 if _is_pos(header) else 0,
        "update_stock": 1,
        "docstatus": _docstatus(header),
        "return_against": _return_against(line_rows, docno_to_serial, "SINV-LEG"),
        "items": items,
        "remarks": clean_str(header.get("NOTES")),
        "legacy_docno": clean_str(header.get("DOCNO")),
        "legacy_docserial": docserial,
    }
    ctx.result.emit("Sales Invoice", payload)
    ctx.result.bump("sales_returns_emitted")


def _return_sales_items(ctx: Context, line_rows: Iterable[dict]) -> list[dict]:
    rows: list[dict] = []
    for line in line_rows:
        catid = clean_str(line.get("CATID"))
        qty = parse_decimal(line.get("CATQTY"))
        if not catid or qty == 0:
            continue
        rows.append({
            "item_code": f"ALA-{catid}",
            "qty": qty,
            "rate": parse_decimal(line.get("CATPRICEWOV")),
            "uom": normalize_uom(line.get("CATUNIT")),
            "warehouse": _warehouse_for_line(ctx, line),
            "income_account": account_full_name(ctx, line.get("SALERETACCID")),
            "allow_zero_valuation_rate": 1,
        })
    return rows


# -- Purchase Return ----------------------------------------------------------

def emit_purchase_returns(ctx: Context) -> None:
    lines_by_pair = _group_invoice_lines(ctx.table("CATEPRETINVDOCDETT"))
    docno_to_serial = _docno_index(ctx.table("CATEPINVDOCT"))
    for row in ctx.table("CATEPRETINVDOCT"):
        if not _accept_invoice(ctx, row, "PurchaseReturn"):
            continue
        _emit_purchase_return(ctx, row, lines_by_pair, docno_to_serial)


def _emit_purchase_return(
    ctx: Context,
    header: dict,
    lines_by_pair: dict[tuple[str, str], list[dict]],
    docno_to_serial: dict[str, str],
) -> None:
    docserial = clean_str(header.get("DOCSERIAL"))
    line_rows = _lines_for(header, lines_by_pair)
    items = _return_purchase_items(ctx, line_rows)
    if not items:
        ctx.result.bump("purchase_returns_skipped_no_lines")
        return
    payload = {
        "name": f"PINV-LEG-RET-{docserial}",
        "supplier": _supplier_for_purchase(ctx, header),
        "posting_date": parse_date(header.get("DOCDATE")),
        "company": ctx.config.company_name,
        "currency": ctx.config.default_currency,
        "conversion_rate": 1.0,
        "credit_to": _creditors(ctx),
        "is_return": 1,
        "update_stock": 1,
        "docstatus": _docstatus(header),
        "return_against": _return_against(line_rows, docno_to_serial, "PINV-LEG"),
        "items": items,
        "remarks": clean_str(header.get("NOTES")),
        "legacy_docno": clean_str(header.get("DOCNO")),
        "legacy_docserial": docserial,
    }
    ctx.result.emit("Purchase Invoice", payload)
    ctx.result.bump("purchase_returns_emitted")


def _return_purchase_items(ctx: Context, line_rows: Iterable[dict]) -> list[dict]:
    rows: list[dict] = []
    for line in line_rows:
        catid = clean_str(line.get("CATID"))
        qty = parse_decimal(line.get("CATQTY"))
        if not catid or qty == 0:
            continue
        rows.append({
            "item_code": f"ALA-{catid}",
            "qty": qty,
            "rate": parse_decimal(line.get("CATPRICEWOV")),
            "uom": normalize_uom(line.get("CATUNIT")),
            "warehouse": _warehouse_for_line(ctx, line),
            "expense_account": account_full_name(ctx, line.get("PURCHRETACCID")),
            "allow_zero_valuation_rate": 1,
        })
    return rows


# -- Shared helpers -----------------------------------------------------------

def _group_invoice_lines(rows: Iterable[dict]) -> dict[tuple[str, str], list[dict]]:
    """Index detail rows by (DOCNO, INVTYPE) — the natural header join key."""
    out: dict[tuple[str, str], list[dict]] = {}
    for r in rows or []:
        key = (clean_str(r.get("DOCNO")), clean_str(r.get("INVTYPE")))
        out.setdefault(key, []).append(r)
    return out


def _lines_for(
    header: dict,
    lines_by_pair: dict[tuple[str, str], list[dict]],
) -> list[dict]:
    key = (clean_str(header.get("DOCNO")), clean_str(header.get("INVTYPE")))
    return lines_by_pair.get(key, [])


def _docno_index(headers: Iterable[dict]) -> dict[str, str]:
    """DOCNO → DOCSERIAL — used so returns can resolve return_against."""
    out: dict[str, str] = {}
    for h in headers or []:
        docno = clean_str(h.get("DOCNO"))
        if docno:
            out[docno] = clean_str(h.get("DOCSERIAL"))
    return out


def _return_against(
    line_rows: Iterable[dict],
    docno_to_serial: dict[str, str],
    prefix: str,
) -> str:
    """Pick the first INDOCNO across the return's lines and resolve it.

    Most returns reference a single original invoice; if multiple are
    referenced we accept the first as the dominant target.
    """
    for line in line_rows or []:
        indocno = clean_str(line.get("INDOCNO"))
        if not indocno or indocno == "0":
            continue
        serial = docno_to_serial.get(indocno)
        if serial:
            return f"{prefix}-{serial}"
    return ""
