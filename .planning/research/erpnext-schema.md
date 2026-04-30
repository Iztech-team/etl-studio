# ERPNext Target Schema — Reference for Legacy ERP Migration

Reference for mapping legacy ERP CSV exports (items, customers, suppliers, accounts, sales invoices, purchase invoices, stock entries) into ERPNext-compatible records. Field names are the actual ERPNext doctype `fieldname` values used by Data Import / REST API.

ERPNext uses **Frappe doctypes**. Each doctype has:
- A `name` (primary key). Either an autoname pattern (naming series, e.g. `ACC-SINV-.YYYY.-`) or a user-supplied field (e.g. `item_code` for Item).
- Mandatory fields (red in the import template) and dependent fields (yellow).
- Child tables (rows belong to a `parent` document via `parent` / `parenttype` / `parentfield`).
- Link fields that must reference an existing master.

---

## 1. Reference / setup masters (import first)

### Currency
- Naming: `name` = currency code (e.g. `USD`).
- Required: `currency_name`, `fraction`, `fraction_units`, `smallest_currency_fraction_value`, `symbol`.
- Already prefilled out-of-the-box; legacy migrations rarely add new ones.

### UOM (Unit of Measure)
- Naming: `name` = UOM name (e.g. `Nos`, `Kg`, `Box`).
- Required: `uom_name`. Optional: `must_be_whole_number`, `enabled`.
- Standard ones (`Nos`, `Kg`, `Litre`, `Hour`, `Unit`, `Box`) already exist.

### Item Group (tree doctype)
- Naming: `name` = `item_group_name`.
- Required: `item_group_name`, `parent_item_group` (or `is_group=1` and `parent_item_group="All Item Groups"`).
- Must exist before any Item references it.

### Customer Group, Supplier Group, Territory (tree doctypes)
- Same shape as Item Group: `<x>_name`, `parent_<x>`, `is_group`.
- `All Customer Groups`, `All Supplier Groups`, `All Territories` are root nodes.

### Warehouse (tree doctype)
- Naming: autoname = `{warehouse_name} - {company_abbr}` (e.g. `Stores - GTPL`).
- Required: `warehouse_name`, `company`, `parent_warehouse` (or `is_group=1`).

### Price List
- Naming: `name` = `price_list_name`.
- Required: `price_list_name`, `currency`, `selling` or `buying` (1).

### Company
- Naming: `name` = `company_name`.
- Required: `company_name`, `abbr` (used in warehouse/account names), `default_currency`, `country`.
- Must exist before any transaction or Account.

---

## 2. Item

Naming: `name` = `item_code` (unless `item_naming_by` is changed in Stock Settings).

| Field | Req | Notes |
|---|---|---|
| `item_code` | yes | unique, becomes `name` |
| `item_name` | yes | human-readable, defaults to item_code |
| `item_group` | yes | must reference an existing Item Group |
| `stock_uom` | yes | Link to UOM; cannot be changed once stock exists |
| `is_stock_item` | no | 1 for inventory items, 0 for service |
| `is_sales_item` / `is_purchase_item` | no | default 1 |
| `description` | no | HTML allowed |
| `valuation_method` | no | `FIFO` / `Moving Average` / `LIFO` |
| `default_warehouse` | no | Link to Warehouse |
| `disabled` | no | soft-delete |
| `has_batch_no`, `has_serial_no` | no | flags for batch/serial tracking |
| `opening_stock`, `valuation_rate` | no | only used at item creation; for migrations prefer Stock Reconciliation |
| `standard_rate` | no | seeds Item Price (Standard Selling) |

Child tables on Item: `uoms` (UOM Conversion Detail: `uom`, `conversion_factor`), `item_defaults` (per-company defaults: `company`, `default_warehouse`, `expense_account`, `income_account`).

### Item Price (separate doctype)
Naming: autoname `{price_list}/{item_code}/...`.
- Required: `item_code`, `price_list`, `price_list_rate`.
- Selling vs Buying is implied by the Price List's `selling` / `buying` flag.
- Optional: `uom`, `currency`, `valid_from`, `valid_upto`, `customer`, `supplier`.

