"""Opening-balance helpers shared between Mirror and Native strategies.

Both strategies emit the same shape of party (Customer/Supplier) and
outstanding-cheque opening JEs. They differ only in how they handle
non-party GL balances:

- Mirror  emits one JE per legacy ACCOUNTT leaf
- Native  aggregates legacy leaves into ERPnext standard buckets

So this module owns the party + cheque emit and the universally-needed
helpers (sign rule, currency conversion, JE pair construction); each
strategy module supplies its own GL-emit on top.
"""
from typing import Any

from core.strategies.erpnext_shared.common import (
    CURRENCY_BY_LEGACY_ID,
    DEFAULT_CURRENCY,
    SENTINEL_DATE,
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

# Legacy CLASS values we route to party-balance branch instead of generic GL.
CUSTOMER_CLASS = "2"
SUPPLIER_CLASS = "3"

# Legacy CLASS values for inventory (handled by Stock Reconciliation, not here).
INVENTORY_CLASSES = {"40", "41", "42"}


# -- Party balances (customers + suppliers) -----------------------------------

def emit_party_balances(
    ctx: Context,
    role: str,
    fx_rates: dict[str, float],
    name_index: dict[str, str],
    parent_ids: set[str],
    party_account: str,
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
        balance_default, original_remark = to_default(balance, row, fx_rates)
        if abs(balance_default) < BALANCE_THRESHOLD:
            ctx.result.bump(f"{stat_key}_skipped_zero")
            continue
        party_name = pick(row, "NAME", "NAMEE", "NAMEH")
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
    abs_amt = round(abs(balance), 2)
    party_line: dict[str, Any] = {
        "account": party_account,
        "party_type": party_type,
        "party": party,
    }
    counter_line: dict[str, Any] = {"account": ctx.with_abbr("Temporary Opening")}
    set_je_pair(
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


# -- Outstanding cheques ------------------------------------------------------

def emit_outstanding_cheques(
    ctx: Context,
    fx_rates: dict[str, float],
    cheques_account: str,
) -> None:
    """One JE per uncleared incoming cheque, posted to cheques_account.

    Filter: incoming (CLASS=1), not cleared (REALCDATE=sentinel), not
    bounced (CHEQUEBACK=0). DEBIT cheques_account, CREDIT Temporary
    Opening — no party link; the customer's GL was already decremented
    when the cheque was received in legacy.
    """
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
        ctx.result.emit("Journal Entry", {
            "name": f"OPN-CHQ-{cheque_id}",
            "voucher_type": "Opening Entry",
            "is_opening": "Yes",
            "cheque_no": cheque_no,
            "cheque_date": cheque_date,
            "company": ctx.config.company_name,
            # Opening JEs all freeze the world on opening_date — the
            # cheque's original DOCDATE / CDATE survive in cheque_date
            # and user_remark for traceback but must NOT drive the
            # posting_date, otherwise ERPnext rejects the row when no
            # Fiscal Year covers that historical date.
            "posting_date": ctx.config.opening_date,
            "user_remark": (
                f"Outstanding cheque #{cheque_no} from {owner}, "
                f"due {cheque_date}, bank {bank}{original_remark}"
            ),
            "docstatus": 1,
            "accounts": [
                {
                    "account": cheques_account,
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


# -- Sign rule + currency conversion ------------------------------------------

def set_je_pair(
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

    `abs_amt` is in the main account's currency. `company_amount` is the
    same value in default currency = abs_amt × main_rate. The counter
    line's *_in_account_currency uses `company_amount` (because the
    counter is always in default currency).

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


def account_ccy_and_rate(
    row: dict, fx_rates: dict[str, float],
) -> tuple[str, float]:
    """Return (ISO currency, rate-to-default) for a legacy ACCOUNTT row."""
    curid = clean_str(row.get("CURID"))
    iso = currency_iso(curid)
    rate = fx_rates.get(curid, 1.0) if curid else 1.0
    return iso, rate


def build_fx_rates(ctx: Context) -> dict[str, float]:
    """CURID → exchange rate (legacy CURT.CURVALUE) lookup."""
    out: dict[str, float] = {}
    for row in ctx.table("CURT"):
        curid = clean_str(row.get("CURID"))
        if curid:
            out[curid] = parse_decimal(row.get("CURVALUE"), default=1.0)
    return out


def to_default(
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


# -- Index helpers ------------------------------------------------------------

def parent_id_set(ctx: Context) -> set[str]:
    """ACCOUNTIDs that appear as someone's FATHERID — i.e. group accounts."""
    out: set[str] = set()
    for row in ctx.table("ACCOUNTT"):
        fid = clean_str(row.get("FATHERID"))
        if fid:
            out.add(fid)
    return out


def party_name_index(ctx: Context, role: str) -> dict[str, str]:
    """Map legacy ACCOUNTID → ERPnext Customer/Supplier name."""
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


def bank_gl_to_bank_account(ctx: Context) -> dict[str, str]:
    """Map legacy bank GL leaf ACCOUNTID → ERPnext Bank Account label.

    Delegates to `masters.bank_gl_leaf_to_label`, which expands each
    BANKACCOUNTT.TYPEA group to its currency-specific leaves and returns
    the matching Bank Account label per leaf.
    """
    return bank_gl_leaf_to_label(ctx)
