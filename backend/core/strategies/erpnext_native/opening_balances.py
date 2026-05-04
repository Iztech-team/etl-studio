"""Native-strategy opening balances: aggregate legacy leaves into ERPnext buckets.

Party + cheque emit is identical to mirror — both use the shared module.
The only divergence is `_emit_gl_balances`, which here SUMS legacy
balances per (bucket, currency) tuple and emits one JE per group instead
of one JE per legacy leaf.

Bank-class accounts are emitted individually (one JE per legacy bank GL
leaf) so each bank account in ERPnext has its own opening balance and
appears correctly in Bank Reconciliation. Everything else aggregates.
"""

from typing import Any

from core.strategies.erpnext_native.account_mapping import (
    BANK_CLASSES,
    classify_account,
)
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
    account_ccy_and_rate,
    bank_gl_to_bank_account,
    build_fx_rates,
    emit_outstanding_cheques,
    emit_party_balances,
    parent_id_set,
    party_name_index,
    set_je_pair,
)


def emit_opening_balances(ctx: Context) -> None:
    """Top-level: emit party JEs + bucketed GL JEs + bank JEs + cheque JEs."""
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
        ctx,
        "customer",
        fx_rates,
        customer_index,
        parent_ids,
        party_account=ctx.with_abbr("Debtors"),
    )
    emit_party_balances(
        ctx,
        "supplier",
        fx_rates,
        supplier_index,
        parent_ids,
        party_account=ctx.with_abbr("Creditors"),
    )
    _emit_bank_balances(ctx, fx_rates, parent_ids, bank_gl_to_label)
    _emit_bucketed_gl_balances(ctx, fx_rates, parent_ids)
    emit_outstanding_cheques(ctx, fx_rates, ctx.with_abbr("Cheques in Hand"))


# -- Bank-class GL balances (one JE per leaf, like mirror) --------------------


def _emit_bank_balances(
    ctx: Context,
    fx_rates: dict[str, float],
    parent_ids: set[str],
    bank_gl_to_label: dict[str, str],
) -> None:
    """Per-leaf opening JE for every bank GL leaf with non-zero balance.

    Mirrors the mirror-strategy GL emit shape for bank accounts only —
    Bank Reconciliation in ERPnext requires per-leaf opening balances.
    """
    for row in ctx.table("ACCOUNTT"):
        cls = clean_str(row.get("CLASS"))
        if cls not in BANK_CLASSES:
            continue
        account_id = clean_str(row.get("ACCOUNTID"))
        if not account_id or account_id in parent_ids:
            continue
        balance = parse_decimal(row.get("AACCBALANCE"))
        if abs(balance) < BALANCE_THRESHOLD:
            ctx.result.bump("opening_bank_balances_skipped_zero")
            continue
        account_ccy, rate = account_ccy_and_rate(row, fx_rates)
        company_amt = balance * rate
        if abs(company_amt) < BALANCE_THRESHOLD:
            ctx.result.bump("opening_bank_balances_skipped_zero")
            continue
        gl_account = account_full_name(ctx, account_id)
        if not gl_account:
            ctx.result.warn(
                "OpeningBalance",
                "missing GL account name",
                legacy_acctid=account_id,
            )
            continue
        original_remark = (
            f" (originally {balance:.2f} {account_ccy} @ {rate})"
            if account_ccy != DEFAULT_CURRENCY
            else ""
        )
        ctx.result.emit(
            "Journal Entry",
            _build_bank_je(
                ctx,
                name=f"OPN-BANK-{account_id}",
                account=gl_account,
                balance=balance,
                company_amount=company_amt,
                account_currency=account_ccy,
                exchange_rate=rate,
                original_remark=original_remark,
                account_name=pick(row, "NAME", "NAMEE", "NAMEH"),
                legacy_acctid=account_id,
                bank_account=bank_gl_to_label.get(account_id),
            ),
        )
        ctx.result.bump("opening_bank_balances_emitted")


