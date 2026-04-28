# Al Arabi ERP System - Data Model & Domain Analysis

## Overview
The Al Arabi legacy ERP is a Turkish/Arabic retail and accounting system with ~137 CSV tables. Primary domains: items/inventory, customers/suppliers, accounting, sales/purchase documents, POS, and users. Data is heavily denormalized with multi-language fields (Turkish, English, Arabic — CATNAME, CATNAMEE, CATNAMEH patterns).

---

## Domain Groups & Core Tables

### 1. ITEMS & PRODUCT CATALOG
**Purpose:** Master data for products/items sold in retail.

#### Core Tables:

**CATEGORYT** (19,176 rows)
- PK: `CATID` (barcode; e.g., 7290005369148)
- Columns: `CATNAME` (Ar), `CATNAMEE` (En), `CATNAMEH` (He), `BARCODE`, `UNIT` (base unit ID), `DEFAULTUNIT`, `SETNO` (set/bundle ID), `QTYTYPE`, `COSTTYPE`
- Denormalized stock fields: `STARTQTY`, `QTYBALANCE`, `QUANTITY`, `MINQTY`, `MAXQTY`, `CATCOUNT`, `CATCOUNTBALANCE`
- Links to: `SETST` (SETNO→SETID for bundles), `UNITT` (UNIT→UNITID), `CATSTORET` (store-level stock)

**CATPRICET** (38,341 rows)
- PK: `PRICEID`
- FK: `CATID` (many prices per item)
- Columns: `SALEPRICE`, `MINSALEPRICE`, `DISCOUNT`, `SALECUR` (currency), `VATTYPE`, `CHANGEDATE`, `PUID` (user audit), `NOTES`
- Purpose: Price lists & discounts by item/currency

**CATSTORET** (6,553 rows)
- Composite key: `CATID`, `STOREID`
- Denormalized per-store stock: `STARTQTY`, `QTYOUT`, `QTYIN`, `QTYBALANCE`, `QUANTITY`, `STOREMINQTY`, `STOREMAXQTY`, `INVENTORYQTY`
- Audit: `CHANGEDATE`, `SQCHANGEDATE`, `SQPUID`

**CATSUPPLIERT** (27,229 rows)
- Composite key: `CATID`, `SUPPLIER` (FK to SUPPLIERT.SUPPID)
- Columns: `ORGID`, `INSERTDATE`, `PUID`
- Purpose: Item-Supplier mapping (links products to suppliers)

**UNITT** (22 rows)
- PK: `UNITID` (e.g., 1, 2, 3…)
- Columns: `UNITNAME` (Ar), `UNITNAMEE` (En), `UNITNAMEH` (He)
- Purpose: Master unit of measure (box, piece, kg, etc.)

**SETST** (56 rows)
- PK: `SETID`
- Columns: `SETNO` (numeric identifier), `SETNAME` (Ar/En/He), `CLASS`, `SETCOLOR`, `PUID`
- Purpose: Product bundles/kits

**Supporting Tables (Optional):**
- `CATDESCT` (46): Item descriptions (RTF-encoded)
- `CATESYNONYMT` (16,347): Alternative item names/codes
- `CATEQUATIONT` (859): Unit conversion rules (equalities between items)
- `CATLEDGERT`: Item-level ledger/history (minimal business value)
- `CATCHANGEST`: Change audit log (skip)
- `CATPICST`: Item pictures metadata
- `CATPRICECHANGEST`, `CATPURCHPRICECHANGEST`: Price history (audit logs)

---

### 2. PARTIES: CUSTOMERS & SUPPLIERS
**Purpose:** Master data for all business partners (customers, suppliers, internal partners).

#### Core Tables:

**CUSTT** (2,229 rows)
- PK: `CUSTID` (maps to ACCOUNT ID in GL)
- FK: `ACCOUNT` (GL account), `PRICEID` (default price list)
- Columns: `RESELLERNO`, `DUEDAYS` (payment terms), `DISCOUNT`, `BANK`, `BANKACCOUNTNO`, `DEFAULTSTOREID`, `THROUGHCUSTID` (reseller hierarchy), `PAYMETHOD`
- Audit: `CHANGEDATE_DATA`
- Special: SAT/SUN/MON/TUE/WED/THU/FRE (visit schedule flags)
- Links: GL account via `ACCOUNT`, price list via `PRICEID`

