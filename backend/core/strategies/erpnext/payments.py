"""Payment Entry from RECDOCT (customer receipts) and PAYDOCT (supplier payments).

RECDOCDETT rows split a payment across two GL accounts:
- party row     — DEBIT for supplier payments / CREDIT for customer receipts
                  (legacy double-entry against the party's ACCOUNTT row)
- cash/bank row — DEBIT for cash-in, CREDIT for cash-out

Cheque metadata (issuer / bank / clearing / bounce flags) is inlined as
custom fields on the Payment Entry rather than living in a separate
'Legacy Cheque' doctype — see planning doc decision.
"""
from typing import Iterable

from core.strategies.erpnext.accounts import account_full_name
from core.strategies.erpnext.common import (
    clean_str,
    customer_id,
    group_by,
    parse_date,
    parse_decimal,
    pick,
    supplier_id,
)
from core.strategies.erpnext.context import Context
from core.strategies.erpnext.masters import bank_account_label

MODE_CASH = "Cash"
MODE_CHEQUE = "Cheque"


def emit_payments(ctx: Context) -> None:
    emit_customer_receipts(ctx)
    emit_supplier_payments(ctx)


# -- Customer Receipts (RECDOCT) ----------------------------------------------

def emit_customer_receipts(ctx: Context) -> None:
    detail_by_doc = group_by(ctx.table("RECDOCDETT"), "DOCNO")
    for header in ctx.table("RECDOCT"):
        _emit_customer_receipt(ctx, header, detail_by_doc)


def _emit_customer_receipt(
    ctx: Context,
    header: dict,
    detail_by_doc: dict[str, list[dict]],
) -> None:
    docno = clean_str(header.get("DOCNO"))
    docserial = clean_str(header.get("DOCSERIAL"))
    details = detail_by_doc.get(docno, [])
    party_row = _pick_party_row(details, "CREDIT")
    cash_row = _pick_party_row(details, "DEBIT")
    if not party_row or not cash_row:
        ctx.result.bump("customer_receipts_skipped_unmatched")
        return
    party_account_id = clean_str(party_row.get("ACCOUNTID"))
    party_type, party_name = ctx.party_link(party_account_id)
    if party_type != "Customer":
        ctx.result.bump("customer_receipts_skipped_non_customer")
        return
    payload = _payment_payload(
        ctx,
        kind="Receive",
        name=f"PE-REC-LEG-{docserial}",
        header=header,
        party_type=party_type,
        party_name=party_name,
        party_row=party_row,
        cash_row=cash_row,
        all_rows=details,
    )
    ctx.result.emit("Payment Entry", payload)
    ctx.result.bump("customer_receipts_emitted")


# -- Supplier Payments (PAYDOCT) ----------------------------------------------

def emit_supplier_payments(ctx: Context) -> None:
    detail_by_doc = group_by(ctx.table("PAYDOCDETT"), "DOCNO")
    for header in ctx.table("PAYDOCT"):
        _emit_supplier_payment(ctx, header, detail_by_doc)


def _emit_supplier_payment(
    ctx: Context,
    header: dict,
    detail_by_doc: dict[str, list[dict]],
) -> None:
    docno = clean_str(header.get("DOCNO"))
    docserial = clean_str(header.get("DOCSERIAL"))
    details = detail_by_doc.get(docno, [])
    party_row = _pick_party_row(details, "DEBIT")
    cash_row = _pick_party_row(details, "CREDIT")
    if not party_row or not cash_row:
        ctx.result.bump("supplier_payments_skipped_unmatched")
        return
    party_account_id = clean_str(party_row.get("ACCOUNTID"))
    party_type, party_name = ctx.party_link(party_account_id)
    if party_type != "Supplier":
        ctx.result.bump("supplier_payments_skipped_non_supplier")
        return
    payload = _payment_payload(
        ctx,
        kind="Pay",
        name=f"PE-PAY-LEG-{docserial}",
        header=header,
        party_type=party_type,
        party_name=party_name,
        party_row=party_row,
        cash_row=cash_row,
        all_rows=details,
    )
    ctx.result.emit("Payment Entry", payload)
    ctx.result.bump("supplier_payments_emitted")


# -- Shared payload builder ---------------------------------------------------

