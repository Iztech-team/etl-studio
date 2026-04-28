# Al Arabi → ERPnext: Strategy Design & Mapping Plan

Comprehensive mapping after deep inspection of all 137 legacy CSVs and the ERPnext doctype reference. This is the implementation contract for the `erpnext` strategy.

---

## Goals & Constraints

- **Strategy design pattern.** Same legacy input → multiple output schemas. First strategy: ERPnext.
- **Target: ERPnext v16.** Doctype field names used here (`item_code`, `customer_name`, `barcodes`, `parent_account`, `is_return`, `update_stock`, `docstatus`, etc.) have been stable since ~v12 and work on v16. Will verify required-field flags against the `frappe/erpnext` v16 branch JSON files at implementation time. Architecture is version-stable; only field-level details may need a check.
- **Output target: Frappe Data Import CSVs** (one CSV per doctype, parent + child rows interleaved per Frappe convention). User loads them via the ERPnext UI Data Import or `bench import-csv` in dependency order. **No direct DB inserts** — bypassing Frappe controllers breaks autoname, GL Entry generation on submit, Stock Ledger Entry creation, validation hooks, and docstatus workflow.
- **Frappe Data Import: confirmed works for our case.** Supports UTF-8 (Arabic), parent+child flat CSVs, Submit-After-Import for transactions, custom doctypes (for Legacy Cheque), Insert/Update modes. Soft recommendation is "few thousand rows per file"; 50K+ degrades active users' performance. **Sales Invoice is the only volume problem** (146K headers, 1M+ lines) — strategy emits pre-chunked CSVs (~5K headers each, ~26 batches) sized for either the UI or `bench import-csv` CLI. Other doctypes fit in 1–2 files.
- **Single PR scope** ("strategy"). All Tier-1 doctypes in one delivery, no artificial slicing.
- **Preserve business value, drop noise.** Skip logging, replication snapshots, UI configuration, deleted-row archives.
- **No taxes for v1.** VAT amounts on legacy invoices are not emitted as Sales/Purchase Taxes child rows. Tax handling deferred — admin can add tax templates and reprocess if needed.
- **Arabic-first language.** ACCOUNTT.NAME (Ar) is populated 100%, NAMEE (En) only 0.2%, NAMEH (He) ~0%. Falling back to English would lose virtually everything. Use `NAME or NAMEE or NAMEH` chain.
- **Monocurrency.** All 146K sales + 2.5K purchase invoices are CURID=1 (NIS / Israeli Shekel). All ACCOUNTT roots CURID=1. Set company currency to **ILS** (ISO code; legacy uses "NIS" which isn't ISO). conversion_rate=1.0 across the board. Multi-currency deferred.
- **Allow Negative Stock = ON.** Strategy config requires Stock Settings → Allow Negative Stock to be enabled before Stock Reconciliation import. ERPnext explicitly designs this flag for the "sale-before-receipt" scenario that legacy data exhibits. Affects 955 items with negative opening stock (using `STARTQTY` as the true opening, not `QTYBALANCE`).

---

## Strategy Plumbing

```
backend/core/strategies/
  __init__.py            # STRATEGIES registry, get_strategy(name)
  base.py                # TransformStrategy ABC, StrategyResult dataclass
  erpnext/
    __init__.py          # ErpnextStrategy class — orchestrates child modules
    masters.py           # Currency lookup, UOM, Warehouse, Item Group, etc.
    items.py             # Item + barcodes + uoms + supplier_items
    parties.py           # Customer + Supplier (phones denormalized in)
    accounts.py          # Account (Chart of Accounts)
    invoices.py          # Sales Invoice + Purchase Invoice (incl. returns)
    payments.py          # Payment Entry from RECDOCT/PAYDOCT
    journals.py          # Journal Entry from ENTRYDOCT, Opening JE from STARTENTRYDOCT
    stock_moves.py       # Stock Reconciliation (opening), Stock Entry (transfers)
    common.py            # multilingual pick, ID generators, Frappe CSV writer
```

### Interface

```python
@dataclass
class StrategyResult:
    output_tables: dict[str, list[dict]]   # {"Item": [...], "Sales Invoice": [...]}
    warnings: list[dict]                   # {table, row, message}
    errors: list[dict]                     # {table, row, error} — row dropped
    stats: dict[str, int]                  # {"items_emitted": ..., "skipped_no_uom": ...}

class TransformStrategy(ABC):
    name: str                              # "erpnext"
    label: str                             # "ERPnext (Al Arabi)"
    description: str
    config_schema: dict                    # company_name, abbr, opening_date, etc.

    @abstractmethod
    def transform(self, tables: dict[str, list[dict]], config: dict) -> StrategyResult: ...
```

### Wiring
- `/api/transform` (currently passthrough) becomes: `strategy = get_strategy(session.strategy_name); result = strategy.transform(tables, config); session.transformed = result.output_tables`.
- New `GET /api/strategies` returns `[{name, label, description, config_schema}]` for the frontend picker.
- Session gains `strategy_name` (default `"erpnext"`) and `strategy_config` (company name, abbr, opening_date, etc.).

---

## ID Generation

To keep ERPnext records clean we generate stable surrogate IDs (don't reuse barcodes / numeric IDs as item codes):

| Doctype | Naming | Example |
|---|---|---|
| Item | `ALA-{CATID}` | `ALA-7290005369148` |
| Customer | `CUST-{ACCOUNTID}` | `CUST-6110001` |
| Supplier | `SUPP-{ACCOUNTID}` | `SUPP-621001` |
| Account | `account_name + " - " + abbr` (autonamed by Frappe) | `الموجودات - ALA` |
| Warehouse | `warehouse_name + " - " + abbr` (autonamed) | `المخزن الرئيس - ALA` |
| Sales Invoice | autonamed via series `ACC-SINV-.YYYY.-.#####` | |
| Purchase Invoice | autonamed via series `ACC-PINV-.YYYY.-.#####` | |
| Payment Entry | autonamed via series | |
| Journal Entry | autonamed via series | |

Legacy IDs preserved in custom fields:
- `Item.legacy_catid` — original CATID
- `Customer.legacy_custid`, `Supplier.legacy_suppid`
- `Account.legacy_acctid`
- `Sales Invoice.legacy_docno`, `Purchase Invoice.legacy_docno` — for cheque/payment matching

---

## Reference Masters

### Currency

Skip emitting; assume ERPnext already has standard currencies.

CURT lookup:
| CURID | CURSHORT (legacy) | ISO code |
|---|---|---|
| 1 | NIS | **ILS** |
| 2 | JD | **JOD** |
| 3 | $$ | **USD** |
| 4 | EUR | **EUR** |

(Legacy uses "NIS" which isn't ISO; map to ILS.)

### UOM

Source: **UNITT** (21 rows) → emit one ERPnext UOM per row. `uom_name = UNITNAMEE if non-empty else UNITNAME`. Skip if name already in standard ERPnext UOMs (Nos, Kg, Litre, Box, etc.).

**Plus**: scan distinct `CATEGORYT.UNIT` (71 distinct text values). For each that doesn't match UNITT.UNITNAME (Arabic) or UNITNAMEE (English), emit an ad-hoc UOM with that exact string. Garbage values (length 1, only digits, "\\", "%", etc.) → emit fallback "وحدة" (Unit) for the item, log warning.

### Warehouse

Source: **STORET** (1 active row: "المخزن الرئيس").

```
warehouse_name = DESCRIPTION  ("المخزن الرئيس")
parent_warehouse = "All Warehouses"
company = config.company
is_group = 0
```

ERPnext autonames as `المخزن الرئيس - {abbr}`.

### Price List

Source: **PRICETYPET** (3 rows, but only 2 referenced by CATPRICET):
- PRICEID 1: `فئة الاسعار الاولى` (Tier 1) → "Al Arabi Standard Selling" (selling=1)
- PRICEID 2: `سعر التجار` (Wholesale) → "Al Arabi Wholesale" (selling=1)

Currency on both: ILS.

### Customer Group / Supplier Group / Territory / Item Group

Single defaults — skip the full SETST grouping system (it's a polymorphic group master that's hard to disambiguate, low value for v1):
- Item Group: "Al Arabi Imported" (parent: "All Item Groups")
- Customer Group: use ERPnext default "Commercial"
- Supplier Group: use ERPnext default "Local"
- Territory: optionally derive from AREAT (514 rows of sales territories) → ERPnext Territory, parent "All Territories". Tier-1.5 if simple, otherwise default "All Territories".

### Company

Caller-provided in config (`company_name`, `abbr`, `country`, `default_currency=ILS`, `chart_of_accounts="Standard"`). Strategy doesn't emit it — must already exist in ERPnext.

---

## Items (CATEGORYT + CATPRICET + CATESYNONYMT + CATEQUATIONT + CATSUPPLIERT)

### Item (one per CATEGORYT row, skip DELETEDCATEGORYT entries)

```
name (item_code) = "ALA-" + CATID
item_name        = CATNAME (Arabic-first; CATNAMEE/H usually empty)
description      = build from: CATDESCT.DESCRIPTION (RTF stripped) +
                   non-barcode CATESYNONYMT entries +
                   English/Hebrew names if present
item_group       = "Al Arabi Imported"
stock_uom        = resolve(CATEGORYT.UNIT) → ERPnext UOM name
                   (match UNITT.UNITNAME or UNITNAMEE; else create custom UOM;
                    fallback "وحدة" with warning)
is_stock_item    = 1
disabled         = 1 if CACTIVE != 1 else 0
has_batch_no     = NEEDBATCH (only 2 items use this — practically all 0)
has_serial_no    = HAVESERIAL (always 0)
weight_per_unit  = WEIGHT
brand            = MANUFACTURER (if non-empty — emit Brand records first)
shelf_life_in_days = ... derived from VALIDITY if set
legacy_catid     = CATID                         (custom field)
```

### Item.barcodes child (Item Barcode) — CRITICAL, do not lose

For each Item, emit barcode child rows from three sources:

1. **CATEGORYT.CATID** as primary barcode. (CATID is barcode-shaped in 19,166 of 19,176 rows.)
2. **CATEGORYT.BARCODE** if non-empty AND ≠ CATID. (Only 56 rows differ — but emit both.)
3. **CATESYNONYMT** rows where `SYNCATID` is numeric and length ∈ {8, 12, 13, 14}:
   - 16,251 of 16,347 are barcode-shaped (only 96 are aliases).
   - Emit as Item Barcode child rows on the parent Item (joined by CATID).

```
barcode      = the value
barcode_type = EAN-8 (len 8) | UPC-A (len 12) | EAN-13 (len 13) | GTIN (len 14) | (blank otherwise)
uom          = item.stock_uom
```

Non-barcode synonyms (96 rows: lengths 1, 4, 6, 10, 11, 20+, or non-numeric) → append to `Item.description` as searchable aliases.

### Item.uoms child (UOM Conversion Detail)

Emit `(uom=stock_uom, conversion_factor=1.0)` for self.

Optional Tier 1.5: from CATEGORYT, `WMUNIT` (wholesale unit) + `WMUNITQTY` (wholesale qty) → second UOM Conversion row if WMUNIT differs from UNIT.

`CATEQUATIONT` (859 rows): these are **inter-item equivalences**, not unit conversions on a single item. EQUTYPE/EQUQTYFACTOR/EQUCATQTY map e.g. "1 carton of CATID = 6 cans of EQUCATID" (different items). ERPnext has no direct doctype for this — defer / store as note.

### Item.supplier_items child (Item Supplier)

Source: **CATSUPPLIERT** (27,229 rows). Group by CATID and emit one row per (CATID, SUPPLIER) pair:
```
supplier         = "SUPP-" + SUPPLIER
supplier_part_no = "" (no field in legacy)
```

### Item Price (separate doctype)

Source: **CATPRICET** (38,341 rows, all 19,161 items priced).

```
item_code        = "ALA-" + CATID
price_list       = "Al Arabi Standard Selling" (PRICEID=1) or "Al Arabi Wholesale" (PRICEID=2)
price_list_rate  = SALEPRICE
currency         = lookup(SALECUR) → ILS / JOD / USD / EUR
uom              = item.stock_uom
valid_from       = CHANGEDATE
```

Skip rows where SALEPRICE = 0 or null.

---

## Parties (CUSTT + SUPPLIERT + ACCOUNTT + CONTACTST)

### Multi-hop relationship (verified)

- `CUSTT.CUSTID == CUSTT.ACCOUNT == ACCOUNTT.ACCOUNTID` (1:1, confirmed by sample)
- Customer name comes from `ACCOUNTT.NAME` (CUSTT has no name column)
- 2,228 customers, 801 suppliers, 544 pure-GL accounts (rest of ACCOUNTT)
- **Total ACCOUNTT = 3,573 = customers + suppliers + pure-GL**

### CONTACTST handling

Inspected: 3,167 rows, but **NAME=0%, EMAIL=0%, ADDRESS=0%, MOBILE=7.5%, OFFICEPHONE=3%**. Effectively useless as a separate Contact doctype.

**Decision: skip Address + Contact doctypes entirely.** Denormalize phone numbers up to Customer/Supplier directly using ERPnext's built-in `mobile_no` and `phone` fields. Saves emitting ~3,000 dynamic-link rows for ~340 actual phone numbers.

### Customer (one per CUSTT row, joined to ACCOUNTT)

```
name             = "CUST-" + CUSTID
customer_name    = ACCOUNTT[CUSTT.ACCOUNT].NAME (Arabic-first, fallback NAMEE)
customer_type    = "Company"
customer_group   = "Commercial"
territory        = "All Territories" (or AREAT lookup if we do Tier 1.5)
default_currency = ILS  (CUSTT has SCHDCURID — almost always 1)
default_price_list = "Al Arabi Standard Selling"
payment_terms    = build from CUSTT.DUEDAYS if > 0 (creates Payment Terms Template)
mobile_no        = CONTACTST[ACCOUNTID].MOBILE (if populated)
phone            = CONTACTST[ACCOUNTID].OFFICEPHONE1 (if populated)
disabled         = 0
legacy_custid    = CUSTID                                    (custom field)
```

### Supplier (one per SUPPLIERT row, joined to ACCOUNTT)

```
name             = "SUPP-" + SUPPID
supplier_name    = ACCOUNTT[SUPPLIERT.ACCOUNT].NAME (Arabic-first)
supplier_type    = "Company"
supplier_group   = "Local"
country          = config.country
default_currency = ILS
mobile_no        = CONTACTST[ACCOUNTID].MOBILE (if populated)
phone            = CONTACTST[ACCOUNTID].OFFICEPHONE1 (if populated)
legacy_suppid    = SUPPID
```

### Walk-in Customer (synthesized)

89% of sales (130,438 of 146,062) have ACCOUNTID=0 (anonymous). Synthesize one Customer:
```
name = "CUST-WALKIN"
customer_name = "زبون نقدي" (Walk-in Customer)
customer_group = "Commercial", territory = "All Territories"
```
All ACCOUNTID=0 sales invoices reference this customer.

### Orphan Invoice Customers (54 ACCOUNTIDs in invoices, not in CUSTT/SUPPLIERT)

Likely employee accounts (CLASS=1) or representative accounts (CLASS=9). Strategy: emit them as additional customers with `legacy_custid` set, name from ACCOUNTT, group "Commercial". Don't lose 54 customers' worth of invoices.

---

## Chart of Accounts (ACCOUNTT + ACCCLASST)

Tree: 3,573 accounts, ALEVEL 0..4 (max depth 4). 7 roots.

### Accounts to emit

**Important**: customer-class (CLASS=2, 2,232 rows) and supplier-class (CLASS=3, 802 rows) ACCOUNTT entries should **NOT** be emitted as ERPnext Account records — ERPnext auto-creates the corresponding Receivable/Payable sub-accounts when we import Customer/Supplier records.

So we emit only:
- All 7 roots (ALEVEL=0)
- All structural intermediate accounts (CLASS != 2 and != 3, ALEVEL ≥ 1)
- = roughly 544 pure-GL accounts + 7 roots = ~551 Account rows

### Root mapping (hand-curated, only 6 needed; root 0 is special)

| ACCOUNTID | NAME (Ar) | English meaning | root_type | report_type |
|---|---|---|---|---|
| 0 | غير محدد | Unspecified (placeholder) | Asset | Balance Sheet |
| 1 | الموجودات | Assets | **Asset** | Balance Sheet |
| 2 | المطلوبات | Liabilities | **Liability** | Balance Sheet |
| 3 | راس المال | Capital / Equity | **Equity** | Balance Sheet |
| 4 | المشتريات والمصاريف | Purchases & Expenses | **Expense** | Profit and Loss |
| 5 | الايرادات | Revenues | **Income** | Profit and Loss |
| 6 | الذمم | Receivables (memo accounts) | **Asset** | Balance Sheet |

ERPnext propagates `root_type` and `report_type` to all descendants automatically. We don't need to set them on the 3,567 children.

### Account_type derivation (per leaf, optional but high-value)

Set `account_type` for leaves to enable correct ERPnext behavior (Bank/Cash/Tax/etc):

| ACCCLASST.CLASSID | Arabic | account_type |
|---|---|---|
| 13 | حساب صندوق نقدي | Cash |
| 10, 14 | الجاري / صندوق الشيكات | Bank |
| 21, 22, 23, 24 | ضرائب | Tax |
| 40, 41, 42 | المخزون | Stock |
| 4 | اصل ثابت | Fixed Asset |
| 47 | مجمع الاستهلاكات | Accumulated Depreciation |
| 7, 34, 36, 45 | مصروف / مشتريات | Expense Account |
| 8, 32, 44 | ايراد / مبيعات | Income Account |
| 33, 35 | مردودات | Income/Expense Account (contra) |
| 51 | الاعتماد | Round Off |
| (others) | | (leave blank — ERPnext default) |

### Emit order

BFS by ALEVEL: 0 → 1 → 2 → 3 → 4. ERPnext requires `parent_account` to exist before child.

Each row:
```
account_name      = ACCOUNTT.NAME (Arabic)
parent_account    = lookup ACCOUNTT[FATHERID].NAME (or null if root)
                    + suffix " - " + abbr after Frappe autonames
is_group          = 1 if any other ACCOUNTT row has this row's ACCOUNTID as FATHERID
root_type         = (only for ALEVEL=0)
report_type       = (only for ALEVEL=0)
account_type      = derived from CLASS (see table above), only for leaves
account_currency  = lookup CURT[CURID].CURSHORT mapped to ISO
company           = config.company
disabled          = 1 if STATUS=0
legacy_acctid     = ACCOUNTID                              (custom field)
```

### Default doctype-mapping accounts (must exist as a result)

After emitting Accounts, the strategy guarantees these exist for invoice/payment use:
- `Debtors - {abbr}` (Receivable) — derive from CLASS=2 parent or pre-existing ERPnext default
- `Creditors - {abbr}` (Payable)
- `Cash - {abbr}` (Cash)
- `Sales - {abbr}` (Income, default income_account)
- `Cost of Goods Sold - {abbr}` (Expense)
- `Stock In Hand - {abbr}` (Stock)

If any of these named defaults aren't directly in legacy data, the strategy emits stub Account rows so subsequent invoice imports succeed.

---

## Sales Invoice (CATESINVDOCT + CATESINVDOCDETT) + Sales Returns (CATESRETINVDOCT)

### Filter

- INVTYPE always = 1, no filter needed.
- POSTFLAG distribution: 6 with 1 (draft), 145,946 with 2 (posted), 2 with 4, 107 with 9 (cancelled). **Filter to POSTFLAG ∈ {1, 2}**, skip 9 (cancelled). Edge values 4 → log warning.
- Returns: emit from `CATESRETINVDOCT` with `is_return=1`.

### Header join key

Header → detail join on `(DOCNO, INVTYPE)`. NOT on DOCSERIAL (which is unique per header but not present in detail).

### Sales Invoice (header) — single doctype, retail vs B2B distinguished by `is_pos`

ERPnext's `Sales Invoice` doctype handles both retail (POS-originated) and B2B credit sales via the `is_pos` flag. Verified to exist in v16 (`erpnext/accounts/doctype/sales_invoice/sales_invoice.json`, field type Check). We do NOT use the separate POS Invoice doctype — it's designed for live POS operation, requires POS Profile + POS Closing Voucher consolidation, and adds setup overhead with no benefit for historical migration.

#### `is_pos` decision rule (driven by SALEPOINT field)

| Legacy pattern | Count | `is_pos` | Behavior |
|---|---|---|---|
| SALEPOINT populated, walk-in (ACCOUNTID=0) | 130,403 | **1** | Retail walk-in, settled at posting |
| SALEPOINT populated, named customer (loyalty) | 15,216 | **1** | Retail named, settled at posting |
| SALEPOINT empty, walk-in (anomaly) | 35 | **1** | Treated as walk-in |
| SALEPOINT empty, named customer | 407 | **0** | B2B credit, settled later by Payment Entry |

**Total: 145,654 with `is_pos=1`, 407 with `is_pos=0`.**

#### Header fields

```
customer            = "CUST-WALKIN" if ACCOUNTID=0 else "CUST-" + ACCOUNTID
posting_date        = DOCDATE
posting_time        = DOCTIME
due_date            = DOCDATE                     if is_pos=1 (settled same day)
                      DUEDATE if non-zero else DOCDATE + 30  if is_pos=0
company             = config.company
currency            = "ILS" (always; CURID=1)
conversion_rate     = 1.0
selling_price_list  = "Al Arabi Standard Selling"
debit_to            = "Debtors - " + abbr
is_pos              = 1 if SALEPOINT non-empty else 0  (see rule above)
is_return           = 0 (1 only on returns from CATESRETINVDOCT)
discount_amount     = DISCOUNTV
docstatus           = 1 (submitted) — POSTFLAG=2 means it's posted in legacy
update_stock        = 1 (legacy invoices already deducted stock)
legacy_docno        = DOCNO
legacy_docserial    = DOCSERIAL
remarks             = NOTES
```

#### `payments` child table (only when `is_pos=1`)

ERPnext requires the `payments` child to be populated when `is_pos=1` so it knows how the customer paid. Derive from POSPAYST (POS payment splits) when present, fallback to a single Cash row of DOCVALUE:
```
mode_of_payment   = "Cash" / "Cheque" / "Card" (from POSPAYST.PAYTYPE)
account           = "Cash - " + abbr  (or appropriate cash/bank account)
amount            = POSPAYST.PAYAMOUNT  (or DOCVALUE if no split row)
```

For `is_pos=0` rows: no `payments` child rows; settled later by Payment Entries from RECDOCT.

### Sales Invoice Item (child, parentfield=`items`)

```
item_code         = "ALA-" + CATID
qty               = CATQTY
rate              = CATPRICEWOV  (price excluding VAT — ERPnext applies tax separately)
uom               = resolve(CATUNIT) — fuzzy match like CATEGORYT.UNIT
warehouse         = "المخزن الرئيس - " + abbr  (always store 1)
income_account    = lookup ACCOUNTT[SALEACCID].NAME + " - " + abbr
discount_amount   = CATDISCOUNT
```

Top 10 SALEACCIDs cover ~95% of lines and are all in the 510101..510115 range — these are revenue sub-accounts.

### Sales Taxes and Charges

**Dropped from v1.** No `taxes` child rows emitted. Legacy `VATAMOUNT` is not transferred. Admin can configure tax templates post-migration and reprocess invoices if VAT recovery is required.

### Sales Returns (CATESRETINVDOCT + CATESRETINVDOCDETT)

Same shape as Sales Invoice with:
- `is_return = 1`
- Detail line `SALERETACCID` (instead of SALEACCID) → `income_account`
- Quantities emitted positive; ERPnext's `is_return` flips signs on save

---

## Purchase Invoice (CATEPINVDOCT + CATEPINVDOCDETT) + Purchase Returns (CATEPRETINVDOCT)

### Filter & join

- INVTYPE always = 1.
- POSTFLAG: 2 = posted (filter to this).
- Header → detail join on `(DOCNO, INVTYPE)`.
- 16 of 225 distinct supplier ACCOUNTIDs are actually customers (legacy data quirk) — emit those as suppliers under their customer name (or accept duplicates).

### Purchase Invoice (header)

```
supplier            = "SUPP-" + ACCOUNTID  (or "CUST-" if it's actually a customer)
posting_date        = DOCDATE
due_date            = DUEDATE if non-zero else DOCDATE + 30 days
bill_no             = MANUALNO  (legacy paper invoice number, recommended)
bill_date           = DOCDATE
company             = config.company
currency            = "ILS"
conversion_rate     = 1.0
buying_price_list   = (none — ERPnext doesn't require it)
credit_to           = "Creditors - " + abbr
update_stock        = 1
docstatus           = 1
legacy_docno        = DOCNO
```

### Purchase Invoice Item

```
item_code         = "ALA-" + CATID
qty               = CATQTY
rate              = CATPRICEWOV
uom               = resolve(CATUNIT)
warehouse         = "المخزن الرئيس - " + abbr
expense_account   = lookup ACCOUNTT[PURCHACCID].NAME + " - " + abbr
                    (PURCHACCID is in the detail row for purchase)
```

### Purchase Returns

Mirror sales returns with `is_return=1`, `PURCHRETACCID` → expense_account.

---

## Payment Entry (RECDOCT + PAYDOCT)

### Customer Receipts (RECDOCT 1,340 + RECDOCDETT 2,775)

Each RECDOCT header is a customer payment. RECDOCDETT row 0 = the DEBIT (cash/bank received), other rows = CREDIT (customer's account).

```
payment_type   = "Receive"
party_type     = "Customer"
party          = "CUST-" + RECDOCDETT[serial=0].ACCOUNTID
posting_date   = DOCDATE
paid_amount    = DOCVALUE
received_amount= DOCVALUE
paid_from      = lookup ACCOUNTT[customer_account].NAME + " - " + abbr  (Receivable)
paid_to        = lookup ACCOUNTT[cash_account].NAME + " - " + abbr      (Cash/Bank)
mode_of_payment = "Cash" if cash row, "Cheque" if CHEQUEID populated
reference_no   = CHEQUE_CHEQUENO (if cheque)
reference_date = CHEQUE_CDATE
```

### Supplier Payments (PAYDOCT 2,831 + PAYDOCDETT 6,026)

Mirror with `payment_type="Pay"`, `party_type="Supplier"`.

### Cross-link to Legacy Cheque

When CHEQUEID is set in the source RECDOCDETT/PAYDOCDETT row, the resulting Payment Entry gets a custom field `linked_legacy_cheque = "CHQ-" + CHEQUEID` pointing to the Legacy Cheque doctype record (see Cheques section below).

---

## Cheques (CHEQUET + CHEQUELEDGERT) — custom doctypes

ERPnext's native cheque tracking (Payment Entry `reference_no` + `reference_date`) loses critical metadata: bank, owner name, clearing date, bounce flag, account lineage. For Al Arabi's cheque-driven business, this is unacceptable. Strategy emits two custom doctypes that mirror legacy 1:1.

### One-time setup (admin runs before importing)

Strategy outputs two doctype-definition JSON files alongside the data CSVs:
- `legacy_cheque_doctype.json` — paste-ready definition for the `Legacy Cheque` doctype
- `legacy_cheque_movement_doctype.json` — definition for the `Legacy Cheque Movement` child doctype

Admin imports these once via ERPnext's Customize Form / DocType Builder (or via `bench` command) before importing the data CSVs. Documented in `migration_setup_checklist.md`.

### Legacy Cheque (one row per CHEQUET row, 1,820 records)

```
name              = autonamed via series "CHQ-.#####"
legacy_chequeid   = CHEQUEID                          (unique, indexed)
cheque_no         = CHEQUENO
cheque_date       = CDATE                             (issue date)
clearing_date     = REALCDATE if not "1899-12-30" else null
posting_date      = DOCDATE
amount            = CVALUE
amount_base       = CMVALUE                           (in base currency)
currency          = lookup(CURID) → ISO
bank              = lookup BANKT[CBANK].BANKNAME
bank_branch       = CBANKBRANCH
bank_account      = lookup BANKACCOUNTT[BANKACC] if set
owner_name        = OWNERNAME                         (← who gave/received the cheque)
class             = CLASS                             (incoming/outgoing/etc)
source_account    = lookup ACCOUNTT[SOURCEACCOUNTID].NAME (where it started)
dest_account      = lookup ACCOUNTT[DESTACCOUNTID].NAME   (where it ended up)
current_account   = lookup ACCOUNTT[ACCOUNTID].NAME       (current location)
returned          = RETURNED                          (← bounce flag, 0/1)
returned_count    = CHEQUEBACK                        (times bounced)
status            = STATUS                            (mapped enum)
notes             = NOTE
linked_party_type = "Customer" or "Supplier" derived from source/dest account
linked_party      = "CUST-..." or "SUPP-..." (link)
linked_payment    = (filled later when matched to Payment Entry)  
movements         = child table → Legacy Cheque Movement rows
```

### Legacy Cheque Movement (child of Legacy Cheque, 1,199 records from CHEQUELEDGERT)

```
movement_date    = TDATE
prev_account     = lookup ACCOUNTT[PREVACCOUNT].NAME
prev_account_name= PREVNAME                           (denormalized from legacy)
curr_account     = lookup ACCOUNTT[CURRACCOUNT].NAME
curr_account_name= CURRNAME
doc_serial       = DOCSERIAL
doc_class        = DOCCLASS                           (which document moved it)
returned_flag    = RETURNED
notes            = NOTES
is_deleted       = ISDELETED
```

### Bidirectional cross-references

- **Legacy Cheque → Payment Entry**: `linked_payment` field stores the Payment Entry name once matched
- **Payment Entry → Legacy Cheque**: custom field `linked_legacy_cheque` stores `CHQ-{CHEQUEID}`
- **Journal Entry (bounce / DNOTEDOCT)**: same `linked_legacy_cheque` custom field
- **Bank Transaction (BANKENTRYDOCDETT)**: same `linked_legacy_cheque` custom field

Result: accountant searching "cheque #30004097" gets the original issuer, dates, every account it passed through, bounce status, and all linked payments/journals.

### Bounced cheques (DNOTEDOCT 28 + DNOTEDOCDETT 55)

Sample shows DNOTEDOCT.FORWHAT = "شيك راجع" (returned cheque). Each generates a Journal Entry with:
- `voucher_type = "Debit Note"` or `"Journal Entry"`
- Detail row: DEBIT customer / CREDIT cheque-bounced account
- Custom field `linked_legacy_cheque = "CHQ-" + CHEQUEID` from the detail row's CHEQUEID
- Custom field `is_cheque_bounce = 1`

### Banking masters

- **BANKT** (78 banks) → ERPnext **Bank** doctype: `bank_name` (Arabic, fallback English)
- **BANKACCOUNTT** (10 bank accounts) → ERPnext **Bank Account**: `account_name`, `bank`, `account_subtype`, `branch_code` from BRANCHNAME, etc.
- **BANKENTRYDOCT/DETT** (278 + 687) → ERPnext **Bank Transaction** + linked Journal Entry with cheque references where applicable

---

## Journal Entry (ENTRYDOCT + STARTENTRYDOCT)

### Manual Journal Entries (ENTRYDOCT 2,752 + ENTRYDOCDETT 14,484)

```
voucher_type   = "Journal Entry"
posting_date   = DOCDATE
company        = config.company
docstatus      = 1 if POSTFLAG=2 else 0
```

Child `accounts`:
```
account     = lookup ACCOUNTT[ACCOUNTID].NAME + " - " + abbr
debit_in_account_currency  = DEBIT
credit_in_account_currency = CREDIT
party_type, party  = derived if account is Receivable/Payable
reference_no, reference_type  = derived if CHEQUEID populated
```

### Opening Journal Entry (STARTENTRYDOCT 19 + STARTENTRYDOCDETT 1,610)

These are opening balances. Emit each STARTENTRYDOCT row as a Journal Entry with:
```
voucher_type = "Opening Entry"
is_opening   = "Yes"
posting_date = config.opening_date  (caller-provided, e.g. 2026-01-01)
```

Cheque-related opening entries (DOCNO 1 = "الشيكات الإفتتاحية") emit cheque-side entries via the Legacy Cheque doctype path (see Cheques section); the Opening JE only covers non-cheque opening balances.

---

## Stock Reconciliation (CATSTORET + CATEGORYT) — opening stock

Source: **CATSTORET** (6,553 rows). One Stock Reconciliation per warehouse with `purpose="Opening Stock"`, `posting_date=config.opening_date` (caller-provided cutover date, e.g. 2026-01-01).

### Use STARTQTY, NOT QTYBALANCE

CATSTORET column semantics (verified by sample math):
- `STARTQTY` = opening qty at start of legacy period (= what we want)
- `QTYIN`, `QTYOUT` = period movements
- `QTYBALANCE` = period delta = QTYIN − QTYOUT (NOT a stock position)
- `QUANTITY` = current qty = STARTQTY + QTYBALANCE

We use **STARTQTY** as the opening quantity for ERPnext.

### Per-row item line
```
item_code      = "ALA-" + CATID
warehouse      = "المخزن الرئيس - " + abbr
qty            = STARTQTY  (negative values emitted as-is — see below)
valuation_rate = lookup CATEGORYT[CATID].COSTPRICE
                 (99.9% of items have COSTPRICE > 0; fallback to PURCHPRICE or 0)
```

### Negative opening stock — Allow Negative Stock setting

Distribution of `CATSTORET.STARTQTY`:
- **2,884 items**: positive opening — emit as-is
- **955 items**: **negative opening** — emit as-is, requires Allow Negative Stock to be ON
- **2,713 items**: zero opening — skip (no row needed)

**Why ERPnext supports this**: Stock Settings → Allow Negative Stock is explicitly designed for the "dispatch before receipt" scenario where legacy systems posted sales before the corresponding receipt was entered, leaving stock negative. The remediation pattern is to enter the missed receipt later, which corrects the balance toward zero. See `docs.frappe.io/erpnext/stock-adjustment-cogs-with-negative-stock`.

**Pre-flight requirement**: strategy config has `requires_allow_negative_stock = true`. Strategy emits a `migration_setup_checklist.md` artifact that includes:
1. Set Stock Settings → Allow Negative Stock = ✓ before importing Stock Reconciliation
2. (Note: from v15+, Allow Negative Stock does NOT apply to Serial/Batch tracked items. Out of 19,176 legacy items only 2 have NEEDBATCH=1 and 0 have HAVESERIAL=1, so this is a non-issue for us.)

### What about CATSTORET.QUANTITY (current snapshot)?

Tempting to use `QUANTITY` directly as the opening (skip the period). But that would conflict with the sales/purchase invoices we're importing in the same window — those invoices would re-deduct stock that's already reflected in QUANTITY. Using STARTQTY + importing all in-window invoices = correct final position matching legacy QUANTITY.

---

## Stock Entry — Stock Transfers (DIVISIONDOCT 243 + DIVISIONDOCDETT 977)

Inter-warehouse transfers. Since STORET has only 1 active store and DIVISIONDOCT samples show FROMSTOREID=TOSTOREID=1 (intra-store transfers), this is essentially low-value. **Defer / skip** for v1 — log the count.

---

## Walk-in Sales Summarization

Anonymous walk-in invoices (`ACCOUNTID=0`, 130,403 rows = 89% of sales) are summarized per `(DOCDATE, SALEPOINT)` to keep import volume manageable. B2B and named POS customers (15,623 rows) are imported per-invoice with full detail.

| Stream | Legacy rows | Output Sales Invoices | Output lines |
|---|---|---|---|
| B2B (`is_pos=0`, named) | 407 | 407 | per-line preserved |
| Named POS (`is_pos=1`) | 15,216 | 15,216 | per-line preserved |
| Walk-in (`is_pos=1`, ACCOUNTID=0) | 130,403 | ~600–800 daily summaries | grouped by (item, uom) per day-terminal |

Walk-in summary header:
```
customer       = "CUST-WALKIN"
posting_date   = DOCDATE  (one summary per date)
is_pos         = 1
docstatus      = 1
update_stock   = 1
remarks        = "Walk-in summary — terminal {SALEPOINT}, {n} legacy invoices"
legacy_summary = 1                                   (custom field flag)
legacy_summary_count   = number of source invoices   (custom field)
legacy_summary_terminal = SALEPOINT                  (custom field)
```

Walk-in summary lines (grouped by item):
```
item_code  = "ALA-" + CATID
qty        = SUM(CATQTY) for that day-terminal-item
rate       = weighted avg of CATPRICEWOV by qty
warehouse  = "المخزن الرئيس - " + abbr
```

Cash payments aggregated similarly via the `payments` child table (sum of POSPAYST per mode for that day-terminal).

**Trade-off**: walk-in returns lose `return_against` linkage to a specific original invoice — the return still imports with correct accounting effect, just no explicit pointer to the summary. Acceptable since walk-ins are anonymous and legacy DB remains as the historical archive.

---

## Employees (EMPLOYEET → ERPnext HR Employee)

In scope. Client uses ERPnext HR module.

EMPLOYEET (132 rows) → Employee doctype. ERPnext HR creates its own salary accounts on first payroll run; the legacy `EMPLOYEET.ACCOUNT` link is preserved via custom field for accounting traceback only.

```
employee_name        = ACCOUNTT[EMPLOYEET.ACCOUNT].NAME (Arabic-first)
gender               = "Male"/"Female" derived from GENDER
date_of_birth        = BIRTH if not 1899-12-30 else null
date_of_joining      = STARTDATE if not 1899-12-30 else CHANGEDATE_DATA
relieving_date       = EMPENDDATE if not 1899-12-30 else null
status               = "Active" if ISWORKING=1 else "Left"
company              = config.company
employment_type      = derived from SALARYTYPE
salary_currency      = lookup(SALARYCURID) → ISO
ctc                  = SALARY  (if non-zero)
attendance_device_id = CARDID  (if set)
notes                = NOTE
legacy_empid         = EMPID                          (custom field)
legacy_acctid        = ACCOUNT                        (custom field — for salary GL traceback)
```

ERPnext v16 Employee required-field check pending verification at implementation time against `frappe/erpnext` v16 branch JSON. Likely required: `employee_name`, `gender`, `date_of_joining`, `company`, `status` — all mappable from legacy.

Out of scope for this strategy: Salary Structure, Salary Slip (operational HR data the client configures post-migration), attendance records (no source data), leave records (no source data).

---

## Drop List (out of scope for ERPnext strategy)

- **LEDGERT** (869K rows) — auto-recreated by ERPnext when invoices/JEs are submitted. Re-importing would double-post. Used only as a verification cross-check (sum-totals reconcile).
- **CATPURCHPRICECHANGEST** (157K), **CATPRICECHANGEST** (3,529) — historical price audit. No business value beyond current cost.
- **STOCKTAKINGT** (4) + **STOCKTAKINGDETT** (3,965) — physical counts during the period. Defer (could map to Stock Reconciliation non-opening).
- **POS_PROMOTIONT** (36), POSCARDT, SALEPOINTT — POS-specific, defer.
- **PUSERT**, attachments, dashboards, menus — out of scope.
- **DIVISIONDOCT** — intra-store transfers; defer.
- All `RPLC_*`, `DELETED*`, logging, MONITORT — drop entirely.

(Cheques, Cheque Movements, Banks, Bank Accounts, Bank Entries — in scope via Payment Entry custom fields + ERPnext Bank/Bank Account/Bank Transaction.)
(Employees — in scope, see Employees section.)

---

## Business-Value Preservation Audit Checklist

After transform, the strategy verifies and reports:

- [ ] **Item barcodes**: every CATEGORYT row contributes ≥ 1 Item Barcode child. Total barcodes ≥ 19,176 (CATIDs) + 56 (BARCODE differs) + 16,251 (synonym barcodes) ≈ **35,483 barcodes preserved**.
- [ ] **Item synonyms** (96 non-barcode aliases) preserved in description.
- [ ] **All 19,176 items** emitted (or report deletion count).
- [ ] **All 38,341 prices** emitted as Item Prices.
- [ ] **All 27,229 item-supplier links** emitted as supplier_items child rows.
- [ ] **All 2,228 customers** + 801 suppliers + Walk-in + 54 orphans = 3,084 parties.
- [ ] **All ~551 GL accounts** (3,573 minus customer/supplier) emitted with hierarchy intact.
- [ ] **All 145,952 valid sales invoices** (POSTFLAG ∈ {1,2}) + 4,536 returns emitted.
- [ ] **All 2,579 valid purchase invoices** + 581 returns emitted.
- [ ] **All 1,340 receipts** + 2,831 payments → Payment Entry.
- [ ] **All 2,752 journal entries** + 19 opening entries → Journal Entry.
- [ ] **Opening stock**: 2,884 positive + 955 negative = 3,839 items with non-zero opening → Stock Reconciliation. (2,713 zero-opening items skipped.)
- [ ] **All 1,820 cheques** preserved as Legacy Cheque records with full metadata (owner, bank, dates, bounce status).
- [ ] **All 1,199 cheque movements** preserved as Legacy Cheque Movement child rows.
- [ ] **All 78 banks + 10 bank accounts + 278 bank entries** preserved.
- [ ] **All 28 bounced-cheque debit notes** preserved as Journal Entry with cheque link.
- [ ] **Cross-references** Payment Entry ↔ Legacy Cheque bidirectional.
- [ ] **Multilingual**: Arabic primary preserved; English/Hebrew (when present) preserved in description.

Rows lost / warnings logged for:
- 107 cancelled sales invoices (POSTFLAG=9) — intentional drop
- 23 items with COSTPRICE=0 — opening stock valuation_rate falls back to PURCHPRICE or 0
- ~135 non-barcode-shaped synonyms — preserved as text in description, not as barcodes
- 71 distinct UNIT strings — fuzzy-resolved to UOM master; garbage values fall back to "وحدة"
- VAT amounts on invoices — intentionally not migrated (taxes deferred)

### Reconciliation cross-check (informational)

After emit, the strategy compares legacy LEDGERT account totals (sum of debits/credits per ACCOUNTID across all 869K entries) against the totals derived from emitted invoices/JEs/payments. Mismatches don't block the migration but are reported per-account so the accountant can investigate any source document we may have missed.

---

## Implementation Build Order

Single PR. Slices for self-testability:

1. **Plumbing**: `core/strategies/{__init__, base}.py`, `/api/strategies` GET, `/api/transform` strategy dispatch, frontend strategy picker.
2. **Helpers** (`erpnext/common.py`): multilingual_pick (Arabic-first), currency_iso(curid), uom_resolve(text), abbr_suffix(name), legacy_id encoders, Frappe-format CSV writer (with chunking for >5K-row outputs).
3. **Reference masters** (`erpnext/masters.py`): UOM (UNITT + ad-hoc from CATEGORYT.UNIT), Warehouse, Price List, Item Group, Customer Group, Supplier Group, Territory, Bank, Bank Account.
4. **Items + barcodes** (`erpnext/items.py`): the headline feature. Item, Item Barcode child (3 sources), supplier_items, Item Price.
5. **Parties** (`erpnext/parties.py`): Customer (with denormalized phone from CONTACTST), Supplier, Walk-in, 54 orphans.
6. **Chart of Accounts** (`erpnext/accounts.py`): 6-root mapping, BFS emit by ALEVEL, account_type derivation, customer/supplier accounts excluded (auto-created by ERPnext).
7. **Invoices** (`erpnext/invoices.py`): Sales Invoice + Sales Return + Purchase Invoice + Purchase Return. No tax rows. Sales Invoice output is chunked (~5K headers per file).
8. **Payments** (`erpnext/payments.py`): Payment Entry from RECDOCT/PAYDOCT, with `linked_legacy_cheque` cross-reference set when CHEQUEID present.
9. **Cheques** (`erpnext/cheques.py`): Legacy Cheque + Legacy Cheque Movement custom doctype JSONs, plus data CSVs from CHEQUET/CHEQUELEDGERT. Bank Transactions from BANKENTRYDOCT.
10. **Journals** (`erpnext/journals.py`): Journal Entry from ENTRYDOCT (incl. bounced-cheque DNOTEDOCT), Opening Journal Entry from STARTENTRYDOCT.
11. **Opening stock** (`erpnext/stock_moves.py`): Stock Reconciliation from CATSTORET.STARTQTY + CATEGORYT.COSTPRICE; `migration_setup_checklist.md` flagging Allow Negative Stock requirement.
12. **Audit/report** (`erpnext/audit.py`): preservation checklist totals, warnings list, LEDGERT cross-check report.

Each slice committed separately within the single PR for review legibility.

## Migration Setup Checklist (admin-facing, emitted by strategy)

Output alongside the data CSVs as `migration_setup_checklist.md`:

1. Create the company in ERPnext with `default_currency=ILS`, custom `abbr` (used throughout autonames).
2. Set Stock Settings → **Allow Negative Stock = ✓** (required for opening stock import).
3. Import the two custom doctype definitions: `legacy_cheque_doctype.json`, `legacy_cheque_movement_doctype.json`.
4. Add custom field `linked_legacy_cheque` (Link to Legacy Cheque) to Payment Entry and Journal Entry doctypes.
5. Import data files in dependency order (numbered file prefixes):
   - `01_uom.csv`, `02_warehouse.csv`, `03_price_list.csv`, `04_groups_*.csv`, `05_bank.csv`, `06_bank_account.csv`
   - `10_account_root.csv`, `10_account_level1..4.csv` (CoA, must be in ALEVEL order)
   - `20_item.csv` (1–4 batch files), `21_item_price.csv` (1–8 batch files)
   - `30_customer.csv`, `31_supplier.csv`
   - `40_legacy_cheque.csv`, `41_legacy_cheque_movement.csv`
   - `50_opening_journal.csv`
   - `51_stock_reconciliation_opening.csv`
   - `60_sales_invoice_NN.csv` (~26 batch files)
   - `61_purchase_invoice.csv` (1–2 files)
   - `62_sales_return.csv`, `63_purchase_return.csv`
   - `70_payment_entry.csv`
   - `71_journal_entry.csv`, `72_journal_entry_bounced_cheque.csv`
   - `80_bank_transaction.csv`
6. For each transactional file, enable **Submit After Import** and **Don't Send Emails**.
7. Verify by running the strategy's reconciliation report against legacy LEDGERT totals.