**SUPPLIERT** (802 rows)
- PK: `SUPPID` (maps to GL account)
- FK: `ACCOUNT` (GL account), `DEFAULTSTOREID`
- Columns: `RESELLERNO`, `DISCOUNT`, `CHEQUEPERIOD`, `BANK`, `BANKACCOUNTNO`, `LONGIVITY`, `SPICVATVALUE`, `CLEARINGINV`
- Purpose: Supplier master (linked to GL accounts)

**PARTNERT** (4 rows)
- PK: `PARTNERID`
- Columns: `ACCOUNT`, `SHARERATIO`, `SHAREAMOUNT`, `STARTDATE`
- Purpose: Partnership shares/ownership

**Supporting Tables (Optional):**
- `CONTACTST`: Contact details (skip for now)

---

### 3. ACCOUNTING & GENERAL LEDGER
**Purpose:** GL accounts, chart of accounts, GL entries, and balance tracking.

#### Core Tables:

**ACCOUNTT** (3,574 rows)
- PK: `ACCOUNTID`
- FK: `FATHERID` (parent account for hierarchical COA), `CURID` (currency)
- Columns: `NAME` (Ar), `NAMEE` (En), `NAMEH` (He), `DETAILID`, `ALEVEL` (depth in hierarchy), `CLASS` (account type), `FATHER` (foreign key copy), `CREATEDATE`, `ENDDATE`
- Balance fields (multi-currency): `MDEBIT`, `MCREDIT`, `MBALANCE` (main curr), `ADEBIT`, `ACREDIT`, `ABALANCE` (alt curr), `MSDEBIT`, `MSCREDIT`, `MSBALANCE`, `ASDEBIT`, `ASCREDIT`, `ASBALANCE` (sub-accounts)
- GL entry limits: `MAXENTRYDB`, `MAXENTRYCR`
- Audit: `CHANGEDATE_DATA`, `CHANGEDATE_BAL`, `PUID`, `LASTUPDATE`
- Status: `STATUS`, `CASHSALE`, `NEEDAPPROVAL`, `BANKACCID`
- Links: `BANKACCID` (if bank account)

**LEDGERT** (869,201 rows)
- PK: `ENTRYID`
- FK: `ENTRYACCOUNT` (GL account ID), `ENTRYCUR` (currency), `PROJECTID`, `RESALERID`
- Columns: `ENTRYNO` (sequence), `ENTRYDEBIT`, `ENTRYCREDIT`, `ENTRYVALUE`, `MENTRYDEBIT`, `MENTRYCREDIT`, `MENTRYVALUE` (multi-currency versions)
- Audit: `INSERTDATE`, `ENTRYTRANSDATE`, `PUID`
- Links: Cheques via `CHEQUEID`, Bank entries, Projects, Resellers
- **This is the transactional heart of GL** — every debit/credit passes through here

**ACCSUBT** (1,761 rows)
- Composite key: `ACCOUNTID`, `ACCSUBID`
- Columns: `SUBMCREDIT`, `SUBMDEBIT`, `SUBMBALANCE`, `SUBACREDIT`, `SUBADEBIT`, `SUBABALANCE`, etc.
- Purpose: Sub-account balances (detail tracking per account)

**ACCCLASST** (41 rows)
- PK: `CLASSID`
- Columns: `CLASSNAME`, `SYSTEM`, `CANHAVECHEQUE`, `CORDER` (sort order), `PARTIN`
- Purpose: Account type/class master (Asset, Liability, Equity, etc.)

**Supporting Tables (Skip):**
- `ACCLISTST`, `ACCLISTSINFOT`: GL list/report templates
- `ACCSUBCLASST`, `ACCSUBPROPT`: Sub-account properties (minimal value)

---

### 4. SALES & PURCHASE DOCUMENTS
**Purpose:** Invoice, return, and delivery document tracking with line-item details.

#### Core Tables (Header/Detail Pattern):

**CATESINVDOCT** (146,062 rows) + **CATESINVDOCDETT** (1,039,911 rows)
- **Header**: PK `DOCSERIAL`, `DOCNO`, `INVTYPE` (1=sales invoice, 2=return, etc.)
  - FK: `ACCOUNTID` (customer), `STOREID`, `RESALERID`
  - Columns: `NAME` (customer name Ar/En/He), `ADDRESS`, `AREAID`, `DOCDATE`, `DOCTIME`, `DUEDATE`, `INSERTDATE`
  - Amounts: `TOTALPRICE`, `TOTALVAT`, `DISCOUNT`, `DOCVALUE` (total inc VAT)
  - Audit: `PUID`, `CHANGEDATE_DATA`
