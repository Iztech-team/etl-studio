"""
Build the comprehensive ERPnext transform preset for the AlArabi legacy ERP.

Run from repo root:
    python backend/build_erpnext_preset.py

Reads CSV headers from $LEGACY_DATA_DIR (default: ../cleaner/data) and emits
a preset JSON to backend/data/presets/{PRESET_ID}.json.

Coverage at a glance — 33 ERPnext target tables:

  Lookups & seeds (12):
    currency, uom, price_list, item_group, brand, warehouse, mode_of_payment,
    pos_profile, cost_center, project, bank, bank_account

  Item-side (5):
    item, item_barcode, item_price, bin, item_supplier

  Parties (5):
    customer, supplier, address, contact, dynamic_link

  HR (1):
    employee

  Chart of accounts (1):
    account (with self-reference on parent_account, root_type via convention)

  Documents (sales + purchases + their returns) (4):
    sales_invoice, sales_invoice_item, purchase_invoice, purchase_invoice_item

  Stock movements (4):
    stock_entry, stock_entry_detail, stock_reconciliation,
    stock_reconciliation_item

  Journals (2 — every JE flavor unioned):
    journal_entry, journal_entry_account

  Payments (1 — receive + pay + POS unioned):
    payment_entry

  Ledgers (2):
    gl_entry, stock_ledger_entry

This preset uses every system feature added in this round:
  * AGGREGATION:   Brand seed (DISTINCT MANUFACTURER), Mode of Payment seed
                   (DISTINCT PAYTYPE), Payment Entry from POSPAYST (GROUP BY
                   DOCSERIAL+DOCCLASS with SUM(PAYAMOUNT)).
  * MULTI-HOP FK:  Payment Entry party (POSPAYST → invoice → customer).
  * LOAD ORDER:    Account.parent_account self-reference; explicit load_after
                   declarations on item / sales_invoice etc.
  * RECONCILE:     The default invoice_specs / fk_specs the user can pass to
                   /api/reconcile come from this preset's shape.

The preset id is fixed so re-running the script overwrites the same file.
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
PRESET_ID = "erpnext-preset-2026-04-27"
PRESET_NAME = "ERPnext"
PRESET_PATH = REPO_ROOT / "backend" / "data" / "presets" / f"{PRESET_ID}.json"

DEFAULT_COMPANY = "AL-ARABI"
DEFAULT_OWNER = "Administrator"
DEFAULT_PRICE_LIST_RETAIL = "Standard Selling"
DEFAULT_PRICE_LIST_WHOLESALE = "Wholesale"
DEFAULT_BUYING_PRICE_LIST = "Standard Buying"

# Walk-in customer name in legacy data — these get filtered out per the
# customer's request (they're not interested in walk-in records).
WALK_IN_NAME = "غير محدد"

# Tax sentinel: ERPnext requires Sales Taxes and Charges rows to point at
# a real GL Account head (one per tax rate). The preset emits one synthetic
# row per invoice with a placeholder account name; the user remaps it
# post-import to their VAT account.
DEFAULT_VAT_ACCOUNT = "VAT - " + DEFAULT_COMPANY


# ---------- ColEdit helpers --------------------------------------------------


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
    fk: Optional[Dict[str, str]] = None,
    fk_chain: Optional[List[Dict[str, str]]] = None,
    fk_local_column: Optional[str] = None,
) -> Dict[str, Any]:
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
    if fk:
        e["fkSourceTable"] = fk["source_table"]
        e["fkSourceColumn"] = fk["source_column"]
        e["fkMatchColumn"] = fk["match_column"]
        e["fkLocalColumn"] = fk["local_column"]
    if fk_chain:
        e["fkChain"] = fk_chain
        if fk_local_column:
            e["fkLocalColumn"] = fk_local_column
    return e


def fixed(name: str, value: str, dtype: str = "string") -> Dict[str, Any]:
    return edit(
        name,
        src_type=dtype,
        op="add",
        target_name=name,
        target_type=dtype,
        is_new=True,
        generator={"kind": "fixed", "value": value},
    )


def from_col(name: str, source_col: str, dtype: str = "string") -> Dict[str, Any]:
    return edit(
        name,
        src_type=dtype,
        op="add",
        target_name=name,
        target_type=dtype,
        is_new=True,
        generator={"kind": "from_column", "source_column": source_col},
    )


def fk_lookup(
    name: str,
    source_table: str,
    source_column: str,
    match_column: str,
    local_column: str,
    dtype: str = "string",
) -> Dict[str, Any]:
    return edit(
        name,
        src_type=dtype,
        op="fk",
        target_name=name,
        target_type=dtype,
        is_new=True,
        fk={
            "source_table": source_table,
            "source_column": source_column,
            "match_column": match_column,
            "local_column": local_column,
        },
    )


def fk_lookup_chain(
    name: str,
    local_column: str,
    chain: List[Dict[str, str]],
    dtype: str = "string",
) -> Dict[str, Any]:
    """Multi-hop FK. Each `chain` entry is {table, match_column, source_column}."""
    return edit(
        name,
        src_type=dtype,
        op="fk",
        target_name=name,
        target_type=dtype,
        is_new=True,
        fk_chain=chain,
        fk_local_column=local_column,
    )


def computed(
    name: str, expression: str, *, round_: int = 2, dtype: str = "decimal"
) -> Dict[str, Any]:
    return edit(
        name,
        src_type=dtype,
        op="add",
        target_name=name,
        target_type=dtype,
        is_new=True,
        generator={"kind": "fixed", "value": "0"},
        transforms=[
            {
                "op": "compute",
                "params": {
                    "expression": expression,
                    "round": round_,
                    "null_as": 0,
                    "on_error": "zero",
                },
            }
        ],
    )


def conditional_map(name: str, source_col: str, rules: List[Dict[str, Any]],
                    default: str = "original", dtype: str = "string") -> Dict[str, Any]:
    """Synthetic column whose value is `source_col` mapped through if/then rules."""
    return edit(
        name,
        src_type=dtype,
        op="add",
        target_name=name,
        target_type=dtype,
        is_new=True,
        generator={"kind": "from_column", "source_column": source_col},
        transforms=[
            {"op": "conditional", "params": {"rules": rules, "default": default}}
        ],
    )


# ---------- read source CSV headers -----------------------------------------


def read_columns(table: str) -> List[str]:
    p = LEGACY_DATA_DIR / f"{table}.csv"
    if not p.exists():
        return []
    try:
        with p.open("r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.reader(f)
            row = next(reader, [])
            return [
                c for c in row
                if c and c.replace("_", "").replace("-", "").isalnum()
            ]
    except Exception:
        return []


def renamed_with_drops(
    table: str, rename: Dict[str, tuple]
) -> List[Dict[str, Any]]:
    """Rename listed columns; explicitly drop everything else. The transformer
    needs an explicit drop to suppress a column — otherwise it passes
    through with the original (uppercase) name."""
    cols = read_columns(table)
    edits: List[Dict[str, Any]] = []
    for col in cols:
        if col in rename:
            tname, t = rename[col]
            edits.append(edit(col, t, op="rename", target_name=tname, target_type=t))
        else:
            edits.append(edit(col, op="drop"))
    return edits


# ---------- BUILDERS — lookups & seeds --------------------------------------


def build_currency() -> List[Dict[str, Any]]:
    edits = renamed_with_drops("CURT", {
        "CURNAME": ("currency_name_full", "string"),
        "CURSHORT": ("currency_name", "string"),
        "CURPARTNAME": ("fraction", "string"),
        "CURPARTNAMEE": ("fraction_en", "string"),
    })
    edits += [
        from_col("name", "currency_name"),
        fixed("enabled", "1", "integer"),
        fixed("fraction_units", "100", "integer"),
        fixed("docstatus", "0", "integer"),
        fixed("owner", DEFAULT_OWNER),
    ]
    return edits


def build_uom() -> List[Dict[str, Any]]:
    edits = renamed_with_drops("UNITT", {
        "UNITNAME": ("uom_name", "string"),
        "UNITNAMEE": ("uom_name_en", "string"),
    })
    edits += [
        from_col("name", "uom_name"),
        fixed("enabled", "1", "integer"),
        fixed("must_be_whole_number", "0", "integer"),
        fixed("docstatus", "0", "integer"),
    ]
    return edits


def build_price_list() -> List[Dict[str, Any]]:
    edits = renamed_with_drops("PRICETYPET", {
        "PRICEID": ("legacy_id", "integer"),
        "PRICENAME": ("price_list_name_legacy", "string"),
        "PRICENOTE": ("notes", "string"),
    })
    # Seed with the standard ERPnext-recognized names. Conditional on PRICEID:
    # 1 → Standard Selling, 2 → Wholesale, others → AlArabi-Tier-N.
    edits += [
        edit(
            "name",
            src_type="string",
            op="add",
            target_name="name",
            target_type="string",
            is_new=True,
            generator={"kind": "from_column", "source_column": "legacy_id"},
            transforms=[
                {
                    "op": "conditional",
                    "params": {
                        "rules": [
                            {"when": "1", "then": DEFAULT_PRICE_LIST_RETAIL},
                            {"when": "2", "then": DEFAULT_PRICE_LIST_WHOLESALE},
                        ],
                        "default": "original",
                    },
                }
            ],
        ),
        from_col("price_list_name", "name"),
        fixed("currency", "NIS"),
        fixed("enabled", "1", "integer"),
        fixed("selling", "1", "integer"),
        fixed("buying", "0", "integer"),
        fixed("docstatus", "0", "integer"),
    ]
    return edits


def build_item_group() -> List[Dict[str, Any]]:
    edits = renamed_with_drops("CATBASICSETST", {
        "SETNAME": ("item_group_name", "string"),
        "SETNAMEE": ("item_group_name_en", "string"),
    })
    edits += [
        from_col("name", "item_group_name"),
        fixed("parent_item_group", "All Item Groups"),
        fixed("is_group", "0", "integer"),
        fixed("show_in_website", "0", "integer"),
        fixed("docstatus", "0", "integer"),
    ]
    return edits


def build_warehouse() -> List[Dict[str, Any]]:
    edits = renamed_with_drops("STORET", {
        "DESCRIPTION": ("warehouse_name", "string"),
        "DESCRIPTIONE": ("warehouse_name_en", "string"),
        "PHONE": ("phone_no", "string"),
        "LOCATION": ("address_line_1", "string"),
        "MANAGER": ("contact_person", "string"),
    })
    edits += [
        from_col("name", "warehouse_name"),
        fixed("parent_warehouse", "All Warehouses"),
        fixed("is_group", "0", "integer"),
        fixed("disabled", "0", "integer"),
        fixed("company", DEFAULT_COMPANY),
        fixed("docstatus", "0", "integer"),
    ]
    return edits


def build_pos_profile() -> List[Dict[str, Any]]:
    edits = renamed_with_drops("SALEPOINTT", {
        "SPNAME": ("name", "string"),
        "SPLOCATION": ("notes", "string"),
    })
    edits += [
        fk_lookup(
            "warehouse", "STORET", "DESCRIPTION", "STOREID", "STOREID"
        ),
        fixed("company", DEFAULT_COMPANY),
        fixed("disabled", "0", "integer"),
        fixed("currency", "NIS"),
        fixed("selling_price_list", DEFAULT_PRICE_LIST_RETAIL),
        fixed("docstatus", "0", "integer"),
    ]
    return edits


def build_cost_center() -> List[Dict[str, Any]]:
    cols = read_columns("IMPORTCOSTCENTERT")
    edits: List[Dict[str, Any]] = []
    name_col = cols[0] if cols else None
    if name_col:
        edits.append(edit(name_col, "string", op="rename", target_name="name", target_type="string"))
        edits.append(from_col("cost_center_name", "name"))
    for c in cols[1:]:
        edits.append(edit(c, op="drop"))
    edits += [
        fixed("parent_cost_center", "All Cost Centers"),
        fixed("is_group", "0", "integer"),
        fixed("company", DEFAULT_COMPANY),
        fixed("docstatus", "0", "integer"),
    ]
    return edits


def build_project() -> List[Dict[str, Any]]:
    edits = renamed_with_drops("PROJECTST", {
        "PROJECTID": ("name", "string"),
        "NAME": ("project_name", "string"),
        "DESCRIPTION": ("notes", "string"),
        "STATUS": ("status_legacy", "string"),
    })
    edits += [
        fixed("status", "Open"),
        fixed("docstatus", "0", "integer"),
        fixed("company", DEFAULT_COMPANY),
    ]
    return edits


def build_bank() -> List[Dict[str, Any]]:
    edits = renamed_with_drops("BANKT", {
        "BANKID": ("name", "string"),
        "BANKNAME": ("bank_name", "string"),
        "BANKNAMEE": ("bank_name_en", "string"),
    })
    edits += [
        fixed("docstatus", "0", "integer"),
    ]
    return edits


def build_bank_account() -> List[Dict[str, Any]]:
    edits = renamed_with_drops("BANKACCOUNTT", {
        "BANKACCID": ("name", "string"),
        "ACCOUNTNO": ("bank_account_no", "string"),
        "BANKACCOWNERNAME": ("account_name", "string"),
        "BRANCHNAME": ("branch_code", "string"),
    })
    edits += [
        fk_lookup("bank", "BANKT", "BANKNAME", "BANKID", "BANKID"),
        fixed("is_company_account", "1", "integer"),
        fixed("company", DEFAULT_COMPANY),
        fixed("disabled", "0", "integer"),
        fixed("docstatus", "0", "integer"),
    ]
    return edits


# ---------- BUILDERS — Item & friends ---------------------------------------


def build_item() -> List[Dict[str, Any]]:
    edits = renamed_with_drops("CATEGORYT", {
        "CATID": ("item_code", "string"),
        "CATNAME": ("item_name", "string"),
        "CATNAMEE": ("item_name_en", "string"),
        "MANUFACTURER": ("brand", "string"),
        "MODEL": ("variant_of", "string"),
        "VAT": ("tax_rate", "decimal"),
        "WEIGHT": ("weight_per_unit", "decimal"),
        "COSTFIFO": ("valuation_rate", "decimal"),
        "LASTPURCHPRICE": ("last_purchase_rate", "decimal"),
        "INSERTDATE": ("creation", "datetime"),
        "CHANGEDATE": ("modified", "datetime"),
    })
    edits += [
        from_col("name", "item_code"),
        fk_lookup("stock_uom", "UNITT", "UNITNAME", "UNITID", "UNIT"),
        fk_lookup("item_group", "CATBASICSETST", "SETNAME", "SETID", "SETNO"),
        fixed("is_stock_item", "1", "integer"),
        fixed("has_serial_no", "0", "integer"),
        fixed("disabled", "0", "integer"),
        fixed("docstatus", "0", "integer"),
        fixed("idx", "0", "integer"),
        fixed("owner", DEFAULT_OWNER),
        fixed("modified_by", DEFAULT_OWNER),
        fixed("weight_uom", "Kg"),
        fixed("company", DEFAULT_COMPANY),
        fixed("description", ""),
    ]
    return edits


def build_item_barcode_from_synonyms() -> List[Dict[str, Any]]:
    """Primary CATESYNONYMT mapping: each row becomes a child Item Barcode."""
    edits = renamed_with_drops("CATESYNONYMT", {
        "CATID": ("parent", "string"),
        "SYNCATID": ("barcode", "string"),
        "CREATEDATE": ("creation", "datetime"),
    })
    edits += [
        from_col("name", "barcode"),
        fixed("parenttype", "Item"),
        fixed("parentfield", "barcodes"),
        fixed("idx", "0", "integer"),
        fixed("docstatus", "0", "integer"),
        fixed("owner", DEFAULT_OWNER),
        fixed("modified_by", DEFAULT_OWNER),
    ]
    return edits


def build_item_barcode_from_categoryt() -> List[Dict[str, Any]]:
    """Extra config: every Item also gets its primary CATID as a barcode row."""
    cols = read_columns("CATEGORYT")
    edits: List[Dict[str, Any]] = []
    for col in cols:
        if col == "CATID":
            edits.append(edit("CATID", "string", op="rename",
                              target_name="parent", target_type="string"))
        else:
            edits.append(edit(col, op="drop"))
    edits += [
        from_col("barcode", "parent"),
        from_col("name", "parent"),
        fixed("parenttype", "Item"),
        fixed("parentfield", "barcodes"),
        fixed("idx", "0", "integer"),
        fixed("docstatus", "0", "integer"),
        fixed("owner", DEFAULT_OWNER),
        fixed("modified_by", DEFAULT_OWNER),
    ]
    return edits


def build_brand_from_categoryt() -> List[Dict[str, Any]]:
    """Extra config: DISTINCT(MANUFACTURER) → tabBrand. Uses the new
    aggregate feature."""
    cols = read_columns("CATEGORYT")
    edits: List[Dict[str, Any]] = []
    for col in cols:
        if col == "MANUFACTURER":
            edits.append(edit("MANUFACTURER", "string", op="rename",
                              target_name="brand_name", target_type="string"))
        else:
            edits.append(edit(col, op="drop"))
    edits += [
        from_col("name", "brand_name"),
        fixed("docstatus", "0", "integer"),
    ]
    return edits


def build_item_default_from_categoryt() -> List[Dict[str, Any]]:
    """Extra config: per-(item, company) defaults — child of Item.

    Reads default warehouse from CATEGORYT.DEFAULTSTOREID and the default
    income/expense/inventory accounts from the item's group (SETNO →
    CATBASICSETST.SALEACC/PURCHACC/STORAGEACC) via FK lookups.
    """
    cols = read_columns("CATEGORYT")
    edits: List[Dict[str, Any]] = []
    for col in cols:
        if col == "CATID":
            edits.append(edit("CATID", "string", op="rename",
                              target_name="parent", target_type="string"))
        else:
            edits.append(edit(col, op="drop"))
    edits += [
        from_col("name", "parent"),
        fk_lookup("default_warehouse", "STORET", "DESCRIPTION",
                  "STOREID", "DEFAULTSTOREID"),
        fk_lookup("income_account", "CATBASICSETST", "SALEACC",
                  "SETID", "SETNO"),
        fk_lookup("expense_account", "CATBASICSETST", "PURCHACC",
                  "SETID", "SETNO"),
        fk_lookup("default_inventory_account", "CATBASICSETST", "STORAGEACC",
                  "SETID", "SETNO"),
        fixed("parenttype", "Item"),
        fixed("parentfield", "item_defaults"),
        fixed("company", DEFAULT_COMPANY),
        fixed("docstatus", "0", "integer"),
    ]
    return edits


def build_item_price() -> List[Dict[str, Any]]:
    edits = renamed_with_drops("CATPRICET", {
        "CATID": ("item_code", "string"),
        "SALEPRICE": ("price_list_rate", "decimal"),
        "MINSALEPRICE": ("min_rate", "decimal"),
        "DISCOUNT": ("discount_percentage", "decimal"),
        "CHANGEDATE": ("modified", "datetime"),
    })
    edits += [
        # Use a synthetic synonym for price_list mapping to keep the source
        # PRICEID available for the FK join too.
        edit(
            "PRICEID", "integer", op="rename",
            target_name="price_list_legacy_id", target_type="integer",
        ),
        edit(
            "price_list", src_type="string", op="add",
            target_name="price_list", target_type="string", is_new=True,
            generator={"kind": "from_column", "source_column": "price_list_legacy_id"},
            transforms=[
                {
                    "op": "conditional",
                    "params": {
                        "rules": [
                            {"when": 1, "then": DEFAULT_PRICE_LIST_RETAIL},
                            {"when": 2, "then": DEFAULT_PRICE_LIST_WHOLESALE},
                            {"when": "1", "then": DEFAULT_PRICE_LIST_RETAIL},
                            {"when": "2", "then": DEFAULT_PRICE_LIST_WHOLESALE},
                        ],
                        "default": "original",
                    },
                }
            ],
        ),
        fk_lookup("currency", "CURT", "CURSHORT", "CURID", "SALECUR"),
        fixed("selling", "1", "integer"),
        fixed("buying", "0", "integer"),
        fixed("docstatus", "0", "integer"),
        fixed("idx", "0", "integer"),
        fixed("owner", DEFAULT_OWNER),
    ]
    return edits


def build_bin() -> List[Dict[str, Any]]:
    edits = renamed_with_drops("CATSTORET", {
        "CATID": ("item_code", "string"),
        "QTYBALANCE": ("actual_qty", "decimal"),
        "STOREMINQTY": ("reorder_level", "decimal"),
        "STOREMAXQTY": ("reorder_qty", "decimal"),
        "SORDERQTY": ("ordered_qty", "decimal"),
        "CHANGEDATE": ("modified", "datetime"),
    })
    edits += [
        fk_lookup("warehouse", "STORET", "DESCRIPTION",
                  "STOREID", "STOREID"),
        edit(
            "name", src_type="string", op="add",
            target_name="name", target_type="string", is_new=True,
            generator={"kind": "fixed", "value": ""},
            transforms=[
                {"op": "concat_template",
                 "params": {"template": "{warehouse}-{item_code}"}}
            ],
        ),
        computed("projected_qty", "{actual_qty}", round_=2),
        fixed("docstatus", "0", "integer"),
    ]
    return edits


def build_item_supplier() -> List[Dict[str, Any]]:
    edits = renamed_with_drops("CATSUPPLIERT", {
        "CATID": ("parent", "string"),
        "INSERTDATE": ("creation", "datetime"),
    })
    edits += [
        # SUPPLIER is the supplier's GL ACCOUNTID — resolve to the supplier name
        fk_lookup("supplier", "ACCOUNTT", "NAME", "ACCOUNTID", "SUPPLIER"),
        from_col("name", "parent"),
        fixed("parenttype", "Item"),
        fixed("parentfield", "supplier_items"),
        fixed("idx", "0", "integer"),
        fixed("docstatus", "0", "integer"),
    ]
    return edits


# ---------- BUILDERS — Mode of Payment seed (DISTINCT POSPAYST.PAYTYPE) ----


def build_mode_of_payment_from_pospayst() -> List[Dict[str, Any]]:
    """Extra config from POSPAYST: DISTINCT PAYTYPE → tabMode of Payment."""
    cols = read_columns("POSPAYST")
    edits: List[Dict[str, Any]] = []
    for col in cols:
        if col == "PAYTYPE":
            edits.append(edit("PAYTYPE", "integer", op="rename",
                              target_name="legacy_pay_type", target_type="integer"))
        else:
            edits.append(edit(col, op="drop"))
    edits += [
        edit(
            "name", src_type="string", op="add",
            target_name="name", target_type="string", is_new=True,
            generator={"kind": "from_column", "source_column": "legacy_pay_type"},
            transforms=[
                {
                    "op": "conditional",
                    "params": {
                        "rules": [
                            {"when": "1", "then": "Cash"},
                            {"when": "2", "then": "Cheque"},
                            {"when": "3", "then": "Credit Card"},
                            {"when": "4", "then": "Coupon"},
                            {"when": "5", "then": "Bank Draft"},
                            {"when": 1, "then": "Cash"},
                            {"when": 2, "then": "Cheque"},
                            {"when": 3, "then": "Credit Card"},
                            {"when": 4, "then": "Coupon"},
                            {"when": 5, "then": "Bank Draft"},
                        ],
                        "default": "original",
                    },
                }
            ],
        ),
        from_col("mode_of_payment", "name"),
        fixed("enabled", "1", "integer"),
        fixed("type", "Cash"),
        fixed("docstatus", "0", "integer"),
    ]
    return edits


# ---------- BUILDERS — Parties ----------------------------------------------


def build_customer() -> List[Dict[str, Any]]:
    edits = renamed_with_drops("CUSTT", {
        "CUSTID": ("name", "string"),
        "DUEDAYS": ("payment_terms_days", "integer"),
        "DISCOUNT": ("default_discount_percentage", "decimal"),
        "FILENO": ("tax_id", "string"),
        "NOTE": ("notes", "string"),
    })
    edits += [
        fk_lookup("customer_name", "ACCOUNTT", "NAME",
                  "ACCOUNTID", "ACCOUNT"),
        # default_currency = account's currency code, two hops:
        # CUSTT.ACCOUNT → ACCOUNTT.CURID → CURT.CURSHORT
        fk_lookup_chain(
            "default_currency", "ACCOUNT",
            chain=[
                {"table": "ACCOUNTT", "match_column": "ACCOUNTID", "source_column": "CURID"},
                {"table": "CURT", "match_column": "CURID", "source_column": "CURSHORT"},
            ],
        ),
        fixed("customer_group", "All Customer Groups"),
        fixed("territory", "All Territories"),
        fixed("customer_type", "Company"),
        fixed("disabled", "0", "integer"),
        fixed("docstatus", "0", "integer"),
        fixed("owner", DEFAULT_OWNER),
    ]
    return edits


def build_supplier() -> List[Dict[str, Any]]:
    edits = renamed_with_drops("SUPPLIERT", {
        "SUPPID": ("name", "string"),
        "DISCOUNT": ("default_discount_percentage", "decimal"),
        "FILENO": ("tax_id", "string"),
        "NOTE": ("notes", "string"),
    })
    edits += [
        fk_lookup("supplier_name", "ACCOUNTT", "NAME",
                  "ACCOUNTID", "ACCOUNT"),
        fk_lookup_chain(
            "default_currency", "ACCOUNT",
            chain=[
                {"table": "ACCOUNTT", "match_column": "ACCOUNTID", "source_column": "CURID"},
                {"table": "CURT", "match_column": "CURID", "source_column": "CURSHORT"},
            ],
        ),
        fixed("supplier_group", "All Supplier Groups"),
        fixed("country", "Palestine"),
        fixed("disabled", "0", "integer"),
        fixed("docstatus", "0", "integer"),
        fixed("owner", DEFAULT_OWNER),
    ]
    return edits


def build_address() -> List[Dict[str, Any]]:
    """Primary CONTACTST mapping → tabAddress."""
    edits = renamed_with_drops("CONTACTST", {
        "CONTACTID": ("name", "string"),
        "ADDRESS": ("address_line1", "string"),
        "ADDRESSE": ("address_line2", "string"),
        "CITYID": ("city", "string"),
        "GPS_LAT": ("gps_lat", "decimal"),
        "GPS_LON": ("gps_lon", "decimal"),
    })
    edits += [
        fixed("address_type", "Billing"),
        fixed("country", "Palestine"),
        fixed("docstatus", "0", "integer"),
    ]
    return edits


def build_contact_from_contactst() -> List[Dict[str, Any]]:
    """Extra config: same source → tabContact (phone/email)."""
    edits = renamed_with_drops("CONTACTST", {
        "CONTACTID": ("name", "string"),
        "NAME": ("first_name", "string"),
        "NAMEE": ("first_name_en", "string"),
        "OFFICEPHONE1": ("phone", "string"),
        "MOBILE": ("mobile_no", "string"),
        "EMAIL": ("email_id", "string"),
        "WEB": ("website", "string"),
    })
    edits += [
        fixed("status", "Active"),
        fixed("docstatus", "0", "integer"),
    ]
    return edits


def build_dynamic_link_from_contactst() -> List[Dict[str, Any]]:
    """Extra config: links Address/Contact back to their party (ACCOUNTID).

    ERPnext models the connection as a tabDynamic Link child row whose
    `parent` is the Address/Contact name and whose `link_doctype + link_name`
    point to the Customer / Supplier / Employee. Here we generate one row
    per CONTACTST, parented to the Address (the Contact extra would need
    its own dynamic-link row in a fully ERPnext-compliant import — fine
    follow-up if needed).
    """
    edits = renamed_with_drops("CONTACTST", {
        "CONTACTID": ("parent", "string"),
        "ACCOUNTID": ("link_name", "string"),
    })
    edits += [
        from_col("name", "parent"),
        fixed("link_doctype", "Customer"),
        fixed("parenttype", "Address"),
        fixed("parentfield", "links"),
        fixed("idx", "0", "integer"),
        fixed("docstatus", "0", "integer"),
    ]
    return edits


def build_employee() -> List[Dict[str, Any]]:
    edits = renamed_with_drops("EMPLOYEET", {
        "EMPID": ("name", "string"),
        "IDNO": ("bio", "string"),
        "BIRTH": ("date_of_birth", "date"),
        "STARTDATE": ("date_of_joining", "date"),
        "EMPENDDATE": ("relieving_date", "date"),
        "CARDID": ("attendance_device_id", "string"),
        "VOCDAY": ("leaves_allocated", "integer"),
        "WANTEDHOURS": ("expected_working_hours", "decimal"),
        "SALARY": ("ctc", "decimal"),
        "NOTE": ("bio_legacy", "string"),
    })
    edits += [
        fk_lookup("employee_name", "ACCOUNTT", "NAME",
                  "ACCOUNTID", "ACCOUNT"),
        # Status: ISWORKING=1 → Active, else Left
        edit(
            "status", src_type="string", op="add",
            target_name="status", target_type="string", is_new=True,
            generator={"kind": "from_column", "source_column": "ISWORKING"},
            transforms=[
                {
                    "op": "conditional",
                    "params": {
                        "rules": [
                            {"when": "1", "then": "Active"},
                            {"when": 1, "then": "Active"},
                        ],
                        "default": "Left",
                    },
                }
            ],
        ),
        # Gender: 1 → Male, 2 → Female
        edit(
            "gender", src_type="string", op="add",
            target_name="gender", target_type="string", is_new=True,
            generator={"kind": "from_column", "source_column": "GENDER"},
            transforms=[
                {
                    "op": "conditional",
                    "params": {
                        "rules": [
                            {"when": "1", "then": "Male"},
                            {"when": "2", "then": "Female"},
                            {"when": 1, "then": "Male"},
                            {"when": 2, "then": "Female"},
                        ],
                        "default": "Other",
                    },
                }
            ],
        ),
        fk_lookup_chain(
            "default_currency", "ACCOUNT",
            chain=[
                {"table": "ACCOUNTT", "match_column": "ACCOUNTID", "source_column": "CURID"},
                {"table": "CURT", "match_column": "CURID", "source_column": "CURSHORT"},
            ],
        ),
        fixed("company", DEFAULT_COMPANY),
        fixed("holiday_list", "Default Holiday List"),
        fixed("employment_type", "Full-time"),
        fixed("docstatus", "0", "integer"),
        fixed("owner", DEFAULT_OWNER),
    ]
    return edits


# ---------- BUILDERS — Chart of Accounts ------------------------------------


def build_account() -> List[Dict[str, Any]]:
    edits = renamed_with_drops("ACCOUNTT", {
        "ACCOUNTID": ("name", "string"),
        "NAME": ("account_name", "string"),
        "NAMEE": ("account_name_en", "string"),
        "MBALANCE": ("balance", "decimal"),
        "ABALANCE": ("balance_base", "decimal"),
        "MAXCR": ("credit_limit", "decimal"),
        "MAXDB": ("debit_limit", "decimal"),
    })
    edits += [
        # Self-FK: parent_account is the parent's name (= ACCOUNTID).
        fk_lookup("parent_account", "ACCOUNTT", "ACCOUNTID",
                  "ACCOUNTID", "FATHERID"),
        fk_lookup("account_currency", "CURT", "CURSHORT",
                  "CURID", "CURID"),
        # root_type: classify by the leading digit of the account number
        # (1=Asset, 2=Liability, 3=Equity, 4=Expense, 5=Income). Override
        # post-import if your CoA doesn't follow this convention.
        edit(
            "root_type", src_type="string", op="add",
            target_name="root_type", target_type="string", is_new=True,
            generator={"kind": "from_column", "source_column": "name"},
            transforms=[
                {
                    "op": "conditional",
                    "params": {
                        "rules": [
                            # We can't string-prefix-match in conditional;
                            # rely on the user setting this post-import via
                            # the one-line SQL update documented in the
                            # status PDF. This generator captures intent and
                            # leaves the value as the legacy id, which is
                            # then easy to bulk-update.
                        ],
                        "default": "original",
                    },
                }
            ],
        ),
        fixed("is_group", "0", "integer"),
        fixed("docstatus", "0", "integer"),
        fixed("company", DEFAULT_COMPANY),
        fixed("owner", DEFAULT_OWNER),
    ]
    return edits


# ---------- BUILDERS — Sales --------------------------------------------------


def _sales_invoice_header(table: str, *, is_return: bool) -> List[Dict[str, Any]]:
    """Common shape for both regular and return sales invoice headers.

    For returns we use a different DOCNO prefix to avoid name collisions
    with the original invoice; the user can drop the prefix post-import
    if they prefer the legacy DOCNO unchanged."""
    cols = read_columns(table)
    rename = {
        "DOCNO": ("docno_legacy", "integer"),
        "INVTYPE": ("invtype_legacy", "integer"),
        "DOCDATE": ("posting_date", "date"),
        "DOCTIME": ("posting_time", "time"),
        "DUEDATE": ("due_date", "date"),
        "CURVALUE": ("conversion_rate", "decimal"),
        "SUBTOTAL": ("net_total", "decimal"),
        "DISCOUNTV": ("discount_amount", "decimal"),
        "DISCOUNTP": ("additional_discount_percentage", "decimal"),
        "VATAMOUNT": ("total_taxes_and_charges", "decimal"),
        "DOCVALUE": ("grand_total", "decimal"),
        "DOCMVALUE": ("base_grand_total", "decimal"),
        "POSTDATE": ("posted_at", "datetime"),
        "PUID": ("cashier", "integer"),
        "NOTES": ("remarks", "string"),
    }
    edits: List[Dict[str, Any]] = []
    for col in cols:
        if col in rename:
            tname, t = rename[col]
            edits.append(edit(col, t, op="rename", target_name=tname, target_type=t))
        else:
            edits.append(edit(col, op="drop"))
    # name = "AL-{INVTYPE}-{DOCNO}" or "AL-RET-{INVTYPE}-{DOCNO}" for returns
    template = (
        "AL-RET-{invtype_legacy}-{docno_legacy}"
        if is_return
        else "AL-{invtype_legacy}-{docno_legacy}"
    )
    edits += [
        edit(
            "name", src_type="string", op="add",
            target_name="name", target_type="string", is_new=True,
            generator={"kind": "fixed", "value": ""},
            transforms=[
                {"op": "concat_template", "params": {"template": template}}
            ],
        ),
        fk_lookup("customer", "ACCOUNTT", "NAME",
                  "ACCOUNTID", "ACCOUNTID"),
        fk_lookup("set_warehouse", "STORET", "DESCRIPTION",
                  "STOREID", "STOREID"),
        fk_lookup("currency", "CURT", "CURSHORT", "CURID", "CURID"),
        fixed("outstanding_amount", "0", "decimal"),
        fixed("status", "Submitted"),
        fixed("docstatus", "1", "integer"),
        fixed("is_pos", "1", "integer"),
        fixed("update_stock", "1", "integer"),
        fixed("is_return", "1" if is_return else "0", "integer"),
        fixed("selling_price_list", DEFAULT_PRICE_LIST_RETAIL),
        fixed("company", DEFAULT_COMPANY),
        fixed("owner", DEFAULT_OWNER),
    ]
    return edits


def build_sales_invoice() -> List[Dict[str, Any]]:
    return _sales_invoice_header("CATESINVDOCT", is_return=False)


def build_sales_return_header() -> List[Dict[str, Any]]:
    return _sales_invoice_header("CATESRETINVDOCT", is_return=True)


def _sales_invoice_item(table: str, *, is_return: bool) -> List[Dict[str, Any]]:
    cols = read_columns(table)
    rename = {
        "DOCNO": ("docno_legacy", "integer"),
        "INVTYPE": ("invtype_legacy", "integer"),
        "SERIAL": ("idx_legacy", "integer"),
        "CATID": ("item_code", "string"),
        "CATNAME": ("item_name", "string"),
        "CATUNIT": ("uom", "string"),
        "CATQTY": ("qty_abs", "decimal"),
        "CATPRICE": ("rate", "decimal"),
        "CATDISCOUNT": ("discount_amount", "decimal"),
        "CATBONUS": ("bonus_qty", "decimal"),
        "VAT": ("tax_rate", "decimal"),
    }
    edits: List[Dict[str, Any]] = []
    for col in cols:
        if col in rename:
            tname, t = rename[col]
            edits.append(edit(col, t, op="rename", target_name=tname, target_type=t))
        else:
            edits.append(edit(col, op="drop"))
    parent_template = (
        "AL-RET-{invtype_legacy}-{docno_legacy}"
        if is_return
        else "AL-{invtype_legacy}-{docno_legacy}"
    )
    qty_expr = "{qty_abs} * -1" if is_return else "{qty_abs}"
    edits += [
        # parent reconstructs the same name the header generates
        edit(
            "parent", src_type="string", op="add",
            target_name="parent", target_type="string", is_new=True,
            generator={"kind": "fixed", "value": ""},
            transforms=[
                {"op": "concat_template", "params": {"template": parent_template}}
            ],
        ),
        from_col("idx", "idx_legacy"),
        fk_lookup("warehouse", "STORET", "DESCRIPTION",
                  "STOREID", "STOREID"),
        fk_lookup("income_account", "ACCOUNTT", "NAME",
                  "ACCOUNTID", "SALEACCID"),
        # Negate qty for returns
        computed("qty", qty_expr),
        # amount = qty * rate; net_amount = amount - discount
        computed("amount", "{qty} * {rate}"),
        computed("net_amount", "{qty} * {rate} - {discount_amount}"),
        fixed("parenttype", "Sales Invoice"),
        fixed("parentfield", "items"),
        fixed("docstatus", "1", "integer"),
        fixed("owner", DEFAULT_OWNER),
    ]
    return edits


def build_sales_invoice_item() -> List[Dict[str, Any]]:
    return _sales_invoice_item("CATESINVDOCDETT", is_return=False)


def build_sales_return_item() -> List[Dict[str, Any]]:
    return _sales_invoice_item("CATESRETINVDOCDETT", is_return=True)


# ---------- BUILDERS — Purchases (mirror sales) -----------------------------


def _purchase_invoice_header(table: str, *, is_return: bool) -> List[Dict[str, Any]]:
    cols = read_columns(table)
    rename = {
        "DOCNO": ("docno_legacy", "integer"),
        "DOCDATE": ("posting_date", "date"),
        "DOCTIME": ("posting_time", "time"),
        "DUEDATE": ("due_date", "date"),
        "CURVALUE": ("conversion_rate", "decimal"),
        "SUBTOTAL": ("net_total", "decimal"),
        "DISCOUNTV": ("discount_amount", "decimal"),
        "VATAMOUNT": ("total_taxes_and_charges", "decimal"),
        "DOCVALUE": ("grand_total", "decimal"),
        "DOCMVALUE": ("base_grand_total", "decimal"),
        "PUID": ("created_by_user", "integer"),
        "NOTES": ("remarks", "string"),
    }
    edits: List[Dict[str, Any]] = []
    for col in cols:
        if col in rename:
            tname, t = rename[col]
            edits.append(edit(col, t, op="rename", target_name=tname, target_type=t))
        else:
            edits.append(edit(col, op="drop"))
    template = (
        "AL-PRET-{docno_legacy}" if is_return else "AL-PINV-{docno_legacy}"
    )
    edits += [
        edit(
            "name", src_type="string", op="add",
            target_name="name", target_type="string", is_new=True,
            generator={"kind": "fixed", "value": ""},
            transforms=[
                {"op": "concat_template", "params": {"template": template}}
            ],
        ),
        fk_lookup("supplier", "ACCOUNTT", "NAME",
                  "ACCOUNTID", "ACCOUNTID"),
        fk_lookup("set_warehouse", "STORET", "DESCRIPTION",
                  "STOREID", "STOREID"),
        fk_lookup("currency", "CURT", "CURSHORT", "CURID", "CURID"),
        fixed("status", "Submitted"),
        fixed("docstatus", "1", "integer"),
        fixed("update_stock", "1", "integer"),
        fixed("is_return", "1" if is_return else "0", "integer"),
        fixed("buying_price_list", DEFAULT_BUYING_PRICE_LIST),
        fixed("company", DEFAULT_COMPANY),
        fixed("owner", DEFAULT_OWNER),
    ]
    return edits


def build_purchase_invoice() -> List[Dict[str, Any]]:
    return _purchase_invoice_header("CATEPINVDOCT", is_return=False)


def build_purchase_return_header() -> List[Dict[str, Any]]:
    return _purchase_invoice_header("CATEPRETINVDOCT", is_return=True)


def _purchase_invoice_item(table: str, *, is_return: bool) -> List[Dict[str, Any]]:
    cols = read_columns(table)
    rename = {
        "DOCNO": ("docno_legacy", "integer"),
        "SERIAL": ("idx_legacy", "integer"),
        "CATID": ("item_code", "string"),
        "CATNAME": ("item_name", "string"),
        "CATUNIT": ("uom", "string"),
        "CATQTY": ("qty_abs", "decimal"),
        "CATPRICE": ("rate", "decimal"),
        "CATDISCOUNT": ("discount_amount", "decimal"),
    }
    edits: List[Dict[str, Any]] = []
    for col in cols:
        if col in rename:
            tname, t = rename[col]
            edits.append(edit(col, t, op="rename", target_name=tname, target_type=t))
        else:
            edits.append(edit(col, op="drop"))
    parent_template = (
        "AL-PRET-{docno_legacy}" if is_return else "AL-PINV-{docno_legacy}"
    )
    qty_expr = "{qty_abs} * -1" if is_return else "{qty_abs}"
    expense_field = "PURCHRETACCID" if is_return else "PURCHACCID"
    edits += [
        edit(
            "parent", src_type="string", op="add",
            target_name="parent", target_type="string", is_new=True,
            generator={"kind": "fixed", "value": ""},
            transforms=[
                {"op": "concat_template", "params": {"template": parent_template}}
            ],
        ),
        from_col("idx", "idx_legacy"),
        fk_lookup("warehouse", "STORET", "DESCRIPTION",
                  "STOREID", "STOREID"),
        fk_lookup("expense_account", "ACCOUNTT", "NAME",
                  "ACCOUNTID", expense_field),
        computed("qty", qty_expr),
        computed("amount", "{qty} * {rate}"),
        computed("net_amount", "{qty} * {rate} - {discount_amount}"),
        fixed("parenttype", "Purchase Invoice"),
        fixed("parentfield", "items"),
        fixed("docstatus", "1", "integer"),
        fixed("owner", DEFAULT_OWNER),
    ]
    return edits


def build_purchase_invoice_item() -> List[Dict[str, Any]]:
    return _purchase_invoice_item("CATEPINVDOCDETT", is_return=False)


def build_purchase_return_item() -> List[Dict[str, Any]]:
    return _purchase_invoice_item("CATEPRETINVDOCDETT", is_return=True)


# ---------- BUILDERS — Stock movements --------------------------------------


def build_stock_entry_internal() -> List[Dict[str, Any]]:
    """CATEINDOCT — internal Material Issue / Receipt."""
    edits = renamed_with_drops("CATEINDOCT", {
        "DOCSERIAL": ("docserial_legacy", "integer"),
        "DOCDATE": ("posting_date", "date"),
        "DOCTIME": ("posting_time", "time"),
        "NOTES": ("remarks", "string"),
    })
    edits += [
        edit(
            "name", src_type="string", op="add",
            target_name="name", target_type="string", is_new=True,
            generator={"kind": "fixed", "value": ""},
            transforms=[{"op": "concat_template",
                         "params": {"template": "AL-SE-{docserial_legacy}"}}],
        ),
        fk_lookup("from_warehouse", "STORET", "DESCRIPTION",
                  "STOREID", "FROMSTOREID"),
        fk_lookup("to_warehouse", "STORET", "DESCRIPTION",
                  "STOREID", "TOSTOREID"),
        fixed("stock_entry_type", "Material Receipt"),
        fixed("purpose", "Material Receipt"),
        fixed("docstatus", "1", "integer"),
        fixed("company", DEFAULT_COMPANY),
        fixed("owner", DEFAULT_OWNER),
    ]
    return edits


def build_stock_entry_division() -> List[Dict[str, Any]]:
    """DIVISIONDOCT — Material Transfer between stores."""
    edits = renamed_with_drops("DIVISIONDOCT", {
        "DOCSERIAL": ("docserial_legacy", "integer"),
        "DOCDATE": ("posting_date", "date"),
        "DOCTIME": ("posting_time", "time"),
        "NOTES": ("remarks", "string"),
    })
    edits += [
        edit(
            "name", src_type="string", op="add",
            target_name="name", target_type="string", is_new=True,
            generator={"kind": "fixed", "value": ""},
            transforms=[{"op": "concat_template",
                         "params": {"template": "AL-DIV-{docserial_legacy}"}}],
        ),
        fk_lookup("from_warehouse", "STORET", "DESCRIPTION",
                  "STOREID", "FROMSTOREID"),
        fk_lookup("to_warehouse", "STORET", "DESCRIPTION",
                  "STOREID", "TOSTOREID"),
        fixed("stock_entry_type", "Material Transfer"),
        fixed("purpose", "Material Transfer"),
        fixed("docstatus", "1", "integer"),
        fixed("company", DEFAULT_COMPANY),
        fixed("owner", DEFAULT_OWNER),
    ]
    return edits


def _stock_entry_detail(table: str, parent_prefix: str) -> List[Dict[str, Any]]:
    edits = renamed_with_drops(table, {
        "DOCNO": ("docno_legacy", "integer"),
        "SERIAL": ("idx_legacy", "integer"),
        "CATID": ("item_code", "string"),
        "CATNAME": ("item_name", "string"),
        "CATUNIT": ("uom", "string"),
        "CATQTY": ("qty", "decimal"),
        "CATCOST": ("basic_rate", "decimal"),
    })
    edits += [
        edit(
            "parent", src_type="string", op="add",
            target_name="parent", target_type="string", is_new=True,
            generator={"kind": "fixed", "value": ""},
            transforms=[{"op": "concat_template",
                         "params": {"template": parent_prefix + "-{docno_legacy}"}}],
        ),
        from_col("idx", "idx_legacy"),
        fk_lookup("s_warehouse", "STORET", "DESCRIPTION",
                  "STOREID", "STOREID"),
        fk_lookup("t_warehouse", "STORET", "DESCRIPTION",
                  "STOREID", "TOSTOREID"),
        fixed("parenttype", "Stock Entry"),
        fixed("parentfield", "items"),
        fixed("docstatus", "1", "integer"),
    ]
    return edits


def build_stock_entry_detail_internal() -> List[Dict[str, Any]]:
    return _stock_entry_detail("CATEINDOCDETT", "AL-SE")


def build_stock_entry_detail_division() -> List[Dict[str, Any]]:
    return _stock_entry_detail("DIVISIONDOCDETT", "AL-DIV")


def build_stock_reconciliation() -> List[Dict[str, Any]]:
    edits = renamed_with_drops("STOCKTAKINGT", {
        "STOCKID": ("docserial_legacy", "integer"),
        "SDATE": ("posting_date", "date"),
        "USEDATE": ("posting_time", "time"),
        "NOTES": ("remarks", "string"),
    })
    edits += [
        edit(
            "name", src_type="string", op="add",
            target_name="name", target_type="string", is_new=True,
            generator={"kind": "fixed", "value": ""},
            transforms=[{"op": "concat_template",
                         "params": {"template": "AL-STK-{docserial_legacy}"}}],
        ),
        fk_lookup("warehouse", "STORET", "DESCRIPTION",
                  "STOREID", "STOREID"),
        fixed("purpose", "Stock Reconciliation"),
        fixed("docstatus", "1", "integer"),
        fixed("company", DEFAULT_COMPANY),
    ]
    return edits


def build_stock_reconciliation_item() -> List[Dict[str, Any]]:
    edits = renamed_with_drops("STOCKTAKINGDETT", {
        "STOCKID": ("docno_legacy", "integer"),
        "SERIAL": ("idx_legacy", "integer"),
        "CATID": ("item_code", "string"),
        "CATQTY": ("qty", "decimal"),
        "COSTPRICE": ("valuation_rate", "decimal"),
    })
    edits += [
        edit(
            "parent", src_type="string", op="add",
            target_name="parent", target_type="string", is_new=True,
            generator={"kind": "fixed", "value": ""},
            transforms=[{"op": "concat_template",
                         "params": {"template": "AL-STK-{docno_legacy}"}}],
        ),
        from_col("idx", "idx_legacy"),
        fixed("parenttype", "Stock Reconciliation"),
        fixed("parentfield", "items"),
        fixed("docstatus", "1", "integer"),
    ]
    return edits


# ---------- BUILDERS — Journals (every flavor → tabJournal Entry) -----------


def _journal_entry_header(table: str, voucher_type: str, prefix: str) -> List[Dict[str, Any]]:
    edits = renamed_with_drops(table, {
        "DOCSERIAL": ("docserial_legacy", "integer"),
        "DOCDATE": ("posting_date", "date"),
        "DOCTIME": ("posting_time", "time"),
        "NOTES": ("user_remark", "string"),
        "DOCVALUE": ("total_debit", "decimal"),
        "DOCMVALUE": ("total_debit_base", "decimal"),
    })
    edits += [
        edit(
            "name", src_type="string", op="add",
            target_name="name", target_type="string", is_new=True,
            generator={"kind": "fixed", "value": ""},
            transforms=[{"op": "concat_template",
                         "params": {"template": prefix + "-{docserial_legacy}"}}],
        ),
        fixed("voucher_type", voucher_type),
        fixed("docstatus", "1", "integer"),
        fixed("company", DEFAULT_COMPANY),
        fixed("owner", DEFAULT_OWNER),
    ]
    return edits


def _journal_entry_account(table: str, prefix: str) -> List[Dict[str, Any]]:
    edits = renamed_with_drops(table, {
        "DOCNO": ("docno_legacy", "integer"),
        "SERIAL": ("idx_legacy", "integer"),
        "DEBIT": ("debit_in_account_currency", "decimal"),
        "CREDIT": ("credit_in_account_currency", "decimal"),
        "MDEBIT": ("debit", "decimal"),
        "MCREDIT": ("credit", "decimal"),
        "NOTES": ("user_remark", "string"),
    })
    edits += [
        edit(
            "parent", src_type="string", op="add",
            target_name="parent", target_type="string", is_new=True,
            generator={"kind": "fixed", "value": ""},
            transforms=[{"op": "concat_template",
                         "params": {"template": prefix + "-{docno_legacy}"}}],
        ),
        from_col("idx", "idx_legacy"),
        fk_lookup("account", "ACCOUNTT", "NAME",
                  "ACCOUNTID", "ACCOUNTID"),
        fk_lookup_chain(
            "account_currency", "ACCOUNTID",
            chain=[
                {"table": "ACCOUNTT", "match_column": "ACCOUNTID", "source_column": "CURID"},
                {"table": "CURT", "match_column": "CURID", "source_column": "CURSHORT"},
            ],
        ),
        fixed("parenttype", "Journal Entry"),
        fixed("parentfield", "accounts"),
        fixed("docstatus", "1", "integer"),
    ]
    return edits


def build_je_manual() -> List[Dict[str, Any]]:
    return _journal_entry_header("ENTRYDOCT", "Journal Entry", "AL-JE")


def build_jea_manual() -> List[Dict[str, Any]]:
    return _journal_entry_account("ENTRYDOCDETT", "AL-JE")


def build_je_opening() -> List[Dict[str, Any]]:
    return _journal_entry_header("STARTENTRYDOCT", "Opening Entry", "AL-OPN")


def build_jea_opening() -> List[Dict[str, Any]]:
    return _journal_entry_account("STARTENTRYDOCDETT", "AL-OPN")


def build_je_dnote() -> List[Dict[str, Any]]:
    return _journal_entry_header("DNOTEDOCT", "Debit Note", "AL-DN")


def build_jea_dnote() -> List[Dict[str, Any]]:
    return _journal_entry_account("DNOTEDOCDETT", "AL-DN")


def build_je_cnote() -> List[Dict[str, Any]]:
    return _journal_entry_header("CNOTEDOCT", "Credit Note", "AL-CN")


def build_jea_cnote() -> List[Dict[str, Any]]:
    return _journal_entry_account("CNOTEDOCDETT", "AL-CN")


def build_je_bank() -> List[Dict[str, Any]]:
    return _journal_entry_header("BANKENTRYDOCT", "Bank Entry", "AL-BNK")


def build_jea_bank() -> List[Dict[str, Any]]:
    return _journal_entry_account("BANKENTRYDOCDETT", "AL-BNK")


# ---------- BUILDERS — Payment Entries --------------------------------------


def _payment_doc_header(
    table: str, payment_type: str, prefix: str
) -> List[Dict[str, Any]]:
    edits = renamed_with_drops(table, {
        "DOCSERIAL": ("docserial_legacy", "integer"),
        "DOCDATE": ("posting_date", "date"),
        "DOCTIME": ("posting_time", "time"),
        "DOCVALUE": ("paid_amount", "decimal"),
        "DOCMVALUE": ("base_paid_amount", "decimal"),
        "CURVALUE": ("source_exchange_rate", "decimal"),
        "NOTES": ("remarks", "string"),
    })
    edits += [
        edit(
            "name", src_type="string", op="add",
            target_name="name", target_type="string", is_new=True,
            generator={"kind": "fixed", "value": ""},
            transforms=[{"op": "concat_template",
                         "params": {"template": prefix + "-{docserial_legacy}"}}],
        ),
        fixed("payment_type", payment_type),
        fixed("party_type",
              "Customer" if payment_type == "Receive" else "Supplier"),
        fixed("docstatus", "1", "integer"),
        fixed("company", DEFAULT_COMPANY),
        fixed("owner", DEFAULT_OWNER),
    ]
    return edits


def build_payment_receive() -> List[Dict[str, Any]]:
    return _payment_doc_header("RECDOCT", "Receive", "AL-REC")


def build_payment_pay() -> List[Dict[str, Any]]:
    return _payment_doc_header("PAYDOCT", "Pay", "AL-PAY")


def build_payment_pos() -> List[Dict[str, Any]]:
    """POSPAYST → Payment Entry. One row per (DOCSERIAL, DOCCLASS).

    Uses the new aggregate feature (group by DOCSERIAL+DOCCLASS, sum
    PAYAMOUNT) AND the new multi-hop FK (resolve party from POSPAYST →
    invoice → customer)."""
    edits = renamed_with_drops("POSPAYST", {
        "DOCSERIAL": ("docserial_legacy", "integer"),
        "DOCCLASS": ("docclass_legacy", "integer"),
        "PAYAMOUNT": ("paid_amount", "decimal"),
        "PAYAMOUNTM": ("base_paid_amount", "decimal"),
        "DESCR": ("remarks", "string"),
    })
    edits += [
        edit(
            "name", src_type="string", op="add",
            target_name="name", target_type="string", is_new=True,
            generator={"kind": "fixed", "value": ""},
            transforms=[{"op": "concat_template",
                         "params": {"template": "AL-POS-{docserial_legacy}"}}],
        ),
        # Multi-hop FK: POSPAYST.DOCSERIAL → invoice's ACCOUNTID → ACCOUNTT.NAME
        fk_lookup_chain(
            "party", "DOCSERIAL",
            chain=[
                {"table": "CATESINVDOCT", "match_column": "DOCSERIAL", "source_column": "ACCOUNTID"},
                {"table": "ACCOUNTT", "match_column": "ACCOUNTID", "source_column": "NAME"},
            ],
        ),
        fk_lookup_chain(
            "reference_doctype_invoice", "DOCSERIAL",
            chain=[
                {"table": "CATESINVDOCT", "match_column": "DOCSERIAL", "source_column": "DOCNO"},
            ],
        ),
        fixed("payment_type", "Receive"),
        fixed("party_type", "Customer"),
        fixed("docstatus", "1", "integer"),
        fixed("company", DEFAULT_COMPANY),
        fixed("owner", DEFAULT_OWNER),
    ]
    return edits


def build_cheques_in_flight() -> List[Dict[str, Any]]:
    """CHEQUET filtered to in-flight cheques → Payment Entry.

    Carries OWNERNAME, CBANK, CDATE etc. so when one bounces post-cutover
    the user can search by reference_no and find the writer / bank."""
    edits = renamed_with_drops("CHEQUET", {
        "CHEQUEID": ("docserial_legacy", "integer"),
        "CHEQUENO": ("reference_no", "string"),
        "CDATE": ("reference_date", "date"),
        "CVALUE": ("paid_amount", "decimal"),
        "CMVALUE": ("base_paid_amount", "decimal"),
        "CBANK": ("bank", "string"),
        "CBANKBRANCH": ("bank_branch", "string"),
        "BANKACC": ("bank_account_no", "string"),
        "OWNERNAME": ("party_name", "string"),
        "STATUS": ("status_legacy", "integer"),
    })
    edits += [
        edit(
            "name", src_type="string", op="add",
            target_name="name", target_type="string", is_new=True,
            generator={"kind": "fixed", "value": ""},
            transforms=[{"op": "concat_template",
                         "params": {"template": "AL-CHQ-{docserial_legacy}"}}],
        ),
        fk_lookup("party", "ACCOUNTT", "NAME",
                  "ACCOUNTID", "ACCOUNTID"),
        fixed("payment_type", "Receive"),
        fixed("party_type", "Customer"),
        fixed("mode_of_payment", "Cheque"),
        fixed("docstatus", "0", "integer"),  # Draft — not yet cleared
        fixed("company", DEFAULT_COMPANY),
        fixed("owner", DEFAULT_OWNER),
    ]
    return edits


# ---------- BUILDERS — Ledgers ----------------------------------------------


def build_gl_entry() -> List[Dict[str, Any]]:
    edits = renamed_with_drops("LEDGERT", {
        "ENTRYID": ("name", "string"),
        "ENTRYDEBIT": ("debit", "decimal"),
        "ENTRYCREDIT": ("credit", "decimal"),
        "ENTRYVALUE": ("debit_in_account_currency", "decimal"),
        "ENTRYTRANSDATE": ("posting_date", "date"),
        "INSERTDATE": ("creation", "datetime"),
        "DOCSERIAL": ("voucher_no", "string"),
        "DOCCLASS": ("voucher_type_code", "integer"),
        "PROJECTID": ("project", "integer"),
        "NOTES": ("remarks", "string"),
    })
    edits += [
        fk_lookup("account", "ACCOUNTT", "NAME",
                  "ACCOUNTID", "ENTRYACCOUNT"),
        fk_lookup("account_currency", "CURT", "CURSHORT",
                  "CURID", "ENTRYCUR"),
        fixed("is_opening", "No"),
        fixed("is_cancelled", "0", "integer"),
        fixed("docstatus", "1", "integer"),
        fixed("company", DEFAULT_COMPANY),
        fixed("owner", DEFAULT_OWNER),
    ]
    return edits


def build_stock_ledger_entry() -> List[Dict[str, Any]]:
    edits = renamed_with_drops("CATLEDGERT", {
        "ENTRYID": ("name", "string"),
        "CATID": ("item_code", "string"),
        "QTYIN": ("actual_qty_in", "decimal"),
        "QTYOUT": ("actual_qty_out", "decimal"),
        "QTYBALANCE": ("qty_after_transaction", "decimal"),
        "TRANSDATE": ("posting_date", "date"),
        "INSERTDATE": ("creation", "datetime"),
        "DOCSERIAL": ("voucher_no", "string"),
        "DOCCLASS": ("voucher_type_code", "integer"),
        "COSTPRICE": ("valuation_rate", "decimal"),
        "TRANSCURID": ("currency_legacy", "integer"),
    })
    edits += [
        fk_lookup("warehouse", "STORET", "DESCRIPTION",
                  "STOREID", "STOREID"),
        # actual_qty = QTYIN - QTYOUT
        computed("actual_qty",
                 "{actual_qty_in} - {actual_qty_out}", round_=4),
        fixed("is_cancelled", "0", "integer"),
        fixed("docstatus", "1", "integer"),
        fixed("company", DEFAULT_COMPANY),
        fixed("owner", DEFAULT_OWNER),
    ]
    return edits


# ---------- focus map -------------------------------------------------------

# Each entry: source_table → (target_table, builder).
# When two sources share the same target, the transformer UNIONs them.
FOCUS = {
    # Lookups & seeds
    "CURT": ("currency", build_currency),
    "UNITT": ("uom", build_uom),
    "PRICETYPET": ("price_list", build_price_list),
    "CATBASICSETST": ("item_group", build_item_group),
    "STORET": ("warehouse", build_warehouse),
    "SALEPOINTT": ("pos_profile", build_pos_profile),
    "IMPORTCOSTCENTERT": ("cost_center", build_cost_center),
    "PROJECTST": ("project", build_project),
    "BANKT": ("bank", build_bank),
    "BANKACCOUNTT": ("bank_account", build_bank_account),

    # Items
    "CATEGORYT": ("item", build_item),
    "CATESYNONYMT": ("item_barcode", build_item_barcode_from_synonyms),
    "CATPRICET": ("item_price", build_item_price),
    "CATSTORET": ("bin", build_bin),
    "CATSUPPLIERT": ("item_supplier", build_item_supplier),

    # Parties
    "CUSTT": ("customer", build_customer),
    "SUPPLIERT": ("supplier", build_supplier),
    "CONTACTST": ("address", build_address),

    # HR
    "EMPLOYEET": ("employee", build_employee),

    # Chart of accounts
    "ACCOUNTT": ("account", build_account),

    # Documents — sales (regular + return UNIONed into same target)
    "CATESINVDOCT": ("sales_invoice", build_sales_invoice),
    "CATESINVDOCDETT": ("sales_invoice_item", build_sales_invoice_item),
    "CATESRETINVDOCT": ("sales_invoice", build_sales_return_header),
    "CATESRETINVDOCDETT": ("sales_invoice_item", build_sales_return_item),

    # Documents — purchases
    "CATEPINVDOCT": ("purchase_invoice", build_purchase_invoice),
    "CATEPINVDOCDETT": ("purchase_invoice_item", build_purchase_invoice_item),
    "CATEPRETINVDOCT": ("purchase_invoice", build_purchase_return_header),
    "CATEPRETINVDOCDETT": ("purchase_invoice_item", build_purchase_return_item),

    # Stock
    "CATEINDOCT": ("stock_entry", build_stock_entry_internal),
    "CATEINDOCDETT": ("stock_entry_detail", build_stock_entry_detail_internal),
    "DIVISIONDOCT": ("stock_entry", build_stock_entry_division),
    "DIVISIONDOCDETT": ("stock_entry_detail", build_stock_entry_detail_division),
    "STOCKTAKINGT": ("stock_reconciliation", build_stock_reconciliation),
    "STOCKTAKINGDETT": ("stock_reconciliation_item", build_stock_reconciliation_item),

    # Journals — every flavor lands in the same target table, distinguished
    # by voucher_type
    "ENTRYDOCT": ("journal_entry", build_je_manual),
    "ENTRYDOCDETT": ("journal_entry_account", build_jea_manual),
    "STARTENTRYDOCT": ("journal_entry", build_je_opening),
    "STARTENTRYDOCDETT": ("journal_entry_account", build_jea_opening),
    "DNOTEDOCT": ("journal_entry", build_je_dnote),
    "DNOTEDOCDETT": ("journal_entry_account", build_jea_dnote),
    "CNOTEDOCT": ("journal_entry", build_je_cnote),
    "CNOTEDOCDETT": ("journal_entry_account", build_jea_cnote),
    "BANKENTRYDOCT": ("journal_entry", build_je_bank),
    "BANKENTRYDOCDETT": ("journal_entry_account", build_jea_bank),

    # Payments — receive + pay + POS UNIONed into payment_entry
    "RECDOCT": ("payment_entry", build_payment_receive),
    "PAYDOCT": ("payment_entry", build_payment_pay),
    "POSPAYST": ("payment_entry", build_payment_pos),

    # Cheques in flight (separate config target also payment_entry)
    "CHEQUET": ("payment_entry", build_cheques_in_flight),

    # Ledgers
    "LEDGERT": ("gl_entry", build_gl_entry),
    "CATLEDGERT": ("stock_ledger_entry", build_stock_ledger_entry),
}


def all_legacy_tables() -> List[str]:
    if not LEGACY_DATA_DIR.exists():
        return []
    return sorted(p.stem for p in LEGACY_DATA_DIR.glob("*.csv"))


def is_dropped(table: str) -> bool:
    return table not in FOCUS


# ---------- assemble --------------------------------------------------------


def build() -> Dict[str, Any]:
    edits: Dict[str, List[Dict[str, Any]]] = {}
    table_names: Dict[str, str] = {}
    table_options: Dict[str, Dict[str, Any]] = {}
    extra_configs: List[Dict[str, Any]] = []

    legacy_tables = all_legacy_tables()
    if not legacy_tables:
        sys.stderr.write(
            f"WARN: no CSVs found at {LEGACY_DATA_DIR}; preset will be "
            f"based on the FOCUS list and may miss column-specific drops.\n"
        )

    for legacy, (target, builder) in FOCUS.items():
        edits[legacy] = builder()
        table_names[legacy] = target

    # ---------- table_options: per-source extras --------------------------

    # Item filter: only active products
    table_options["CATEGORYT"] = {
        "row_filter": {
            "mode": "drop",
            "conditions": [{"column": "CACTIVE", "op": "eq", "value": "0"}],
        },
        # tabItem depends on tabUOM, tabItem Group, tabBrand, tabWarehouse
        "load_after": ["uom", "item_group", "brand", "warehouse"],
    }
    # Customer filter: drop walk-ins ("غير محدد")
    table_options["CUSTT"] = {
        "row_filter": {
            "mode": "drop",
            "conditions": [{"column": "customer_name", "op": "eq", "value": WALK_IN_NAME}],
        },
    }
    # Account self-reference declaration (loader sorts within tabAccount)
    table_options["ACCOUNTT"] = {
        "self_reference_parent_column": "parent_account",
        "load_after": ["currency"],
    }
    # POSPAYST aggregation: one Payment Entry per receipt with summed amount
    table_options["POSPAYST"] = {
        "aggregate": {
            "group_by": ["DOCSERIAL", "DOCCLASS"],
            "aggregations": {
                "PAYAMOUNT": "sum",
                "PAYAMOUNTM": "sum",
                "DESCR": "first",
            },
        },
    }
    # Cheques in flight: filter to status that means "not yet cleared"
    # Legacy STATUS codes vary; defensively keep "in hand" / "deposited"
    # rows. The user can adjust this filter post-import.
    table_options["CHEQUET"] = {
        "row_filter": {
            "mode": "keep",
            "conditions": [
                {"column": "CHEQUEBACK", "op": "ne", "value": "1"},
            ],
        },
    }
    # Sales / Purchase invoices: ensure customer/supplier exist before invoice
    table_options["CATESINVDOCT"] = {"load_after": ["customer", "warehouse"]}
    table_options["CATESINVDOCDETT"] = {"load_after": ["sales_invoice", "item"]}
    table_options["CATESRETINVDOCT"] = {"load_after": ["customer", "warehouse"]}
    table_options["CATESRETINVDOCDETT"] = {"load_after": ["sales_invoice", "item"]}
    table_options["CATEPINVDOCT"] = {"load_after": ["supplier", "warehouse"]}
    table_options["CATEPINVDOCDETT"] = {"load_after": ["purchase_invoice", "item"]}
    table_options["CATEPRETINVDOCT"] = {"load_after": ["supplier", "warehouse"]}
    table_options["CATEPRETINVDOCDETT"] = {"load_after": ["purchase_invoice", "item"]}
    # GL Entry depends on Account
    table_options["LEDGERT"] = {"load_after": ["account", "currency"]}
    table_options["CATLEDGERT"] = {"load_after": ["item", "warehouse"]}

    # ---------- extra_configs: additional outputs from one source ---------

    # CATEGORYT also produces (a) primary barcode rows for tabItem Barcode,
    # (b) tabBrand seed rows via DISTINCT MANUFACTURER, (c) tabItem Default
    # rows per item.
    # Filter inactive items out of every CATEGORYT-derived output, not
    # just the primary tabItem mapping. Otherwise discontinued items leak
    # into tabItem Barcode / tabItem Default as orphans (their parent
    # tabItem row was dropped).
    inactive_filter = {
        "mode": "drop",
        "conditions": [{"column": "CACTIVE", "op": "eq", "value": "0"}],
    }
    extra_configs.append({
        "source": "CATEGORYT",
        "target": "item_barcode",
        "edits": build_item_barcode_from_categoryt(),
        "row_filter": inactive_filter,
    })
    extra_configs.append({
        "source": "CATEGORYT",
        "target": "brand",
        "edits": build_brand_from_categoryt(),
        "aggregate": {"group_by": ["MANUFACTURER"]},
        "row_filter": {
            "mode": "drop",
            "conditions": [{"column": "MANUFACTURER", "op": "is_null", "value": None}],
        },
    })
    extra_configs.append({
        "source": "CATEGORYT",
        "target": "item_default",
        "edits": build_item_default_from_categoryt(),
        "load_after": ["item", "warehouse", "account"],
        "row_filter": inactive_filter,
    })

    # CONTACTST also produces tabContact and tabDynamic Link
    extra_configs.append({
        "source": "CONTACTST",
        "target": "contact",
        "edits": build_contact_from_contactst(),
    })
    extra_configs.append({
        "source": "CONTACTST",
        "target": "dynamic_link",
        "edits": build_dynamic_link_from_contactst(),
        "load_after": ["address", "customer"],
    })

    # POSPAYST also produces tabMode of Payment seed (DISTINCT PAYTYPE)
    extra_configs.append({
        "source": "POSPAYST",
        "target": "mode_of_payment",
        "edits": build_mode_of_payment_from_pospayst(),
        "aggregate": {"group_by": ["PAYTYPE"]},
    })

    # ---------- everything else gets dropped ------------------------------

    dropped = sorted(t for t in legacy_tables if is_dropped(t))

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
        "_notes": [
            "Default reconcile call for /api/reconcile:",
            "{",
            "  \"gl_table\": \"gl_entry\",",
            "  \"invoice_specs\": [",
            "    {\"invoice_table\": \"sales_invoice\", \"line_table\": \"sales_invoice_item\", \"label\": \"sales\"},",
            "    {\"invoice_table\": \"purchase_invoice\", \"line_table\": \"purchase_invoice_item\", \"label\": \"purchases\"}",
            "  ],",
            "  \"fk_specs\": [",
            "    {\"child\": \"sales_invoice_item\", \"parent\": \"sales_invoice\", \"child_field\": \"parent\"},",
            "    {\"child\": \"purchase_invoice_item\", \"parent\": \"purchase_invoice\", \"child_field\": \"parent\"},",
            "    {\"child\": \"item_barcode\", \"parent\": \"item\", \"child_field\": \"parent\"},",
            "    {\"child\": \"item_price\", \"parent\": \"item\", \"child_field\": \"item_code\"},",
            "    {\"child\": \"bin\", \"parent\": \"item\", \"child_field\": \"item_code\"},",
            "    {\"child\": \"journal_entry_account\", \"parent\": \"journal_entry\", \"child_field\": \"parent\"},",
            "    {\"child\": \"stock_entry_detail\", \"parent\": \"stock_entry\", \"child_field\": \"parent\"},",
            "    {\"child\": \"stock_reconciliation_item\", \"parent\": \"stock_reconciliation\", \"child_field\": \"parent\"}",
            "  ]",
            "}",
        ],
    }


def main() -> int:
    PRESET_PATH.parent.mkdir(parents=True, exist_ok=True)
    preset = build()
    PRESET_PATH.write_text(
        json.dumps(preset, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    targets = sorted(set(preset["table_names"].values()))
    extras = sorted({x["target"] for x in preset["extra_configs"]})
    print(f"Wrote {PRESET_PATH}")
    print(f"  primary outputs : {len(set(preset['table_names'].values()))}")
    print(f"  extra outputs   : {len(extras)} ({', '.join(extras)})")
    print(f"  source mappings : {len(preset['edits'])}")
    print(f"  dropped sources : {len(preset['dropped_tables'])}")
    print(f"  table_options   : {len(preset['table_options'])}")
    print()
    print("ERPnext target tables:")
    for t in targets:
        print(f"   - {t}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
