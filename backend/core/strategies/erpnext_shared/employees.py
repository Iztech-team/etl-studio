"""Employee emit (EMPLOYEET → Employee doctype, ERPnext HR module).

ERPnext v16 marks five fields as required: first_name, company, status,
gender, date_of_birth, date_of_joining. The legacy data routinely uses
the 1899-12-30 sentinel for unknown dates so we fall back to defensible
defaults rather than skip the row.
"""

from core.strategies.erpnext_shared.common import (
    clean_str,
    employee_id,
    is_truthy,
    parse_date,
    parse_decimal,
    pick,
)
from core.strategies.erpnext_shared.context import Context

# Sensible fallback for the rare row missing both BIRTH and a usable
# placeholder. ERPnext won't accept null on a required Date field.
DEFAULT_DOB = "1990-01-01"


def emit_employees(ctx: Context) -> None:
    for row in ctx.table("EMPLOYEET"):
        _emit_employee(ctx, row)


def _emit_employee(ctx: Context, row: dict) -> None:
    empid = clean_str(row.get("EMPID"))
    if not empid:
        ctx.result.bump("employees_skipped_no_empid")
        return
    name = _employee_name(ctx, row)
    if not name:
        ctx.result.warn("Employee", "missing ACCOUNTT.NAME", legacy_empid=empid)
        return
    is_working = is_truthy(row.get("ISWORKING"))
    join_date = _join_date(ctx, row)
    payload = {
        "name": employee_id(empid),
        "employee_number": empid,
        "first_name": name,
        "employee_name": name,
        "company": ctx.config.company_name,
        "gender": _gender(row),
        "date_of_birth": parse_date(row.get("BIRTH")) or DEFAULT_DOB,
        "date_of_joining": join_date,
        "relieving_date": "",
        "status": "Active" if is_working else "Left",
        "salary_currency": ctx.config.default_currency,
        "ctc": parse_decimal(row.get("SALARY")),
        "attendance_device_id": clean_str(row.get("CARDID")),
        "bio": clean_str(row.get("NOTE")),
        "legacy_empid": empid,
        "legacy_acctid": clean_str(row.get("ACCOUNT")),
    }
    ctx.result.emit("Employee", payload)
    ctx.result.bump("employees_emitted")


def _employee_name(ctx: Context, row: dict) -> str:
    account_id = clean_str(row.get("ACCOUNT"))
    account = ctx.accounts_by_id.get(account_id, {})
    return pick(account, "NAME", "NAMEE", "NAMEH")


def _gender(row: dict) -> str:
    """Legacy GENDER: 1=Male, 2=Female; default Male if unknown."""
    raw = clean_str(row.get("GENDER"))
    if raw == "2":
        return "Female"
    return "Male"


def _join_date(ctx: Context, row: dict) -> str:
    return (
        parse_date(row.get("STARTDATE"))
        or parse_date(row.get("CHANGEDATE_DATA"))
        or ctx.config.opening_date
        or DEFAULT_DOB
    )
