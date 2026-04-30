"""Orchestrate live ERPnext import from Frappe-shaped CSVs.

Walks an output directory of `NN_doctype.csv` files in dependency order
(file-name ascending = correct since the writer prefixes each one with
its topological ordinal). For each:

- `10_account.csv` → `import_coa` (Chart of Accounts importer)
- everything else  → upload + Data Import + form_start_import + poll

Stops on first failure. Yields events (suitable for SSE streaming):
{"event": "stage" | "progress" | "done" | "error" | "complete", ...}.
"""
from __future__ import annotations

import csv
import io
import json
import os
import time
from typing import Any, Iterator

from core.load.erpnext_client import ErpnextClient, ErpnextError, parse_import_log


# Filename slug → ERPnext doctype. Mirror of writer._DOCTYPE_FROM_SAFE
# but keyed on the prefixed slug actually used in output filenames.
SLUG_TO_DOCTYPE: dict[str, str] = {
    "uom": "UOM",
    "warehouse": "Warehouse",
    "price_list": "Price List",
    "item_group": "Item Group",
    "brand": "Brand",
    "bank": "Bank",
    "bank_account": "Bank Account",
    "customer": "Customer",
    "supplier": "Supplier",
    "employee": "Employee",
    "item": "Item",
    "item_price": "Item Price",
    "journal_entry_opening": "Journal Entry",
    "journal_entry": "Journal Entry",
    "sales_invoice": "Sales Invoice",
    "sales_return": "Sales Invoice",
    "purchase_invoice": "Purchase Invoice",
    "purchase_return": "Purchase Invoice",
    "payment_entry": "Payment Entry",
    "stock_reconciliation": "Stock Reconciliation",
}

# Doctypes we'll try to ensure have import permission. The
# `allow_import=1` flag is already set on standard ERPnext doctypes —
# trying to PUT it via the API requires developer mode and fails on
# production sites, so we skip it. We only nudge Custom DocPerm.
DOCTYPES_NEEDING_IMPORT_PERM = sorted(set(SLUG_TO_DOCTYPE.values()) - {"Account"})

# Filenames we don't yet support over the live API. Operator can still
# download the CSV and run it manually.
SKIP_VIA_API = {"stock_reconciliation"}

POLL_INTERVAL_SEC = 1.0
POLL_TIMEOUT_SEC = 600


