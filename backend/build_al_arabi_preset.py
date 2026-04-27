"""
Build the AL-ARABI transform preset for the legacy AlArabi ERP CSVs.

Run from repo root:
    python backend/build_al_arabi_preset.py

Reads CSV headers from $LEGACY_DATA_DIR (default: ../cleaner/data) and emits
a preset JSON to backend/data/presets/al-arabi.json. The preset:

  - drops ~80 noise tables (RPLC_*, DELETED*, audit/log/UI tables)
  - renames the ~20 focus tables to clean English names
  - renames every important column to snake_case
  - adds a `line_total` compute column on sales / purchase invoice lines
  - feeds CATEGORYT and CATESYNONYMT both into one `product_barcodes` output
    via extra_configs (UNION ALL)
  - filters CATEGORYT down to active products with a row_filter

The preset id is fixed so re-running this script overwrites the same file
rather than creating a duplicate.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
LEGACY_DATA_DIR = Path(
    os.environ.get("LEGACY_DATA_DIR", REPO_ROOT.parent / "cleaner" / "data")
)
PRESET_ID = "al-arabi-preset-2026-04-27"
PRESET_NAME = "AL-ARABI"
# presets_store reads files by `{id}.json` (see presets._path), so the
# filename and the id MUST match — otherwise GET /api/transform-presets/{id}
# returns 404 even though the preset shows up in the list.
PRESET_PATH = REPO_ROOT / "backend" / "data" / "presets" / f"{PRESET_ID}.json"


# ---------- helpers ----------------------------------------------------------


def read_columns(table: str) -> List[str]:
    """Return the header row of a legacy CSV. Empty list if file is missing
    or its header is corrupted (CATPICST etc.)."""
    p = LEGACY_DATA_DIR / f"{table}.csv"
    if not p.exists():
        return []
    try:
        with p.open("r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.reader(f)
            row = next(reader, [])
            # Filter out columns that are obviously corrupted (binary blobs
            # in CATPICST land in the header sometimes).
            return [c for c in row if c and c.replace("_", "").replace("-", "").isalnum()]
    except Exception:
        return []


def edit(
    name: str,
    src_type: str = "string",
    op: str = "keep",
    target_name: Optional[str] = None,
    target_type: Optional[str] = None,
    *,
    is_new: bool = False,
    generator: Optional[Dict[str, Any]] = None,
    transforms: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Construct one ColEdit dict in the format the frontend / preset uses."""
    e: Dict[str, Any] = {
        "name": name,
        "type": src_type,
        "op": op,
        "targetName": target_name if target_name is not None else name.lower(),
        "targetType": target_type if target_type is not None else src_type,
    }
    if is_new:
        e["isNew"] = True
    if generator is not None:
        e["generator"] = generator
    if transforms:
        e["transforms"] = transforms
    return e


def keep_with_renames(
    table: str,
    rename: Dict[str, tuple],  # legacy_name -> (clean_name, type)
    drop_others: bool = True,
) -> List[Dict[str, Any]]:
    """Build edits for a focus table: rename the listed columns, drop others."""
    cols = read_columns(table)
    edits: List[Dict[str, Any]] = []
    seen: set = set()
    for col in cols:
        if col in rename:
            clean_name, t = rename[col]
            edits.append(edit(col, t, op="rename", target_name=clean_name, target_type=t))
            seen.add(col)
        elif drop_others:
            edits.append(edit(col, op="drop"))
        else:
            edits.append(edit(col))  # keep as-is, lowercase target
    # Warn if rename refers to a column we didn't actually find — caught early
    # so the preset doesn't silently miss a rename.
    missing = set(rename) - seen
    if missing and cols:
        sys.stderr.write(
            f"WARN: {table}: rename referenced unknown columns: {sorted(missing)}\n"
        )
    return edits


# ---------- per-table rename specs ------------------------------------------