- **Detail**: PK `DOCNO`, `INVTYPE`, `SERIAL`, `DETORDER`
  - FK: `CATID` (item), `STOREID`
  - Columns: `CATNAME` (item name Ar/En/He), `CATQTY`, `CATPRICE`, `CATDISCOUNT`, `CATBONUS`, `CATCOUNT` (counted qty if applicable)
  - Multi-language units: `CATUNIT`, `CATUNITE`, `CATUNITH`
  - VAT: `VATYPE`, `SALEACCID` (GL account for this line)
  - Denormalized: `CATPRICEWOV` (price without VAT), `DISCOUNTVWOV`
- **Relationships**: Each header 1:many with details; FK to customers/accounts; FK to items; cross-refs GL accounts
- **Business value**: Core sales transaction log

**CATEPINVDOCT** (2,580 rows) + **CATEPINVDOCDETT** (14,975 rows)
- Purchase invoices from suppliers (same structure as CATESINVDOCT)
- PK: `DOCSERIAL`, `DOCNO`, `INVTYPE`
- FK: `ACCOUNTID` (supplier), `STOREID`
- Purpose: Inbound goods receipt + cost tracking

**CATESINVDOCT variants (Returns & Pre-Returns):**
- `CATESRETINVDOCT` (sales returns header) + `CATESRETINVDOCDETT` (return lines) — similar structure
- `CATEPRETINVDOCT` (purchase return header) + `CATEPRETINVDOCDETT` (purchase return lines)

**ENTRYDOCT** (2,752 rows) + **ENTRYDOCDETT** (14,484 rows)
- General journal entries / Manual GL postings
- **Header**: PK `DOCSERIAL`, `DOCNO`
  - Columns: `MANUALNO`, `BOOKNO`, `DOCDATE`, `DUEDATE`, `DOCVALUE` (total entry), `PROJECTID`, `RESALERID`
- **Detail**: PK `DOCNO`, `SERIAL`
  - FK: `ACCOUNTID` (account being debited/credited), `ACCSUBID` (sub-account)
  - Columns: `DEBIT`, `CREDIT`, `BALANCE`, `NOTES`
  - Multi-currency: `CURID`, `CURVALUE`, `MDEBIT`, `MCREDIT`, `MBALANCE`
  - Cheque link: `CHEQUEID` (if payment by cheque)
- Purpose: Manual journal entries (AR adjustments, depreciation, etc.)

**Supporting Document Types:**
- `BANKENTRYDOCT` + `BANKENTRYDOCDETT`: Bank reconciliation entries
- `RECDOCT` + `RECDOCDETT`: Receiving/delivery documents
- `CNOTEDOCT` + `CNOTEDOCDETT`: Credit notes
- `DNOTEDOCT` + `DNOTEDOCDETT`: Debit notes
- `PAYDOCT` + `PAYDOCDETT`: Payment documents
- `DIVISIONDOCT` + `DIVISIONDOCDETT`: Stock division/transfer documents

---

### 5. INVENTORY & STOCKTAKING
**Purpose:** Physical stock counts and inventory adjustments.

#### Core Tables:

**STOCKTAKINGT** (4 rows)
- PK: `STOCKID`, `INVTYPE`
- Columns: `STOREID`, `SDATE` (count date), `USEDATE` (finalization date), `POSTFLAG` (0=draft, 1=posted)
- Audit: `PUID`, `INSERTDATE`, `POSTDATE`, `POSTPUID`, `POSTNOTE`
- Purpose: Stocktake session header

**STOCKTAKINGDETT** (3,965 rows)
- FK: `STOCKID` (header), `CATID` (item)
- Columns: `CATQTY` (system qty), `CATCOUNT` (counted qty), `QTYWHENPOST` (final qty), `CHANGESETNO` (batch ID), `COSTPRICE`, `COSTCURID`
- Audit: `PUID`, `INSERTDATE`, `INSERTTIME`
- Purpose: Physical count line items; delta between CATQTY and CATCOUNT drives GL adjustments

**STARTENTRYDOCT** + **STARTENTRYDOCDETT**
- Opening balance / period start entries (minimal rows)

