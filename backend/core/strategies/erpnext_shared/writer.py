"""Frappe Data Import CSV writer for ERPnext doctype output.

Translates the strategy's `output_tables` (records-with-nested-children
shape) into the flat CSV format ERPnext's Data Import UI expects:
parent fields once on the first row of a group, then continuation rows
that carry exactly one child-row at a time with parent columns blank.

Files are emitted with topological-order numeric prefixes so the admin
imports them in dependency order. Records that exceed CHUNK_SIZE are
split into multiple files with `_NNN` suffixes (Sales Invoice in
particular hits this).

This module knows nothing about how output_tables was generated — it
just consumes the shape and writes correct Frappe CSVs. Audit report
and migration checklist artifacts are written alongside as `99_*` files.
"""
from __future__ import annotations

import csv
import json
import os
from typing import Any, Iterable

CHUNK_SIZE = 5_000


# Frappe Data Import accepts two formats for child columns:
#   1. `<table_fieldname>.<child_field_fieldname>`  (e.g. `barcodes.barcode`)
#   2. `<child_field_label> (<table_field_label>)`  (e.g. `Barcode (Barcodes)`)
# Verified against frappe/frappe v16 importer.py
# (build_fields_dict_for_column_matching). We use format 1 — unambiguous,
# no label lookup required, and matches whatever the parent's actual
# child-table fieldname is on this v16 install.

# Topological dependency order. Earlier-prefixed files must be imported
# before later-prefixed ones so cross-doctype references resolve.
DOCTYPE_PREFIX: dict[str, str] = {
    # Independent masters (no link dependencies on other emitted doctypes)
    "UOM": "01",          # custom UOMs only — v16 built-ins skipped
    "Warehouse": "02",
    "Price List": "03",
    "Item Group": "04",
    "Brand": "05",
    "Bank": "06",
    # Tree doctypes (Account uses CoA Importer, not Data Import)
    "Account": "10",
    "Bank Account": "11", # depends on Account + Bank
    # Parties (must precede Item — Item.supplier_items references Supplier)
    "Customer": "20",
    "Supplier": "21",
    "Employee": "22",
    # Items (depend on Supplier, Item Group, UOM, Warehouse, Price List)
    "Item": "30",
    "Item Price": "31",
    # 50 reserved for opening journal entries (split out at write time)
    "Stock Reconciliation": "51",
    # 60 reserved for non-return Sales Invoices
    "Purchase Invoice": "61",
    # 62 reserved for sales returns
    # 63 reserved for purchase returns
    "Payment Entry": "70",
    # 71 reserved for non-opening Journal Entries
}

# The per-doctype "primary stream" filename root. Splits handled below.
SPLITS = {
    "Sales Invoice": [
        ("60", "sales_invoice", lambda r: not r.get("is_return")),
        ("62", "sales_return", lambda r: bool(r.get("is_return"))),
    ],
    "Purchase Invoice": [
        ("61", "purchase_invoice", lambda r: not r.get("is_return")),
        ("63", "purchase_return", lambda r: bool(r.get("is_return"))),
    ],
    "Journal Entry": [
        ("50", "journal_entry_opening",
         lambda r: r.get("is_opening") in ("Yes", "yes", 1, True)),
        ("71", "journal_entry",
         lambda r: r.get("is_opening") not in ("Yes", "yes", 1, True)),
    ],
}


def write_frappe_csvs(
    output_tables: dict[str, list[dict[str, Any]]],
    output_dir: str,
    audit_report: dict | None = None,
    checklist_md: str | None = None,
    bucket_coverage_md: str | None = None,
    include_legacy_fields: bool = True,
    staging_dir: str | None = None,
) -> list[str]:
    """Write all doctype CSVs in dependency order.

    Two input modes:
    - `output_tables` populated (in-memory mode): iterate the dict and
      emit per doctype.
    - `staging_dir` set (disk-streaming mode): the strategy already
      wrote per-doctype JSONL files there during transform. Read them
      back lazily one doctype at a time so peak memory stays bounded.

    `include_legacy_fields=False` strips every `legacy_*` parent and
    child column from the output so the admin doesn't have to register
    custom fields in ERPnext before importing.

    Returns the list of filenames produced (relative to output_dir).
    """
    os.makedirs(output_dir, exist_ok=True)
    written: list[str] = []
    for doctype, records in _iter_doctype_records(output_tables, staging_dir):
        if doctype.startswith("__") or not records:
            continue
        cleaned = _strip_legacy(records) if not include_legacy_fields else records
        written.extend(_write_one_doctype(doctype, cleaned, output_dir))
    written.extend(_write_audit_artifacts(
        output_dir, audit_report, checklist_md, bucket_coverage_md,
    ))
    written.sort()
    return written


