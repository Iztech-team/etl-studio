"""Opening balances — the new heart of the migration.

Replaces invoice/payment/journal emission. Instead of full transaction
history, we emit one Journal Entry per non-zero leaf GL account in legacy:

- Customer balances → JE with `party_type=Customer`
- Supplier balances → JE with `party_type=Supplier`
- Bank / Cash / VAT / Capital / Drawings / etc → JE plain
- Outstanding incoming cheques → individual JE per CHEQUET row

**Sign rule** (universal, no per-account-type special-casing):
    AACCBALANCE > 0 → DEBIT  the account, CREDIT Temporary Opening
    AACCBALANCE < 0 → CREDIT the account, DEBIT  Temporary Opening
The legacy already encoded which side via the sign — we just follow it.

**Multi-currency**: balances convert to default currency (ILS) using
`CURT.CURVALUE`. Original amount + rate preserved in `user_remark` for
audit traceability.

**Skipped from generic GL emit** (handled elsewhere or are P&L roots):

- Customer (CLASS=2) / Supplier (CLASS=3) leaves → party JE branch
- Inventory (CLASS=40/41/42) → handled by Stock Reconciliation
- Group / parent accounts → auto-aggregate from children in ERPnext
- Revenue (root 5) / Expense (root 4) accumulators → close annually
- GL 118 (Cheques for Collection) → handled per-cheque
"""
from typing import Any

from core.strategies.erpnext_shared.common import (
    CURRENCY_BY_LEGACY_ID,
    DEFAULT_CURRENCY,
    account_full_name,
    clean_str,
    currency_iso,
    customer_id,
    parse_date,
    parse_decimal,
    pick,
    supplier_id,
)
from core.strategies.erpnext_shared.context import Context
from core.strategies.erpnext_shared.masters import bank_gl_leaf_to_label

# Skip rounding noise — anything below this in absolute terms is treated as zero.
BALANCE_THRESHOLD = 0.01

# Legacy date sentinel for "never set" — REALCDATE uses this until cleared.
SENTINEL_DATE = "1899-12-30"

# Legacy CLASS values we route to party-balance branch instead of generic GL.
CUSTOMER_CLASS = "2"
SUPPLIER_CLASS = "3"

# Legacy CLASS values for inventory (handled by Stock Reconciliation, not here).
INVENTORY_CLASSES = {"40", "41", "42"}

# Legacy ACCOUNTIDs whose balance is reconstructed via individual cheque JEs.
SPECIAL_HANDLED_IDS = {"118"}


def emit_opening_balances(ctx: Context) -> None:
    """Top-level: emit opening JEs for every non-zero leaf GL account."""
    if not ctx.config.opening_date:
        ctx.result.warn(
            "OpeningBalance",
            "no opening_date configured — skipping all opening emit",
        )
        return
    fx_rates = _fx_rates(ctx)
    parent_ids = _parent_id_set(ctx)
    customer_index = _party_name_index(ctx, role="customer")
    supplier_index = _party_name_index(ctx, role="supplier")
    bank_gl_to_label = _bank_gl_to_bank_account(ctx)

    _emit_party_balances(ctx, fx_rates, "customer", customer_index, parent_ids)
    _emit_party_balances(ctx, fx_rates, "supplier", supplier_index, parent_ids)
    _emit_gl_balances(ctx, fx_rates, parent_ids, bank_gl_to_label)
    _emit_outstanding_cheques(ctx, fx_rates)


# -- Party balances (customers + suppliers) -----------------------------------