PRODUCTS = {
    "CATID": ("barcode", "string"),
    "CATNAME": ("name_ar", "string"),
    "CATNAMEE": ("name_en", "string"),
    "BARCODE": ("alt_barcode", "string"),
    "UNIT": ("unit_id", "integer"),
    "DEFAULTUNIT": ("default_unit_id", "integer"),
    "SETNO": ("group_id", "integer"),
    "MANUFACTURER": ("manufacturer", "string"),
    "PURCHPRICE": ("purchase_price", "decimal"),
    "PURCHCURID": ("purchase_currency_id", "integer"),
    "COSTFIFO": ("cost_fifo", "decimal"),
    "COSTPRICE": ("cost_price", "decimal"),
    "LASTPURCHPRICE": ("last_purchase_price", "decimal"),
    "LASTPURCHVAT": ("last_purchase_vat", "decimal"),
    "VAT": ("vat_rate", "decimal"),
    "WEIGHT": ("weight", "decimal"),
    "VOLUME": ("volume", "decimal"),
    "CACTIVE": ("is_active", "boolean"),
    "DEFAULTSTOREID": ("default_store_id", "integer"),
    "HAVESERIAL": ("tracks_serials", "boolean"),
    "INSERTDATE": ("created_at", "date"),
    "CHANGEDATE": ("updated_at", "date"),
    "PUID": ("created_by_user_id", "integer"),
    "LPUID": ("updated_by_user_id", "integer"),
    "NOTES": ("notes", "string"),
}

CATESYNONYMT_AS_BARCODES = {
    "CATID": ("product_barcode", "string"),
    "SYNCATID": ("scan_code", "string"),
    "SYNCATNAME": ("label", "string"),
    "CREATEDATE": ("created_at", "date"),
}

PRODUCT_PRICES = {
    "PRICEID": ("tier_id", "integer"),
    "CATID": ("product_barcode", "string"),
    "SALEPRICE": ("sale_price", "decimal"),
    "MINSALEPRICE": ("min_sale_price", "decimal"),
    "DISCOUNT": ("default_discount_pct", "decimal"),
    "SALECUR": ("currency_id", "integer"),
    "VATTYPE": ("vat_type", "integer"),
    "CHANGEDATE": ("updated_at", "date"),
    "NOTES": ("notes", "string"),
}

PRODUCT_STOCK = {
    "STOREID": ("store_id", "integer"),
    "CATID": ("product_barcode", "string"),
    "STARTQTY": ("opening_qty", "decimal"),
    "QTYIN": ("qty_in", "decimal"),
    "QTYOUT": ("qty_out", "decimal"),
    "QTYBALANCE": ("qty_balance", "decimal"),
    "QUANTITY": ("on_hand_qty", "decimal"),
    "STOREMINQTY": ("reorder_min", "decimal"),
    "STOREMAXQTY": ("reorder_max", "decimal"),
    "CHANGEDATE": ("updated_at", "datetime"),
}

PRODUCT_GROUPS = {
    "SETID": ("group_id", "integer"),
    "SETNAME": ("name_ar", "string"),
    "SETNAMEE": ("name_en", "string"),
    "SALEACC": ("sales_account_id", "integer"),
    "SALERETACC": ("sales_return_account_id", "integer"),
    "PURCHACC": ("purchase_account_id", "integer"),
    "PURCHRETACC": ("purchase_return_account_id", "integer"),
    "STORAGEACC": ("inventory_account_id", "integer"),
    "PROJECTID": ("default_project_id", "integer"),
}

PRODUCT_SUPPLIERS = {
    "CATID": ("product_barcode", "string"),
    "SUPPLIER": ("supplier_account_id", "integer"),
    "ORGID": ("org_id", "integer"),
    "INSERTDATE": ("created_at", "date"),
    "PUID": ("created_by_user_id", "integer"),
}

UNITS = {
    "UNITID": ("unit_id", "integer"),
    "UNITNAME": ("name_ar", "string"),
    "UNITNAMEE": ("name_en", "string"),
}

CURRENCIES = {
    "CURID": ("currency_id", "integer"),
    "CURNAME": ("name_ar", "string"),
    "CURNAMEE": ("name_en", "string"),
    "CURSHORT": ("code", "string"),
    "CURVALUE": ("fx_rate", "decimal"),
    "LASTUPDATE": ("updated_at", "datetime"),
}

STORES = {
    "STOREID": ("store_id", "integer"),
    "DESCRIPTION": ("name_ar", "string"),
    "DESCRIPTIONE": ("name_en", "string"),
    "MANAGER": ("manager", "string"),
    "PHONE": ("phone", "string"),
    "LOCATION": ("location", "string"),
    "SACTIVE": ("is_active", "boolean"),
    "NOTE": ("notes", "string"),
}

