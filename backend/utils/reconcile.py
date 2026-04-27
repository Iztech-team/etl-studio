"""Reconciliation pass — turn "lossless migration" from a claim into a
measurable property.

Given a transformed result + the legacy raw, runs four classes of check:

  1. **Voucher balance** — for every voucher_no in the GL entry table,
     sum(debit) must equal sum(credit) within tolerance.
  2. **Per-account balance tie-out** — for every account that exists in
     both the legacy and the target, the sum of debits-minus-credits in
     the migrated GL Entries must equal the legacy account's balance.
  3. **Per-document line totals** — for every Sales / Purchase Invoice,
     sum(line.amount) must approximately equal the document grand_total.
  4. **FK integrity** — every child row's parent reference must resolve
     to a row that actually exists in the parent table.

The result is a `ReconcileReport` dict with a top-level pass/fail flag
plus a list of issue records the user can drill into.

Used in two places:
  - The /api/reconcile/{session_id} endpoint (manual pre-load check)
  - Optionally, automatically right after /api/transform, blocking load
    if the report fails. The caller decides.

The thresholds (currency_tolerance, count_tolerance) are intentionally
exposed as parameters so the user can dial them per project. Legacy
systems often have rounding drift; a single penny per invoice is fine,
a dollar isn't.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

# ---------- public types ----------------------------------------------------

# A single reconciliation issue. Categorized so the report can summarize
# without losing detail. `severity` is "error" (blocks load) or "warning".
Issue = Dict[str, Any]


def _add(issues: List[Issue], **fields: Any) -> None:
    issues.append(fields)


# ---------- check 1: voucher balance ----------------------------------------


def check_voucher_balance(
    gl_rows: List[Dict[str, Any]],
    *,
    voucher_field: str = "voucher_no",
    debit_field: str = "debit",
    credit_field: str = "credit",
    tolerance: float = 0.01,
) -> List[Issue]:
    """For every voucher_no, Σ(debit) must equal Σ(credit). The tolerance
    forgives sub-cent rounding drift but flags anything bigger."""
    by_voucher: Dict[Any, Tuple[float, float]] = {}
    for r in gl_rows:
        v = r.get(voucher_field)
        if v is None or v == "":
            continue
        d = _num(r.get(debit_field))
        c = _num(r.get(credit_field))
        old = by_voucher.get(v, (0.0, 0.0))
        by_voucher[v] = (old[0] + d, old[1] + c)

    issues: List[Issue] = []
    for v, (d, c) in by_voucher.items():
        diff = round(d - c, 4)
        if abs(diff) > tolerance:
            _add(
                issues,
                check="voucher_balance",
                severity="error",
                voucher=v,
                debit=round(d, 4),
                credit=round(c, 4),
                diff=diff,
            )
    return issues


# ---------- check 2: per-account balance tie-out ----------------------------


def check_account_balances(
    gl_rows: List[Dict[str, Any]],
    legacy_balances: Dict[Any, float],
    *,
    account_field: str = "account",
    debit_field: str = "debit",
    credit_field: str = "credit",
    tolerance: float = 0.01,
) -> List[Issue]:
    """`legacy_balances` is a dict mapping the same identifier the GL
    rows use for `account` to the legacy snapshot balance. Caller is
    responsible for converting from legacy ACCOUNTID → ERPnext name if
    they renamed."""
    derived: Dict[Any, float] = {}
    for r in gl_rows:
        a = r.get(account_field)
        if a is None or a == "":
            continue
        derived[a] = derived.get(a, 0.0) + _num(r.get(debit_field)) - _num(r.get(credit_field))

    issues: List[Issue] = []
    all_accounts = set(derived) | set(legacy_balances)
    for a in all_accounts:
        legacy = round(_num(legacy_balances.get(a)), 4)
        target = round(derived.get(a, 0.0), 4)
        diff = round(target - legacy, 4)
        if abs(diff) > tolerance:
            _add(
                issues,
                check="account_balance",
                severity="error",
                account=a,
                legacy_balance=legacy,
                target_derived=target,
                diff=diff,
            )
    return issues


# ---------- check 3: invoice line totals ------------------------------------


def check_invoice_line_totals(
    invoice_rows: List[Dict[str, Any]],
    line_rows: List[Dict[str, Any]],
    *,
    invoice_name_field: str = "name",
    invoice_total_field: str = "grand_total",
    invoice_tax_field: str = "total_taxes_and_charges",
    line_parent_field: str = "parent",
    line_amount_field: str = "amount",
    tolerance: float = 0.05,
    label: str = "sales_invoice",
) -> List[Issue]:
    """Verify each invoice's grand_total ≈ Σ(line.amount) + total_taxes.
    Tolerance is more generous than voucher balance because legacy
    rounding rules differ across line vs document totals."""
    line_sum: Dict[Any, float] = {}
    for r in line_rows:
        p = r.get(line_parent_field)
        if p is None or p == "":
            continue
        line_sum[p] = line_sum.get(p, 0.0) + _num(r.get(line_amount_field))

    issues: List[Issue] = []
    for inv in invoice_rows:
        name = inv.get(invoice_name_field)
        if name is None or name == "":
            continue
        total = _num(inv.get(invoice_total_field))
        tax = _num(inv.get(invoice_tax_field))
        derived = round(line_sum.get(name, 0.0) + tax, 4)
        diff = round(derived - total, 4)
        if abs(diff) > tolerance:
            _add(
                issues,
                check="invoice_line_totals",
                severity="error",
                doctype=label,
                invoice=name,
                invoice_grand_total=round(total, 4),
                lines_plus_tax=derived,
                diff=diff,
            )
    return issues


# ---------- check 4: FK integrity -------------------------------------------


def check_fk_integrity(
    target_tables: Dict[str, List[Dict[str, Any]]],
    fk_specs: Iterable[Dict[str, str]],
    *,
    name_column: str = "name",
) -> List[Issue]:
    """Each fk_spec is `{child: target_name, parent: target_name,
    child_field: ..., parent_field: name_column-by-default}`. We check
    that every non-null value in `child_field` of `child` rows exists as
    a value in `parent_field` of the parent table."""
    issues: List[Issue] = []
    for spec in fk_specs:
        child_t = spec.get("child")
        parent_t = spec.get("parent")
        child_f = spec.get("child_field")
        parent_f = spec.get("parent_field") or name_column
        if not (child_t and parent_t and child_f):
            continue
        child_rows = target_tables.get(child_t, [])
        parent_rows = target_tables.get(parent_t, [])
        if not child_rows or not parent_rows:
            continue
        parent_keys = {r.get(parent_f) for r in parent_rows if r.get(parent_f) is not None}
        orphans = 0
        sample: List[Any] = []
        for r in child_rows:
            v = r.get(child_f)
            if v is None or v == "":
                continue
            if v not in parent_keys:
                orphans += 1
                if len(sample) < 5:
                    sample.append(v)
        if orphans > 0:
            _add(
                issues,
                check="fk_integrity",
                severity="error",
                child_table=child_t,
                parent_table=parent_t,
                child_field=child_f,
                orphan_count=orphans,
                sample_orphan_values=sample,
            )
    return issues


# ---------- top-level report ------------------------------------------------


def reconcile(
    target_tables: Dict[str, List[Dict[str, Any]]],
    *,
    legacy_account_balances: Optional[Dict[Any, float]] = None,
    invoice_specs: Optional[List[Dict[str, str]]] = None,
    gl_table: str = "gl_entry",
    fk_specs: Optional[List[Dict[str, str]]] = None,
    voucher_tolerance: float = 0.01,
    account_tolerance: float = 0.01,
    invoice_tolerance: float = 0.05,
) -> Dict[str, Any]:
    """Run every check that has the data available. Skips silently when
    a needed table is missing (e.g. no GL entries means voucher and
    account checks can't run)."""
    issues: List[Issue] = []
    summary: Dict[str, Any] = {"checks_run": [], "checks_skipped": []}

    gl_rows = target_tables.get(gl_table, [])
    if gl_rows:
        issues += check_voucher_balance(gl_rows, tolerance=voucher_tolerance)
        summary["checks_run"].append("voucher_balance")
        if legacy_account_balances:
            issues += check_account_balances(
                gl_rows,
                legacy_account_balances,
                tolerance=account_tolerance,
            )
            summary["checks_run"].append("account_balance")
        else:
            summary["checks_skipped"].append("account_balance (no legacy balances provided)")
    else:
        summary["checks_skipped"].append(f"voucher_balance ({gl_table} not in output)")
        summary["checks_skipped"].append(f"account_balance ({gl_table} not in output)")

    for spec in invoice_specs or []:
        inv_t = spec.get("invoice_table")
        line_t = spec.get("line_table")
        label = spec.get("label", inv_t or "invoice")
        if not inv_t or not line_t:
            continue
        inv_rows = target_tables.get(inv_t, [])
        line_rows = target_tables.get(line_t, [])
        if not inv_rows or not line_rows:
            summary["checks_skipped"].append(f"invoice_line_totals[{label}] (missing rows)")
            continue
        issues += check_invoice_line_totals(
            inv_rows, line_rows,
            tolerance=invoice_tolerance,
            label=label,
        )
        summary["checks_run"].append(f"invoice_line_totals[{label}]")

    if fk_specs:
        issues += check_fk_integrity(target_tables, fk_specs)
        summary["checks_run"].append("fk_integrity")

    errors = sum(1 for i in issues if i.get("severity") == "error")
    warnings = sum(1 for i in issues if i.get("severity") == "warning")
    return {
        "ok": errors == 0,
        "summary": {
            **summary,
            "issue_count": len(issues),
            "errors": errors,
            "warnings": warnings,
        },
        "issues": issues,
    }


# ---------- helpers ---------------------------------------------------------


def _num(v: Any) -> float:
    if v is None or v == "":
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0
