"""Mirror-strategy opening balances: one JE per legacy ACCOUNTT leaf.

Party + cheque + helper logic lives in
`erpnext_shared.opening_balances`; this module only adds the per-leaf
GL emit which is the part that distinguishes Mirror from Native.

**Sign rule** (universal, no per-account-type special-casing):
    AACCBALANCE > 0 → DEBIT  the account, CREDIT Temporary Opening
    AACCBALANCE < 0 → CREDIT the account, DEBIT  Temporary Opening

**Skipped from generic GL emit** (handled elsewhere or are P&L roots):

- Customer (CLASS=2) / Supplier (CLASS=3) leaves → party JE branch
- Inventory (CLASS=40/41/42) → handled by Stock Reconciliation
- Group / parent accounts → auto-aggregate from children in ERPnext
- Revenue (root 5) / Expense (root 4) accumulators → close annually
- GL 118 (Cheques for Collection) → reconstructed via per-cheque JEs
"""
from typing import Any

from core.strategies.erpnext_shared.common import (
    DEFAULT_CURRENCY,
    account_full_name,
    clean_str,
    parse_decimal,
    pick,
)
from core.strategies.erpnext_shared.context import Context
from core.strategies.erpnext_shared.opening_balances import (
    BALANCE_THRESHOLD,
    CUSTOMER_CLASS,
    INVENTORY_CLASSES,
    SUPPLIER_CLASS,
    account_ccy_and_rate,
    bank_gl_to_bank_account,
    build_fx_rates,
    emit_outstanding_cheques,
    emit_party_balances,
    parent_id_set,
    party_name_index,
    set_je_pair,
)

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
    fx_rates = build_fx_rates(ctx)
    parent_ids = parent_id_set(ctx)
    customer_index = party_name_index(ctx, role="customer")
    supplier_index = party_name_index(ctx, role="supplier")
    bank_gl_to_label = bank_gl_to_bank_account(ctx)

    emit_party_balances(
        ctx, "customer", fx_rates, customer_index, parent_ids,
        party_account=ctx.with_abbr("Debtors"),
    )
    emit_party_balances(
        ctx, "supplier", fx_rates, supplier_index, parent_ids,
        party_account=ctx.with_abbr("Creditors"),
    )
    _emit_gl_balances(ctx, fx_rates, parent_ids, bank_gl_to_label)
    emit_outstanding_cheques(ctx, fx_rates, ctx.with_abbr("Cheques in Hand"))


def _emit_gl_balances(
    ctx: Context,
    fx_rates: dict[str, float],
    parent_ids: set[str],
    bank_gl_to_label: dict[str, str],
) -> None:
    """Emit JE per leaf GL account with non-zero balance."""
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
        account_ccy, rate = account_ccy_and_rate(row, fx_rates)
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
            balance=balance,
            company_amount=company_amt,
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
    if account_id[0] in ("4", "5"):
        return False  # P&L accumulators close annually, don't carry
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
    """GL opening JE — main line in account's native currency, counter in default."""
    abs_amt = round(abs(balance), 2)
    abs_company = round(abs(company_amount), 2)
    main_line: dict[str, Any] = {"account": account}
    if bank_account:
        main_line["bank_account"] = bank_account
    counter_line: dict[str, Any] = {"account": ctx.with_abbr("Temporary Opening")}
    set_je_pair(
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
