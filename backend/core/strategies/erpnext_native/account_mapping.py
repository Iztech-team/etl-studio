"""Legacy ACCOUNTT → ERPnext standard-CoA bucket classifier.

Phase 1 mapping uses CLASS only (the legacy account-class code). Anything
that doesn't match a CLASS rule falls through to a root-based fallback —
deliberately coarse so most legacy expense/income lands in
`Miscellaneous Expenses` / `Sales` until Phase 2 adds NAME heuristics
to split them into specific buckets (Salary, Office Rent, etc).

The bucket name returned here is the ERPnext leaf's `account_name` —
callers append the company abbr via `ctx.with_abbr(bucket)` to get the
autonamed form (`Sales - ALA`).
"""
from core.strategies.erpnext_shared.common import (
    ROOT_TYPE_BY_ID,
    clean_str,
    walk_to_root,
)
from core.strategies.erpnext_shared.context import Context

# Direct CLASS → bucket mapping. Every classification we know with confidence.
CLASS_TO_BUCKET: dict[str, str] = {
    "13": "Cash",
    "21": "VAT",
    "22": "VAT",
    "23": "VAT",
    "24": "VAT",
    "4":  "Furniture and Fixtures",  # generic Fixed Asset bucket; admin can split later
    "47": "Accumulated Depreciation",
    "51": "Round Off",
    # Indirect-expense leaves (everything routes to one bucket pre Phase 2)
    "7":  "Miscellaneous Expenses",
    "34": "Miscellaneous Expenses",
    "35": "Miscellaneous Expenses",
    "36": "Miscellaneous Expenses",
    "45": "Miscellaneous Expenses",
    # Direct-income leaves (everything routes to Sales pre Phase 2)
    "8":  "Sales",
    "32": "Sales",
    "33": "Sales",
    "44": "Sales",
}

# Customer/supplier — handled per-party (party_type linkage), not as bucket.
PARTY_CLASSES = {"2", "3"}

# Inventory — handled by Stock Reconciliation, not aggregated as a bucket.
INVENTORY_CLASSES = {"40", "41", "42"}

# Bank-class accounts — emitted as per-currency leaves under Bank Accounts;
# their balances post to those leaves, not to an aggregated bucket.
BANK_CLASSES = {"10", "14"}

# Fallback by walked root_type when CLASS doesn't pin a bucket.
FALLBACK_BY_ROOT_TYPE: dict[str, str] = {
    "Asset":     "Earnest Money",       # tiny / unused for most legacies
    "Liability": "Accrued Expenses",
    "Equity":    "Capital Stock",
    "Income":    "Sales",
    "Expense":   "Miscellaneous Expenses",
}


def classify_account(ctx: Context, row: dict) -> str | None:
    """Return the bucket leaf name for a legacy account, or None to skip.

    Returns None for:
    - Customer / supplier per-party leaves (handled by emit_party_balances)
    - Inventory leaves (handled by Stock Reconciliation)
    - Bank-class leaves (emitted individually under Bank Accounts)
    - P&L accumulators on roots 4 / 5 (close annually, don't carry over)
    """
    cls = clean_str(row.get("CLASS"))
    if cls in PARTY_CLASSES or cls in INVENTORY_CLASSES or cls in BANK_CLASSES:
        return None
    if cls in CLASS_TO_BUCKET:
        return CLASS_TO_BUCKET[cls]
    account_id = clean_str(row.get("ACCOUNTID"))
    if account_id and account_id[0] in ("4", "5"):
        return None
    root_id = walk_to_root(account_id, ctx.accounts_by_id)
    root_type, _ = ROOT_TYPE_BY_ID.get(root_id, ("Asset", "Balance Sheet"))
    return FALLBACK_BY_ROOT_TYPE.get(root_type, "Miscellaneous Expenses")
