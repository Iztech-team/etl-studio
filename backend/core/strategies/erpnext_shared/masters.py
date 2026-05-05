"""Reference master emit — UOM, Warehouse, Price List, Item Group, Brand,
Bank, Bank Account.

These are the lookups every other domain depends on; they get emitted
first so subsequent slices can reference them by name. Each `emit_*`
helper handles one doctype, no cross-talk.
"""

from core.strategies.erpnext_shared.common import (
    ERPNEXT_BUILTIN_UOMS,
    clean_str,
    currency_iso,
    normalize_uom,
    pick,
)
from core.strategies.erpnext_shared.context import Context

# Frappe-default tree roots — present out of the box on a new ERPnext install.
ROOT_ITEM_GROUP = "All Item Groups"
ROOT_WAREHOUSE = "All Warehouses"
ROOT_TERRITORY = "All Territories"
ROOT_CUSTOMER_GROUP = "All Customer Groups"
ROOT_SUPPLIER_GROUP = "All Supplier Groups"

# Names our other doctypes will reference — keep these in one place so
# items.py and parties.py don't drift.
ITEM_GROUP_NAME = "Products"
TERRITORY_NAME = "All Territories"
CUSTOMER_GROUP_NAME = "Commercial"
SUPPLIER_GROUP_NAME = "Local"

PRICE_LIST_FALLBACK_NAMES = {
    "1": "Standard Selling",
    "2": "Wholesale",
    "3": "Tertiary",
}


def emit_masters(ctx: Context) -> None:
    """Emit every reference master. Prefer the per-entity entry points
    (`emit_item_masters`, `emit_bank_masters`) when running a partial
    migration so unselected doctypes don't appear in the output.
    """
    emit_item_masters(ctx)
    emit_bank_masters(ctx)


def emit_item_masters(ctx: Context) -> None:
    emit_uoms(ctx)
    emit_item_group(ctx)
    emit_warehouses(ctx)
    emit_price_lists(ctx)
    emit_brands(ctx)


def emit_bank_masters(ctx: Context) -> None:
    emit_banks(ctx)
    emit_bank_accounts(ctx)


# -- UOM ----------------------------------------------------------------------


def emit_uoms(ctx: Context) -> None:
    """Emit UOM records ONLY for legacy units that v16 doesn't ship.

    Each legacy unit (Arabic free-text or UNITT.UNITNAMEE) is funneled
    through `normalize_uom`. Names that already exist as ERPnext v16
    built-ins (Box, Kg, Litre, Tonne, Cup, Square Meter, …) are NOT
    re-emitted — Frappe rejects duplicates. Shape-specific units that
    v16 doesn't have (Carton, Can, Tin, Bottle, Packet, Bag, Piece, …)
    DO get emitted so items can reference them by name.
    """
    seen: set[str] = set()
    skipped_builtin: set[str] = set()
    for row in ctx.table("UNITT"):
        for field in ("UNITNAME", "UNITNAMEE"):
            _emit_uom(ctx, clean_str(row.get(field)), seen, skipped_builtin)
    for row in ctx.iter_streamed("CATEGORYT"):
        for field in ("UNIT", "DEFAULTUNIT", "WMUNIT"):
            _emit_uom(ctx, clean_str(row.get(field)), seen, skipped_builtin)
    ctx.result.bump("uoms_emitted_custom", len(seen))
    ctx.result.bump("uoms_skipped_builtin", len(skipped_builtin))


def _emit_uom(
    ctx: Context,
    raw: str,
    seen: set[str],
    skipped_builtin: set[str],
) -> None:
    name = normalize_uom(raw)
    if not name:
        return
    if name in ERPNEXT_BUILTIN_UOMS:
        skipped_builtin.add(name)
        return
    if name in seen:
        return
    seen.add(name)
    ctx.result.emit(
        "UOM",
        {
            "name": name,
            "uom_name": name,
            "enabled": 1,
            "must_be_whole_number": 1,
        },
    )


# -- Item Group ---------------------------------------------------------------


def emit_item_group(ctx: Context) -> None:
    ctx.result.emit(
        "Item Group",
        {
            "name": ITEM_GROUP_NAME,
            "item_group_name": ITEM_GROUP_NAME,
            "parent_item_group": ROOT_ITEM_GROUP,
            "is_group": 0,
        },
    )
    ctx.result.bump("item_groups_emitted")