def _build_bank_je(
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
    abs_amt = round(abs(balance), 2)
    abs_company = round(abs(company_amount), 2)
    main_line: dict[str, Any] = {"account": account}
    if bank_account:
        main_line["bank_account"] = bank_account
    counter_line: dict[str, Any] = {"account": ctx.with_abbr("Temporary Opening")}
    set_je_pair(
        main_line,
        counter_line,
        abs_amt,
        company_amount=abs_company,
        debit_main=balance > 0,
        main_currency=account_currency,
        main_rate=exchange_rate,
        counter_currency=DEFAULT_CURRENCY,
        counter_rate=1.0,
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
        "legacy_kind": "opening_bank",
    }


# -- Bucketed GL balances (one JE per bucket, summed across legacy leaves) ----


def _emit_bucketed_gl_balances(
    ctx: Context,
    fx_rates: dict[str, float],
    parent_ids: set[str],
) -> None:
    """Sum non-bank GL balances by ERPnext bucket and emit one JE per bucket.

    Multi-currency leaves are converted to default currency first, so
    every bucket totals in ILS regardless of the source mix. The
    individual legacy ACCOUNTIDs that fed each bucket are preserved
    in the JE remark for audit traceback, and dumped in full to the
    bucket-coverage markdown report so the operator can refine the
    NAME rule list iteratively.
    """
    aggregates: dict[str, dict[str, Any]] = {}
    for row in ctx.table("ACCOUNTT"):
        account_id = clean_str(row.get("ACCOUNTID"))
        if not account_id or account_id in parent_ids:
            continue
        bucket = classify_account(ctx, row)
        if not bucket:
            continue
        balance = parse_decimal(row.get("AACCBALANCE"))
        if abs(balance) < BALANCE_THRESHOLD:
            continue
        account_ccy, rate = account_ccy_and_rate(row, fx_rates)
        company_amt = balance * rate
        if abs(company_amt) < BALANCE_THRESHOLD:
            continue
        agg = aggregates.setdefault(
            bucket,
            {
                "balance": 0.0,
                "accounts": [],
            },
        )
        agg["balance"] += company_amt
        agg["accounts"].append(
            {
                "id": account_id,
                "name": pick(row, "NAME", "NAMEE", "NAMEH"),
                "balance": company_amt,
            }
        )

    for bucket, data in aggregates.items():
        balance = data["balance"]
        if abs(balance) < BALANCE_THRESHOLD:
            ctx.result.bump("opening_bucket_balances_skipped_zero")
            continue
        ctx.result.emit(
            "Journal Entry",
            _build_bucket_je(
                ctx,
                bucket=bucket,
                balance=balance,
                legacy_ids=[a["id"] for a in data["accounts"]],
            ),
        )
        ctx.result.bump("opening_bucket_balances_emitted")

    _emit_bucket_coverage_report(ctx, aggregates)


def _build_bucket_je(
    ctx: Context,
    bucket: str,
    balance: float,
    legacy_ids: list[str],
) -> dict[str, Any]:
    """One bucketed opening JE, both lines in default currency."""
    abs_amt = round(abs(balance), 2)
    main_line: dict[str, Any] = {"account": ctx.with_abbr(bucket)}
    counter_line: dict[str, Any] = {"account": ctx.with_abbr("Temporary Opening")}
    set_je_pair(
        main_line,
        counter_line,
        abs_amt,
        company_amount=abs_amt,
        debit_main=balance > 0,
        main_currency=DEFAULT_CURRENCY,
        main_rate=1.0,
        counter_currency=DEFAULT_CURRENCY,
        counter_rate=1.0,
    )
    legacy_summary = ",".join(legacy_ids[:20])
    if len(legacy_ids) > 20:
        legacy_summary += f",…(+{len(legacy_ids) - 20} more)"
    return {
        "name": f"OPN-NAT-{_slug(bucket)}",
        "voucher_type": "Opening Entry",
        "is_opening": "Yes",
        "company": ctx.config.company_name,
        "posting_date": ctx.config.opening_date,
        "user_remark": (
            f"Opening balance — {bucket} (aggregated from "
            f"{len(legacy_ids)} legacy leaves: {legacy_summary})"
        ),
        "docstatus": 1,
        "accounts": [main_line, counter_line],
        "total_debit": abs_amt,
        "total_credit": abs_amt,
        "multi_currency": 0,
        "legacy_kind": "opening_bucket",
    }


def _emit_bucket_coverage_report(
    ctx: Context,
    aggregates: dict[str, dict[str, Any]],
) -> None:
    """Markdown report listing every legacy account → bucket assignment.

    Highlights fallback buckets (Miscellaneous Expenses, Sales, Earnest
    Money, Accrued Expenses, Capital Stock) so the operator can scan
    them for clusters and tell us what NAME regex to add.
    """
    md = _build_coverage_markdown(aggregates)
    ctx.result.output_tables["__native_bucket_coverage__"] = [
        {
            "filename": "99_native_bucket_coverage.md",
            "content": md,
        }
    ]


def _build_coverage_markdown(aggregates: dict[str, dict[str, Any]]) -> str:
    fallback_buckets = {
        "Miscellaneous Expenses",
        "Sales",
        "Earnest Money",
        "Accrued Expenses",
        "Capital Stock",
    }
    total_accounts = sum(len(d["accounts"]) for d in aggregates.values())
    grand_total = sum(d["balance"] for d in aggregates.values())

    lines: list[str] = []
    lines.append("# Native Bucket Coverage Report\n")
    lines.append(
        "Generated by `ErpnextNativeStrategy`. Each section below lists "
        "every legacy ACCOUNTT row that fed into a single ERPnext bucket. "
        "Use the **fallback buckets** to find clusters of accounts that "
        "should be split out via NAME regex rules in `account_mapping.py`.\n"
    )
    lines.append("## Summary\n")
    lines.append(f"- Buckets used: **{len(aggregates)}**")
    lines.append(f"- Legacy accounts classified: **{total_accounts}**")
    lines.append(f"- Grand total (default currency): **{grand_total:,.2f}**\n")

    fallbacks = sorted(
        ((b, d) for b, d in aggregates.items() if b in fallback_buckets),
        key=lambda kv: -abs(kv[1]["balance"]),
    )
    routed = sorted(
        ((b, d) for b, d in aggregates.items() if b not in fallback_buckets),
        key=lambda kv: -abs(kv[1]["balance"]),
    )

    if fallbacks:
        lines.append("## ⚠ Fallback buckets (review these to refine mapping)\n")
        for bucket, data in fallbacks:
            lines.append(_bucket_section(bucket, data))

    if routed:
        lines.append("## Hand-routed buckets\n")
        for bucket, data in routed:
            lines.append(_bucket_section(bucket, data))

    return "\n".join(lines)


def _bucket_section(bucket: str, data: dict[str, Any]) -> str:
    accts = sorted(data["accounts"], key=lambda a: -abs(a["balance"]))
    out: list[str] = []
    out.append(
        f"### {bucket} ({len(accts)} account"
        f"{'s' if len(accts) != 1 else ''}, "
        f"net {data['balance']:,.2f})\n"
    )
    out.append("| ACCOUNTID | NAME | balance |")
    out.append("|---|---|---:|")
    for a in accts:
        name = (a["name"] or "").replace("|", "\\|")
        out.append(f"| {a['id']} | {name} | {a['balance']:,.2f} |")
    out.append("")
    return "\n".join(out)


def _slug(s: str) -> str:
    return s.lower().replace(" ", "-").replace("/", "-")
