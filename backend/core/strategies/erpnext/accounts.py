"""Chart of Accounts emit (ACCOUNTT → Account doctype).

Three load-bearing decisions live here:

1. The 6 hand-curated root accounts get explicit `root_type` /
   `report_type`; ERPnext propagates those to all 3,500+ descendants
   automatically. This matches the legacy tree (7 roots; ACCOUNTID=0 is
   a placeholder treated as Asset).

2. CLASS=2 (customer) and CLASS=3 (supplier) ACCOUNTT rows are NOT
   emitted as Account records — ERPnext creates one Receivable /
   Payable sub-account per Customer / Supplier on import. Re-emitting
   them here would produce duplicates.

3. Accounts are emitted in ALEVEL order so a child's `parent_account`
   reference (which uses the parent's autonamed form `{name} - {abbr}`)
   resolves to a row that already exists.
"""
from typing import Iterable

from core.strategies.erpnext.common import (
    clean_str,
    currency_iso,
    pick,
)
from core.strategies.erpnext.context import Context

# 6 real roots + the ACCOUNTID=0 placeholder. Maps ACCOUNTID → (root_type,
# report_type). The Arabic names live in ACCOUNTT.NAME so we don't repeat
# them here.
ROOT_TYPE_BY_ID: dict[str, tuple[str, str]] = {
    "0": ("Asset", "Balance Sheet"),     # غير محدد (placeholder)
    "1": ("Asset", "Balance Sheet"),     # الموجودات
    "2": ("Liability", "Balance Sheet"), # المطلوبات
    "3": ("Equity", "Balance Sheet"),    # راس المال
    "4": ("Expense", "Profit and Loss"), # المشتريات والمصاريف
    "5": ("Income", "Profit and Loss"),  # الايرادات
    "6": ("Asset", "Balance Sheet"),     # الذمم (memo / receivables)
}

# Per-leaf account_type derived from ACCCLASST.CLASSID. Optional but lets
# ERPnext recognize Cash / Bank / Tax / Stock accounts and do the right
# thing in invoice/payment workflows.
ACCOUNT_TYPE_BY_CLASS: dict[str, str] = {
    "13": "Cash",
    "10": "Bank",
    "14": "Bank",
    "21": "Tax",
    "22": "Tax",
    "23": "Tax",
    "24": "Tax",
    "40": "Stock",
    "41": "Stock",
    "42": "Stock",
    "4": "Fixed Asset",
    "47": "Accumulated Depreciation",
    "7": "Expense Account",
    "34": "Expense Account",
    "36": "Expense Account",
    "45": "Expense Account",
    "35": "Expense Account",
    "8": "Income Account",
    "32": "Income Account",
    "44": "Income Account",
    "33": "Income Account",
    "51": "Round Off",
}

# These two CLASS values represent customer / supplier individual accounts.
# Skip emitting them as Account — ERPnext creates them via Customer /
# Supplier doctypes automatically.
SKIP_CLASSES = {"2", "3"}


def emit_accounts(ctx: Context) -> None:
    deleted = _deleted_account_ids(ctx)
    parent_ids = _parent_id_set(ctx)
    rows = _emittable_accounts(ctx, deleted)
    rows.sort(key=_sort_key)
    for row in rows:
        _emit_account(ctx, row, parent_ids)


# -- Emission -----------------------------------------------------------------

def _emit_account(
    ctx: Context,
    row: dict,
    parent_ids: set[str],
) -> None:
    account_id = clean_str(row.get("ACCOUNTID"))
    name = pick(row, "NAME", "NAMEE", "NAMEH")
    if not name:
        ctx.result.warn("Account", "missing NAME", legacy_acctid=account_id)
        return
    is_root = account_id in ROOT_TYPE_BY_ID
    payload = {
        "name": ctx.with_abbr(name),
        "account_name": name,
        "company": ctx.config.company_name,
        "parent_account": _parent_account_name(ctx, row, is_root),
        "is_group": 1 if account_id in parent_ids else 0,
        "account_currency": currency_iso(row.get("CURID")),
        "disabled": 0 if _is_active(row) else 1,
        "legacy_acctid": account_id,
        "legacy_class": clean_str(row.get("CLASS")),
    }
    if is_root:
        root_type, report_type = ROOT_TYPE_BY_ID[account_id]
        payload["root_type"] = root_type
        payload["report_type"] = report_type
    leaf_type = _account_type_for(row, payload["is_group"])
    if leaf_type:
        payload["account_type"] = leaf_type
    ctx.result.emit("Account", payload)
    ctx.result.bump("accounts_emitted")


def _parent_account_name(ctx: Context, row: dict, is_root: bool) -> str:
    if is_root:
        return ""
    parent_id = clean_str(row.get("FATHERID"))
    parent = ctx.accounts_by_id.get(parent_id)
    if not parent:
        return ""
    parent_name = pick(parent, "NAME", "NAMEE", "NAMEH")
    return ctx.with_abbr(parent_name) if parent_name else ""


def _account_type_for(row: dict, is_group: int) -> str:
    if is_group:
        return ""
    return ACCOUNT_TYPE_BY_CLASS.get(clean_str(row.get("CLASS")), "")


def _is_active(row: dict) -> bool:
    """STATUS in ACCOUNTT: 1 = active, 0 = inactive."""
    s = clean_str(row.get("STATUS"))
    return s != "0"


# -- Filtering ----------------------------------------------------------------

def _emittable_accounts(ctx: Context, deleted: set[str]) -> list[dict]:
    out: list[dict] = []
    for row in ctx.table("ACCOUNTT"):
        if not _should_emit(row, deleted, ctx):
            ctx.result.bump("accounts_skipped")
            continue
        out.append(row)
    return out


def _should_emit(row: dict, deleted: set[str], ctx: Context) -> bool:
    account_id = clean_str(row.get("ACCOUNTID"))
    if not account_id or account_id in deleted:
        return False
    cls = clean_str(row.get("CLASS"))
    if cls in SKIP_CLASSES:
        # Customer/supplier individual accounts — auto-created by ERPnext.
        return False
    return True


def _sort_key(row: dict) -> tuple:
    """ALEVEL ascending so parents come before children in the import file."""
    level = clean_str(row.get("ALEVEL")) or "0"
    try:
        depth = int(level)
    except ValueError:
        depth = 0
    return (depth, clean_str(row.get("ACCOUNTID")))


def _parent_id_set(ctx: Context) -> set[str]:
    """ACCOUNTIDs that appear as FATHERID somewhere — i.e. group accounts."""
    out: set[str] = set()
    for row in ctx.table("ACCOUNTT"):
        fid = clean_str(row.get("FATHERID"))
        if fid:
            out.add(fid)
    return out


def _deleted_account_ids(ctx: Context) -> set[str]:
    return {
        clean_str(r.get("ACCOUNTID"))
        for r in ctx.table("DELETEDACCOUNTT")
        if clean_str(r.get("ACCOUNTID"))
    }


# -- Cross-reference helper for invoices / payments ---------------------------

def account_full_name(ctx: Context, account_id) -> str:
    """Return the autonamed Account form '{name} - {abbr}' for an ACCOUNTID."""
    row = ctx.accounts_by_id.get(clean_str(account_id))
    if not row:
        return ""
    name = pick(row, "NAME", "NAMEE", "NAMEH")
    return ctx.with_abbr(name) if name else ""
