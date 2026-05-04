"""Items, barcodes, item-suppliers, prices.

Critical preservation requirements (per planning doc):
- Every CATEGORYT row contributes ≥ 1 Item Barcode child (CATID itself).
- CATEGORYT.BARCODE emitted when it differs from CATID.
- CATESYNONYMT entries that are barcode-shaped (numeric, len 8/12/13/14)
  emit additional Item Barcode rows; non-barcode synonyms preserved as
  Item.description aliases so search still finds them.
- CATEQUATIONT (item-equivalence) is OUT of scope here — those are
  inter-item relationships, not unit conversions on a single item.
"""
from typing import Iterable

from core.strategies.erpnext_shared.common import (
    clean_str,
    currency_iso,
    group_by,
    index_by,
    is_truthy,
    item_id,
    normalize_uom,
    parse_date,
    parse_decimal,
    pick,
    supplier_id,
)
from core.strategies.erpnext_shared.context import Context
from core.strategies.erpnext_shared.masters import (
    ITEM_GROUP_NAME,
    price_list_name,
    warehouse_for_store,
)

BARCODE_TYPES = {8: "EAN-8", 12: "UPC-A", 13: "EAN-13", 14: "GTIN"}


def emit_items(ctx: Context) -> None:
    deleted = _deleted_catids(ctx)
    descriptions = index_by(ctx.table("CATDESCT"), "CATID")
    synonyms = group_by(ctx.table("CATESYNONYMT"), "CATID")
    suppliers = group_by(ctx.table("CATSUPPLIERT"), "CATID")
    default_warehouse = _default_warehouse(ctx)
    global_barcodes: set[str] = set()
    for row in ctx.iter_streamed("CATEGORYT"):
        catid = clean_str(row.get("CATID"))
        if not catid or catid in deleted:
            ctx.result.bump("items_skipped_deleted")
            continue
        _emit_item(ctx, row, descriptions, synonyms, suppliers, default_warehouse, global_barcodes)


def emit_item_prices(ctx: Context) -> None:
    # Build CATID → stock_uom lookup once so each price row can carry the
    # correct uom (Item Price.uom is required on v16). The uom map's
    # keys also tell us which items the strategy actually knows about,
    # so we drop prices that reference deleted / unknown items —
    # otherwise Frappe rejects the row with 'Value ALA-176 missing for
    # Item' on import.
    item_uom_by_catid = _index_item_uoms(ctx)
    deleted = _deleted_catids(ctx)
    valid_catids = set(item_uom_by_catid.keys()) - deleted
    for row in ctx.table("CATPRICET"):
        catid = clean_str(row.get("CATID"))
        if not catid or catid not in valid_catids:
            ctx.result.bump("item_prices_skipped_missing_item")
            continue
        _emit_item_price(ctx, row, item_uom_by_catid)


def _index_item_uoms(ctx: Context) -> dict[str, str]:
    out: dict[str, str] = {}
    for r in ctx.iter_streamed("CATEGORYT"):
        cid = clean_str(r.get("CATID"))
        if cid:
            out[cid] = _stock_uom(r)
    return out


# -- Item ---------------------------------------------------------------------

def _emit_item(
    ctx: Context,
    row: dict,
    descriptions: dict[str, dict],
    synonyms: dict[str, list[dict]],
    suppliers: dict[str, list[dict]],
    default_warehouse: str,
    global_barcodes: set[str],
) -> None:
    catid = clean_str(row.get("CATID"))
    item_syns = synonyms.get(catid, [])
    barcodes, aliases = _collect_barcodes(catid, row.get("BARCODE"), item_syns, global_barcodes)

    ctx.result.emit("Item", {
        "name": item_id(catid),
        "item_code": item_id(catid),
        "item_name": pick(row, "CATNAME", "CATNAMEE", "CATNAMEH"),
        "description": _build_description(row, descriptions, aliases),
        "item_group": ITEM_GROUP_NAME,
        "stock_uom": _stock_uom(row),
        "is_stock_item": 1,
        "is_sales_item": 1,
        "is_purchase_item": 1,
        "disabled": 0 if _is_active(row) else 1,
        "has_batch_no": 1 if is_truthy(row.get("NEEDBATCH")) else 0,
        "has_serial_no": 1 if is_truthy(row.get("HAVESERIAL")) else 0,
        "weight_per_unit": parse_decimal(row.get("WEIGHT")),
        "brand": clean_str(row.get("MANUFACTURER")),
        "barcodes": barcodes,
        "uoms": _uom_conversions(row),
        "supplier_items": _supplier_items(ctx, suppliers.get(catid, [])),
        "item_defaults": _item_defaults(ctx, default_warehouse),
        "legacy_catid": catid,
    })
    ctx.result.bump("items_emitted")
    ctx.result.bump("barcodes_emitted", len(barcodes))


def _is_active(row: dict) -> bool:
    """CACTIVE in CATEGORYT: 1 = active, 0/2 / blank = disabled."""
    return clean_str(row.get("CACTIVE")) == "1"


def _stock_uom(row: dict) -> str:
    return normalize_uom(row.get("UNIT"))


