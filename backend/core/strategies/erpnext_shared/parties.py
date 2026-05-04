"""Customer + Supplier + walk-in + orphan-from-invoices.

CONTACTST is essentially empty in our data (0% emails / names, 7% mobile,
3% office phone) so the Contact and Address doctypes aren't used. The few
populated phones are denormalized straight onto Customer / Supplier.

Walk-in customer absorbs the 130K+ anonymous invoices (ACCOUNTID=0).
Orphan customers are ACCOUNTIDs that appear in CATESINVDOCT but in
neither CUSTT nor SUPPLIERT — typically employee or representative
accounts; we emit them as customers so their invoices have a valid party.
"""

from core.strategies.erpnext_shared.common import (
    WALKIN_CUSTOMER_ID,
    clean_str,
    customer_id,
    group_by,
    normalize_phone,
    pick,
    supplier_id,
)
from core.strategies.erpnext_shared.context import Context
from core.strategies.erpnext_shared.masters import (
    CUSTOMER_GROUP_NAME,
    SUPPLIER_GROUP_NAME,
    TERRITORY_NAME,
    price_list_name,
)

WALKIN_DISPLAY_NAME = "زبون نقدي"

CUSTOMER_TYPE_DEFAULT = "Company"
SUPPLIER_TYPE_DEFAULT = "Company"


def emit_customers(ctx: Context) -> None:
    """Emit walk-in + regular + orphan Customer records."""
    contacts = group_by(ctx.table("CONTACTST"), "ACCOUNTID")
    _emit_walkin_customer(ctx)
    for row in ctx.table("CUSTT"):
        _emit_customer(ctx, row, contacts)
    _emit_orphan_customers(ctx, contacts)


def emit_suppliers(ctx: Context) -> None:
    """Emit Supplier records from SUPPLIERT."""
    contacts = group_by(ctx.table("CONTACTST"), "ACCOUNTID")
    for row in ctx.table("SUPPLIERT"):
        _emit_supplier(ctx, row, contacts)


# -- Walk-in ------------------------------------------------------------------


def _emit_walkin_customer(ctx: Context) -> None:
    ctx.result.emit(
        "Customer",
        {
            "name": WALKIN_CUSTOMER_ID,
            "customer_name": WALKIN_DISPLAY_NAME,
            "customer_type": CUSTOMER_TYPE_DEFAULT,
            "customer_group": CUSTOMER_GROUP_NAME,
            "territory": TERRITORY_NAME,
            "default_currency": ctx.config.default_currency,
            "disabled": 0,
            "legacy_custid": "0",
            "legacy_kind": "walkin",
        },
    )
    ctx.result.bump("walkin_customers_emitted")


# -- Customer (CUSTT) ---------------------------------------------------------


def _emit_customer(
    ctx: Context,
    row: dict,
    contacts: dict[str, list[dict]],
) -> None:
    custid = clean_str(row.get("CUSTID"))
    account_id = clean_str(row.get("ACCOUNT")) or custid
    if not account_id:
        ctx.result.bump("customers_skipped_no_account")
        return
    name = _account_name(ctx, account_id)
    if not name:
        ctx.result.warn("Customer", "missing ACCOUNTT.NAME", legacy_custid=custid)
        return
    phone = _phone_for(contacts.get(account_id, []))
    # v16 Customer has only `mobile_no` (Read Only, auto-populated from
    # linked Contact). No `phone` field — the template column is a
    # generator artifact but doesn't map. Office phone is dropped.
    ctx.result.emit(
        "Customer",
        {
            "name": customer_id(custid),
            "customer_name": name,
            "customer_type": CUSTOMER_TYPE_DEFAULT,
            "customer_group": CUSTOMER_GROUP_NAME,
            "territory": TERRITORY_NAME,
            "default_currency": ctx.config.default_currency,
            "default_price_list": price_list_name(ctx, row.get("PRICEID")),
            "mobile_no": phone["mobile"] or phone["office"],
            "disabled": 0,
            "legacy_custid": custid,
            "legacy_kind": "regular",
        },
    )
    ctx.result.bump("customers_emitted")


# -- Supplier (SUPPLIERT) -----------------------------------------------------