def _emit_party_balances(
    ctx: Context,
    fx_rates: dict[str, float],
    role: str,
    name_index: dict[str, str],
    parent_ids: set[str],
) -> None:
    """Emit one opening JE per customer/supplier account with non-zero balance.

    Legacy holds each party's net owing in their per-party GL account
    (CLASS=2 for customers, CLASS=3 for suppliers). That's already
    post-cheque-received in legacy's accounting — we mirror it directly
    as an opening receivable/payable in ERPnext, linked via party_type.

    Group accounts (e.g. 611 'حساب الزبائن' which parents the customer
    leaves) carry an aggregated AACCBALANCE; we skip those to avoid
    double-counting against the per-customer leaves underneath.
    """
    is_customer = role == "customer"
    target_class = CUSTOMER_CLASS if is_customer else SUPPLIER_CLASS
    party_account = ctx.with_abbr("Debtors") if is_customer else ctx.with_abbr("Creditors")
    party_type = "Customer" if is_customer else "Supplier"
    fallback_id = customer_id if is_customer else supplier_id
    name_prefix = "OPN-CUST" if is_customer else "OPN-SUPP"
    stat_key = f"opening_{role}_balances"

    for row in ctx.table("ACCOUNTT"):
        if clean_str(row.get("CLASS")) != target_class:
            continue
        account_id = clean_str(row.get("ACCOUNTID"))
        if not account_id or account_id in parent_ids:
            continue
        balance = parse_decimal(row.get("AACCBALANCE"))
        if abs(balance) < BALANCE_THRESHOLD:
            ctx.result.bump(f"{stat_key}_skipped_zero")
            continue
        balance_default, original_remark = _to_default(balance, row, fx_rates)
        # Skip if conversion produced a sub-threshold balance.
        if abs(balance_default) < BALANCE_THRESHOLD:
            ctx.result.bump(f"{stat_key}_skipped_zero")
            continue
        party_name = pick(row, "NAME", "NAMEE", "NAMEH")
        # Resolve to ERPnext Customer / Supplier doctype name. Falls back
        # to CUST-{ACCOUNTID} for orphan-style accounts (matches the
        # naming used by parties.emit_orphan_customers).
        party = name_index.get(account_id) or fallback_id(account_id)
        ctx.result.emit("Journal Entry", _build_party_je(
            ctx,
            name=f"{name_prefix}-{account_id}",
            party_type=party_type,
            party=party,
            party_account=party_account,
            balance=balance_default,
            original_remark=original_remark,
            party_name=party_name,
            legacy_acctid=account_id,
        ))
        ctx.result.bump(f"{stat_key}_emitted")


def _build_party_je(
    ctx: Context,
    name: str,
    party_type: str,
    party: str,
    party_account: str,
    balance: float,
    original_remark: str,
    party_name: str,
    legacy_acctid: str,
) -> dict[str, Any]:
    """Customer / Supplier opening JE — both lines in default (ILS) currency.

    Debtors / Creditors are deliberately ILS-only in the CoA emit, so any
    foreign-currency customer/supplier balance has been pre-converted to
    ILS by the caller (see `_to_default`). Both lines therefore use ILS
    with `exchange_rate=1.0`.
    """
    abs_amt = round(abs(balance), 2)
    party_line: dict[str, Any] = {
        "account": party_account,
        "party_type": party_type,
        "party": party,
    }
    counter_line: dict[str, Any] = {"account": ctx.with_abbr("Temporary Opening")}
    _set_je_pair(
        party_line, counter_line, abs_amt,
        company_amount=abs_amt,
        debit_main=balance > 0,
        main_currency=DEFAULT_CURRENCY, main_rate=1.0,
        counter_currency=DEFAULT_CURRENCY, counter_rate=1.0,
    )
    return {
        "name": name,
        "voucher_type": "Opening Entry",
        "is_opening": "Yes",
        "company": ctx.config.company_name,
        "posting_date": ctx.config.opening_date,
        "user_remark": f"Opening balance — {party_name}{original_remark}",
        "docstatus": 1,
        "accounts": [party_line, counter_line],
        "total_debit": abs_amt,
        "total_credit": abs_amt,
        "multi_currency": 0,
        "legacy_acctid": legacy_acctid,
        "legacy_kind": "opening_party",
    }


# -- Generic GL balances ------------------------------------------------------