def run_live_import(
    output_dir: str, client: ErpnextClient, company: str,
    already_imported: dict[str, dict] | None = None,
    on_file_imported: Any = None,
    selected_doctypes: list[str] | None = None,
) -> Iterator[dict]:
    """Yield progress events while pushing every CSV in `output_dir`.

    `already_imported` maps file_name → record from a previous successful
    run; matching files are skipped so re-runs don't replay finished
    imports. Pass an empty dict (or None) to force a full re-upload.

    `selected_doctypes` constrains the run to a subset (matched by the
    target doctype, not file name — so all chunks of a chunked doctype
    move together). None means send everything.

    `on_file_imported(file_name, doctype, imported_count)` is called
    after each fully-successful file so the caller can persist the
    record for the next re-run's skip set.
    """
    files = _ordered_csv_files(output_dir)
    if not files:
        yield {"event": "error", "message": "no CSV files in output dir — run transform first"}
        return
    already = already_imported or {}
    selection = set(selected_doctypes) if selected_doctypes is not None else None

    yield {"event": "stage", "name": "preflight",
           "doctypes": DOCTYPES_NEEDING_IMPORT_PERM}
    for doctype in DOCTYPES_NEEDING_IMPORT_PERM:
        try:
            client.grant_import_perm(doctype)
            yield {"event": "preflight", "doctype": doctype, "status": "ok"}
        except ErpnextError as e:
            # Non-fatal — most standard doctypes already have the right
            # perms. We surface the failure and let the actual import
            # call fail loudly if perms really are the blocker.
            yield {"event": "preflight", "doctype": doctype,
                   "status": "warning", "message": str(e)}

    summary: list[dict] = []
    for fname in files:
        slug = _slug_from_filename(fname)
        if slug in SKIP_VIA_API:
            yield {"event": "skipped", "file": fname,
                   "reason": "not yet supported via live API — download CSV manually"}
            summary.append({"file": fname, "status": "skipped"})
            continue

        doctype = SLUG_TO_DOCTYPE.get(slug)
        if not doctype:
            yield {"event": "skipped", "file": fname, "reason": f"unknown doctype slug: {slug}"}
            summary.append({"file": fname, "status": "skipped"})
            continue

        if selection is not None and doctype not in selection:
            yield {"event": "skipped", "file": fname, "doctype": doctype,
                   "reason": "deselected"}
            summary.append({"file": fname, "doctype": doctype, "status": "skipped"})
            continue

        prior = already.get(fname)
        if prior:
            yield {"event": "skipped", "file": fname, "doctype": doctype,
                   "reason": f"already imported {prior['imported_count']} rows on "
                             f"{prior['completed_at']} — toggle 'Re-upload everything' to redo"}
            summary.append({"file": fname, "doctype": doctype, "status": "skipped",
                            "imported": prior["imported_count"]})
            continue

        path = os.path.join(output_dir, fname)
        result: dict = {}
        try:
            handler = _import_coa if slug == "account" else _import_via_data_import
            for ev in handler(client, path, doctype, company):
                ev = {"file": fname, "doctype": doctype, **ev}
                if ev.get("event") == "done":
                    result = ev
                yield ev
        except ErpnextError as e:
            yield {"event": "error", "file": fname, "doctype": doctype,
                   "message": str(e), "payload": e.payload}
            summary.append({"file": fname, "status": "error", "error": str(e)})
            return

        summary.append({"file": fname, **result})
        # Only persist a 'this file is done' record when Frappe reports
        # a fully successful import. Partial Success means the user will
        # want a retry on the next run, so we don't mark it complete.
        if on_file_imported and result.get("status") == "success":
            on_file_imported(fname, doctype, int(result.get("imported") or 0))

    counts = _verify_counts(client, summary)
    yield {"event": "complete", "summary": summary, "verification": counts}


# -- per-file handlers (generators yielding progress events) -----------------

def _import_via_data_import(
    client: ErpnextClient, path: str, doctype: str, company: str,
) -> Iterator[dict]:
    """Upload, queue, then poll Frappe Data Import. Yields progress events
    so the user sees Frappe's own status (Queued / In Progress / Success)
    in near-real-time instead of one batched 'done' at the end."""
    fname = os.path.basename(path)
    with open(path, "rb") as fh:
        content = fh.read()

    # Item Price references item_code on a doctype the loader uploads
    # earlier in the same run. If the strategy filtered some Items out
    # but their prices slipped through, drop those rows here so Frappe
    # doesn't complain. Source of truth is our own item CSVs in the
    # output dir — no ERPnext round-trip needed.
    if doctype == "Item Price":
        emitted_items = _read_emitted_item_codes(os.path.dirname(path))
        if emitted_items:
            content, dropped = _filter_csv_by_column(content, "item_code", emitted_items)
            if dropped:
                yield {"event": "filtering",
                       "message": f"dropped {dropped} Item Price rows referencing items not in 30_item.csv",
                       "filtered": dropped}

    yield {"event": "uploading", "stage": "upload"}
    file_url = client.upload_file(fname, content, content_type="text/csv")
    if not file_url:
        raise ErpnextError("upload_file returned no file_url")

    yield {"event": "uploading", "stage": "create_data_import"}
    name = client.create_data_import(doctype, file_url)
    if not name:
        raise ErpnextError("create_data_import returned no name")

    client.start_data_import(name)
    yield {"event": "queued", "data_import": name}
    yield from _poll_data_import_streaming(client, name)