---

## 3. Customer

Naming: by default `name` = `customer_name`. If Selling Settings → `cust_master_name = "Naming Series"`, then auto: `CUST-.YYYY.-.#####`.

| Field | Req | Notes |
|---|---|---|
| `customer_name` | yes | |
| `customer_type` | yes | `Company` or `Individual` |
| `customer_group` | yes | Link, must exist |
| `territory` | yes | Link, must exist |
| `default_currency` | no | else taken from Company |
| `default_price_list` | no | |
| `tax_id` | no | VAT/GSTIN/EIN |
| `disabled` | no | |
| `is_internal_customer`, `represents_company` | no | inter-company |

### Address (separate doctype, linked via Dynamic Link child table)
- Naming: autoname `{address_title}-{address_type}` (e.g. `Acme-Billing`).
- Required: `address_title`, `address_type` (`Billing`/`Shipping`/`Other`), `address_line1`, `city`, `country`.
- Linkage: child row in `links` table — `link_doctype="Customer"`, `link_name="<customer_name>"`. Same Address can be linked to many parties.

### Contact (separate doctype, linked via Dynamic Link child table)
- Naming: autoname from `first_name + last_name`.
- Required: `first_name`. Optional: `last_name`, `email_ids` child table (`email_id`, `is_primary`), `phone_nos` child table (`phone`, `is_primary_phone`).
- Linkage: same `links` child table mechanism as Address.

---

## 4. Supplier

Naming: `name` = `supplier_name` by default; otherwise series `SUPP-.YYYY.-.####`.

| Field | Req | Notes |
|---|---|---|
| `supplier_name` | yes | |
| `supplier_type` | yes | `Company` / `Individual` |
| `supplier_group` | yes | Link, must exist |
| `country` | no | |
| `default_currency` | no | |
| `tax_id` | no | |
| `disabled`, `on_hold` | no | |

Address and Contact link the same way as Customer (Dynamic Link to `Supplier`).

---

## 5. Account (Chart of Accounts)

Tree doctype, per Company.
Naming: autoname = `{account_name} - {company_abbr}` (e.g. `Cash - GTPL`).

| Field | Req | Notes |
|---|---|---|
| `account_name` | yes | |
| `company` | yes | Link |
| `parent_account` | yes (unless root) | the named ledger above; must exist |
| `is_group` | yes | 1 = group/folder, 0 = ledger |
| `root_type` | yes for roots | `Asset` / `Liability` / `Equity` / `Income` / `Expense` |
| `report_type` | yes for roots | `Balance Sheet` / `Profit and Loss` |
| `account_type` | no | `Bank`, `Cash`, `Receivable`, `Payable`, `Stock`, `Tax`, `Fixed Asset`, `Expense Account`, `Income Account`, `Round Off`, `Stock Received But Not Billed`, `Stock Adjustment`, `Cost of Goods Sold`, etc. |
| `account_currency` | no | default = company currency |
| `tax_rate` | no | for Tax accounts |

Recommended import path: use **Chart of Accounts Importer** (overwrites the auto-created CoA for the company — only safe if there are no transactions yet). Otherwise import bottom-up: roots first, then groups, then leaves.

---

## 6. Sales Invoice (header) + Sales Invoice Item (lines)

Sales Invoice naming: series `ACC-SINV-.YYYY.-.#####` (autoname).

### Sales Invoice (header)

| Field | Req | Notes |
|---|---|---|
| `customer` | yes | Link to Customer |
| `company` | yes | |
| `posting_date` | yes | accounting date |
| `due_date` | yes | |
| `currency` | yes | usually fetched from Customer |
| `conversion_rate` | yes | 1.0 for company currency |
| `selling_price_list` | yes | Link to Price List |
| `debit_to` | yes | Receivable account, e.g. `Debtors - GTPL` |
| `is_pos`, `is_return`, `update_stock` | no | flags |
| `customer_address`, `shipping_address_name` | no | |
| `naming_series` | no | override autoname |
| `cost_center`, `project` | no | |

