"""End-of-run audit: preservation report + admin setup checklist.

Runs last so it can read the final stats and the legacy table sizes
side by side. Two outputs land in `ctx.result`:

- `audit_report` (under stats / output_tables) — preservation counts
  vs source counts so the operator can confirm nothing was silently
  dropped.

- `__migration_setup_checklist__` — markdown for the ERPnext admin to
  follow before importing the CSVs (Stock Settings flag, custom field
  registration, dependency-ordered import sequence).
"""
from typing import Any

from core.strategies.erpnext.context import Context

CHECKLIST_KEY = "__migration_setup_checklist__"


def emit_audit(ctx: Context) -> None:
    _emit_preservation_report(ctx)
    _emit_setup_checklist(ctx)


# -- Preservation report ------------------------------------------------------

def _emit_preservation_report(ctx: Context) -> None:
    legacy_counts = _legacy_counts(ctx)
    output_counts = {dt: len(rows) for dt, rows in ctx.result.output_tables.items()}
    report = {
        "legacy_row_counts": legacy_counts,
        "output_doctype_counts": output_counts,
        "preserved": _preservation_summary(ctx, legacy_counts, output_counts),
        "warnings_count": len(ctx.result.warnings),
        "errors_count": len(ctx.result.errors),
    }
    ctx.result.output_tables["__audit_report__"] = [report]
    for key, value in output_counts.items():
        ctx.result.bump(f"out_{_slug(key)}", value)


def _legacy_counts(ctx: Context) -> dict[str, int]:
    return {name: len(rows) for name, rows in ctx.legacy.items()}


def _preservation_summary(
    ctx: Context,
    legacy: dict[str, int],
    output: dict[str, int],
) -> list[dict[str, Any]]:
    """One row per major preservation invariant, with pass/fail pulse."""
    rows: list[dict[str, Any]] = []
    rows.append(_check(
        "Items",
        legacy.get("CATEGORYT", 0) - len(_deleted_catids(ctx)),
        output.get("Item", 0),
    ))
    rows.append(_check(
        "Item Prices (non-zero only)",
        ctx.result.stats.get("item_prices_emitted", 0),
        output.get("Item Price", 0),
    ))
    rows.append(_check(
        "Customers (incl. walk-in + orphans)",
        legacy.get("CUSTT", 0) + 1
        + ctx.result.stats.get("orphan_customers_emitted", 0),
        output.get("Customer", 0),
    ))
    rows.append(_check(
        "Suppliers",
        legacy.get("SUPPLIERT", 0),
        output.get("Supplier", 0),
    ))
    rows.append(_check(
        "Banks",
        legacy.get("BANKT", 0),
        output.get("Bank", 0),
        slack=2,  # legacy may have duplicate bank names
    ))
    rows.append(_check(
        "Bank Accounts",
        legacy.get("BANKACCOUNTT", 0),
        output.get("Bank Account", 0),
    ))
    rows.append(_check(
        "Sales Invoices (named + summaries + returns)",
        ctx.result.stats.get("sales_invoices_emitted", 0)
        + ctx.result.stats.get("walkin_summaries_emitted", 0)
        + ctx.result.stats.get("sales_returns_emitted", 0),
        output.get("Sales Invoice", 0),
    ))
    rows.append(_check(
        "Purchase Invoices (incl. returns)",
        ctx.result.stats.get("purchase_invoices_emitted", 0)
        + ctx.result.stats.get("purchase_returns_emitted", 0),
        output.get("Purchase Invoice", 0),
    ))
    rows.append(_check(
        "Payment Entries",
        ctx.result.stats.get("customer_receipts_emitted", 0)
        + ctx.result.stats.get("supplier_payments_emitted", 0),
        output.get("Payment Entry", 0),
    ))
    rows.append(_check(
        "Journal Entries (manual + opening + bounced)",
        ctx.result.stats.get("manual_journals_emitted", 0)
        + ctx.result.stats.get("opening_journals_emitted", 0)
        + ctx.result.stats.get("bounced_cheque_journals_emitted", 0),
        output.get("Journal Entry", 0),
    ))
    rows.append(_check(
        "Employees",
        legacy.get("EMPLOYEET", 0),
        output.get("Employee", 0),
        slack=5,
    ))
    return rows


def _check(label: str, expected: int, actual: int, slack: int = 0) -> dict:
    diff = actual - expected
    status = "ok" if abs(diff) <= slack else ("over" if diff > 0 else "short")
    return {"label": label, "expected": expected, "actual": actual,
            "diff": diff, "status": status}


def _deleted_catids(ctx: Context) -> set[str]:
    return {r.get("CATID", "") for r in ctx.table("DELETEDCATEGORYT") if r.get("CATID")}


def _slug(name: str) -> str:
    return name.lower().replace(" ", "_")


# -- Migration setup checklist (markdown) ------------------------------------

