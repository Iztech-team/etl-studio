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
        ctx.result.emit(
            "Journal Entry",
            _build_party_je(
                ctx,
                name=f"{name_prefix}-{account_id}",
                party_type=party_type,
                party=party,
                party_account=party_account,
                balance=balance_default,
                original_remark=original_remark,
                party_name=party_name,
                legacy_acctid=account_id,
            ),
        )
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
        party_line,
        counter_line,
        abs_amt,
        company_amount=abs_amt,
        debit_main=balance > 0,
        main_currency=DEFAULT_CURRENCY,
        main_rate=1.0,
        counter_currency=DEFAULT_CURRENCY,
        counter_rate=1.0,
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

# Incoming cheque-holding classes.
CHEQUE_HOLDING_CLASSES = {
    "14",  # حساب صندوق الشيكات — physical cheque box (in hand)
    "11",  # حساب برسم التحصيل — sent to bank for collection, not yet cleared
}

# Outgoing cheque-holding classes.
OUTGOING_HOLDING_CLASSES = {
    "12",  # حساب برسم الدفع — cheques issued, pending clearance
}

# Bounced/returned cheque class — excluded from outstanding.
BOUNCED_CHEQUE_CLASSES = {
    "15",  # حساب المسحوبات — bounced/returned cheques
}


def emit_outstanding_cheques(
    ctx: Context,
    fx_rates: dict[str, float],
) -> None:
    """One JE per outstanding cheque, posted to the actual holding account.

    Two populations of outstanding cheques exist in legacy:

    A) Tracked (have CHEQUELEDGERT entries): last ledger row tells us
       which account the cheque currently sits in.
    B) Untracked (no CHEQUELEDGERT): bulk-imported on day 1 without
       GL postings. SOURCEACCOUNTID (incoming) or DESTACCOUNTID
       (outgoing) tells us the intended holding account.

    Both are emitted as individual opening JEs to the actual legacy
    account (e.g. 1121 صندوق الشيكات\شيكل). The corresponding GL
    balance emission is suppressed for cheque-holding classes so
    there's no double counting.

    Incoming (CLASS=1): debit the holding account, credit Temporary Opening.
    Outgoing (CLASS=2): credit the holding account, debit Temporary Opening.
    """
    temp_opening = ctx.with_abbr("Temporary Opening")
    latest_acct_per_cheque = _build_latest_cheque_account(ctx)
    party_by_account = _build_party_account_map(ctx)

    for cheque in ctx.iter_streamed("CHEQUET"):
        target_account_id = _resolve_cheque_holding_account(
            cheque, latest_acct_per_cheque, ctx.accounts_by_id
        )
        if not target_account_id:
            continue
        cheque_id = clean_str(cheque.get("CHEQUEID"))
        cheque_no = clean_str(cheque.get("CHEQUENO"))
        cheque_date = parse_date(cheque.get("CDATE")) or ""
        owner = clean_str(cheque.get("OWNERNAME"))
        bank = _cheque_bank_name(ctx, cheque)
        original_remark = _cheque_original_remark(cheque)
        is_incoming = clean_str(cheque.get("CLASS")) == "1"

        account_name = account_full_name(ctx, target_account_id)
        if not account_name:
            ctx.result.bump("opening_cheques_skipped_no_account")
            continue

        # Native currency of the target account.
        acct_row = ctx.accounts_by_id.get(target_account_id, {})
        account_ccy = currency_iso(acct_row.get("CURID"))
        rate = fx_rates.get(clean_str(acct_row.get("CURID")), 1.0)
        native_amt = round(abs(parse_decimal(cheque.get("CVALUE"))), 2)
        if native_amt < BALANCE_THRESHOLD:
            ctx.result.bump("opening_cheques_skipped_zero")
            continue
        company_amt = round(native_amt * rate, 2)

        main_line: dict[str, Any] = {"account": account_name}
        counter_line: dict[str, Any] = {"account": temp_opening}
        set_je_pair(
            main_line,
            counter_line,
            native_amt,
            company_amount=company_amt,
            debit_main=is_incoming,
            main_currency=account_ccy,
            main_rate=rate,
            counter_currency=DEFAULT_CURRENCY,
            counter_rate=1.0,
        )

        party_type, party = _resolve_cheque_party(cheque, party_by_account)
        party_hint = f" — party: {party_type}/{party}" if party_type and party else ""
        direction = "incoming" if is_incoming else "outgoing"

        ctx.result.emit(
            "Journal Entry",
            {
                "name": f"OPN-CHQ-{cheque_id}",
                "voucher_type": "Opening Entry",
                "is_opening": "Yes",
                "cheque_no": cheque_no,
                "cheque_date": cheque_date,
                "company": ctx.config.company_name,
                "posting_date": ctx.config.opening_date,
                "user_remark": (
                    f"Outstanding {direction} cheque #{cheque_no} from {owner}, "
                    f"due {cheque_date}, bank {bank}{party_hint}{original_remark}"
                ),
                "docstatus": 1,
                "accounts": [main_line, counter_line],
                "total_debit": company_amt,
                "total_credit": company_amt,
                "multi_currency": 1 if account_ccy != DEFAULT_CURRENCY else 0,
                "legacy_chequeid": cheque_id,
                "legacy_kind": "opening_cheque",
            },
        )
        ctx.result.bump(f"opening_cheques_{direction}_emitted")


