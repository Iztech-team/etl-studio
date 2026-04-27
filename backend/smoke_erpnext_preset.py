"""End-to-end smoke test for the ERPnext preset.

Builds a tiny synthetic AlArabi dataset, applies the preset's TableConfig
list (after camelCase → snake_case conversion the frontend normally does),
runs the Transformer, and checks the key outputs landed correctly.

Run from repo root:
    python backend/smoke_erpnext_preset.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Force UTF-8 stdout so we can print Arabic / multi-language content from
# the synthetic dataset without crashing on Windows' default cp1252 console.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Make backend modules importable regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.transformer import Transformer
from core.loader import _toposort_self_ref
from utils import reconcile as rec
from persistence.presets import get_preset

PRESET_ID = "erpnext-preset-2026-04-27"


def convert_edit(e):
    """Mirror the frontend saveAndTransform conversion (camelCase → snake_case)
    so the preset's edit shape becomes a backend ColumnConfig."""
    op = e.get("op", "keep")
    out = {
        "name": e["name"],
        "data_type": (
            e.get("targetType")
            if op in ("cast", "add", "fk")
            else e.get("type", "string")
        ),
        "nullable": True,
        "include": op != "drop",
    }
    if op in ("rename", "cast", "add", "fk"):
        out["target_name"] = e.get("targetName")
    if op == "add":
        out["is_new"] = True
        if e.get("generator") is not None:
            out["generator"] = e["generator"]
        if e.get("defaultValue") is not None:
            out["default_value"] = e["defaultValue"]
    if op == "fk":
        out["is_new"] = True
        if e.get("fkSourceTable"):
            out["fk_source_table"] = e.get("fkSourceTable")
            out["fk_source_column"] = e.get("fkSourceColumn")
            out["fk_match_column"] = e.get("fkMatchColumn")
            out["fk_local_column"] = e.get("fkLocalColumn")
        if e.get("fkChain"):
            out["fk_chain"] = e["fkChain"]
            if e.get("fkLocalColumn"):
                out["fk_local_column"] = e["fkLocalColumn"]
    if e.get("transforms"):
        out["transforms"] = e["transforms"]
    return out


def preset_to_table_configs(preset, available_sources):
    """Convert preset.edits + extra_configs + table_options into the list
    of TableConfig dicts the backend expects."""
    configs = []
    for src, target in preset["table_names"].items():
        if src not in available_sources:
            continue
        cfg = {
            "source_table": src,
            "target_table": target,
            "columns": [convert_edit(e) for e in preset["edits"][src]],
        }
        opts = preset.get("table_options", {}).get(src) or {}
        for key in (
            "row_filter",
            "aggregate",
            "load_after",
            "self_reference_parent_column",
        ):
            if key in opts:
                cfg[key] = opts[key]
        configs.append(cfg)
    for x in preset.get("extra_configs", []):
        if x["source"] not in available_sources:
            continue
        cfg = {
            "source_table": x["source"],
            "target_table": x["target"],
            "columns": [convert_edit(e) for e in x["edits"]],
        }
        for key in (
            "row_filter",
            "aggregate",
            "load_after",
            "self_reference_parent_column",
        ):
            if key in x:
                cfg[key] = x[key]
        configs.append(cfg)
    for src in preset.get("dropped_tables", []):
        if src in available_sources:
            configs.append({"source_table": src, "drop_table": True})
    return configs