ACCOUNTS = {
    "ACCOUNTID": ("account_id", "integer"),
    "FATHERID": ("parent_account_id", "integer"),
    "NAME": ("name_ar", "string"),
    "NAMEE": ("name_en", "string"),
    "CLASS": ("class_id", "integer"),
    "ALEVEL": ("level", "integer"),
    "CURID": ("default_currency_id", "integer"),
    "MBALANCE": ("balance", "decimal"),
    "ABALANCE": ("balance_base", "decimal"),
    "MAXCR": ("credit_limit", "decimal"),
    "MAXDB": ("debit_limit", "decimal"),
    "NATURE": ("nature", "integer"),
    "STATUS": ("status", "integer"),
    "BANKACCID": ("bank_account_id", "integer"),
    "CHANGEDATE_DATA": ("updated_at", "datetime"),
}

ACCOUNT_CLASSES = {
    "CLASSID": ("class_id", "integer"),
    "CLASSNAME": ("name", "string"),
}

CUSTOMERS = {
    "CUSTID": ("customer_id", "integer"),
    "ACCOUNT": ("account_id", "integer"),
    "DUEDAYS": ("payment_term_days", "integer"),
    "DISCOUNT": ("default_discount_pct", "decimal"),
    "PRICEID": ("price_tier_id", "integer"),
    "DEFAULTSTOREID": ("default_store_id", "integer"),
    "BANK": ("bank_id", "integer"),
    "BANKACCOUNTNO": ("bank_account_no", "string"),
    "FILENO": ("tax_file_no", "string"),
    "NOTE": ("notes", "string"),
}

SUPPLIERS = {
    "SUPPID": ("supplier_id", "integer"),
    "ACCOUNT": ("account_id", "integer"),
    "DISCOUNT": ("default_discount_pct", "decimal"),
    "BANK": ("bank_id", "integer"),
    "BANKACCOUNTNO": ("bank_account_no", "string"),
    "FILENO": ("tax_file_no", "string"),
    "NOTE": ("notes", "string"),
}

CONTACTS = {
    "CONTACTID": ("contact_id", "integer"),
    "ACCOUNTID": ("account_id", "integer"),
    "NAME": ("name", "string"),
    "NAMEE": ("name_en", "string"),
    "OFFICEPHONE1": ("office_phone", "string"),
    "MOBILE": ("mobile", "string"),
    "EMAIL": ("email", "string"),
    "WEB": ("website", "string"),
    "ADDRESS": ("address", "string"),
}

SALES_INVOICES = {
    "DOCNO": ("invoice_no", "integer"),
    "INVTYPE": ("invoice_type", "integer"),
    "DOCDATE": ("invoice_date", "date"),
    "DOCTIME": ("invoice_time", "time"),
    "DUEDATE": ("due_date", "date"),
    "ACCOUNTID": ("customer_account_id", "integer"),
    "NAME": ("customer_name", "string"),
    "STOREID": ("store_id", "integer"),
    "SALEPOINT": ("register_id", "integer"),
    "CURID": ("currency_id", "integer"),
    "CURVALUE": ("fx_rate", "decimal"),
    "SUBTOTAL": ("subtotal", "decimal"),
    "DISCOUNTV": ("discount_amount", "decimal"),
    "DISCOUNTP": ("discount_pct", "decimal"),
    "VATAMOUNT": ("vat_amount", "decimal"),
    "DOCVALUE": ("total_amount", "decimal"),
    "DOCMVALUE": ("total_amount_base", "decimal"),
    "POSTDATE": ("posted_at", "date"),
    "CARDID": ("loyalty_card_id", "integer"),
    "PUID": ("cashier_id", "integer"),
    "NOTES": ("notes", "string"),
}

SALES_INVOICE_LINES = {
    "DOCNO": ("invoice_no", "integer"),
    "INVTYPE": ("invoice_type", "integer"),
    "SERIAL": ("line_no", "integer"),
    "CATID": ("product_barcode", "string"),
    "CATNAME": ("product_name_snapshot", "string"),
    "CATUNIT": ("unit_snapshot", "string"),
    "CATQTY": ("quantity", "decimal"),
    "CATPRICE": ("unit_price", "decimal"),
    "CATDISCOUNT": ("discount_amount", "decimal"),
    "CATBONUS": ("free_qty", "decimal"),
    "VAT": ("vat_pct", "decimal"),
    "SALEACCID": ("revenue_account_id", "integer"),
    "STOREID": ("store_id", "integer"),
    "PROMID": ("promotion_id", "integer"),
    "NOTES": ("notes", "string"),
}