# -- Warehouse ----------------------------------------------------------------


def emit_warehouses(ctx: Context) -> None:
    for row in ctx.table("STORET"):
        _emit_warehouse(ctx, row)


def _emit_warehouse(ctx: Context, row: dict) -> None:
    name = pick(row, "DESCRIPTION", "DESCRIPTIONE", "DESCRIPTIONH")
    if not name:
        return
    # parent_warehouse left blank: ERPnext doesn't require a parent for
    # leaf warehouses, and assuming a global "All Warehouses" root fails
    # in fresh-company setups where that group hasn't been created yet.
    # Admin can re-parent post-import via UI if a hierarchy is desired.
    ctx.result.emit(
        "Warehouse",
        {
            "name": ctx.with_abbr(name),
            "warehouse_name": name,
            "company": ctx.config.company_name,
            "is_group": 0,
            "legacy_storeid": clean_str(row.get("STOREID")),
        },
    )
    ctx.result.bump("warehouses_emitted")


def warehouse_for_store(ctx: Context, store_id) -> str:
    """Resolve a legacy STOREID to the autonamed ERPnext Warehouse name."""
    sid = clean_str(store_id)
    store = ctx.stores_by_id.get(sid)
    if not store:
        return ""
    base = pick(store, "DESCRIPTION", "DESCRIPTIONE", "DESCRIPTIONH")
    return ctx.with_abbr(base) if base else ""


# -- Price List ---------------------------------------------------------------


def emit_price_lists(ctx: Context) -> None:
    seen: set[str] = set()
    for row in ctx.table("PRICETYPET"):
        _emit_price_list(ctx, row, seen)


def _emit_price_list(ctx: Context, row: dict, seen: set[str]) -> None:
    name = pick(row, "PRICENAME")
    if not name:
        # Use a stable English fallback so cross-doctype references resolve.
        name = PRICE_LIST_FALLBACK_NAMES.get(
            clean_str(row.get("PRICEID")),
            "Standard Price List",
        )
    if name in seen:
        return
    seen.add(name)
    ctx.result.emit(
        "Price List",
        {
            "name": name,
            "price_list_name": name,
            "currency": ctx.config.default_currency,
            "selling": 1,
            "buying": 0,
            "enabled": 1,
            "legacy_priceid": clean_str(row.get("PRICEID")),
        },
    )
    ctx.result.bump("price_lists_emitted")


def price_list_name(ctx: Context, legacy_price_id) -> str:
    """Resolve a legacy PRICEID to the Price List name we emitted."""
    pid = clean_str(legacy_price_id)
    for row in ctx.table("PRICETYPET"):
        if clean_str(row.get("PRICEID")) == pid:
            chosen = pick(row, "PRICENAME")
            if chosen:
                return chosen
    return PRICE_LIST_FALLBACK_NAMES.get(pid, "Standard Price List")


# -- Brand --------------------------------------------------------------------


def emit_brands(ctx: Context) -> None:
    """Each unique CATEGORYT.MANUFACTURER becomes a Brand record."""
    seen: set[str] = set()
    for row in ctx.iter_streamed("CATEGORYT"):
        name = clean_str(row.get("MANUFACTURER"))
        if not name or name in seen:
            continue
        seen.add(name)
        ctx.result.emit("Brand", {"name": name, "brand": name})
    ctx.result.bump("brands_emitted", len(seen))


# -- Bank / Bank Account ------------------------------------------------------


def emit_banks(ctx: Context) -> None:
    seen: set[str] = set()
    for row in ctx.table("BANKT"):
        name = pick(row, "BANKNAME", "BANKNAMEE", "BANKNAMEH")
        if not name or name in seen:
            continue
        seen.add(name)
        ctx.result.emit(
            "Bank",
            {
                "name": name,
                "bank_name": name,
                "legacy_bankid": clean_str(row.get("BANKID")),
            },
        )
    ctx.result.bump("banks_emitted", len(seen))


_PLACEHOLDER_ACCOUNT_NO = "99/99999"