def _iter_doctype_records(
    output_tables: dict[str, list[dict[str, Any]]],
    staging_dir: str | None,
):
    """Yield (doctype, records) pairs from whichever source has data.

    Disk-mode: read each JSONL file fully into memory ONLY for the
    duration of writing that doctype's CSV, then drop. Keeps peak
    memory bounded to one doctype's records at a time.
    """
    if staging_dir and os.path.isdir(staging_dir):
        for fname in sorted(os.listdir(staging_dir)):
            if not fname.endswith(".jsonl"):
                continue
            doctype = _doctype_from_jsonl(fname)
            path = os.path.join(staging_dir, fname)
            records: list[dict[str, Any]] = []
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        records.append(json.loads(line))
            yield doctype, records
    for doctype, records in output_tables.items():
        if not doctype.startswith("__"):
            yield doctype, records


_DOCTYPE_FROM_SAFE = {
    "uom": "UOM",
    "warehouse": "Warehouse",
    "price_list": "Price List",
    "item_group": "Item Group",
    "brand": "Brand",
    "bank": "Bank",
    "bank_account": "Bank Account",
    "account": "Account",
    "item": "Item",
    "item_price": "Item Price",
    "customer": "Customer",
    "supplier": "Supplier",
    "employee": "Employee",
    "sales_invoice": "Sales Invoice",
    "purchase_invoice": "Purchase Invoice",
    "stock_reconciliation": "Stock Reconciliation",
    "payment_entry": "Payment Entry",
    "journal_entry": "Journal Entry",
}


def _doctype_from_jsonl(fname: str) -> str:
    stem = fname[:-len(".jsonl")]
    # JSONL stems come from `_safe_doctype()` which preserves case but
    # replaces spaces with underscores ('Bank Account' → 'Bank_Account').
    # The dict keys are lowercase, so normalize before lookup. Fall back
    # to the underscore-stripped stem if no entry matches.
    return _DOCTYPE_FROM_SAFE.get(stem.lower(), stem.replace("_", " "))


def _strip_legacy(records: list[dict]) -> list[dict]:
    """Remove `legacy_*` keys from each record (and its child rows).

    Mutation-free: returns new dicts so the in-memory strategy result
    stays intact for the audit report and re-runs.
    """
    return [_strip_one(r) for r in records]


def _strip_one(record: dict) -> dict:
    out: dict = {}
    for key, value in record.items():
        if isinstance(key, str) and key.startswith("legacy_"):
            continue
        if isinstance(value, list):
            out[key] = [_strip_one(c) if isinstance(c, dict) else c for c in value]
        else:
            out[key] = value
    return out


# -- per-doctype dispatch -----------------------------------------------------

def _write_one_doctype(
    doctype: str,
    records: list[dict],
    output_dir: str,
) -> list[str]:
    if doctype == "Account":
        return _write_coa_importer_csv(records, output_dir)
    if doctype in SPLITS:
        return _write_split_streams(doctype, records, output_dir)
    prefix = DOCTYPE_PREFIX.get(doctype, "90")
    base = _slug(doctype)
    return _write_chunks(records, output_dir, prefix, base, doctype)


# -- Account: Chart of Accounts Importer template -----------------------------
# Tree doctypes can't be imported via regular Data Import — Frappe validates
# every parent_account link against the DB up-front, so on pass 1 nothing
# exists yet and every reference fails. ERPnext ships a dedicated tool for
# CoA hierarchies (Accounting → Chart of Accounts Importer) which processes
# rows top-down and resolves the tree in one pass.
#
# That tool expects a fixed 8-column template with short names (no abbr
# suffix) — Parent Account references the parent's short name; Frappe
# applies the abbr automatically when it creates each Frappe record.

COA_HEADERS = [
    "Account Name", "Parent Account", "Account Number",
    "Parent Account Number", "Is Group", "Account Type",
    "Root Type", "Account Currency",
]


def _write_coa_importer_csv(records: list[dict], output_dir: str) -> list[str]:
    path = os.path.join(output_dir, "10_account.csv")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_ALL)
        writer.writerow(COA_HEADERS)
        for r in records:
            writer.writerow([
                r.get("account_name", ""),
                _coa_parent_short_name(r),
                "",  # Account Number — legacy doesn't carry this
                "",  # Parent Account Number — same
                1 if r.get("is_group") else 0,
                r.get("account_type", "") or "",
                r.get("root_type", "") or "",
                r.get("account_currency", "") or "",
            ])
    return [os.path.basename(path)]


def _coa_parent_short_name(record: dict) -> str:
    """Account.parent_account in our records is the autonamed form
    'X - {abbr}'; the CoA Importer wants the short name 'X'."""
    parent = record.get("parent_account") or ""
    if " - " in parent:
        return parent.rsplit(" - ", 1)[0]
    return parent


def _write_split_streams(
    doctype: str,
    records: list[dict],
    output_dir: str,
) -> list[str]:
    out: list[str] = []
    for prefix, base, predicate in SPLITS[doctype]:
        subset = [r for r in records if predicate(r)]
        if subset:
            out.extend(_write_chunks(subset, output_dir, prefix, base, doctype))
    return out