def _emit_supplier(
    ctx: Context,
    row: dict,
    contacts: dict[str, list[dict]],
) -> None:
    suppid = clean_str(row.get("SUPPID"))
    account_id = clean_str(row.get("ACCOUNT")) or suppid
    if not account_id:
        ctx.result.bump("suppliers_skipped_no_account")
        return
    name = _account_name(ctx, account_id)
    if not name:
        ctx.result.warn("Supplier", "missing ACCOUNTT.NAME", legacy_suppid=suppid)
        return
    phone = _phone_for(contacts.get(account_id, []))
    # v16 Supplier mirrors Customer — only mobile_no exists, no phone.
    ctx.result.emit(
        "Supplier",
        {
            "name": supplier_id(suppid),
            "supplier_name": name,
            "supplier_type": SUPPLIER_TYPE_DEFAULT,
            "supplier_group": SUPPLIER_GROUP_NAME,
            "country": ctx.config.country,
            "default_currency": ctx.config.default_currency,
            "mobile_no": phone["mobile"] or phone["office"],
            "disabled": 0,
            "legacy_suppid": suppid,
        },
    )
    ctx.result.bump("suppliers_emitted")


# -- Orphans (referenced by invoices, not in CUSTT/SUPPLIERT) -----------------


def _emit_orphan_customers(ctx: Context, contacts: dict[str, list[dict]]) -> None:
    """Customers that appear in invoices but not in CUSTT/SUPPLIERT.

    Typically employee accounts (CLASS=1) or representative accounts
    (CLASS=9) that the legacy system happily accepts as invoice parties.
    Emit them as customers to keep the invoices' party references valid.
    """
    for account_id in _orphan_invoice_account_ids(ctx):
        _emit_orphan(ctx, account_id, contacts)


def _emit_orphan(
    ctx: Context,
    account_id: str,
    contacts: dict[str, list[dict]],
) -> None:
    name = _account_name(ctx, account_id)
    if not name:
        ctx.result.warn("Orphan", "no ACCOUNTT.NAME", account_id=account_id)
        return
    phone = _phone_for(contacts.get(account_id, []))
    ctx.result.emit(
        "Customer",
        {
            "name": customer_id(account_id),
            "customer_name": name,
            "customer_type": CUSTOMER_TYPE_DEFAULT,
            "customer_group": CUSTOMER_GROUP_NAME,
            "territory": TERRITORY_NAME,
            "default_currency": ctx.config.default_currency,
            "mobile_no": phone["mobile"] or phone["office"],
            "disabled": 0,
            "legacy_custid": account_id,
            "legacy_kind": "orphan",
        },
    )
    ctx.result.bump("orphan_customers_emitted")


def _phone_for(contact_rows: list[dict]) -> dict[str, str]:
    """Pick the first non-empty MOBILE / OFFICEPHONE1 across contact rows.

    Each value runs through normalize_phone to strip embedded names /
    notes (legacy data sometimes has '0597640262شادي' as one field).
    """
    mobile = ""
    office = ""
    for r in contact_rows or []:
        if not mobile:
            mobile = normalize_phone(r.get("MOBILE")) or normalize_phone(
                r.get("MOBILE2")
            )
        if not office:
            office = normalize_phone(r.get("OFFICEPHONE1")) or normalize_phone(
                r.get("OFFICEPHONE2")
            )
        if mobile and office:
            break
    return {"mobile": mobile, "office": office}


def _orphan_invoice_account_ids(ctx: Context) -> list[str]:
    """ACCOUNTIDs that appear as a sales-invoice or sales-return party
    but aren't in CUSTT. We still emit them as Customer records so
    Sales Invoice's `customer` link resolves — this includes accounts
    that are ALSO in SUPPLIERT (some suppliers act as customers in
    legacy data). Customer and Supplier are separate doctypes in v16,
    so a 'CUST-621010' record alongside 'SUPP-621010' doesn't conflict.

    Uses iter_streamed for CATESINVDOCT (memory-bounded scan) since
    that table is in SKIP_EAGER_LOAD; only ACCOUNTID is needed so we
    don't keep rows in memory.
    """
    customers = ctx.customer_account_ids
    seen: set[str] = set()
    for source in ("CATESINVDOCT", "CATESRETINVDOCT"):
        rows = (
            ctx.iter_streamed(source) if source == "CATESINVDOCT" else ctx.table(source)
        )
        for row in rows:
            aid = clean_str(row.get("ACCOUNTID"))
            if not aid or aid == "0":
                continue
            if aid in customers or aid in seen:
                continue
            seen.add(aid)
    return sorted(seen)


# -- Helpers ------------------------------------------------------------------


def _account_name(ctx: Context, account_id: str) -> str:
    row = ctx.accounts_by_id.get(account_id)
    if not row:
        return ""
    return pick(row, "NAME", "NAMEE", "NAMEH")