### Sales Invoice Item (child table, parentfield = `items`)

Each row links to parent via `parent` (=Sales Invoice name), `parenttype="Sales Invoice"`, `parentfield="items"`.

| Field | Req | Notes |
|---|---|---|
| `item_code` | yes | Link to Item |
| `qty` | yes | |
| `rate` | yes | unit price in invoice currency |
| `uom` | no | defaults to item's stock_uom |
| `conversion_factor` | no | UOM → stock_uom factor |
| `warehouse` | yes if `update_stock=1` | |
| `income_account`, `cost_center` | no | inferred from Item / Company defaults |
| `amount` | computed | `qty * rate` |

Other child tables on Sales Invoice: `taxes` (Sales Taxes and Charges), `payment_schedule`, `payments` (POS).

---

## 7. Purchase Invoice + Purchase Invoice Item

Purchase Invoice naming: series `ACC-PINV-.YYYY.-.#####`.

### Purchase Invoice (header)

| Field | Req | Notes |
|---|---|---|
| `supplier` | yes | Link to Supplier |
| `company` | yes | |
| `posting_date` | yes | |
| `due_date` | yes | |
| `bill_no` | recommended | supplier's invoice number |
| `bill_date` | recommended | |
| `currency`, `conversion_rate` | yes | |
| `buying_price_list` | no | |
| `credit_to` | yes | Payable account, e.g. `Creditors - GTPL` |
| `update_stock` | no | if 1, also creates stock ledger entries (warehouse mandatory on lines) |
| `is_return` | no | for debit notes |

### Purchase Invoice Item (child, parentfield = `items`)

| Field | Req | Notes |
|---|---|---|
| `item_code` | yes | |
| `qty` | yes | |
| `rate` | yes | |
| `uom`, `conversion_factor` | no | |
| `warehouse` | yes if `update_stock=1` | |
| `expense_account` | no | from Item defaults |
| `cost_center` | no | |

Child tables: `taxes` (Purchase Taxes and Charges), `payment_schedule`.

---

## 8. Stock Entry / Stock Reconciliation

### Stock Entry
Naming: series `MAT-STE-.YYYY.-.#####`.

| Field | Req | Notes |
|---|---|---|
| `stock_entry_type` | yes | `Material Receipt`, `Material Issue`, `Material Transfer`, `Manufacture`, `Repack` |
| `purpose` | yes | derived from `stock_entry_type` |
| `posting_date`, `posting_time` | yes | |
| `company` | yes | |
| `from_warehouse` / `to_warehouse` | one or both | depends on purpose; transfer needs both |
| `is_opening` | no | `Yes` to mark opening balance entries (no GL impact if before fiscal start) |

Child table `items` (Stock Entry Detail):
- Required: `item_code`, `qty`, `s_warehouse` and/or `t_warehouse`, `basic_rate` (for inflows / valuation).
- Optional: `batch_no`, `serial_no`, `uom`, `conversion_factor`.

### Stock Reconciliation
Naming: series `MAT-STR-.YYYY.-.#####`. Preferred for **opening stock migration** of non-serialized items.
- Required: `purpose` (`Opening Stock` or `Stock Reconciliation`), `posting_date`, `company`.
- Child table `items`: `item_code`, `warehouse`, `qty`, `valuation_rate`. Setting `qty=0` writes off stock.

---

## Dependency / import order

Strict order (each step depends on prior). Within a step, child rows of any doctype depend on their parent row being inserted first — Frappe Data Import handles this if all rows are in the same file.

1. **Company**, **Currency**
2. **UOM**
3. **Account** (Chart of Accounts) — roots → groups → leaves; or bulk via CoA Importer
4. **Warehouse** (tree)
5. **Item Group**, **Customer Group**, **Supplier Group**, **Territory** (trees, roots first)
6. **Price List**
7. **Item** → then **Item Price**, **Item UOM Conversions** (child of Item)
8. **Customer**, **Supplier**
9. **Address**, **Contact** (with Dynamic Links pointing to existing Customer/Supplier)
10. **Stock Reconciliation** (opening stock) — before any sales/purchase that consumes stock
11. **Sales Invoice** + Sales Invoice Item (child rows in same file)
12. **Purchase Invoice** + Purchase Invoice Item