def _write_chunks(
    records: list[dict],
    output_dir: str,
    prefix: str,
    base: str,
    doctype: str,
) -> list[str]:
    if len(records) <= CHUNK_SIZE:
        path = os.path.join(output_dir, f"{prefix}_{base}.csv")
        _write_csv(path, records, doctype)
        return [os.path.basename(path)]
    paths: list[str] = []
    for idx, chunk in enumerate(_chunk(records, CHUNK_SIZE), start=1):
        suffix = f"{idx:03d}"
        path = os.path.join(output_dir, f"{prefix}_{base}_{suffix}.csv")
        _write_csv(path, chunk, doctype)
        paths.append(os.path.basename(path))
    return paths


def _chunk(items: list[dict], size: int) -> Iterable[list[dict]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


# -- column / row layout (Frappe flat CSV) -----------------------------------

def _write_csv(path: str, records: list[dict], doctype: str) -> None:
    parent_fields, child_tables = _collect_columns(records)
    headers = _headers(parent_fields, child_tables, doctype)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(headers)
        for record in records:
            for row in _record_rows(record, parent_fields, child_tables, doctype):
                writer.writerow(_row_values(row, headers))


def _collect_columns(
    records: list[dict],
) -> tuple[list[str], dict[str, list[str]]]:
    parent_fields: list[str] = []
    seen_parent: set[str] = set()
    child_tables: dict[str, list[str]] = {}
    child_seen: dict[str, set[str]] = {}

    for record in records:
        for key, value in record.items():
            if isinstance(value, list):
                _collect_child_columns(key, value, child_tables, child_seen)
                continue
            if key not in seen_parent:
                seen_parent.add(key)
                parent_fields.append(key)
    return parent_fields, child_tables


def _collect_child_columns(
    field: str,
    rows: list,
    child_tables: dict[str, list[str]],
    child_seen: dict[str, set[str]],
) -> None:
    columns = child_tables.setdefault(field, [])
    seen = child_seen.setdefault(field, set())
    for child in rows or []:
        if not isinstance(child, dict):
            continue
        for k in child.keys():
            if k not in seen:
                seen.add(k)
                columns.append(k)


def _headers(
    parent_fields: list[str],
    child_tables: dict[str, list[str]],
    parent_doctype: str,
) -> list[str]:
    out: list[str] = []
    if "name" in parent_fields:
        out.append("ID")
        out.extend(f for f in parent_fields if f != "name")
    else:
        out.append("ID")
        out.extend(parent_fields)
    for child_field, columns in child_tables.items():
        out.extend(f"{child_field}.{col}" for col in columns)
    return out


def _record_rows(
    record: dict,
    parent_fields: list[str],
    child_tables: dict[str, list[str]],
    parent_doctype: str,
) -> Iterable[dict[str, Any]]:
    """Yield the CSV rows for a single parent record.

    Row 0 carries parent fields + the first child of every child table.
    Continuation rows carry exactly one extra child-row from one table.
    """
    first: dict[str, Any] = {"ID": record.get("name", "")}
    for f in parent_fields:
        if f == "name":
            continue
        first[f] = record.get(f, "")
    for child_field, columns in child_tables.items():
        children = _child_rows(record.get(child_field))
        if children:
            _fill_child_columns(first, child_field, columns, children[0], parent_doctype)
    yield first

    for child_field, columns in child_tables.items():
        children = _child_rows(record.get(child_field))
        for child in children[1:]:
            row: dict[str, Any] = {}
            _fill_child_columns(row, child_field, columns, child, parent_doctype)
            yield row


def _child_rows(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [c for c in value if isinstance(c, dict)]


def _fill_child_columns(
    row: dict,
    child_field: str,
    columns: list[str],
    child: dict,
    parent_doctype: str,
) -> None:
    for col in columns:
        row[f"{child_field}.{col}"] = child.get(col, "")


def _row_values(row: dict, headers: list[str]) -> list[Any]:
    return [_format_value(row.get(h, "")) for h in headers]


def _format_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


# -- audit / checklist artifacts ---------------------------------------------

def _write_audit_artifacts(
    output_dir: str,
    audit_report: dict | None,
    checklist_md: str | None,
    bucket_coverage_md: str | None = None,
) -> list[str]:
    out: list[str] = []
    if audit_report:
        path = os.path.join(output_dir, "99_audit_report.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(audit_report, fh, ensure_ascii=False, indent=2)
        out.append(os.path.basename(path))
    if checklist_md:
        path = os.path.join(output_dir, "99_migration_setup_checklist.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(checklist_md)
        out.append(os.path.basename(path))
    if bucket_coverage_md:
        path = os.path.join(output_dir, "99_native_bucket_coverage.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(bucket_coverage_md)
        out.append(os.path.basename(path))
    return out


# -- helpers ------------------------------------------------------------------

def _slug(doctype: str) -> str:
    return doctype.lower().replace(" ", "_")