**STORET** (2 rows)
- PK: `STOREID`
- Columns: `DESCRIPTION` (Ar/En/He), `MANAGER`, `PHONE`, `LOCATION`
- Purpose: Warehouse/store master (where stock is held)

---

### 6. POS (Point of Sale)
**Purpose:** Retail POS terminals, promotions, and card-based payment tracking.

#### Core Tables:

**SALEPOINTT** (7 rows)
- PK: `SALEPOINTID`
- FK: `STOREID`, `PRICELISTID`, `PROJECTID`
- Columns: `SPNAME`, `SPLOCATION`, `NOTES`
- Purpose: POS terminal master

**POS_PROMOTIONT** (36 rows)
- PK: `PROMID`
- Columns: `PROMNAME`, `PROMTYPE`, `ISACTIVE`, `FROMDATE`, `TODATE`, `PRIO` (priority)
- Promotion mechanics: `X`, `Y`, `Z` (thresholds/tiers), `SET1ALLITEMS`, `SET2ALLITEMS`, `DONTEXCLUDEOTHERS`, `PROMCATID`
- Purpose: Promotional rules (bundles, discounts, buy-X-get-Y)

**POSCARDT** & **POSCARDSETST** & **POSPAYST**
- POS card loyalty/payment methods (small tables, limited value)

**POSFAVT**
- Favorite items for quick-recall POS (skip)

---

### 7. BANKING & FINANCIAL INSTRUMENTS
**Purpose:** Bank accounts, cheques, and bank-to-GL reconciliation.

#### Core Tables:

**BANKT** (78 rows)
- PK: `BANKID`
- Columns: `BANKNAME` (Ar/En/He), `BANKTYPE`
- Purpose: Bank master reference

**BANKACCOUNTT** (10 rows)
- PK: `BANKACCID`
- FK: `BANKID` (which bank), `COMMACCID` (commission GL account)
- Columns: `ACCOUNTNO` (account number at bank), `TYPEA`, `TYPEB`, `TYPEC`, `TYPED` (account subtypes), `BRANCHNAME`, `BANKACCOWNERNAME`, `PHONE`, `FAX`, `ADDRESS`
- Purpose: Bank account master (links GL accounts to actual bank accounts)

**CHEQUET** (1,820 rows)
- PK: `CHEQUEID`
- FK: `ACCOUNTID` (GL account), `BANKACC` (bank account), `CURID` (currency)
- Columns: `CHEQUENO`, `CDATE` (cheque date), `REALCDATE` (clearing date), `CVALUE`, `CMVALUE` (multi-curr), `CLASS` (cheque type), `OWNERNAME`, `SOURCEACCOUNTID`
- Audit: `PUID`
- Purpose: Cheque master (every cheque issued/received is tracked)

**CHEQUELEDGERT** (1,199 rows)
- FK: `CHEQUEID`, `DOCSERIAL`, `DOCID` (which document posted the cheque)
- Columns: `PREVACCOUNT`, `CURRACCOUNT` (cheque account movement tracking), `TDATE` (transition date), `ISDELETED`
- Purpose: Cheque GL posting history (prevents double-posting)

**BANKENTRYDOCT** + **BANKENTRYDOCDETT**
- Bank reconciliation batches and line items

---

### 8. USERS & PERMISSIONS
**Purpose:** User accounts, roles, and audit trails.

#### Core Tables:

**PUSERT** (16 rows)
- PK: `PUID` (user ID)
- Columns: `PUNAME` (Ar), `PUUSERNAME`, `PUPASSWORD`, `PU_ACTIVE_2101` (active flag), `PUGROUP` (role group)
- Permissions: `POSONLY`, `USERDOCS` (allowed document types), `DEFAULTSTOREID`, `DEFAULTPROJECTID`
- Audit: `PUID` is used in most other tables as audit trail (WHO created/modified)
- **Note**: Will likely not migrate to ERPNext if using SSO/OAuth

**EMPLOYEET** (132 rows)
- FK: `ACCOUNT` (GL account for salary), `EMPID`
- Columns: `IDNO`, `BIRTH`, `STARTTIME`, `ENDTIME`, `CARDID`, `SALARY`, `VOCDAY`, `EMPSTATUS`
- Purpose: HR data (salaries, attendance); minimal business value for current ETL

**Supporting:**
- `PUSERGROUPT`: User groups/roles (skip if SSO planned)
- `PUSERPRIVILEGEST`: Permission matrix (granular perms)
- `PUSERLOGT`: User login audit log (skip)
- `PUSERREPSECT`: User report settings