def _payment_payload(
    ctx: Context,
    kind: str,
    name: str,
    header: dict,
    party_type: str,
    party_name: str,
    party_row: dict,
    cash_row: dict,
    all_rows: list[dict],
) -> dict:
    amount = parse_decimal(header.get("DOCVALUE"))
    party_account = account_full_name(ctx, party_row.get("ACCOUNTID"))
    cash_account = account_full_name(ctx, cash_row.get("ACCOUNTID"))
    cheque_meta = _cheque_metadata(ctx, all_rows)
    return {
        "name": name,
        "payment_type": kind,
        "company": ctx.config.company_name,
        "posting_date": parse_date(header.get("DOCDATE")),
        "party_type": party_type,
        "party": party_name,
        "paid_amount": amount,
        "received_amount": amount,
        "source_exchange_rate": 1.0,
        "target_exchange_rate": 1.0,
        "paid_from": party_account if kind == "Receive" else cash_account,
        "paid_to": cash_account if kind == "Receive" else party_account,
        "mode_of_payment": MODE_CHEQUE if cheque_meta else MODE_CASH,
        "reference_no": cheque_meta.get("cheque_no", "") if cheque_meta else "",
        "reference_date": cheque_meta.get("cheque_date", "") if cheque_meta else "",
        "remarks": clean_str(header.get("FORWHAT")) or clean_str(header.get("NOTES")),
        "docstatus": 1 if clean_str(header.get("POSTFLAG")) == "2" else 0,
        # Cheque-specific custom fields (empty when not a cheque payment).
        **(cheque_meta or {}),
        "legacy_docno": clean_str(header.get("DOCNO")),
        "legacy_docserial": clean_str(header.get("DOCSERIAL")),
    }


# -- Cheque metadata lookup ---------------------------------------------------

def _cheque_metadata(ctx: Context, all_rows: list[dict]) -> dict:
    """Scan all detail rows for cheque info — legacy puts it on the cheque-box
    side (DEBIT for receipts, CREDIT for payments), not the party side.

    Returns custom-field dict to splat onto the Payment Entry, or {} if no
    cheque was used.
    """
    cheque_row = _find_cheque_row(all_rows)
    if not cheque_row:
        return {}
    chequeid = clean_str(cheque_row.get("CHEQUEID"))
    cheque = _cheque_by_id(ctx).get(chequeid) if chequeid else None
    bank_name = _cheque_bank_name(ctx, cheque_row, cheque)
    return {
        "cheque_no": clean_str((cheque or {}).get("CHEQUENO"))
                     or clean_str(cheque_row.get("CHEQUE_CHEQUENO")),
        "cheque_date": parse_date((cheque or {}).get("CDATE")
                                  or cheque_row.get("CHEQUE_CDATE")),
        "cheque_clearing_date": parse_date((cheque or {}).get("REALCDATE")
                                           or cheque_row.get("CHEQUE_REALCDATE")),
        "cheque_owner_name": clean_str((cheque or {}).get("OWNERNAME")
                                       or cheque_row.get("CHEQUE_OWNERNAME")),
        "cheque_bank": bank_name,
        "cheque_branch": clean_str((cheque or {}).get("CBANKBRANCH")
                                   or cheque_row.get("CHEQUE_CBANKBRANCH")),
        "cheque_returned": 1 if _is_returned(cheque, cheque_row) else 0,
        "cheque_returned_count": int(parse_decimal(
            (cheque or {}).get("CHEQUEBACK"), default=0,
        )),
        "cheque_bank_account": bank_account_label(
            ctx, (cheque or {}).get("BANKACC"),
        ),
        "linked_legacy_cheque_id": chequeid,
    }


def _find_cheque_row(all_rows: list[dict]) -> dict | None:
    for r in all_rows or []:
        if clean_str(r.get("CHEQUEID")) or clean_str(r.get("CHEQUE_CHEQUENO")):
            return r
    return None


def _cheque_by_id(ctx: Context) -> dict[str, dict]:
    cached = getattr(ctx, "_cheque_index", None)
    if cached is not None:
        return cached
    index = {clean_str(r.get("CHEQUEID")): r for r in ctx.table("CHEQUET")
             if clean_str(r.get("CHEQUEID"))}
    ctx._cheque_index = index  # type: ignore[attr-defined]
    return index


def _cheque_bank_name(ctx: Context, party_row: dict, cheque: dict | None) -> str:
    bank_id = clean_str((cheque or {}).get("CBANK")) \
              or clean_str(party_row.get("CHEQUE_CBANK"))
    if not bank_id:
        return ""
    bank = ctx.banks_by_id.get(bank_id)
    return pick(bank or {}, "BANKNAME", "BANKNAMEE", "BANKNAMEH")


def _is_returned(cheque: dict | None, party_row: dict) -> bool:
    if cheque and clean_str(cheque.get("RETURNED")) not in {"", "0"}:
        return True
    if clean_str(party_row.get("CHEQUE_RETURNED")) not in {"", "0"}:
        return True
    return False


# -- Helpers ------------------------------------------------------------------

def _pick_party_row(details: Iterable[dict], dr_or_cr: str) -> dict | None:
    """Return the first detail row with a non-zero amount in the named column."""
    for r in details or []:
        if parse_decimal(r.get(dr_or_cr)) > 0:
            return r
    return None
