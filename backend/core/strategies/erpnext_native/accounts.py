"""Native-strategy CoA emit — only the customs not in default ERPnext.

Assumes the admin creates the company first so ERPnext auto-installs
its standard CoA (Debtors, Creditors, Sales, Cash, etc.). This module
adds the small set of leaves the migration needs that aren't shipped
by default:

- Per-currency bank GL leaves under "Bank Accounts" (so masters.py's
  Bank Account records have a leaf to link to)
- "Cheques in Hand" under "Cash In Hand" (target for outstanding-cheque
  opening JEs)
- "VAT" under "Duties and Taxes" (catch-all for legacy VAT classes
  21/22/23/24 until Phase 2 splits them per rate)
"""
from core.strategies.erpnext_shared.common import (
    clean_str,
    currency_iso,
    pick,
)
from core.strategies.erpnext_shared.context import Context

# Custom leaves under standard ERPnext groups.
# (account_name, parent_short_name, root_type, account_type)
STANDARD_CUSTOMS: list[tuple[str, str, str, str]] = [
    ("Cheques in Hand", "Cash In Hand", "Asset", "Cash"),
    ("VAT", "Duties and Taxes", "Liability", "Tax"),
]


def emit_accounts(ctx: Context) -> None:
    _emit_standard_customs(ctx)
    _emit_bank_gl_leaves(ctx)


def _emit_standard_customs(ctx: Context) -> None:
    for name, parent_short, root_type, account_type in STANDARD_CUSTOMS:
        ctx.result.emit("Account", {
            "name": ctx.with_abbr(name),
            "account_name": name,
            "company": ctx.config.company_name,
            "parent_account": ctx.with_abbr(parent_short),
            "is_group": 0,
            "account_currency": ctx.config.default_currency,
            "root_type": root_type,
            "report_type": "Balance Sheet",
            "account_type": account_type,
        })
        ctx.result.bump("native_custom_leaves_emitted")


def _emit_bank_gl_leaves(ctx: Context) -> None:
    """Re-emit each legacy bank GL leaf under standard 'Bank Accounts' parent.

    The legacy ACCOUNTT row's NAME is preserved so `account_full_name`
    keeps producing the same auto-named form Mirror does — masters.py
    can link Bank Accounts to these leaves without per-strategy
    branching.
    """
    parent = ctx.with_abbr("Bank Accounts")
    children_by_father = _children_by_father(ctx)
    seen: set[str] = set()
    for ba in ctx.table("BANKACCOUNTT"):
        typea = clean_str(ba.get("TYPEA"))
        if not typea:
            continue
        for leaf_id in _expand_to_leaves(ctx, typea, children_by_father):
            if leaf_id in seen:
                continue
            seen.add(leaf_id)
            row = ctx.accounts_by_id.get(leaf_id, {})
            name = pick(row, "NAME", "NAMEE", "NAMEH")
            if not name:
                continue
            abbr = clean_str(ctx.config.company_abbr)
            parts = [leaf_id, name]
            if abbr and abbr not in parts[-1]:
                parts.append(abbr)
            autoname = " - ".join(parts)
            ctx.result.emit("Account", {
                "name": autoname,
                "account_name": name,
                "account_number": leaf_id,
                "company": ctx.config.company_name,
                "parent_account": parent,
                "is_group": 0,
                "account_currency": currency_iso(row.get("CURID")),
                "root_type": "Asset",
                "report_type": "Balance Sheet",
                "account_type": "Bank",
                "legacy_acctid": leaf_id,
            })
            ctx.result.bump("native_bank_gl_leaves_emitted")


def _children_by_father(ctx: Context) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for row in ctx.table("ACCOUNTT"):
        fid = clean_str(row.get("FATHERID"))
        aid = clean_str(row.get("ACCOUNTID"))
        if fid and aid:
            out.setdefault(fid, []).append(aid)
    return out


def _expand_to_leaves(
    ctx: Context,
    account_id: str,
    children_by_father: dict[str, list[str]],
) -> list[str]:
    if not account_id or account_id not in ctx.accounts_by_id:
        return []
    leaves: list[str] = []
    stack = [account_id]
    seen: set[str] = set()
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        kids = children_by_father.get(cur, [])
        if not kids:
            leaves.append(cur)
        else:
            stack.extend(kids)
    return leaves