PURCHASE_INVOICES = {
    "DOCNO": ("invoice_no", "integer"),
    "DOCDATE": ("invoice_date", "date"),
    "ACCOUNTID": ("supplier_account_id", "integer"),
    "NAME": ("supplier_name", "string"),
    "STOREID": ("store_id", "integer"),
    "CURID": ("currency_id", "integer"),
    "SUBTOTAL": ("subtotal", "decimal"),
    "DISCOUNTV": ("discount_amount", "decimal"),
    "VATAMOUNT": ("vat_amount", "decimal"),
    "DOCVALUE": ("total_amount", "decimal"),
    "POSTDATE": ("posted_at", "date"),
    "PUID": ("cashier_id", "integer"),
    "NOTES": ("notes", "string"),
}

PURCHASE_INVOICE_LINES = {
    "DOCNO": ("invoice_no", "integer"),
    "SERIAL": ("line_no", "integer"),
    "CATID": ("product_barcode", "string"),
    "CATNAME": ("product_name_snapshot", "string"),
    "CATQTY": ("quantity", "decimal"),
    "CATPRICE": ("unit_price", "decimal"),
    "CATDISCOUNT": ("discount_amount", "decimal"),
    "PURCHACCID": ("expense_account_id", "integer"),
    "STOREID": ("store_id", "integer"),
    "NOTES": ("notes", "string"),
}

JOURNAL_ENTRIES = {
    "ENTRYID": ("entry_id", "integer"),
    "ENTRYNO": ("entry_no", "integer"),
    "ENTRYACCOUNT": ("account_id", "integer"),
    "ENTRYDEBIT": ("debit", "decimal"),
    "ENTRYCREDIT": ("credit", "decimal"),
    "ENTRYVALUE": ("net_amount", "decimal"),
    "ENTRYCUR": ("currency_id", "integer"),
    "ENTRYTRANSDATE": ("transaction_date", "date"),
    "INSERTDATE": ("created_at", "date"),
    "DOCSERIAL": ("source_doc_serial", "integer"),
    "DOCCLASS": ("source_doc_class", "integer"),
    "ACCSUBID": ("sub_account_id", "integer"),
    "PROJECTID": ("project_id", "integer"),
    "CHEQUEID": ("cheque_id", "integer"),
    "NOTES": ("notes", "string"),
}

PAYMENT_SPLITS = {
    "DOCSERIAL": ("invoice_serial", "integer"),
    "DOCCLASS": ("invoice_class", "integer"),
    "SERIAL": ("line_no", "integer"),
    "PAYTYPE": ("payment_method", "integer"),
    "PAYAMOUNT": ("amount", "decimal"),
    "PAYAMOUNTM": ("amount_base", "decimal"),
    "DESCR": ("description", "string"),
}

PRICE_TIERS = {
    "PRICEID": ("tier_id", "integer"),
    "PRICENAME": ("name", "string"),
    "PRICENOTE": ("notes", "string"),
}

REGISTERS = {
    "SALEPOINTID": ("register_id", "integer"),
    "SPNAME": ("name_ar", "string"),
    "SPLOCATION": ("location", "string"),
    "PRICELISTID": ("price_tier_id", "integer"),
    "STOREID": ("store_id", "integer"),
}

# ---------- focus tables: legacy -> (clean_name, rename_dict) ---------------

FOCUS = {
    "CATEGORYT": ("products", PRODUCTS),
    "CATESYNONYMT": ("product_barcodes", CATESYNONYMT_AS_BARCODES),  # primary feed
    "CATPRICET": ("product_prices", PRODUCT_PRICES),
    "CATSTORET": ("product_stock", PRODUCT_STOCK),
    "CATBASICSETST": ("product_groups", PRODUCT_GROUPS),
    "CATSUPPLIERT": ("product_suppliers", PRODUCT_SUPPLIERS),
    "UNITT": ("units", UNITS),
    "CURT": ("currencies", CURRENCIES),
    "STORET": ("stores", STORES),
    "PRICETYPET": ("price_tiers", PRICE_TIERS),
    "SALEPOINTT": ("registers", REGISTERS),
    "ACCOUNTT": ("accounts", ACCOUNTS),
    "ACCCLASST": ("account_classes", ACCOUNT_CLASSES),
    "CUSTT": ("customers", CUSTOMERS),
    "SUPPLIERT": ("suppliers", SUPPLIERS),
    "CONTACTST": ("contacts", CONTACTS),
    "CATESINVDOCT": ("sales_invoices", SALES_INVOICES),
    "CATESINVDOCDETT": ("sales_invoice_lines", SALES_INVOICE_LINES),
    "CATEPINVDOCT": ("purchase_invoices", PURCHASE_INVOICES),
    "CATEPINVDOCDETT": ("purchase_invoice_lines", PURCHASE_INVOICE_LINES),
    "LEDGERT": ("journal_entries", JOURNAL_ENTRIES),
    "POSPAYST": ("invoice_payment_splits", PAYMENT_SPLITS),
}