def _poll_data_import_streaming(
    client: ErpnextClient, name: str,
) -> Iterator[dict]:
    """Poll Frappe until the Data Import finishes. Yields one event per
    poll showing current status + parsed row counts + any template
    warnings, then a final 'done' or raises ErpnextError on failure."""
    deadline = time.monotonic() + POLL_TIMEOUT_SEC
    last_status = ""
    last_progress = (-1, -1)
    while True:
        if time.monotonic() > deadline:
            raise ErpnextError(f"Data Import {name} timed out after {POLL_TIMEOUT_SEC}s")
        time.sleep(POLL_INTERVAL_SEC)
        d = client.get_data_import_status(name)
        status = d.get("status") or "Pending"
        log = list(parse_import_log(d.get("import_log") or ""))
        successes = sum(1 for r in log if r.get("success"))
        failures = sum(1 for r in log if not r.get("success"))
        warnings = _parse_warnings(d.get("template_warnings"))

        terminal = status in {"Success", "Partial Success", "Error"}
        progress_changed = (successes, failures) != last_progress
        status_changed = status != last_status
        if status_changed or progress_changed or terminal:
            ev: dict = {"event": "polling", "status": status,
                        "imported": successes, "failed": failures,
                        "data_import": name}
            if warnings:
                ev["warnings"] = warnings
            yield ev
            last_status = status
            last_progress = (successes, failures)

        if not terminal:
            continue

        errors = [_log_error(r) for r in log if not r.get("success")][:10]
        if status == "Success":
            yield {"event": "done", "status": "success",
                   "imported": successes, "failed": 0,
                   "data_import": name, "warnings": warnings}
            return
        if status == "Partial Success":
            yield {"event": "done", "status": "partial",
                   "imported": successes, "failed": failures,
                   "data_import": name, "errors": errors, "warnings": warnings}
            return
        # Status == "Error"
        if errors:
            err = "; ".join(errors)[:1000]
        else:
            log_rows = client.get_data_import_error_log(name)
            err = (log_rows[0]["error"] if log_rows
                   else d.get("failure_message") or "Data Import failed")
        if warnings:
            err = f"{err} | warnings: {' | '.join(warnings)[:500]}"
        raise ErpnextError(f"Data Import {name} failed: {err}")


def _read_emitted_item_codes(output_dir: str) -> set[str]:
    """Collect item_code values from every 30_item*.csv chunk we wrote.

    Item Price's item_code references the same set, so the value of
    `name` / `item_code` in those CSVs is the authoritative list of
    Items the strategy actually emitted this run.
    """
    out: set[str] = set()
    for fname in sorted(os.listdir(output_dir)):
        if not fname.endswith(".csv"):
            continue
        if not fname.startswith("30_item"):
            continue
        if "item_price" in fname:  # 31_item_price has different prefix anyway
            continue
        path = os.path.join(output_dir, fname)
        try:
            with open(path, "rb") as fh:
                content = fh.read()
            text = content.decode("utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        if not rows:
            continue
        header = rows[0]
        idx = header.index("item_code") if "item_code" in header else (
            header.index("ID") if "ID" in header else None
        )
        if idx is None:
            continue
        for row in rows[1:]:
            if idx < len(row) and row[idx].strip():
                out.add(row[idx].strip())
    return out


def _filter_csv_by_column(
    content: bytes, column: str, valid_values: set[str],
) -> tuple[bytes, int]:
    """Drop rows whose `column` value isn't in `valid_values`.

    Frappe Data Import CSVs have a parent header row plus optional
    continuation rows for child tables; continuation rows leave the
    parent column blank. We only filter rows that have a non-empty
    value in `column` — the leading row of each parent record.
    """
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content, 0
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return content, 0
    header = rows[0]
    if column not in header:
        return content, 0
    idx = header.index(column)
    out: list[list[str]] = [header]
    dropped = 0
    keep_current = True
    for row in rows[1:]:
        if len(row) <= idx:
            if keep_current:
                out.append(row)
            continue
        cell = row[idx].strip()
        if cell:
            keep_current = cell in valid_values
            if keep_current:
                out.append(row)
            else:
                dropped += 1
        else:
            if keep_current:
                out.append(row)
    if dropped == 0:
        return content, 0
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerows(out)
    return buf.getvalue().encode("utf-8"), dropped


def _parse_warnings(raw: Any) -> list[str]:
    """`template_warnings` arrives as a JSON string of objects with
    'message' (plus 'row', 'col', 'type'). Render to a flat list."""
    if not raw:
        return []
    try:
        items = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return [str(raw)[:200]]
    out: list[str] = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict):
            msg = item.get("message") or ""
            row = item.get("row")
            col = item.get("col") or item.get("column")
            prefix = ""
            if row:
                prefix += f"row {row}"
            if col:
                prefix += f" col {col}" if prefix else f"col {col}"
            out.append(f"{prefix}: {msg}" if prefix else str(msg))
        else:
            out.append(str(item))
    return out