def _resolve_cheque_holding_account(
    cheque: dict,
    latest_acct_per_cheque: dict[str, str],
    accounts_by_id: dict[str, dict],
) -> str | None:
    """Determine which holding account an outstanding cheque belongs to.

    Returns the account ID if the cheque is outstanding, None if cleared/invalid.
    """
    cheque_class = clean_str(cheque.get("CLASS"))
    cheque_id = clean_str(cheque.get("CHEQUEID"))
    if not cheque_id or cheque_class not in ("1", "2"):
        return None

    is_incoming = cheque_class == "1"
    valid_classes = CHEQUE_HOLDING_CLASSES if is_incoming else OUTGOING_HOLDING_CLASSES

    # A) Tracked cheques: use latest CHEQUELEDGERT position.
    latest_acct = latest_acct_per_cheque.get(cheque_id)
    if latest_acct and latest_acct != "0":
        acct_class = clean_str(accounts_by_id.get(latest_acct, {}).get("CLASS"))
        if acct_class in BOUNCED_CHEQUE_CLASSES:
            return None
        if acct_class in valid_classes:
            return latest_acct
        return None  # cleared — moved to bank/customer/etc.

    # B) Untracked cheques: SOURCEACCOUNTID (incoming) or DESTACCOUNTID (outgoing).
    fallback_field = "SOURCEACCOUNTID" if is_incoming else "DESTACCOUNTID"
    fallback_acct = clean_str(cheque.get(fallback_field))
    if not fallback_acct or fallback_acct == "0":
        return None
    acct_class = clean_str(accounts_by_id.get(fallback_acct, {}).get("CLASS"))
    if acct_class in BOUNCED_CHEQUE_CLASSES:
        return None
    if acct_class in valid_classes:
        return fallback_acct
    return None


def _build_latest_cheque_account(ctx: Context) -> dict[str, str]:
    """Map CHEQUEID → CURRACCOUNT of its highest-SERIAL ledger row.

    CHEQUELEDGERT records each movement of a cheque between accounts;
    the latest row tells us where the cheque is right now. Used by
    the outstanding-cheque filter — see _is_outstanding_incoming_cheque.
    """
    latest: dict[str, tuple[int, str]] = {}
    for row in ctx.table("CHEQUELEDGERT"):
        cheque_id = clean_str(row.get("CHEQUEID"))
        if not cheque_id:
            continue
        try:
            serial = int(clean_str(row.get("SERIAL")) or "0")
        except ValueError:
            continue
        curr = clean_str(row.get("CURRACCOUNT"))
        if cheque_id not in latest or serial > latest[cheque_id][0]:
            latest[cheque_id] = (serial, curr)
    return {cheque_id: acc for cheque_id, (_, acc) in latest.items()}


def _resolve_cheque_party(
    cheque: dict,
    party_by_account: dict[str, tuple[str, str]],
) -> tuple[str | None, str | None]:
    """Find the customer/supplier this cheque is linked to.

    CHEQUET has 5 account-id fields (FIRST, FIRSTDEST, SOURCE, DEST,
    ACCOUNTID). FIRST is the original booking account — for incoming
    cheques that's always the customer. The current SOURCE/DEST flip
    as the cheque physically moves between accounts (customer →
    cheque box → bank), so they're unreliable for party identification.

    Try each candidate in order; return the first one that matches a
    party-bearing account. Returns (None, None) if nothing matches.
    """
    candidates = (
        clean_str(cheque.get("FIRSTACCOUNTID")),
        clean_str(cheque.get("ACCOUNTID")),
        clean_str(cheque.get("SOURCEACCOUNTID")),
        clean_str(cheque.get("DESTACCOUNTID")),
        clean_str(cheque.get("FIRSTDESTACCOUNTID")),
    )
    for acc in candidates:
        if acc and acc in party_by_account:
            return party_by_account[acc]
    return None, None


def _build_party_account_map(ctx: Context) -> dict[str, tuple[str, str]]:
    """Build a map from legacy account ID → (party_type, party_id) for
    all customers and suppliers. Used to tag cheque JE lines with their
    source party.

    Returns: {account_id: (party_type, party_id), ...}
    where party_type is "Customer" or "Supplier" and party_id is the
    customer/supplier code."""
    out: dict[str, tuple[str, str]] = {}

    # Map customer accounts. The party value must match the Customer
    # doctype's `name` field (primary key) — which we encode as
    # 'CUST-{custid}' in parties.py. Same for suppliers.
    for row in ctx.table("CUSTT"):
        account = clean_str(row.get("ACCOUNT"))
        custid = clean_str(row.get("CUSTID"))
        if account and custid:
            out[account] = ("Customer", customer_id(custid))

    for row in ctx.table("SUPPLIERT"):
        account = clean_str(row.get("ACCOUNT"))
        suppid = clean_str(row.get("SUPPID"))
        if account and suppid:
            out[account] = ("Supplier", supplier_id(suppid))

    return out


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
    row: dict,
    fx_rates: dict[str, float],
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