def _emit_gl_balances(
    ctx: Context,
    fx_rates: dict[str, float],
    parent_ids: set[str],
    bank_gl_to_label: dict[str, str],
) -> None:
    """Emit JE per leaf GL account with non-zero balance.

    Skips: party leaves (handled above), inventory (stock recon), parent
    groups (auto-aggregate), P&L roots (4/5), and special-handled IDs.
    """
    for row in ctx.table("ACCOUNTT"):
        if not _is_emittable_gl(row, parent_ids):
            continue
        balance = parse_decimal(row.get("AACCBALANCE"))
        if abs(balance) < BALANCE_THRESHOLD:
            ctx.result.bump("opening_gl_balances_skipped_zero")
            continue
        account_id = clean_str(row.get("ACCOUNTID"))
        # Preserve the GL account's native currency on the main line —
        # ERPnext requires `debit_in_account_currency` to match the
        # account's own currency. Conversion to company currency happens
        # via `exchange_rate` on the JE line, not by us.
        account_ccy, rate = _account_ccy_and_rate(row, fx_rates)
        company_amt = balance * rate
        if abs(company_amt) < BALANCE_THRESHOLD:
            ctx.result.bump("opening_gl_balances_skipped_zero")
            continue
        gl_account = account_full_name(ctx, account_id)
        if not gl_account:
            ctx.result.warn(
                "OpeningBalance", "missing GL account name",
                legacy_acctid=account_id,
            )
            continue
        original_remark = (
            f" (originally {balance:.2f} {account_ccy} @ {rate})"
            if account_ccy != DEFAULT_CURRENCY else ""
        )
        ctx.result.emit("Journal Entry", _build_gl_je(
            ctx,
            name=f"OPN-GL-{account_id}",
            account=gl_account,
            balance=balance,                  # in account's own currency
            company_amount=company_amt,       # in default (ILS) currency
            account_currency=account_ccy,
            exchange_rate=rate,
            original_remark=original_remark,
            account_name=pick(row, "NAME", "NAMEE", "NAMEH"),
            legacy_acctid=account_id,
            bank_account=bank_gl_to_label.get(account_id),
        ))
        ctx.result.bump("opening_gl_balances_emitted")


def _is_emittable_gl(row: dict, parent_ids: set[str]) -> bool:
    account_id = clean_str(row.get("ACCOUNTID"))
    if not account_id or account_id in SPECIAL_HANDLED_IDS:
        return False
    if account_id in parent_ids:
        return False  # group — auto-aggregates from children in ERPnext
    cls = clean_str(row.get("CLASS"))
    if cls in (CUSTOMER_CLASS, SUPPLIER_CLASS):
        return False  # handled by party-balance branch
    if cls in INVENTORY_CLASSES:
        return False  # handled by Stock Reconciliation
    # P&L accumulators (Revenue / Expense roots) — close annually, don't carry.
    if account_id[0] in ("4", "5"):
        return False
    return True


def _build_gl_je(
    ctx: Context,
    name: str,
    account: str,
    balance: float,
    company_amount: float,
    account_currency: str,
    exchange_rate: float,
    original_remark: str,
    account_name: str,
    legacy_acctid: str,
    bank_account: str | None,
) -> dict[str, Any]:
    """GL opening JE — main line in account's native currency, counter in default.

    `balance` is in `account_currency` (e.g. USD). `company_amount` is
    `balance * exchange_rate` in default currency (ILS). The Temporary
    Opening counter-line balances in default currency at rate 1.0;
    ERPnext's `total_debit`/`total_credit` are reported in default
    currency too, so the JE balances at the company level even when
    the main line is foreign.
    """
    abs_amt = round(abs(balance), 2)            # in account currency
    abs_company = round(abs(company_amount), 2) # in default currency
    main_line: dict[str, Any] = {"account": account}
    if bank_account:
        main_line["bank_account"] = bank_account
    counter_line: dict[str, Any] = {"account": ctx.with_abbr("Temporary Opening")}
    _set_je_pair(
        main_line, counter_line, abs_amt,
        company_amount=abs_company,
        debit_main=balance > 0,
        main_currency=account_currency, main_rate=exchange_rate,
        counter_currency=DEFAULT_CURRENCY, counter_rate=1.0,
    )
    return {
        "name": name,
        "voucher_type": "Opening Entry",
        "is_opening": "Yes",
        "company": ctx.config.company_name,
        "posting_date": ctx.config.opening_date,
        "user_remark": f"Opening balance — {account_name}{original_remark}",
        "docstatus": 1,
        "accounts": [main_line, counter_line],
        "total_debit": abs_company,
        "total_credit": abs_company,
        "multi_currency": 1 if account_currency != DEFAULT_CURRENCY else 0,
        "legacy_acctid": legacy_acctid,
        "legacy_kind": "opening_gl",
    }


# -- Outstanding cheques ------------------------------------------------------