def _log_error(row: dict) -> str:
    msgs = row.get("messages") or []
    rn = row.get("row_number") or "?"
    if isinstance(msgs, list) and msgs:
        return f"row {rn}: {msgs[0]}"
    return f"row {rn}: failed"


def _import_coa(
    client: ErpnextClient, path: str, doctype: str, company: str,
) -> Iterator[dict]:
    """Chart of Accounts importer is a one-shot synchronous method —
    no polling, but we still yield begin/done events for consistent
    UX with the Data Import handler."""
    if not company:
        raise ErpnextError("Chart of Accounts importer requires a company name")
    yield {"event": "uploading", "stage": "upload"}
    with open(path, "rb") as fh:
        content = fh.read()
    file_url = client.upload_file(os.path.basename(path), content, content_type="text/csv")
    yield {"event": "uploading", "stage": "import_coa"}
    resp = client.import_chart_of_accounts(file_url, company)
    msg = (resp or {}).get("message") or {}
    imported = len(msg.get("imported") or [])
    failed = len(msg.get("failed_to_import") or [])
    out: dict = {"event": "done",
                 "status": "success" if failed == 0 else "partial",
                 "imported": imported, "failed": failed}
    if failed:
        out["errors"] = (msg.get("failed_to_import") or [])[:10]
    yield out


# -- verification -------------------------------------------------------------

def _verify_counts(client: ErpnextClient, summary: list[dict]) -> dict[str, dict]:
    """Query ERPnext for actual row counts per doctype after import."""
    seen: dict[str, int] = {}
    for entry in summary:
        if entry.get("status") not in {"done", "success", "partial"}:
            continue
        dt = entry.get("doctype")
        if not dt:
            continue
        if dt in seen:
            seen[dt] += int(entry.get("imported") or 0)
        else:
            seen[dt] = int(entry.get("imported") or 0)
    out: dict[str, dict] = {}
    for dt, expected in seen.items():
        try:
            actual = client.get_count(dt)
        except ErpnextError as e:
            out[dt] = {"expected": expected, "actual": None, "error": str(e)}
            continue
        out[dt] = {"expected": expected, "actual": actual}
    return out


# -- helpers ------------------------------------------------------------------

def _ordered_csv_files(output_dir: str) -> list[str]:
    return sorted(
        f for f in os.listdir(output_dir)
        if f.endswith(".csv") and not f.startswith("99_")
    )


def _slug_from_filename(fname: str) -> str:
    stem = fname[:-len(".csv")] if fname.endswith(".csv") else fname
    parts = stem.split("_", 1)
    if len(parts) != 2:
        return stem
    rest = parts[1]
    # Strip trailing chunk suffix `_001`, `_002`, …
    if "_" in rest:
        head, tail = rest.rsplit("_", 1)
        if tail.isdigit():
            return head
    return rest