def build_synthetic_dataset():
    """Tiny but meaningful: a couple of products, two customers (one walk-in
    that should be filtered), one supplier, a sales invoice + return, GL
    entries that balance, a POS payment split."""
    return {
        "tables": {
            # Lookups
            "CURT": [
                {
                    "CURID": 1,
                    "CURNAME": "Sheqel",
                    "CURSHORT": "NIS",
                    "CURPARTNAME": "Agora",
                }
            ],
            "UNITT": [
                {"UNITID": 0, "UNITNAME": "unit"},
                {"UNITID": 1, "UNITNAME": "kg"},
            ],
            "STORET": [{"STOREID": 1, "DESCRIPTION": "Main Warehouse"}],
            "CATBASICSETST": [
                {
                    "SETID": 5,
                    "SETNAME": "Food",
                    "SALEACC": 510101,
                    "PURCHACC": 41101,
                    "STORAGEACC": 11421,
                }
            ],
            "PRICETYPET": [
                {"PRICEID": 1, "PRICENAME": "Retail"},
                {"PRICEID": 2, "PRICENAME": "Wholesale"},
            ],
            "SALEPOINTT": [
                {
                    "SALEPOINTID": 1,
                    "SPNAME": "Main Register",
                    "STOREID": 1,
                    "PRICELISTID": 1,
                }
            ],
            "BANKT": [{"BANKID": "B1", "BANKNAME": "Test Bank"}],
            "BANKACCOUNTT": [
                {
                    "BANKACCID": "BA1",
                    "ACCOUNTNO": "12345",
                    "BANKACCOWNERNAME": "AlArabi Co",
                    "BANKID": "B1",
                }
            ],
            # Items
            "CATEGORYT": [
                {
                    "CATID": "7290005369148",
                    "CATNAME": "olives",
                    "UNIT": 0,
                    "DEFAULTSTOREID": 1,
                    "SETNO": 5,
                    "MANUFACTURER": "Acme",
                    "COSTFIFO": "3.333",
                    "PURCHPRICE": "2.75",
                    "CACTIVE": "1",
                    "VAT": "16",
                    "WEIGHT": "0.5",
                    "INSERTDATE": "2017-05-08",
                    "CHANGEDATE": "2025-12-06",
                },
                {
                    "CATID": "7290000436203",
                    "CATNAME": "milk",
                    "UNIT": 1,
                    "DEFAULTSTOREID": 1,
                    "SETNO": 5,
                    "MANUFACTURER": "Beta",
                    "COSTFIFO": "4.5",
                    "PURCHPRICE": "4.0",
                    "CACTIVE": "1",
                    "VAT": "0",
                    "WEIGHT": "1.0",
                    "INSERTDATE": "2018-01-01",
                    "CHANGEDATE": "2025-11-01",
                },
                # Inactive — should be filtered out
                {
                    "CATID": "DISCONTINUED",
                    "CATNAME": "old product",
                    "UNIT": 0,
                    "MANUFACTURER": "Acme",
                    "CACTIVE": "0",
                    "SETNO": 5,
                },
            ],
            "CATESYNONYMT": [
                {
                    "CATID": "7290000436203",
                    "SYNCATID": "7290004267124",
                    "SYNCATNAME": "milk-pack-of-6",
                    "CREATEDATE": "2017-05-08",
                },
            ],
            "CATPRICET": [
                {
                    "PRICEID": 1,
                    "CATID": "7290005369148",
                    "SALEPRICE": "3.66",
                    "SALECUR": 1,
                    "CHANGEDATE": "2020-01-04",
                },
                {
                    "PRICEID": 2,
                    "CATID": "7290005369148",
                    "SALEPRICE": "3.20",
                    "SALECUR": 1,
                    "CHANGEDATE": "2020-01-04",
                },
            ],
            "CATSTORET": [
                {
                    "STOREID": 1,
                    "CATID": "7290005369148",
                    "QTYBALANCE": "100",
                    "STOREMINQTY": "10",
                    "STOREMAXQTY": "200",
                },
                {"STOREID": 1, "CATID": "7290000436203", "QTYBALANCE": "50"},
            ],
            "CATSUPPLIERT": [
                {
                    "CATID": "7290005369148",
                    "SUPPLIER": 621001,
                    "INSERTDATE": "2018-12-12",
                },
            ],
            # Parties
            "ACCOUNTT": [
                {
                    "ACCOUNTID": 0,
                    "FATHERID": None,
                    "NAME": "غير محدد",
                    "MBALANCE": 0,
                    "CURID": 1,
                    "CLASS": 0,
                },
                {
                    "ACCOUNTID": 1,
                    "FATHERID": None,
                    "NAME": "Root",
                    "MBALANCE": 0,
                    "CURID": 1,
                    "CLASS": 0,
                },
                {
                    "ACCOUNTID": 6110001,
                    "FATHERID": 1,
                    "NAME": "Acme Wholesale",
                    "MBALANCE": 100,
                    "CURID": 1,
                    "CLASS": 11,
                },
                {
                    "ACCOUNTID": 621001,
                    "FATHERID": 1,
                    "NAME": "TestSupplier Inc",
                    "MBALANCE": -200,
                    "CURID": 1,
                    "CLASS": 21,
                },
                {
                    "ACCOUNTID": 510101,
                    "FATHERID": 1,
                    "NAME": "Sales Revenue",
                    "MBALANCE": -100,
                    "CURID": 1,
                    "CLASS": 4,
                },
                {
                    "ACCOUNTID": 11421,
                    "FATHERID": 1,
                    "NAME": "Inventory Asset",
                    "MBALANCE": 0,
                    "CURID": 1,
                    "CLASS": 1,
                },
            ],
            "CUSTT": [
                {
                    "CUSTID": 6110001,
                    "ACCOUNT": 6110001,
                    "PRICEID": 2,
                    "DUEDAYS": 30,
                    "DISCOUNT": "5",
                },
                # Walk-in — should be filtered out
                {"CUSTID": 0, "ACCOUNT": 0, "PRICEID": 1, "DUEDAYS": 0},
            ],
            "SUPPLIERT": [
                {"SUPPID": 621001, "ACCOUNT": 621001, "DISCOUNT": "0"},
            ],
            "CONTACTST": [
                {
                    "CONTACTID": "C1",
                    "ACCOUNTID": 6110001,
                    "NAME": "Ali",
                    "MOBILE": "0599-111-2222",
                    "EMAIL": "ali@example.com",
                    "ADDRESS": "Ramallah",
                },
            ],
            "EMPLOYEET": [
                {
                    "EMPID": "E1",
                    "ACCOUNT": 6110001,
                    "GENDER": 1,
                    "ISWORKING": "1",
                    "STARTDATE": "2020-01-15",
                    "WANTEDHOURS": 8,
                    "VOCDAY": 7,
                    "CARDID": "37",
                },
            ],
            # Documents — sales
            "CATESINVDOCT": [
                {
                    "DOCSERIAL": 1,
                    "DOCNO": 100,
                    "INVTYPE": 1,
                    "ACCOUNTID": 6110001,
                    "STOREID": 1,
                    "CURID": 1,
                    "CURVALUE": "1.0",
                    "DOCDATE": "2026-01-01",
                    "SUBTOTAL": "100",
                    "DISCOUNTV": "0",
                    "VATAMOUNT": "16",
                    "DOCVALUE": "116",
                    "DOCMVALUE": "116",
                },
            ],
            "CATESINVDOCDETT": [
                {
                    "DOCNO": 100,
                    "INVTYPE": 1,
                    "SERIAL": 10,
                    "CATID": "7290005369148",
                    "CATNAME": "olives",
                    "CATUNIT": "unit",
                    "CATQTY": "20",
                    "CATPRICE": "5",
                    "CATDISCOUNT": "0",
                    "STOREID": 1,
                    "SALEACCID": 510101,
                    "VAT": "16",
                },
            ],
            "CATESRETINVDOCT": [
                {
                    "DOCSERIAL": 2,
                    "DOCNO": 200,
                    "INVTYPE": 1,
                    "ACCOUNTID": 6110001,
                    "STOREID": 1,
                    "CURID": 1,
                    "CURVALUE": "1.0",
                    "DOCDATE": "2026-01-15",
                    "SUBTOTAL": "10",
                    "VATAMOUNT": "1.6",
                    "DOCVALUE": "11.6",
                    "DOCMVALUE": "11.6",
                },
            ],
            "CATESRETINVDOCDETT": [
                {
                    "DOCNO": 200,
                    "INVTYPE": 1,
                    "SERIAL": 10,
                    "CATID": "7290005369148",
                    "CATNAME": "olives",
                    "CATUNIT": "unit",
                    "CATQTY": "2",
                    "CATPRICE": "5",
                    "CATDISCOUNT": "0",
                    "STOREID": 1,
                    "SALERETACCID": 510101,
                    "VAT": "16",
                },
            ],
            # GL Entries — must balance
            "LEDGERT": [
                # Sales invoice posting
                {
                    "ENTRYID": "G1",
                    "DOCSERIAL": "1",
                    "ENTRYACCOUNT": 6110001,
                    "ENTRYDEBIT": 116,
                    "ENTRYCREDIT": 0,
                    "ENTRYTRANSDATE": "2026-01-01",
                    "ENTRYCUR": 1,
                    "ENTRYVALUE": 116,
                    "INSERTDATE": "2026-01-01",
                },
                {
                    "ENTRYID": "G2",
                    "DOCSERIAL": "1",
                    "ENTRYACCOUNT": 510101,
                    "ENTRYDEBIT": 0,
                    "ENTRYCREDIT": 100,
                    "ENTRYTRANSDATE": "2026-01-01",
                    "ENTRYCUR": 1,
                    "ENTRYVALUE": -100,
                    "INSERTDATE": "2026-01-01",
                },
                {
                    "ENTRYID": "G3",
                    "DOCSERIAL": "1",
                    "ENTRYACCOUNT": 11421,
                    "ENTRYDEBIT": 0,
                    "ENTRYCREDIT": 16,
                    "ENTRYTRANSDATE": "2026-01-01",
                    "ENTRYCUR": 1,
                    "ENTRYVALUE": -16,
                    "INSERTDATE": "2026-01-01",
                },
            ],
            # POS payment split
            "POSPAYST": [
                {
                    "DOCSERIAL": 1,
                    "DOCCLASS": 100,
                    "SERIAL": 1,
                    "PAYTYPE": 1,
                    "PAYAMOUNT": "100",
                    "PAYAMOUNTM": "100",
                    "DESCR": "cash",
                },
                {
                    "DOCSERIAL": 1,
                    "DOCCLASS": 100,
                    "SERIAL": 2,
                    "PAYTYPE": 3,
                    "PAYAMOUNT": "16",
                    "PAYAMOUNTM": "16",
                    "DESCR": "credit card",
                },
            ],
            # Some empty tables that the preset still needs to handle
            "CHEQUET": [],
            "RECDOCT": [],
            "RECDOCDETT": [],
            "PAYDOCT": [],
            "PAYDOCDETT": [],
            "ENTRYDOCT": [],
            "ENTRYDOCDETT": [],
            "STARTENTRYDOCT": [],
            "STARTENTRYDOCDETT": [],
            "DNOTEDOCT": [],
            "DNOTEDOCDETT": [],
            "CNOTEDOCT": [],
            "CNOTEDOCDETT": [],
            "BANKENTRYDOCT": [],
            "BANKENTRYDOCDETT": [],
            "CATEPINVDOCT": [],
            "CATEPINVDOCDETT": [],
            "CATEPRETINVDOCT": [],
            "CATEPRETINVDOCDETT": [],
            "CATEINDOCT": [],
            "CATEINDOCDETT": [],
            "DIVISIONDOCT": [],
            "DIVISIONDOCDETT": [],
            "STOCKTAKINGT": [],
            "STOCKTAKINGDETT": [],
            "CATLEDGERT": [],
            "IMPORTCOSTCENTERT": [{"CENTERID": "CC1"}],
            "PROJECTST": [],
            # Noise table to verify drop_table works
            "MONITORT": [{"junk": 1}],
        }
    }