# Tables we explicitly drop. Safe noise: replication mirrors, soft-delete
# archives, audit/log tables, UI/menu/dashboard config, and dev-only stuff.
DROPPED_PATTERNS = (
    "RPLC_",  # mobile-replication snapshots
    "DELETED",  # soft-delete archives
)
DROPPED_EXACT = {
    "MONITORT", "DOCLOGST", "EMPLOGT", "PUSERLOGT", "BACKUPLOGT",
    "SQLLOGT", "EXCEPTIONST", "CATCHANGEST", "ACCOUNTCHANGEST",
    "CATPRICECHANGEST", "CATPURCHPRICECHANGEST", "CURCHANGEST",
    "CLIPBOARDT", "INTERNALMAILT", "DASHBOARDST", "DASHBOARDSECT",
    "FAVMENUT", "PMENUT", "VISIBLEMENUT", "HEADERT", "POSFAVT",
    "SHEETSTABLET", "SPEEDINFOT", "DICTIONARYT", "SETST", "FIXT",
    "CONSTT", "CATPICST", "SERIALIZET", "DATEST", "OPENPERIODT",
    "VALIDITYT", "DELIVERYPROCT", "IMPORTCOSTCENTERT", "ACTIVATIONT",
    "PREVTOPTENSALET", "DOCNOTEST", "PRELEDGERT", "PRECATLEDGERT",
    "GETCURUSERST", "REPORTARCHIVET", "TODOT", "AGENDAT",
    "CATSETST", "CATSETSCLASST", "CATNUMBERINGT", "CATBASICSETST_TOO",
    "CURCATEGORYT", "PUSERGROUPT", "PUSERPRIVILEGEST", "PUSERREPSECT",
    "PUSERT", "PROJECTST", "PARTNERT", "RESALERT", "DELIVERYPROCT",
    "ACCSETSCLASST", "GS1PREFIXT", "ATTCATALOGT", "AREAT",
    "STOCKTAKINGT", "STOCKTAKINGDETT", "POSCARDT", "POSCARDSETST",
    "POS_PROMOTIONT", "POS_PROMOTIONSETST", "BANKT", "BANKBRANCHT",
    "BANKACCOUNTT", "BANKENTRYDOCT", "BANKENTRYDOCDETT", "CHEQUET",
    "CHEQUELEDGERT", "DIVISIONDOCT", "DIVISIONDOCDETT", "DNOTEDOCT",
    "DNOTEDOCDETT", "CNOTEDOCT", "CNOTEDOCDETT", "PAYDOCT", "PAYDOCDETT",
    "RECDOCT", "RECDOCDETT", "ENTRYDOCT", "ENTRYDOCDETT",
    "STARTENTRYDOCT", "STARTENTRYDOCDETT", "CATEPRETINVDOCT",
    "CATEPRETINVDOCDETT", "CATESRETINVDOCT", "CATESRETINVDOCDETT",
    "CATEINDOCT", "CATEINDOCDETT", "CATEQUATIONT",
    "EMPLOYEET", "ACCSUBT", "ACCSUBPROPT", "ACCSUBCLASST",
    "ACCLISTST", "ACCLISTSINFOT", "CATLEDGERT", "LISTST", "CATDESCT",
}


def all_legacy_tables() -> List[str]:
    if not LEGACY_DATA_DIR.exists():
        return []
    return sorted(p.stem for p in LEGACY_DATA_DIR.glob("*.csv"))


def is_dropped(table: str) -> bool:
    if table in FOCUS:
        return False
    if any(table.startswith(p) for p in DROPPED_PATTERNS):
        return True
    return table in DROPPED_EXACT


# ---------- build the preset -------------------------------------------------