def _build_description(
    row: dict,
    descriptions: dict[str, dict],
    aliases: list[str],
) -> str:
    parts: list[str] = []
    for field_name in ("CATNAMEE", "CATNAMEH"):
        secondary = clean_str(row.get(field_name))
        if secondary:
            parts.append(secondary)
    desc_row = descriptions.get(clean_str(row.get("CATID")), {})
    desc = clean_str(desc_row.get("DESCRIPTION"))
    if desc:
        parts.append(desc)
    if aliases:
        parts.append("Aliases: " + ", ".join(aliases))
    return " | ".join(parts)


# -- Barcodes -----------------------------------------------------------------

def _collect_barcodes(
    catid: str,
    barcode_field,
    synonyms: list[dict],
    global_barcodes: set[str],
) -> tuple[list[dict], list[str]]:
    """Return (barcode rows, non-barcode alias strings).

    Three sources are considered in priority order: CATID itself (primary),
    the CATEGORYT.BARCODE field (if it differs), and CATESYNONYMT.SYNCATID.
    Each value is deduped both within-item and across-items (via
    global_barcodes) so ERPnext's global barcode uniqueness constraint
    is never violated.
    """
    seen: set[str] = set()
    barcodes: list[dict] = []
    aliases: list[str] = []
    _add_barcode(catid, seen, barcodes, global_barcodes)
    secondary = clean_str(barcode_field)
    if secondary and secondary != catid:
        _add_barcode(secondary, seen, barcodes, global_barcodes)
    for syn in synonyms:
        value = clean_str(syn.get("SYNCATID"))
        if not value or value in seen:
            continue
        if _is_barcode_shaped(value):
            _add_barcode(value, seen, barcodes, global_barcodes)
        else:
            aliases.append(value)
    return barcodes, aliases


def _add_barcode(value: str, seen: set[str], out: list[dict], global_barcodes: set[str]) -> None:
    if not value or value in seen or value in global_barcodes:
        return
    seen.add(value)
    global_barcodes.add(value)
    out.append({"barcode": value})


def _is_barcode_shaped(value: str) -> bool:
    return value.isdigit() and len(value) in BARCODE_TYPES


# -- Item child tables --------------------------------------------------------

def _uom_conversions(row: dict) -> list[dict]:
    """Stock UOM = self conversion factor 1.0; add WMUNIT if it differs."""
    rows: list[dict] = []
    stock = _stock_uom(row)
    rows.append({"uom": stock, "conversion_factor": 1.0})
    wholesale = normalize_uom(row.get("WMUNIT"))
    factor = parse_decimal(row.get("WMUNITQTY"), default=1.0)
    if wholesale and wholesale != stock and factor > 0:
        rows.append({"uom": wholesale, "conversion_factor": factor})
    return rows


def _supplier_items(ctx: Context, supplier_rows: Iterable[dict]) -> list[dict]:
    """Build Item.supplier_items child rows.

    Drops references that point to non-supplier accounts. Legacy data
    has ~1,200 CATSUPPLIERT rows where the SUPPLIER value is a CUSTT
    customer ID (82 customers who also act as item suppliers for some
    products) — those references would fail Frappe's link validation.
    """
    valid = ctx.supplier_account_ids
    seen: set[str] = set()
    rows: list[dict] = []
    for r in supplier_rows or []:
        sid = clean_str(r.get("SUPPLIER"))
        if not sid or sid in seen or sid not in valid:
            if sid and sid not in valid:
                ctx.result.bump("supplier_items_skipped_non_supplier")
            continue
        seen.add(sid)
        rows.append({"supplier": supplier_id(sid), "supplier_part_no": ""})
    return rows


def _item_defaults(ctx: Context, default_warehouse: str) -> list[dict]:
    return [{
        "company": ctx.config.company_name,
        "default_warehouse": default_warehouse,
    }]


def _default_warehouse(ctx: Context) -> str:
    """Pick the first STORET row's autonamed Warehouse — single store in our data."""
    for store in ctx.table("STORET"):
        wh = warehouse_for_store(ctx, store.get("STOREID"))
        if wh:
            return wh
    return ""


def _deleted_catids(ctx: Context) -> set[str]:
    return {
        clean_str(r.get("CATID"))
        for r in ctx.table("DELETEDCATEGORYT")
        if clean_str(r.get("CATID"))
    }


# -- Item Price ---------------------------------------------------------------

def _emit_item_price(ctx: Context, row: dict, item_uom_by_catid: dict[str, str]) -> None:
    rate = parse_decimal(row.get("SALEPRICE"))
    if rate <= 0:
        ctx.result.bump("item_prices_skipped_zero")
        return
    catid = clean_str(row.get("CATID"))
    if not catid:
        ctx.result.bump("item_prices_skipped_no_catid")
        return
    legacy_priceid = clean_str(row.get("PRICEID"))
    ctx.result.emit("Item Price", {
        "name": f"PRC-LEG-{legacy_priceid}-{catid}",
        "item_code": item_id(catid),
        "price_list": price_list_name(ctx, row.get("PRICEID")),
        "price_list_rate": rate,
        "currency": currency_iso(row.get("SALECUR")),
        "uom": item_uom_by_catid.get(catid, ""),
        "valid_from": parse_date(row.get("CHANGEDATE")),
        "legacy_priceid": legacy_priceid,
    })
    ctx.result.bump("item_prices_emitted")
