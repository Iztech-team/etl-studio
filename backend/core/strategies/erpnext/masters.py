"""Reference master emit — UOM, Warehouse, Price List, Item Group, Brand,
Bank, Bank Account.

These are the lookups every other domain depends on; they get emitted
first so subsequent slices can reference them by name. Each `emit_*`
helper handles one doctype, no cross-talk.
"""
from core.strategies.erpnext.common import (
    DEFAULT_UOM,
    clean_str,
    pick,
)
from core.strategies.erpnext.context import Context

# Frappe-default tree roots — present out of the box on a new ERPnext install.
ROOT_ITEM_GROUP = "All Item Groups"
ROOT_WAREHOUSE = "All Warehouses"
ROOT_TERRITORY = "All Territories"
ROOT_CUSTOMER_GROUP = "All Customer Groups"
ROOT_SUPPLIER_GROUP = "All Supplier Groups"

# Names our other doctypes will reference — keep these in one place so
# items.py and parties.py don't drift.
ITEM_GROUP_NAME = "Al Arabi Imported"
TERRITORY_NAME = "All Territories"
CUSTOMER_GROUP_NAME = "Commercial"
SUPPLIER_GROUP_NAME = "Local"

PRICE_LIST_FALLBACK_NAMES = {
    "1": "Al Arabi Standard Selling",
    "2": "Al Arabi Wholesale",
    "3": "Al Arabi Tertiary",
}


def emit_masters(ctx: Context) -> None:
    """Top-level master emit — invoked once at the start of transform."""
    emit_uoms(ctx)
    emit_item_group(ctx)
    emit_warehouses(ctx)
    emit_price_lists(ctx)
    emit_brands(ctx)
    emit_banks(ctx)
    emit_bank_accounts(ctx)


# -- UOM ----------------------------------------------------------------------

def emit_uoms(ctx: Context) -> None:
    """Emit one UOM per distinct legacy unit string.

    Sources (in order): UNITT (canonical), CATEGORYT.UNIT/DEFAULTUNIT/WMUNIT
    (free-text per item). Fallback "وحدة" is always emitted so items with
    empty UNIT columns can resolve.
    """
    seen: set[str] = set()
    for row in ctx.table("UNITT"):
        _emit_uom(ctx, pick(row, "UNITNAME", "UNITNAMEE"), seen)
    for row in ctx.table("CATEGORYT"):
        for field_name in ("UNIT", "DEFAULTUNIT", "WMUNIT"):
            _emit_uom(ctx, clean_str(row.get(field_name)), seen)
    _emit_uom(ctx, DEFAULT_UOM, seen)
    ctx.result.bump("uoms_emitted", len(seen))


def _emit_uom(ctx: Context, name: str, seen: set[str]) -> None:
    if not name or name in seen:
        return
    seen.add(name)
    ctx.result.emit("UOM", {"uom_name": name, "enabled": 1})


# -- Item Group ---------------------------------------------------------------

def emit_item_group(ctx: Context) -> None:
    ctx.result.emit("Item Group", {
        "item_group_name": ITEM_GROUP_NAME,
        "parent_item_group": ROOT_ITEM_GROUP,
        "is_group": 0,
    })
    ctx.result.bump("item_groups_emitted")


# -- Warehouse ----------------------------------------------------------------

def emit_warehouses(ctx: Context) -> None:
    for row in ctx.table("STORET"):
        _emit_warehouse(ctx, row)


def _emit_warehouse(ctx: Context, row: dict) -> None:
    name = pick(row, "DESCRIPTION", "DESCRIPTIONE", "DESCRIPTIONH")
    if not name:
        return
    ctx.result.emit("Warehouse", {
        "warehouse_name": name,
        "company": ctx.config.company_name,
        "parent_warehouse": ROOT_WAREHOUSE,
        "is_group": 0,
        "legacy_storeid": clean_str(row.get("STOREID")),
    })
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
            "Al Arabi Price List",
        )
    if name in seen:
        return
    seen.add(name)
    ctx.result.emit("Price List", {
        "price_list_name": name,
        "currency": ctx.config.default_currency,
        "selling": 1,
        "buying": 0,
        "enabled": 1,
        "legacy_priceid": clean_str(row.get("PRICEID")),
    })
    ctx.result.bump("price_lists_emitted")


def price_list_name(ctx: Context, legacy_price_id) -> str:
    """Resolve a legacy PRICEID to the Price List name we emitted."""
    pid = clean_str(legacy_price_id)
    for row in ctx.table("PRICETYPET"):
        if clean_str(row.get("PRICEID")) == pid:
            chosen = pick(row, "PRICENAME")
            if chosen:
                return chosen
    return PRICE_LIST_FALLBACK_NAMES.get(pid, "Al Arabi Price List")


# -- Brand --------------------------------------------------------------------

def emit_brands(ctx: Context) -> None:
    """Each unique CATEGORYT.MANUFACTURER becomes a Brand record."""
    seen: set[str] = set()
    for row in ctx.table("CATEGORYT"):
        name = clean_str(row.get("MANUFACTURER"))
        if not name or name in seen:
            continue
        seen.add(name)
        ctx.result.emit("Brand", {"brand": name})
    ctx.result.bump("brands_emitted", len(seen))


# -- Bank / Bank Account ------------------------------------------------------

def emit_banks(ctx: Context) -> None:
    seen: set[str] = set()
    for row in ctx.table("BANKT"):
        name = pick(row, "BANKNAME", "BANKNAMEE", "BANKNAMEH")
        if not name or name in seen:
            continue
        seen.add(name)
        ctx.result.emit("Bank", {
            "bank_name": name,
            "legacy_bankid": clean_str(row.get("BANKID")),
        })
    ctx.result.bump("banks_emitted", len(seen))


def emit_bank_accounts(ctx: Context) -> None:
    for row in ctx.table("BANKACCOUNTT"):
        _emit_bank_account(ctx, row)


def _emit_bank_account(ctx: Context, row: dict) -> None:
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
    label = f"{bank_name} - {account_no}" if account_no else bank_name
    ctx.result.emit("Bank Account", {
        "account_name": label,
        "bank": bank_name,
        "is_company_account": 1,
        "company": ctx.config.company_name,
        "branch_code": clean_str(row.get("BRANCHNAME")),
        "phone_number": clean_str(row.get("PHONE")),
        "address_line_1": clean_str(row.get("ADDRESS")),
        "legacy_bankaccid": clean_str(row.get("BANKACCID")),
    })
    ctx.result.bump("bank_accounts_emitted")


def bank_account_label(ctx: Context, bankaccid) -> str:
    """Recompute the same label used at emit time, for cross-references."""
    raw = ctx.bank_accounts_by_id.get(clean_str(bankaccid))
    if not raw:
        return ""
    bank = ctx.banks_by_id.get(clean_str(raw.get("BANKID")), {})
    bank_name = pick(bank, "BANKNAME", "BANKNAMEE", "BANKNAMEH")
    account_no = clean_str(raw.get("ACCOUNTNO"))
    if not bank_name:
        return ""
    return f"{bank_name} - {account_no}" if account_no else bank_name