def build() -> Dict[str, Any]:
    edits: Dict[str, List[Dict[str, Any]]] = {}
    table_names: Dict[str, str] = {}
    extra_configs: List[Dict[str, Any]] = []
    table_options: Dict[str, Dict[str, Any]] = {}

    legacy_tables = all_legacy_tables()
    if not legacy_tables:
        sys.stderr.write(
            f"WARN: no CSVs found at {LEGACY_DATA_DIR}; "
            f"will still emit a preset based on the FOCUS list only.\n"
        )

    # Focus tables — generate per-column edits.
    for legacy, (clean, rename) in FOCUS.items():
        edits[legacy] = keep_with_renames(legacy, rename, drop_others=True)
        table_names[legacy] = clean

    # Extra synthetic columns -------------------------------------------------

    # Sales / purchase invoice lines: append a `line_total` compute column.
    line_total_compute = {
        "op": "compute",
        "params": {
            "expression": "{quantity} * {unit_price} - {discount_amount}",
            "round": 2,
            "null_as": 0,
        },
    }
    edits["CATESINVDOCDETT"].append(
        edit(
            "line_total",
            src_type="decimal",
            op="add",
            target_name="line_total",
            target_type="decimal",
            is_new=True,
            generator={"kind": "fixed", "value": "0"},
            transforms=[line_total_compute],
        )
    )
    edits["CATEPINVDOCDETT"].append(
        edit(
            "line_total",
            src_type="decimal",
            op="add",
            target_name="line_total",
            target_type="decimal",
            is_new=True,
            generator={"kind": "fixed", "value": "0"},
            transforms=[line_total_compute],
        )
    )

    # CATESYNONYMT primary config feeds product_barcodes; mark each row
    # is_primary=false (CATEGORYT extra config below adds the primary rows).
    edits["CATESYNONYMT"].append(
        edit(
            "is_primary",
            src_type="boolean",
            op="add",
            target_name="is_primary",
            target_type="boolean",
            is_new=True,
            generator={"kind": "fixed", "value": "false"},
        )
    )

    # CATEGORYT extra config -> product_barcodes (UNION ALL with CATESYNONYMT)
    cat_cols = read_columns("CATEGORYT")
    cat_extra_edits: List[Dict[str, Any]] = []
    for col in cat_cols:
        if col == "CATID":
            cat_extra_edits.append(
                edit("CATID", "string", op="rename", target_name="product_barcode", target_type="string")
            )
        else:
            cat_extra_edits.append(edit(col, op="drop"))
    cat_extra_edits.append(
        edit(
            "scan_code",
            src_type="string",
            op="add",
            target_name="scan_code",
            target_type="string",
            is_new=True,
            generator={"kind": "from_column", "source_column": "product_barcode"},
        )
    )
    cat_extra_edits.append(
        edit(
            "is_primary",
            src_type="boolean",
            op="add",
            target_name="is_primary",
            target_type="boolean",
            is_new=True,
            generator={"kind": "fixed", "value": "true"},
        )
    )
    extra_configs.append(
        {"source": "CATEGORYT", "target": "product_barcodes", "edits": cat_extra_edits}
    )

    # Row filter: only export active products.
    table_options["CATEGORYT"] = {
        "row_filter": {
            "mode": "keep",
            "conditions": [
                {"column": "is_active", "op": "eq", "value": "true"},
            ],
        }
    }

    # Tables we explicitly drop -----------------------------------------------
    dropped = sorted(t for t in legacy_tables if is_dropped(t))
    # If LEGACY_DATA_DIR was missing, fall back to the static list so the
    # preset is still useful.
    if not legacy_tables:
        dropped = sorted(DROPPED_EXACT)

    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": PRESET_ID,
        "name": PRESET_NAME,
        "schema_signature": sorted(edits.keys()),
        "table_names": table_names,
        "edits": edits,
        "dropped_tables": dropped,
        "table_options": table_options,
        "extra_configs": extra_configs,
        "created_at": now,
        "updated_at": now,
    }


def main() -> int:
    PRESET_PATH.parent.mkdir(parents=True, exist_ok=True)
    preset = build()
    PRESET_PATH.write_text(
        json.dumps(preset, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Wrote {PRESET_PATH}")
    print(f"  focus tables : {len(preset['edits'])}")
    print(f"  dropped      : {len(preset['dropped_tables'])}")
    print(f"  extra configs: {len(preset['extra_configs'])}")
    print(f"  row filters  : {len(preset['table_options'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