def emit_bank_accounts(ctx: Context) -> None:
    """Emit one Bank Account doctype per (BANKACCOUNTT × currency-leaf).

    Legacy `BANKACCOUNTT.TYPEA` typically points to a GROUP GL account
    (e.g. account 11302 = "البنك العربي\\الجاري") whose children are the
    actual posting leaves split per currency:
       11302 (group, ILS-tagged)
         ├─ 1130201 (ILS leaf)
         ├─ 1130202 (JOD leaf)
         └─ 1130203 (USD leaf)

    ERPnext requires `Bank Account.account` to be a LEAF account, and
    each currency variant deserves its own Bank Account record so
    Bank Reconciliation works per currency. We expand TYPEA's subtree
    to leaves and emit one Bank Account per leaf, suffixing the label
    with the currency code when the bank has more than one currency
    variant.
    """
    seen_labels: set[str] = set()
    children_by_father = _children_by_father(ctx)
    for row in ctx.table("BANKACCOUNTT"):
        _emit_bank_account(ctx, row, seen_labels, children_by_father)


def _emit_bank_account(
    ctx: Context,
    row: dict,
    seen_labels: set[str],
    children_by_father: dict[str, list[str]],
) -> None:
    bank = ctx.banks_by_id.get(clean_str(row.get("BANKID")), {})
    bank_name = pick(bank, "BANKNAME", "BANKNAMEE", "BANKNAMEH")
    if not bank_name:
        ctx.result.warn(
            "BankAccount",
            "unresolved BANKID — skipping",
            legacy_bankaccid=clean_str(row.get("BANKACCID")),
        )
        return
    account_no = clean_str(row.get("ACCOUNTNO"))
    base_label = f"{bank_name} - {account_no}" if account_no else bank_name
    is_placeholder = account_no == _PLACEHOLDER_ACCOUNT_NO

    if is_placeholder:
        # Legacy placeholder row — emit a single record without a GL link
        # so cheque references resolve. No leaf expansion needed.
        _emit_one_bank_account(
            ctx,
            row,
            base_label,
            gl_account="",
            currency="",
            seen_labels=seen_labels,
            legacy_gl_acctid="",
        )
        return

    typea_leaves = _expand_to_leaves(
        ctx, clean_str(row.get("TYPEA")), children_by_father
    )
    if not typea_leaves:
        ctx.result.warn(
            "BankAccount",
            "TYPEA resolves to no GL leaves — emitting without account link",
            legacy_bankaccid=clean_str(row.get("BANKACCID")),
        )
        _emit_one_bank_account(
            ctx,
            row,
            base_label,
            gl_account="",
            currency="",
            seen_labels=seen_labels,
            legacy_gl_acctid="",
        )
        return

    from core.strategies.erpnext_shared.common import account_full_name

    multi_currency = len(typea_leaves) > 1
    for leaf_acctid in typea_leaves:
        leaf_row = ctx.accounts_by_id.get(leaf_acctid, {})
        currency = currency_iso(leaf_row.get("CURID"))
        suffix = f" - {currency}" if multi_currency else ""
        label = f"{base_label}{suffix}"
        gl_account = account_full_name(ctx, leaf_acctid)
        _emit_one_bank_account(
            ctx,
            row,
            label,
            gl_account=gl_account,
            currency=currency,
            seen_labels=seen_labels,
            legacy_gl_acctid=leaf_acctid,
        )


def _emit_one_bank_account(
    ctx: Context,
    row: dict,
    label: str,
    gl_account: str,
    currency: str,
    seen_labels: set[str],
    legacy_gl_acctid: str,
) -> None:
    if label in seen_labels:
        ctx.result.bump("bank_accounts_skipped_duplicate")
        return
    seen_labels.add(label)
    # `account_currency` is intentionally NOT emitted: in v16 it's a
    # read-only fetched field on Bank Account that mirrors the linked
    # Account's currency. Frappe Data Import warns 'cannot match
    # column account_currency' if we send it, even though the value
    # would be correct.
    payload = {
        "name": label,
        "account_name": label,
        "bank": pick(
            ctx.banks_by_id.get(clean_str(row.get("BANKID")), {}),
            "BANKNAME",
            "BANKNAMEE",
            "BANKNAMEH",
        ),
        "account": gl_account,
        "is_company_account": 1 if gl_account else 0,
        "company": ctx.config.company_name,
        "bank_account_no": clean_str(row.get("ACCOUNTNO")),
        "branch_code": clean_str(row.get("BRANCHNAME")),
        "legacy_bankaccid": clean_str(row.get("BANKACCID")),
        "legacy_gl_acctid": legacy_gl_acctid,
    }
    ctx.result.emit("Bank Account", payload)
    ctx.result.bump("bank_accounts_emitted")