def _emit_outstanding_cheques(
    ctx: Context,
    fx_rates: dict[str, float],
) -> None:
    """Emit individual JE per uncleared incoming cheque.

    Filter: incoming (CLASS=1), not cleared (REALCDATE=sentinel), not
    bounced (CHEQUEBACK=0). Each JE: DEBIT Cheques in Hand, CREDIT
    Temporary Opening — no party link, since the customer's GL was
    already decremented in legacy when the cheque was received (and that
    state is reflected in the customer balance JE).
    """
    cheques_in_hand = ctx.with_abbr("Cheques in Hand")
    temp_opening = ctx.with_abbr("Temporary Opening")
    for cheque in ctx.iter_streamed("CHEQUET"):
        if not _is_outstanding_incoming_cheque(cheque):
            continue
        amount_default = _cheque_amount_default(cheque, fx_rates)
        if abs(amount_default) < BALANCE_THRESHOLD:
            ctx.result.bump("opening_cheques_skipped_zero")
            continue
        cheque_id = clean_str(cheque.get("CHEQUEID"))
        cheque_no = clean_str(cheque.get("CHEQUENO"))
        cheque_date = parse_date(cheque.get("CDATE")) or ""
        owner = clean_str(cheque.get("OWNERNAME"))
        bank = _cheque_bank_name(ctx, cheque)
        original_remark = _cheque_original_remark(cheque)
        abs_amt = round(abs(amount_default), 2)
        # Both lines in default currency: legacy CHEQUET.CMVALUE is
        # already in main currency, and Cheques in Hand is ILS by design.
        ctx.result.emit("Journal Entry", {
            "name": f"OPN-CHQ-{cheque_id}",
            "voucher_type": "Opening Entry",
            "is_opening": "Yes",
            "cheque_no": cheque_no,
            "cheque_date": cheque_date,
            "company": ctx.config.company_name,
            "posting_date": parse_date(cheque.get("DOCDATE"))
                            or ctx.config.opening_date,
            "user_remark": (
                f"Outstanding cheque #{cheque_no} from {owner}, "
                f"due {cheque_date}, bank {bank}{original_remark}"
            ),
            "docstatus": 1,
            "accounts": [
                {
                    "account": cheques_in_hand,
                    "account_currency": DEFAULT_CURRENCY,
                    "exchange_rate": 1.0,
                    "debit_in_account_currency": abs_amt,
                    "credit_in_account_currency": 0,
                },
                {
                    "account": temp_opening,
                    "account_currency": DEFAULT_CURRENCY,
                    "exchange_rate": 1.0,
                    "debit_in_account_currency": 0,
                    "credit_in_account_currency": abs_amt,
                },
            ],
            "total_debit": abs_amt,
            "total_credit": abs_amt,
            "multi_currency": 0,
            "legacy_chequeid": cheque_id,
            "legacy_kind": "opening_cheque",
        })
        ctx.result.bump("opening_cheques_emitted")


def _is_outstanding_incoming_cheque(cheque: dict) -> bool:
    realcdate = clean_str(cheque.get("REALCDATE"))
    if realcdate and not realcdate.startswith(SENTINEL_DATE):
        return False
    if clean_str(cheque.get("CHEQUEBACK")) == "1":
        return False
    if clean_str(cheque.get("CLASS")) != "1":
        return False
    return True


def _cheque_amount_default(cheque: dict, fx_rates: dict[str, float]) -> float:
    """CMVALUE is already in main currency; CVALUE × rate is the fallback."""
    cmvalue = parse_decimal(cheque.get("CMVALUE"))
    if cmvalue:
        return cmvalue
    cvalue = parse_decimal(cheque.get("CVALUE"))
    rate = fx_rates.get(clean_str(cheque.get("CURID")), 1.0)
    return cvalue * rate


def _cheque_bank_name(ctx: Context, cheque: dict) -> str:
    bank_id = clean_str(cheque.get("CBANK"))
    if not bank_id:
        return ""
    bank = ctx.banks_by_id.get(bank_id)
    if not bank:
        return ""
    return pick(bank, "BANKNAME", "BANKNAMEE", "BANKNAMEH")


def _cheque_original_remark(cheque: dict) -> str:
    curid = clean_str(cheque.get("CURID"))
    if not curid or curid == "1":
        return ""
    iso = CURRENCY_BY_LEGACY_ID.get(curid, "")
    cvalue = parse_decimal(cheque.get("CVALUE"))
    return f" (originally {cvalue:.2f} {iso})"


