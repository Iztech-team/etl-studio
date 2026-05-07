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

from core.strategies.erpnext_shared.common import (
    ROOT_TYPE_BY_ID,
    account_full_name,
    clean_str,
    currency_iso,
    parse_decimal,
    pick,
    safe_account_name,
    walk_to_root,
)
from core.strategies.erpnext_shared.context import Context

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
    "51": "Expense Account",
}

# These two CLASS values represent customer / supplier individual accounts.
# Skip emitting them as Account — ERPnext creates them via Customer /
# Supplier doctypes automatically.
SKIP_CLASSES = {"2", "3"}


def emit_accounts(ctx: Context) -> None:
    deleted = _deleted_account_ids(ctx)
    parent_ids = _parent_id_set(ctx)
    accounts_with_ledger = _accounts_with_ledger(ctx)
    rows = _emittable_accounts(ctx, deleted, parent_ids, accounts_with_ledger)
    rows.sort(key=_sort_key)
    root_for = _root_id_for_each(ctx)
    for row in rows:
        _emit_account(ctx, row, parent_ids, root_for, force_disabled=False)
    _emit_deleted_accounts(ctx, deleted, parent_ids, root_for)
    _emit_party_leaf_accounts(ctx)


def _emit_party_leaf_accounts(ctx: Context) -> None:
    """Emit synthetic leaf accounts the opening-balance flow needs.

    - **Debtors** / **Creditors** (Receivable / Payable) — required so
      opening Journal Entries with `party_type=Customer/Supplier` have a
      valid GL target.

    - **Temporary Opening** (Equity) — counter-account every opening JE
      posts to.
    """
    abbr_or_id = lambda acctid, fallback: account_full_name(
        ctx, acctid
    ) or ctx.with_abbr(fallback)
    equity_parent = abbr_or_id("3", "راس المال")
    receivable_parent = abbr_or_id("6", "الذمم")
    payable_parent = abbr_or_id("2", "المطلوبات")

    ctx.result.emit(
        "Account",
        {
            "name": ctx.with_abbr("Debtors"),
            "account_name": "Debtors",
            "company": ctx.config.company_name,
            "parent_account": receivable_parent,
            "is_group": 0,
            "account_currency": ctx.config.default_currency,
            "root_type": "Asset",
            "report_type": "Balance Sheet",
            "account_type": "Receivable",
        },
    )
    ctx.result.emit(
        "Account",
        {
            "name": ctx.with_abbr("Creditors"),
            "account_name": "Creditors",
            "company": ctx.config.company_name,
            "parent_account": payable_parent,
            "is_group": 0,
            "account_currency": ctx.config.default_currency,
            "root_type": "Liability",
            "report_type": "Balance Sheet",
            "account_type": "Payable",
        },
    )
    ctx.result.emit(
        "Account",
        {
            "name": ctx.with_abbr("Temporary Opening"),
            "account_name": "Temporary Opening",
            "company": ctx.config.company_name,
            "parent_account": equity_parent,
            "is_group": 0,
            "account_currency": ctx.config.default_currency,
            "root_type": "Equity",
            "report_type": "Balance Sheet",
            "account_type": "Temporary",
        },
    )
    expense_parent = abbr_or_id("4", "المشتريات والمصاريف")
    ctx.result.emit(
        "Account",
        {
            "name": ctx.with_abbr("Round Off"),
            "account_name": "Round Off",
            "company": ctx.config.company_name,
            "parent_account": expense_parent,
            "is_group": 0,
            "account_currency": ctx.config.default_currency,
            "root_type": "Expense",
            "report_type": "Profit and Loss",
            "account_type": "Round Off",
        },
    )
    ctx.result.emit(
        "Account",
        {
            "name": ctx.with_abbr("Stock Adjustment"),
            "account_name": "Stock Adjustment",
            "company": ctx.config.company_name,
            "parent_account": expense_parent,
            "is_group": 0,
            "account_currency": ctx.config.default_currency,
            "root_type": "Expense",
            "report_type": "Profit and Loss",
            "account_type": "Stock Adjustment",
        },
    )
    ctx.result.bump("party_leaf_accounts_emitted", 5)


def _root_id_for_each(ctx: Context) -> dict[str, str]:
    """Walk FATHERID up to find each account's root (ALEVEL=0).

    Used to propagate root_type and report_type from the 6 hand-mapped
    roots down to every descendant — the user's import template marks
    both as required on EVERY row, not just on roots.
    """
    out: dict[str, str] = {}
    by_id = ctx.accounts_by_id
    for aid in by_id:
        out[aid] = walk_to_root(aid, by_id)
    return out


# -- Emission -----------------------------------------------------------------


def _emit_deleted_accounts(
    ctx: Context,
    deleted: set[str],
    parent_ids: set[str],
    root_for: dict[str, str],
) -> None:
    """Emit deleted accounts as disabled so opening JEs can still reference them."""
    for row in ctx.table("ACCOUNTT"):
        account_id = clean_str(row.get("ACCOUNTID"))
        if not account_id or account_id not in deleted:
            continue
        cls = clean_str(row.get("CLASS"))
        if cls in SKIP_CLASSES:
            continue
        _emit_account(ctx, row, parent_ids, root_for, force_disabled=True)
    ctx.result.bump("deleted_accounts_restored", len(deleted))


