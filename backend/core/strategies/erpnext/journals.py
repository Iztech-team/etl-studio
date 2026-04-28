"""Journal Entry from three legacy sources:

- ENTRYDOCT       → standard manual journal entries (2,752 docs)
- STARTENTRYDOCT  → opening balance entries (is_opening=Yes, 19 docs)
- DNOTEDOCT       → bounced-cheque debit notes (28 docs)

Each header gets one Journal Entry record with N `accounts` child rows
mirroring the legacy detail rows. Cheque metadata on a detail row is
inlined as custom fields on the matching `accounts` child row so the
cheque trail survives even when it's a non-payment journal posting.
"""
from typing import Iterable

from core.strategies.erpnext.accounts import account_full_name
from core.strategies.erpnext.common import (
    clean_str,
    group_by,
    parse_date,
    parse_decimal,
    pick,
)
from core.strategies.erpnext.context import Context
from core.strategies.erpnext.masters import bank_account_label

VT_JOURNAL = "Journal Entry"
VT_OPENING = "Opening Entry"
VT_DEBIT_NOTE = "Debit Note"


def emit_journals(ctx: Context) -> None:
    emit_manual_journals(ctx)
    emit_opening_journals(ctx)
    emit_bounced_cheque_journals(ctx)


# -- Manual journals (ENTRYDOCT) ---------------------------------------------

def emit_manual_journals(ctx: Context) -> None:
    detail_by_doc = group_by(ctx.table("ENTRYDOCDETT"), "DOCNO")
    for header in ctx.table("ENTRYDOCT"):
        _emit_journal(
            ctx,
            header=header,
            details=detail_by_doc.get(clean_str(header.get("DOCNO")), []),
            voucher_type=VT_JOURNAL,
            name_prefix="JE-LEG",
            is_opening=False,
            stat_key="manual_journals",
        )


# -- Opening balance journals (STARTENTRYDOCT) -------------------------------

def emit_opening_journals(ctx: Context) -> None:
    detail_by_doc = group_by(ctx.table("STARTENTRYDOCDETT"), "DOCNO")
    for header in ctx.table("STARTENTRYDOCT"):
        _emit_journal(
            ctx,
            header=header,
            details=detail_by_doc.get(clean_str(header.get("DOCNO")), []),
            voucher_type=VT_OPENING,
            name_prefix="JE-OPN",
            is_opening=True,
            stat_key="opening_journals",
            posting_override=ctx.config.opening_date,
        )


# -- Bounced cheques (DNOTEDOCT) ---------------------------------------------

def emit_bounced_cheque_journals(ctx: Context) -> None:
    detail_by_doc = group_by(ctx.table("DNOTEDOCDETT"), "DOCNO")
    for header in ctx.table("DNOTEDOCT"):
        _emit_journal(
            ctx,
            header=header,
            details=detail_by_doc.get(clean_str(header.get("DOCNO")), []),
            voucher_type=VT_DEBIT_NOTE,
            name_prefix="JE-BNC",
            is_opening=False,
            stat_key="bounced_cheque_journals",
            extra_fields={"is_cheque_bounce": 1},
        )


# -- Shared emitter -----------------------------------------------------------

def _emit_journal(
    ctx: Context,
    header: dict,
    details: list[dict],
    voucher_type: str,
    name_prefix: str,
    is_opening: bool,
    stat_key: str,
    posting_override: str | None = None,
    extra_fields: dict | None = None,
) -> None:
    docserial = clean_str(header.get("DOCSERIAL"))
    accounts = _journal_accounts(ctx, details)
    if not accounts:
        ctx.result.bump(f"{stat_key}_skipped_no_accounts")
        return
    posting_date = posting_override or parse_date(header.get("DOCDATE"))
    payload = {
        "name": f"{name_prefix}-{docserial}",
        "voucher_type": voucher_type,
        "company": ctx.config.company_name,
        "posting_date": posting_date,
        "is_opening": "Yes" if is_opening else "No",
        "user_remark": clean_str(header.get("FORWHAT"))
                        or clean_str(header.get("NOTES")),
        "docstatus": 1 if clean_str(header.get("POSTFLAG")) == "2" else 0,
        "accounts": accounts,
        "total_debit": _sum_column(accounts, "debit_in_account_currency"),
        "total_credit": _sum_column(accounts, "credit_in_account_currency"),
        "legacy_docno": clean_str(header.get("DOCNO")),
        "legacy_docserial": docserial,
        **(extra_fields or {}),
    }
    ctx.result.emit("Journal Entry", payload)
    ctx.result.bump(f"{stat_key}_emitted")