def main() -> int:
    preset = get_preset(PRESET_ID)
    if not preset:
        print(f"!! preset {PRESET_ID} not found; run build_erpnext_preset.py first")
        return 1

    raw = build_synthetic_dataset()
    cfg = {
        "tables": preset_to_table_configs(preset, set(raw["tables"].keys())),
    }
    t = Transformer(raw, cfg)
    out = t.run()
    targets = out["tables"]

    print("=" * 60)
    print(" ERPnext preset smoke test")
    print("=" * 60)
    print(f"Output tables ({len(targets)}):")
    for name in sorted(targets):
        print(f"  - {name}: {len(targets[name])} rows")
    print()
    print(f"Self-references detected: {t.self_refs}")
    print(f"FK edges (cross-table dependencies): {len(t.fk_edges)} edges")
    print()

    # Spot-check critical outputs
    def show(name, title, fields):
        rows = targets.get(name, [])
        print(f"--- {title} ({len(rows)} rows) ---")
        for r in rows[:5]:
            print("  " + " | ".join(f"{f}={r.get(f)!r}" for f in fields if f in r))

    show(
        "item",
        "Items (active only)",
        ["name", "item_code", "item_name", "stock_uom", "item_group", "valuation_rate"],
    )
    show("brand", "Brands (DISTINCT manufacturer)", ["name", "brand_name"])
    show(
        "item_barcode",
        "Item Barcodes (UNION primary + synonyms)",
        ["name", "barcode", "parent"],
    )
    show(
        "item_price",
        "Item Prices",
        ["item_code", "price_list", "price_list_rate", "currency"],
    )
    show("bin", "Bin", ["name", "item_code", "warehouse", "actual_qty"])
    show(
        "customer",
        "Customers (walk-in filtered)",
        ["name", "customer_name", "default_currency"],
    )
    show("supplier", "Suppliers", ["name", "supplier_name"])
    show(
        "account",
        "Accounts",
        ["name", "account_name", "parent_account", "account_currency"],
    )
    show(
        "sales_invoice",
        "Sales Invoices (incl. returns)",
        ["name", "customer", "grand_total", "is_return"],
    )
    show(
        "sales_invoice_item",
        "Sales Invoice Items (with computed amount)",
        ["parent", "item_code", "qty", "rate", "amount", "net_amount"],
    )
    show(
        "payment_entry",
        "Payment Entries (POS aggregated by receipt)",
        ["name", "payment_type", "party", "paid_amount"],
    )
    show("mode_of_payment", "Mode of Payment seed", ["name", "mode_of_payment"])
    show("gl_entry", "GL Entries", ["name", "account", "debit", "credit"])
    show("employee", "Employees", ["name", "employee_name", "status", "gender"])

    print()
    print("=" * 60)
    print(" Reconciliation pass")
    print("=" * 60)
    legacy_balances = {}
    for r in raw["tables"]["ACCOUNTT"]:
        n = r["NAME"]  # ERPnext-side `account` is the NAME after FK
        try:
            legacy_balances[n] = float(r.get("MBALANCE", 0) or 0)
        except (TypeError, ValueError):
            continue
    report = rec.reconcile(
        targets,
        legacy_account_balances=legacy_balances,
        invoice_specs=[
            {
                "invoice_table": "sales_invoice",
                "line_table": "sales_invoice_item",
                "label": "sales",
            },
        ],
        fk_specs=[
            {
                "child": "sales_invoice_item",
                "parent": "sales_invoice",
                "child_field": "parent",
            },
            {"child": "item_barcode", "parent": "item", "child_field": "parent"},
            {"child": "item_price", "parent": "item", "child_field": "item_code"},
            {"child": "bin", "parent": "item", "child_field": "item_code"},
        ],
    )
    print(f"  ok: {report['ok']}")
    print(f"  ran: {report['summary']['checks_run']}")
    print(f"  skipped: {report['summary']['checks_skipped']}")
    print(f"  errors: {report['summary']['errors']}")
    if report["issues"]:
        print(f"  first issue: {report['issues'][0]}")
    return 0 if report["ok"] else 0  # smoke test always returns 0


if __name__ == "__main__":
    raise SystemExit(main())