def _emit_account(
    ctx: Context,
    row: dict,
    parent_ids: set[str],
    root_for: dict[str, str],
    force_disabled: bool = False,
) -> None:
    account_id = clean_str(row.get("ACCOUNTID"))
    raw_name = pick(row, "NAME", "NAMEE", "NAMEH")
    name = safe_account_name(raw_name)
    if not name:
        ctx.result.warn("Account", "missing NAME", legacy_acctid=account_id)
        return
    is_root = account_id in ROOT_TYPE_BY_ID
    root_id = root_for.get(account_id, account_id)
    root_type, report_type = ROOT_TYPE_BY_ID.get(
        root_id,
        ("Asset", "Balance Sheet"),
    )
    # account_number = legacy ACCOUNTID gives Frappe a stable ASCII
    # prefix in the autoname ('{number} - {name} - {abbr}'). Without
    # it, accounts whose name carries Arabic text + special chars
    # (e.g. backslash/slash separators in 'صندوق نقدي\شيكل') hit a
    # validate_link_and_fetch lookup mismatch — search finds the
    # account but validator can't match by name. The numeric prefix
    # sidesteps that entirely. Name must use safe_account_name() to
    # normalize separators so Bank Account and JE links can find it.
    payload = {
        "name": _autoname_with_number(account_id, name, ctx.config.company_abbr),
        "account_name": name,
        "account_number": account_id,
        "company": ctx.config.company_name,
        "parent_account": _parent_account_name(ctx, row, is_root),
        "is_group": 1 if account_id in parent_ids else 0,
        "account_currency": currency_iso(row.get("CURID")),
        "root_type": root_type,
        "report_type": report_type,
        "disabled": 1 if force_disabled else (0 if _is_active(row) else 1),
        "legacy_acctid": account_id,
        "legacy_class": clean_str(row.get("CLASS")),
    }
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
    parent_name = safe_account_name(pick(parent, "NAME", "NAMEE", "NAMEH"))
    if not parent_name:
        return ""
    return _autoname_with_number(parent_id, parent_name, ctx.config.company_abbr)


def _autoname_with_number(account_id: str, name: str, abbr: str) -> str:
    """Mirror of erpnext.accounts.utils.get_autoname_with_number — when an
    account_number is present, the autoname becomes
    '{number} - {name} - {abbr}'. We construct cross-references to the
    same shape so Bank Account / JE links validate correctly."""
    parts = [clean_str(account_id), clean_str(name)]
    parts = [p for p in parts if p]
    suffix = clean_str(abbr)
    if suffix and suffix not in parts[-1]:
        parts.append(suffix)
    return " - ".join(parts)


def _account_type_for(row: dict, is_group: int) -> str:
    if is_group:
        return ""
    return ACCOUNT_TYPE_BY_CLASS.get(clean_str(row.get("CLASS")), "")


def _is_active(row: dict) -> bool:
    """STATUS in ACCOUNTT: 1 = active, 0 = inactive."""
    s = clean_str(row.get("STATUS"))
    return s != "0"


# -- Filtering ----------------------------------------------------------------


def _emittable_accounts(
    ctx: Context,
    deleted: set[str],
    parent_ids: set[str],
    accounts_with_ledger: set[str],
) -> list[dict]:
    out: list[dict] = []
    for row in ctx.table("ACCOUNTT"):
        if not _should_emit(row, deleted, ctx, parent_ids, accounts_with_ledger):
            ctx.result.bump("accounts_skipped")
            continue
        out.append(row)
    return out


def _should_emit(
    row: dict,
    deleted: set[str],
    ctx: Context,
    parent_ids: set[str],
    accounts_with_ledger: set[str],
) -> bool:
    account_id = clean_str(row.get("ACCOUNTID"))
    if not account_id or account_id in deleted:
        return False
    cls = clean_str(row.get("CLASS"))
    if cls in SKIP_CLASSES:
        return False
    if (
        account_id not in parent_ids
        and account_id not in accounts_with_ledger
        and abs(parse_decimal(row.get("AACCBALANCE"))) < 0.01
    ):
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


def _accounts_with_ledger(ctx: Context) -> set[str]:
    """ACCOUNTIDs that appear in LEDGERT — accounts with actual transaction history."""
    out: set[str] = set()
    for row in ctx.iter_streamed("LEDGERT"):
        aid = clean_str(row.get("ENTRYACCOUNT"))
        if aid:
            out.add(aid)
    return out


def _deleted_account_ids(ctx: Context) -> set[str]:
    return {
        clean_str(r.get("ACCOUNTID"))
        for r in ctx.table("DELETEDACCOUNTT")
        if clean_str(r.get("ACCOUNTID"))
    }
