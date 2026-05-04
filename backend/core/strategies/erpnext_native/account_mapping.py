"""Legacy ACCOUNTT → ERPnext standard-CoA bucket classifier.

Two-pass classification:

1. CLASS-based — pins specific buckets we know with confidence
   (Cash, VAT, Round Off, Accumulated Depreciation, Fixed Asset).
2. NAME regex — for catch-all expense / income classes (7, 34, 35,
   36, 45 → expenses; 8, 32, 33, 44 → income), match the legacy
   account NAME against a rule list to split into specific ERPnext
   leaves (Salary, Office Rent, Utility Expenses, Sales, Service…).
   Anything that doesn't match a regex falls back to
   `Miscellaneous Expenses` / `Sales`.

The bucket name returned here is the ERPnext leaf's `account_name` —
callers append the company abbr via `ctx.with_abbr(bucket)` to get the
autonamed form (`Sales - ALA`). Every bucket below must exist as a
real Account in ERPnext at import time, either because it's part of
the standard CoA or because we emit it as a custom in
`erpnext_native/accounts.py`.
"""

import re

from core.strategies.erpnext_shared.common import (
    ROOT_TYPE_BY_ID,
    clean_str,
    pick,
    walk_to_root,
)
from core.strategies.erpnext_shared.context import Context

# Direct CLASS → bucket mapping for classes we can pin without name analysis.
CLASS_TO_BUCKET: dict[str, str] = {
    "13": "Cash",
    "21": "VAT",
    "22": "VAT",
    "23": "VAT",
    "24": "VAT",
    "4": "Furniture and Fixtures",
    "47": "Accumulated Depreciation",
    "51": "Round Off",
}

# Catch-all classes that need NAME-based refinement to pick a bucket.
EXPENSE_CLASSES = {"7", "34", "35", "36", "45"}
INCOME_CLASSES = {"8", "32", "33", "44"}

# Customer/supplier — handled per-party (party_type linkage), not as bucket.
PARTY_CLASSES = {"2", "3"}

# Inventory — handled by Stock Reconciliation, not aggregated as a bucket.
INVENTORY_CLASSES = {"40", "41", "42"}

# Bank-class accounts — emitted as per-currency leaves under Bank Accounts;
# their balances post to those leaves, not to an aggregated bucket.
BANK_CLASSES = {"10", "14"}

# Fallback by walked root_type when CLASS doesn't pin a bucket.
FALLBACK_BY_ROOT_TYPE: dict[str, str] = {
    "Asset": "Earnest Money",
    "Liability": "Accrued Expenses",
    "Equity": "Capital Stock",
    "Income": "Sales",
    "Expense": "Miscellaneous Expenses",
}

# Conservative starter set. Each rule = (compiled regex, ERPnext leaf name).
# All target leaves exist in ERPnext's default Indirect Expenses group.
# Order matters — first match wins, so put specific patterns before broad
# ones. Refine via the bucket-coverage report after a real run.
EXPENSE_NAME_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"راتب|رواتب|أجور|اجور|مرتب|مكافأ"), "Salary"),
    (re.compile(r"إيجار|ايجار"), "Office Rent"),
    (re.compile(r"كهرباء|ماء|مياه|هاتف|تلفون|انترنت|إنترنت"), "Utility Expenses"),
    (re.compile(r"إعلان|اعلان|تسويق|دعاية"), "Marketing Expenses"),
    (re.compile(r"نقل|شحن|توصيل|مواصلات"), "Freight and Forwarding Charges"),
    (re.compile(r"سفر|تذاكر سفر|تنقل"), "Travel Expenses"),
    (re.compile(r"استهلاك|إهلاك|اهلاك"), "Depreciation"),
    (re.compile(r"عمولة بنك|رسوم بنك|عمولات بنك"), "Bank Charges"),
    (re.compile(r"محام|قانون|قضائي|محاماة"), "Legal Expenses"),
    (re.compile(r"قرطاسية|طباعة|أوراق"), "Print and Stationery"),
    (re.compile(r"بريد|طوابع"), "Postal Expenses"),
    (re.compile(r"صيانة"), "Office Maintenance Expenses"),
    (re.compile(r"ضيافة|ترفيه"), "Entertainment Expenses"),
    (re.compile(r"فائدة"), "Interest Expense"),
]

INCOME_NAME_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"خدمة|خدمات"), "Service"),
    (re.compile(r"فائدة"), "Interest Income"),
    (re.compile(r"مبيعات|بيع"), "Sales"),
]


def classify_account(ctx: Context, row: dict) -> str | None:
    """Return the bucket leaf name for a legacy account, or None to skip.

    Skipped (None): party leaves, inventory, bank-class, P&L accumulators
    on roots 4 / 5.
    """
    cls = clean_str(row.get("CLASS"))
    if cls in PARTY_CLASSES or cls in INVENTORY_CLASSES or cls in BANK_CLASSES:
        return None
    if cls in CLASS_TO_BUCKET:
        return CLASS_TO_BUCKET[cls]
    account_id = clean_str(row.get("ACCOUNTID"))
    if account_id and account_id[0] in ("4", "5"):
        return None
    name = pick(row, "NAME", "NAMEE", "NAMEH")
    if cls in EXPENSE_CLASSES:
        return _match_name(name, EXPENSE_NAME_RULES) or "Miscellaneous Expenses"
    if cls in INCOME_CLASSES:
        return _match_name(name, INCOME_NAME_RULES) or "Sales"
    root_id = walk_to_root(account_id, ctx.accounts_by_id)
    root_type, _ = ROOT_TYPE_BY_ID.get(root_id, ("Asset", "Balance Sheet"))
    return FALLBACK_BY_ROOT_TYPE.get(root_type, "Miscellaneous Expenses")


def _match_name(name: str, rules: list[tuple[re.Pattern, str]]) -> str | None:
    if not name:
        return None
    for pattern, bucket in rules:
        if pattern.search(name):
            return bucket
    return None