def _emit_setup_checklist(ctx: Context) -> None:
    md = _checklist_markdown(ctx)
    ctx.result.output_tables[CHECKLIST_KEY] = [{"filename": "migration_setup_checklist.md",
                                                "content": md}]


def _checklist_markdown(ctx: Context) -> str:
    company = ctx.config.company_name
    abbr = ctx.config.company_abbr
    has_negative = ctx.result.stats.get("stock_lines_negative", 0) > 0
    return _CHECKLIST_TEMPLATE.format(
        company=company,
        abbr=abbr,
        opening_date=ctx.config.opening_date or "(set in config)",
        currency=ctx.config.default_currency,
        country=ctx.config.country,
        negative_note=_NEGATIVE_BLURB if has_negative else "",
    )


_NEGATIVE_BLURB = (
    "    The strategy emitted negative-qty rows for items that legacy "
    "data shows below zero (typically dispatch-before-receipt). "
    "ERPnext designed Allow Negative Stock for exactly this case.\n"
)


_CHECKLIST_TEMPLATE = """# Migration Setup Checklist — Al Arabi → ERPnext v16

This is a one-time setup the ERPnext admin runs **before** importing
the data CSVs. Each step is required for the imports to succeed.

## 1. Create the company

- Company name: **{company}**
- Abbreviation: **{abbr}**  (used in autonamed warehouses / accounts)
- Default currency: **{currency}**
- Country: **{country}**
- Use the standard Chart of Accounts initially; the strategy emits
  Account records that augment / replace the relevant branches.

## 2. Stock Settings

- Stock Settings → **Allow Negative Stock = ✓**
{negative_note}

## 3. Add custom fields (cheque + traceback)

The strategy emits a number of legacy_* and cheque_* fields on
standard doctypes. Register them via Customize Form once:

- **Sales Invoice**: legacy_docno, legacy_docserial, legacy_kind,
  legacy_summary, legacy_summary_count, legacy_summary_terminal
- **Purchase Invoice**: legacy_docno, legacy_docserial
- **Customer**: legacy_custid, legacy_kind
- **Supplier**: legacy_suppid
- **Account**: legacy_acctid, legacy_class
- **Item**: legacy_catid
- **Employee**: legacy_empid, legacy_acctid
- **Payment Entry** (cheque metadata): cheque_owner_name (Data),
  cheque_bank (Link → Bank), cheque_branch (Data),
  cheque_clearing_date (Date), cheque_returned (Check),
  cheque_returned_count (Int), cheque_bank_account (Data),
  linked_legacy_cheque_id (Data), legacy_docno, legacy_docserial
- **Journal Entry**: linked_legacy_cheque_id, is_cheque_bounce (Check),
  legacy_docno, legacy_docserial; on the `accounts` child:
  cheque_no, cheque_date, cheque_clearing_date, cheque_owner_name,
  cheque_bank, cheque_branch, cheque_returned, cheque_bank_account,
  linked_legacy_cheque_id

(Field types in parens; default Data otherwise.)

## 4. Import sequence

Use Frappe Data Import (UI) for masters; `bench --site … import-csv
--submit` for the bulk transactional files.

```
01_uom.csv                          → UOM (insert)
02_warehouse.csv                    → Warehouse
03_price_list.csv                   → Price List
04_item_group.csv                   → Item Group
05_brand.csv                        → Brand
06_bank.csv                         → Bank
10_account.csv                      → USE 'Chart of Accounts Importer'
                                      (Accounting → Chart of Accounts
                                      Importer), NOT regular Data Import.
                                      Tree doctype validation fails on
                                      Data Import because parent_account
                                      links are checked against the DB
                                      up-front; the dedicated importer
                                      handles the hierarchy in one pass.
                                      File is the 8-column CoA template.
11_bank_account.csv                 → Bank Account (references the GL
                                      Account from 10_, hence imported
                                      after.)
20_customer.csv                     → Customer (incl. walk-in, orphans)
21_supplier.csv                     → Supplier
22_employee.csv                     → Employee
30_item.csv (chunked)               → Item (with barcodes child;
                                      depends on Supplier from 21_)
31_item_price.csv (chunked)         → Item Price
50_opening_journal.csv              → Journal Entry (is_opening=Yes)
51_stock_reconciliation.csv         → Stock Reconciliation (Opening)
60_sales_invoice_NN.csv (chunked)   → Sales Invoice (incl. returns)
61_purchase_invoice.csv             → Purchase Invoice (incl. returns)
70_payment_entry.csv                → Payment Entry (with cheque fields)
71_journal_entry.csv                → Journal Entry (manual + bounced)
```

For each transactional file, enable **Submit After Import** and
**Don't Send Emails** in the Data Import form.

## 5. Verify

After load, compare the strategy's preservation report (in the
transform output) against ERPnext's record counts to confirm parity.
"""