def _journal_accounts(ctx: Context, details: Iterable[dict]) -> list[dict]:
    rows: list[dict] = []
    for d in details or []:
        row = _journal_account_row(ctx, d)
        if row:
            rows.append(row)
    return rows


def _journal_account_row(ctx: Context, detail: dict) -> dict | None:
    account = account_full_name(ctx, detail.get("ACCOUNTID"))
    if not account:
        return None
    debit = parse_decimal(detail.get("DEBIT"))
    credit = parse_decimal(detail.get("CREDIT"))
    if debit == 0 and credit == 0:
        return None
    party_type, party_name = ctx.party_link(detail.get("ACCOUNTID"))
    row: dict = {
        "account": account,
        "debit_in_account_currency": debit,
        "credit_in_account_currency": credit,
        "user_remark": clean_str(detail.get("NOTES")),
    }
    if party_type:
        row["party_type"] = party_type
        row["party"] = party_name
    _attach_cheque_fields(ctx, detail, row)
    return row


def _attach_cheque_fields(ctx: Context, detail: dict, row: dict) -> None:
    chequeid = clean_str(detail.get("CHEQUEID"))
    cheque_no = clean_str(detail.get("CHEQUE_CHEQUENO"))
    if not chequeid and not cheque_no:
        return
    cheque = _cheque_by_id(ctx).get(chequeid) if chequeid else None
    bank = _bank_name_for(ctx, detail, cheque)
    row["reference_type"] = ""
    row["reference_name"] = ""
    row["cheque_no"] = cheque_no or clean_str((cheque or {}).get("CHEQUENO"))
    row["cheque_date"] = parse_date((cheque or {}).get("CDATE")
                                    or detail.get("CHEQUE_CDATE"))
    row["cheque_clearing_date"] = parse_date((cheque or {}).get("REALCDATE")
                                              or detail.get("CHEQUE_REALCDATE"))
    row["cheque_owner_name"] = clean_str((cheque or {}).get("OWNERNAME")
                                         or detail.get("CHEQUE_OWNERNAME"))
    row["cheque_bank"] = bank
    row["cheque_branch"] = clean_str((cheque or {}).get("CBANKBRANCH")
                                     or detail.get("CHEQUE_CBANKBRANCH"))
    row["cheque_returned"] = 1 if _is_returned(cheque, detail) else 0
    row["cheque_bank_account"] = bank_account_label(
        ctx, (cheque or {}).get("BANKACC"),
    )
    row["linked_legacy_cheque_id"] = chequeid


def _cheque_by_id(ctx: Context) -> dict[str, dict]:
    cached = getattr(ctx, "_cheque_index", None)
    if cached is not None:
        return cached
    index = {clean_str(r.get("CHEQUEID")): r for r in ctx.table("CHEQUET")
             if clean_str(r.get("CHEQUEID"))}
    ctx._cheque_index = index  # type: ignore[attr-defined]
    return index


def _bank_name_for(ctx: Context, detail: dict, cheque: dict | None) -> str:
    bank_id = clean_str((cheque or {}).get("CBANK")) \
              or clean_str(detail.get("CHEQUE_CBANK"))
    if not bank_id:
        return ""
    bank = ctx.banks_by_id.get(bank_id)
    return pick(bank or {}, "BANKNAME", "BANKNAMEE", "BANKNAMEH")


def _is_returned(cheque: dict | None, detail: dict) -> bool:
    if cheque and clean_str(cheque.get("RETURNED")) not in {"", "0"}:
        return True
    if clean_str(detail.get("CHEQUE_RETURNED")) not in {"", "0"}:
        return True
    return False


def _sum_column(rows: Iterable[dict], key: str) -> float:
    return sum(float(r.get(key, 0) or 0) for r in rows or [])
