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
import os
import time
from typing import Any, Iterable, Iterator

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

POLL_INTERVAL_SEC = 2.0
POLL_TIMEOUT_SEC = 600


def run_live_import(
    output_dir: str, client: ErpnextClient, company: str,
) -> Iterator[dict]:
    """Yield progress events while pushing every CSV in `output_dir`."""
    files = _ordered_csv_files(output_dir)
    if not files:
        yield {"event": "error", "message": "no CSV files in output dir — run transform first"}
        return

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

        yield {"event": "uploading", "file": fname, "doctype": doctype}
        path = os.path.join(output_dir, fname)
        try:
            if slug == "account":
                result = _import_coa(client, path, company)
            else:
                result = _import_via_data_import(client, path, doctype)
        except ErpnextError as e:
            yield {"event": "error", "file": fname, "doctype": doctype, "message": str(e),
                   "payload": e.payload}
            summary.append({"file": fname, "status": "error", "error": str(e)})
            return

        result["file"] = fname
        result["doctype"] = doctype
        yield {"event": "done", **result}
        summary.append({"file": fname, "status": "done", **result})

    counts = _verify_counts(client, summary)
    yield {"event": "complete", "summary": summary, "verification": counts}


# -- per-file handlers --------------------------------------------------------

def _import_via_data_import(
    client: ErpnextClient, path: str, doctype: str,
) -> dict:
    fname = os.path.basename(path)
    with open(path, "rb") as fh:
        content = fh.read()
    file_url = client.upload_file(fname, content, content_type="text/csv")
    if not file_url:
        raise ErpnextError("upload_file returned no file_url")

    name = client.create_data_import(doctype, file_url)
    if not name:
        raise ErpnextError("create_data_import returned no name")

    client.start_data_import(name)
    return _poll_data_import(client, name)


def _poll_data_import(client: ErpnextClient, name: str) -> dict:
    deadline = time.monotonic() + POLL_TIMEOUT_SEC
    while True:
        if time.monotonic() > deadline:
            raise ErpnextError(f"Data Import {name} timed out after {POLL_TIMEOUT_SEC}s")
        time.sleep(POLL_INTERVAL_SEC)
        d = client.get_data_import_status(name)
        status = d.get("status") or "Pending"
        if status in {"Pending", "In Progress", "Queued", "Started"}:
            continue
        log = list(parse_import_log(d.get("import_log") or ""))
        successes = sum(1 for r in log if r.get("success"))
        failures = sum(1 for r in log if not r.get("success"))
        if status == "Success":
            return {"status": "success", "imported": successes, "failed": 0,
                    "data_import": name}
        if status == "Partial Success":
            return {"status": "partial", "imported": successes, "failed": failures,
                    "data_import": name,
                    "errors": [_log_error(r) for r in log if not r.get("success")][:10]}
        # Error
        if not log:
            errs = client.get_data_import_error_log(name)
            err = errs[0]["error"] if errs else d.get("failure_message") or "Data Import failed"
        else:
            err = "; ".join(_log_error(r) for r in log if not r.get("success"))[:1000]
        raise ErpnextError(f"Data Import {name} failed: {err}")


def _log_error(row: dict) -> str:
    msgs = row.get("messages") or []
    rn = row.get("row_number") or "?"
    if isinstance(msgs, list) and msgs:
        return f"row {rn}: {msgs[0]}"
    return f"row {rn}: failed"


def _import_coa(client: ErpnextClient, path: str, company: str) -> dict:
    if not company:
        raise ErpnextError("Chart of Accounts importer requires a company name")
    with open(path, "rb") as fh:
        content = fh.read()
    file_url = client.upload_file(os.path.basename(path), content, content_type="text/csv")
    resp = client.import_chart_of_accounts(file_url, company)
    msg = (resp or {}).get("message") or {}
    imported = len(msg.get("imported") or [])
    failed = len(msg.get("failed_to_import") or [])
    out: dict = {"status": "success" if failed == 0 else "partial",
                 "imported": imported, "failed": failed}
    if failed:
        out["errors"] = (msg.get("failed_to_import") or [])[:10]
    return out


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