def _children_by_father(ctx: Context) -> dict[str, list[str]]:
    """Group ACCOUNTT rows by FATHERID so we can walk subtrees cheaply."""
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
    """Return the list of leaf ACCOUNTIDs descending from `account_id`.

    If `account_id` is itself a leaf, the result is `[account_id]`.
    Returns `[]` if the account doesn't exist in `ACCOUNTT`.
    """
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


def bank_account_label(ctx: Context, bankaccid, leaf_acctid: str | None = None) -> str:
    """Recompute the Bank Account label for cross-document references.

    With multi-currency split, a single legacy BANKACCID can produce
    multiple Bank Account doctypes — one per currency leaf. Pass
    `leaf_acctid` to disambiguate; without it, returns the base label
    (works for single-currency banks).
    """
    raw = ctx.bank_accounts_by_id.get(clean_str(bankaccid))
    if not raw:
        return ""
    bank = ctx.banks_by_id.get(clean_str(raw.get("BANKID")), {})
    bank_name = pick(bank, "BANKNAME", "BANKNAMEE", "BANKNAMEH")
    if not bank_name:
        return ""
    account_no = clean_str(raw.get("ACCOUNTNO"))
    base = f"{bank_name} - {account_no}" if account_no else bank_name
    if leaf_acctid:
        leaf_row = ctx.accounts_by_id.get(clean_str(leaf_acctid), {})
        # Only suffix when there's more than one currency variant —
        # callers shouldn't have to track that, so we always check.
        children_by_father = _children_by_father_cached(ctx)
        leaves = _expand_to_leaves(ctx, clean_str(raw.get("TYPEA")), children_by_father)
        if len(leaves) > 1:
            ccy = currency_iso(leaf_row.get("CURID"))
            return f"{base} - {ccy}" if ccy else base
    return base


def _children_by_father_cached(ctx: Context) -> dict[str, list[str]]:
    cached = getattr(ctx, "_children_by_father", None)
    if cached is not None:
        return cached
    out = _children_by_father(ctx)
    ctx._children_by_father = out  # type: ignore[attr-defined]
    return out


def bank_gl_leaf_to_label(ctx: Context) -> dict[str, str]:
    """Map every TYPEA-derived leaf ACCOUNTID → its Bank Account label.

    Used by opening_balances to set `bank_account` on JE lines posting
    to bank GL accounts so the entries appear in Bank Reconciliation.
    Only TYPEA is mapped — TYPEB (cheques for collection) and TYPEC
    (post-dated cheques) are NOT bank accounts in the ERPnext sense.
    """
    out: dict[str, str] = {}
    children_by_father = _children_by_father_cached(ctx)
    for row in ctx.table("BANKACCOUNTT"):
        if clean_str(row.get("ACCOUNTNO")) == _PLACEHOLDER_ACCOUNT_NO:
            continue
        bank = ctx.banks_by_id.get(clean_str(row.get("BANKID")), {})
        bank_name = pick(bank, "BANKNAME", "BANKNAMEE", "BANKNAMEH")
        if not bank_name:
            continue
        account_no = clean_str(row.get("ACCOUNTNO"))
        base = f"{bank_name} - {account_no}" if account_no else bank_name
        leaves = _expand_to_leaves(ctx, clean_str(row.get("TYPEA")), children_by_father)
        multi = len(leaves) > 1
        for leaf in leaves:
            leaf_row = ctx.accounts_by_id.get(leaf, {})
            ccy = currency_iso(leaf_row.get("CURID")) if multi else ""
            label = f"{base} - {ccy}" if ccy else base
            out.setdefault(leaf, label)
    return out