# -- Helpers ------------------------------------------------------------------

def _set_je_pair(
    main: dict[str, Any],
    counter: dict[str, Any],
    abs_amt: float,
    company_amount: float,
    debit_main: bool,
    main_currency: str,
    main_rate: float,
    counter_currency: str,
    counter_rate: float,
) -> None:
    """Apply the sign-rule + currency tagging on a two-line JE pair.

    `abs_amt` is in main account's currency. `company_amount` is the same
    value in default (company) currency = abs_amt × main_rate. The
    counter line's *_in_account_currency uses `company_amount` (because
    Temporary Opening is always in default currency).

    Sign-rule: positive legacy balance → DEBIT the main account.
    """
    main["account_currency"] = main_currency
    main["exchange_rate"] = main_rate
    counter["account_currency"] = counter_currency
    counter["exchange_rate"] = counter_rate
    if debit_main:
        main["debit_in_account_currency"] = abs_amt
        main["credit_in_account_currency"] = 0
        counter["debit_in_account_currency"] = 0
        counter["credit_in_account_currency"] = company_amount
    else:
        main["debit_in_account_currency"] = 0
        main["credit_in_account_currency"] = abs_amt
        counter["debit_in_account_currency"] = company_amount
        counter["credit_in_account_currency"] = 0


def _account_ccy_and_rate(
    row: dict, fx_rates: dict[str, float],
) -> tuple[str, float]:
    """Return (ISO currency, rate-to-default) for a legacy ACCOUNTT row."""
    curid = clean_str(row.get("CURID"))
    iso = currency_iso(curid)
    rate = fx_rates.get(curid, 1.0) if curid else 1.0
    return iso, rate


def _fx_rates(ctx: Context) -> dict[str, float]:
    """Build CURID → exchange rate (legacy CURT.CURVALUE) lookup."""
    out: dict[str, float] = {}
    for row in ctx.table("CURT"):
        curid = clean_str(row.get("CURID"))
        if curid:
            out[curid] = parse_decimal(row.get("CURVALUE"), default=1.0)
    return out


def _to_default(
    balance: float,
    account_row: dict,
    fx_rates: dict[str, float],
) -> tuple[float, str]:
    """Convert account balance to default currency. Returns (converted, remark)."""
    curid = clean_str(account_row.get("CURID"))
    if not curid or curid == "1":
        return balance, ""
    rate = fx_rates.get(curid, 1.0)
    converted = balance * rate
    iso = CURRENCY_BY_LEGACY_ID.get(curid, "")
    return converted, f" (originally {balance:.2f} {iso} @ {rate})"


def _parent_id_set(ctx: Context) -> set[str]:
    """ACCOUNTIDs that appear as someone's FATHERID — i.e. group accounts."""
    out: set[str] = set()
    for row in ctx.table("ACCOUNTT"):
        fid = clean_str(row.get("FATHERID"))
        if fid:
            out.add(fid)
    return out


def _party_name_index(ctx: Context, role: str) -> dict[str, str]:
    """Map legacy ACCOUNTID → ERPnext Customer/Supplier name.

    Mirrors `parties.emit_customers` / `emit_suppliers` naming so opening
    JEs reference the same party records the operator already imported.
    """
    if role == "customer":
        table_name, pid_field, id_func = "CUSTT", "CUSTID", customer_id
    else:
        table_name, pid_field, id_func = "SUPPLIERT", "SUPPID", supplier_id
    out: dict[str, str] = {}
    for row in ctx.table(table_name):
        pid = clean_str(row.get(pid_field))
        if not pid:
            continue
        legacy_acctid = clean_str(row.get("ACCOUNT")) or pid
        out[legacy_acctid] = id_func(pid)
    return out


def _bank_gl_to_bank_account(ctx: Context) -> dict[str, str]:
    """Map legacy bank GL leaf ACCOUNTID → ERPnext Bank Account label.

    Delegates to `masters.bank_gl_leaf_to_label`, which expands each
    BANKACCOUNTT.TYPEA group to its currency-specific leaves and returns
    the matching Bank Account label per leaf. Only TYPEA leaves are
    included — TYPEB (cheques for collection) and TYPEC (post-dated
    cheques) are not bank accounts in the ERPnext sense.
    """
    return bank_gl_leaf_to_label(ctx)