---

## Sample CSV import row (Sales Invoice with two line items)

ERPNext Data Import flattens parent + child into one CSV. Parent fields appear once in the first row of a group; each item line repeats the parent ID.

```csv
ID,Customer,Posting Date,Due Date,Company,Currency,Conversion Rate,Selling Price List,Debit To,ID (Items),Item Code (Items),Qty (Items),Rate (Items),UOM (Items),Warehouse (Items)
,ACME Corp,2025-01-15,2025-02-14,GTPL,USD,1.0,Standard Selling,Debtors - GTPL,,WIDGET-001,10,15.00,Nos,Stores - GTPL
,,,,,,,,,,WIDGET-002,5,42.50,Nos,Stores - GTPL
```

The blank `ID` column tells the importer to autoname; subsequent rows with empty parent fields are treated as additional child rows of the previous parent. Mandatory columns are red in the downloaded template; dependent (linked) columns are yellow.

---

## Common gotchas

- **Master order matters.** Item creation fails if `item_group` doesn't exist; Customer fails without `customer_group` and `territory`; Account fails without `parent_account`.
- **Warehouse name suffix.** Warehouses and ledger Accounts auto-append ` - <company_abbr>`; legacy CSVs that store just `Stores` must be transformed to `Stores - GTPL`.
- **Stock UOM is immutable** once an item has stock movements. Fix it before any Stock Reconciliation/Stock Entry runs.
- **Don't use Item.opening_stock for migration** of more than a handful of items. Use Stock Reconciliation with `purpose=Opening Stock` per warehouse — it handles valuation rate, batch/serial properly.
- **Chart of Accounts Importer overwrites** all existing accounts for that company. Run it on a fresh company only; never after the first transaction.
- **Sales/Purchase Invoice currency vs company currency.** `conversion_rate` is mandatory and must equal 1.0 if the invoice currency equals the company default currency. Forgetting this is a frequent import failure.
- **Receivable / Payable accounts** (`debit_to`, `credit_to`) must have `account_type = "Receivable"` / `"Payable"` and match the invoice currency, otherwise submission fails.
- **Submission state.** Invoices and Stock Entries are submittable; rows imported as draft (`docstatus=0`) will not affect GL or stock until submitted. Set `docstatus=1` in the import to submit immediately.
- **Address/Contact linkage uses Dynamic Link child rows**, not a flat field. Each row needs `link_doctype`, `link_name`, `link_title`.
- **Naming series must be enabled.** If you import a Sales Invoice with `naming_series="ACC-SINV-.YYYY.-"` but that series isn't in the Naming Series doctype, the import fails. Either pre-create the series or pass an explicit `name`.
- **Tax rows reference Account links** that must already exist with `account_type="Tax"`.
- **Item Price is its own doctype** — set `standard_rate` on Item to seed it, but for multi-price-list migrations, import Item Price rows separately keyed by `(item_code, price_list, uom)`.

---

## Source references (docs.frappe.io / docs.erpnext.com)

- `/erpnext/data-import` — template format, mandatory/dependent highlighting
- `/erpnext/chart-of-accounts`, `/erpnext/chart-of-accounts-importer`
- `/erpnext/customer`, `/erpnext/supplier`, `/erpnext/selling-settings`, `/erpnext/buying-settings`
- `/erpnext/item-price`, `/erpnext/price-lists`, `/erpnext/stock-settings`
- `/erpnext/sales-invoice`, `/erpnext/purchase-invoice`, `/erpnext/sales-integration`
- `/erpnext/stock-entry-purpose`, `/erpnext/stock-reconciliation`, `/erpnext/opening-stock`
- `/erpnext/address`, `/erpnext/contact`, `/erpnext/naming-series`
- Doctype JSON definitions: `github.com/frappe/erpnext/blob/develop/erpnext/<module>/doctype/<doctype>/<doctype>.json` (authoritative for `reqd`, `fieldtype`, `options`).