---

### 9. REFERENCE & CONFIGURATION TABLES
**Purpose:** Constants, currencies, areas, projects, and system configuration.

#### Core Tables:

**CURT** (5 rows)
- PK: `CURID`
- Columns: `CURNAME` (Ar), `CURSHORT` (code like "TRY", "USD"), `CURVALUE` (exchange rate to base), `DEFAULTCASHBOX`
- Purpose: Currency master (for multi-currency accounting)

**AREAT** (514 rows)
- PK: `AREAID`
- FK: `RESALERID` (reseller/branch this area belongs to)
- Columns: `AREANAME` (Ar/En/He), `AREAGROUPID`, `ITINERARYID`, visit schedule flags (SAT/SUN/MON/etc.)
- Purpose: Sales territories / delivery zones

**PROJECTST** (2 rows)
- PK: `PROJECTID`
- Columns: `NAME`, `ACCOUNTID` (project GL account), `STATUS`
- Purpose: Cost center / project master (for job costing)

**UNITT** (see Items section)
- Unit of measure master

**CONSTT** (635 rows)
- System constants (numeric parameters, thresholds, defaults)
- Columns: `CONSTNAME`, `CONSTSV` (string value), `CONSTFV` (float), `CONSTTV` (text)
- Purpose: Configuration parameters

**PRICETYPET** (3 rows)
- PK: `PRICEID`
- Columns: `PRICENAME`, `PRICENOTE`
- Purpose: Price list types

**OPENPERIODT** (5 rows)
- PK: `GID`
- Columns: `PERIODTYPE`, `FROMDATE`, `TODATE`, `VACATION`, `USEDDOCS`
- Purpose: Accounting periods / fiscal calendar

---

## Skip List: Low/No Business Value Tables

**Logging & Audit (Skip):**
- `BACKUPLOGT` (275): Database backup log
- `SQLLOGT` (1,240): SQL query log
- `EMPLOGT` (6,657): Employee login/attendance log
- `PUSERLOGT` (2,468): User login audit
- `DOCLOGST`: Document logging
- `EXCEPTIONST` (2): Exception stack traces

**System & UI (Skip):**
- `DICTIONARYT` (1,085): Spell-check / term dictionary
- `CLIPBOARDT` (6): Copy-paste clipboard
- `MONITORT` (463,901): **HUGE** — system performance monitoring (useless for business)
- `DATEST`: Date constants (internal use)
- `FIXT`: System fixtures
- `HEADERT`: Report headers
- `SHEETSTABLET`: Spreadsheet configuration
- `PMENUT`, `VISIBLEMENUT`, `FAVMENUT`: Menu configuration UI
- `DASHBOARDST`, `DASHBOARDSECT`: Dashboard layouts
- `SPEEDINFOT`: Cache/speed metrics

**Replication Snapshots (Skip — Duplicates of main tables):**
- `RPLC_ACCOUNTT`, `RPLC_CATEGORYT`, `RPLC_CUSTT`, `RPLC_CATEQUATIONT`, `RPLC_CATDESCT`, `RPLC_CATESYNONYMT`, `RPLC_CATPRICET`, `RPLC_ACTIVATIONT`, `RPLC_CONSTT`, `RPLC_LISTST`, `RPLC_POS_PROMOTIONT`, `RPLC_POS_PROMOTIONSETST`, `RPLC_SALEPOINTT`, `RPLC_BALS_ACCOUNTT`, `RPLC_BALS_CATEGORYT`, `RPLC_PUSERT`
  - These are replication change-data-capture snapshots for syncing to mobile/branch systems — **drop entirely**

**Deleted/Archive (Skip):**
- `DELETEDACCOUNTT` (27): Deleted GL accounts
- `DELETEDCATEGORYT` (12): Deleted items
- `DELETED_SINVDETT`: Deleted invoice lines

**Low-Value Masters (Optional Skip):**
- `ATTCATALOGT`: Attachment catalog (file metadata)
- `GS1PREFIXT`: GS1 barcode prefixes (reference only)
- `SERIALIZET`: Serial number master (minimal use for non-tracked items)
- `RESALERT`: Resale alert flags
- `INTERNALMAILT`: Internal messaging (skip)
- `LISTST`: Generic lists / data dictionary

---

## Data Model Summary

### Foreign Key Patterns:

**Customer ↔ GL Account:**
```
CUSTT.ACCOUNT → ACCOUNTT.ACCOUNTID
CUSTT.PRICEID → CATPRICET.PRICEID
```

**Item ↔ Prices ↔ Stores:**
```
CATEGORYT.CATID ← CATPRICET.CATID
CATEGORYT.CATID ← CATSTORET.CATID
CATSTORET.STOREID → STORET.STOREID
```

**Invoice Header ↔ Details ↔ GL:**
```
CATESINVDOCT.DOCNO ← CATESINVDOCDETT.DOCNO
CATESINVDOCT.ACCOUNTID → ACCOUNTT.ACCOUNTID (customer)
CATESINVDOCDETT.CATID → CATEGORYT.CATID (item)
CATESINVDOCDETT.SALEACCID → ACCOUNTT.ACCOUNTID (revenue account)
```

**GL Entry ↔ Document ↔ Cheque:**
```
LEDGERT.ENTRYACCOUNT → ACCOUNTT.ACCOUNTID
LEDGERT.CHEQUEID → CHEQUET.CHEQUEID
CHEQUET.ACCOUNTID → ACCOUNTT.ACCOUNTID
```

### Key Technical Observations:

1. **Denormalization:** Stock quantities (QTY*, BALANCE*) are stored in both CATEGORYT and CATSTORET — denormalized from inventory transactions.
2. **Multi-Language Fields:** Ar/En/He suffixes on all text fields (NAME, NAMEE, NAMEH).
3. **Audit Trail:** Every table has a `PUID` (user) and `CHANGEDATE_*` columns for who/when tracking.
4. **Multi-Currency:** Most amounts stored in base currency (M*) and alternate (A*) plus original (plain) columns.
5. **Hierarchies:** GL accounts (FATHERID→ACCOUNTID), Items (THROUGHCUSTID for resellers), Areas (AREAGROUPID).
6. **Large Transactional Tables:**
   - LEDGERT (869K GL entries) — heart of system
   - CATESINVDOCDETT (1M+ invoice lines) — core sales
   - CATSTORET (6.5K store-item combos) — stock tracking

---

## Recommended Priority for Migration

### Tier 1 (MUST HAVE):
1. ACCOUNTT + ACCCLASST + ACCSUBT + LEDGERT — GL foundation
2. CUSTT + SUPPLIERT — Party master
3. CATEGORYT + CATPRICET + CATSTORET + UNITT — Item master
4. CATESINVDOCT + CATESINVDOCDETT (sales invoices)
5. CATEPINVDOCT + CATEPINVDOCDETT (purchase invoices)
6. CATESINVDOCT variants (returns)

### Tier 2 (ESSENTIAL):
7. CHEQUET + CHEQUELEDGERT — Payment tracking
8. BANKT + BANKACCOUNTT — Bank master
9. STOCKTAKINGT + STOCKTAKINGDETT — Inventory adjustments
10. ENTRYDOCT + ENTRYDOCDETT — Manual GL entries
11. STORET + AREAT — Warehouse/territory masters

### Tier 3 (NICE-TO-HAVE):
12. SALEPOINTT + POS_PROMOTIONT — POS configuration
13. PROJECTST + OPENPERIODT — Cost centers & periods
14. EMPLOYEET (if payroll needed)
15. PUSERT (if migrating user access; SSO likely makes this obsolete)

### Tier 4 (DROP):
- All RPLC_*, DELETED*, logging, monitoring tables
- Menu, Dashboard, UI configuration tables

---

## Open Questions / Risks

1. **INVESTORYQTY vs QUANTITY:** What is the difference between `CATSTORET.INVENTORYQTY` and `CATSTORET.QUANTITY`? Which is the "source of truth"?
2. **MONITORT Table (463K rows):** Is this still actively written to? If so, it will slow ETL. Recommend excluding entirely.
3. **Encoding:** Data appears to be UTF-8 with Arabic/Turkish content. Confirm character set on import.
4. **Missing Document Types:** Are there custom document types (workflows) not captured in the standard CATE*INVDOC* pattern?
5. **GL Posting Dates:** Clarify if `CHANGEDATE_DATA` vs `CHANGEDATE_BAL` differ and which should be used for period cutoff.
6. **Exchange Rates:** CURT.CURVALUE is static — is there a historical rate table (not visible here)?
7. **Cheque Clearing:** How long are cheques held in CHEQUET after posting? Is REALCDATE populated for all cleared cheques?

