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

from core.strategies.erpnext_shared.context import Context

CHECKLIST_KEY = "__migration_setup_checklist__"


def emit_audit(ctx: Context) -> None:
    _emit_preservation_report(ctx)
    _emit_setup_checklist(ctx)


# -- Preservation report ------------------------------------------------------


def _emit_preservation_report(ctx: Context) -> None:
    legacy_counts = _legacy_counts(ctx)
    # Use doctype_counts() so this works regardless of whether the
    # strategy ran in in-memory or disk-streaming mode — it tracks emits
    # via a counter independent of where rows ended up.
    output_counts = ctx.result.doctype_counts()
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
    """One row per major preservation invariant, with pass/fail pulse.

    Only checks entities the user selected — partial migrations skip the
    rest so the report doesn't flag deliberately-omitted slices as
    "short".
    """
    active = ctx.config.selected_entities
    stats = ctx.result.stats
    rows: list[dict[str, Any]] = []
    if "items" in active:
        rows.append(
            _check(
                "Items",
                max(0, legacy.get("CATEGORYT", 0) - len(_deleted_catids(ctx))),
                output.get("Item", 0),
            )
        )
        rows.append(
            _check(
                "Item Prices (non-zero only)",
                stats.get("item_prices_emitted", 0),
                output.get("Item Price", 0),
            )
        )
    if "customers" in active:
        rows.append(
            _check(
                "Customers (incl. walk-in + orphans)",
                legacy.get("CUSTT", 0) + 1 + stats.get("orphan_customers_emitted", 0),
                output.get("Customer", 0),
            )
        )
    if "suppliers" in active:
        rows.append(
            _check(
                "Suppliers",
                legacy.get("SUPPLIERT", 0),
                output.get("Supplier", 0),
            )
        )
    if "bank_accounts" in active:
        rows.append(
            _check(
                "Banks",
                legacy.get("BANKT", 0),
                output.get("Bank", 0),
                slack=2,
            )
        )
        rows.append(
            _check(
                "Bank Accounts",
                legacy.get("BANKACCOUNTT", 0),
                output.get("Bank Account", 0),
            )
        )
    if "opening_balances" in active:
        rows.append(
            _check(
                "Opening Journal Entries (parties + GL + cheques)",
                _opening_je_expected(stats),
                output.get("Journal Entry", 0),
            )
        )
    if "employees" in active:
        rows.append(
            _check(
                "Employees",
                legacy.get("EMPLOYEET", 0),
                output.get("Employee", 0),
                slack=5,
            )
        )
    return rows


def _opening_je_expected(stats: dict[str, int]) -> int:
    """Sum every `opening_*_emitted` stat so mirror's per-leaf and native's
    bucketed / bank-leaf JE counts both contribute to the same total."""
    return sum(
        v
        for k, v in stats.items()
        if k.startswith("opening_") and k.endswith("_emitted")
    )


def _check(label: str, expected: int, actual: int, slack: int = 0) -> dict:
    diff = actual - expected
    status = "ok" if abs(diff) <= slack else ("over" if diff > 0 else "short")
    return {
        "label": label,
        "expected": expected,
        "actual": actual,
        "diff": diff,
        "status": status,
    }


def _deleted_catids(ctx: Context) -> set[str]:
    return {r.get("CATID", "") for r in ctx.table("DELETEDCATEGORYT") if r.get("CATID")}


def _slug(name: str) -> str:
    return name.lower().replace(" ", "_")


# -- Migration setup checklist (markdown) ------------------------------------


def _emit_setup_checklist(ctx: Context) -> None:
    md = _checklist_markdown(ctx)
    ctx.result.output_tables[CHECKLIST_KEY] = [
        {"filename": "migration_setup_checklist.md", "content": md}
    ]


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


_CHECKLIST_TEMPLATE = """# Migration Setup Checklist — ERPnext v16

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

## 2b. Fiscal Year (REQUIRED)

ERPnext rejects every Journal Entry whose `posting_date` doesn't fall
inside an active Fiscal Year for the company. The standard install
auto-creates one for the install year only — older years are NOT
created from a Company's `date_of_establishment`.

Before importing the opening JE files, ensure a Fiscal Year covers
your **opening_date** ({opening_date}). Either:

- **Accounting → Fiscal Year → New** with year_start_date and
  year_end_date that bracket the opening date, or
- run the live ERPnext push (the loader auto-creates a Jan→Dec
  Fiscal Year for the opening date's year if none exists).

## 3. Add custom fields (traceback)

The strategy emits a few `legacy_*` fields on standard doctypes for
post-migration auditability. Register them via Customize Form once:

- **Customer**: legacy_custid, legacy_kind
- **Supplier**: legacy_suppid
- **Account**: legacy_acctid, legacy_class
- **Item**: legacy_catid
- **Employee**: legacy_empid, legacy_acctid
- **Journal Entry**: legacy_acctid, legacy_chequeid, legacy_kind

(All Data fields. Toggle off via `include_legacy_fields=False` if you
don't want the custom-field setup step.)

## 4. Import sequence

Use Frappe Data Import (UI) for masters; the **Chart of Accounts
Importer** for accounts; bulk submit for opening JEs.

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
                                      8-column CoA template format.
                                      Includes synthetic Debtors,
                                      Creditors, Temporary Opening,
                                      and Cheques in Hand.
11_bank_account.csv                 → Bank Account (references GL
                                      Accounts from 10_, hence after.)
20_customer.csv                     → Customer (incl. walk-in, orphans)
21_supplier.csv                     → Supplier
22_employee.csv                     → Employee
30_item.csv (chunked)               → Item (with barcodes child)
31_item_price.csv (chunked)         → Item Price
50_journal_entry_opening_NN.csv     → Journal Entry (is_opening=Yes)
                                      Three flavours interleaved:
                                      • OPN-CUST-* customer balances
                                      • OPN-SUPP-* supplier balances
                                      • OPN-GL-*   bank/cash/VAT/
                                                   capital/etc.
                                      • OPN-CHQ-*  outstanding cheques
51_stock_reconciliation.csv         → Stock Reconciliation (Opening)
```

For the opening JE files, enable **Submit After Import** and
**Don't Send Emails** in the Data Import form.

## 5. Verify

After load, check **Trial Balance**:

- The synthetic **Temporary Opening** account should net to ~zero
  if the legacy books balance. A non-zero residual = data integrity
  gap in the legacy source (e.g., orphan accounts, unposted journals).
- **Customer Aging** report should show customer-by-customer balances.
- **Supplier Aging** report should show supplier-by-supplier balances.
- **Cheques in Hand** account ledger lists each outstanding cheque
  with its number, date, and originator (in the JE remark).

After verification, you can disable / archive the **Temporary Opening**
account (or post a closing JE to roll its residual into Retained
Earnings if you want a perfectly clean trial balance).
"""
