"""Pure helpers shared across erpnext domain modules.

No I/O, no state. Each function is a small, named operation that the
domain modules compose. Anything stateful (lookups, config, result
accumulator) lives on Context (see context.py).
"""
from typing import Any, Iterable

# Sentinel "no value" date that legacy uses for null timestamps.
SENTINEL_DATE = "1899-12-30"

CURRENCY_BY_LEGACY_ID: dict[str, str] = {
    "1": "ILS",  # NIS / Sheqel — base currency
    "2": "JOD",  # Jordanian Dinar
    "3": "USD",  # Dollar
    "4": "EUR",  # Euro
}

DEFAULT_CURRENCY = "ILS"
DEFAULT_UOM = "وحدة"


# -- text / value coercion ----------------------------------------------------

def clean_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def pick(row: dict, *fields: str) -> str:
    """First non-empty field value (Arabic-first chain: NAME → NAMEE → NAMEH)."""
    for f in fields:
        v = clean_str(row.get(f))
        if v:
            return v
    return ""


def is_truthy(value: Any) -> bool:
    """Legacy uses 1/0/true/false/yes/no with mixed casing for booleans."""
    s = clean_str(value).lower()
    return s in {"1", "true", "yes", "y", "t"}


def parse_decimal(value: Any, default: float = 0.0) -> float:
    s = clean_str(value)
    if not s:
        return default
    try:
        return float(s)
    except (TypeError, ValueError):
        return default


# -- date / time --------------------------------------------------------------

def parse_date(value: Any) -> str | None:
    """Return YYYY-MM-DD or None for empty / sentinel dates."""
    s = clean_str(value)
    if not s:
        return None
    head = s.split(" ", 1)[0]
    if head.startswith(SENTINEL_DATE):
        return None
    return head


def parse_time(value: Any) -> str | None:
    """Return HH:MM:SS or None — strips trailing fractional seconds."""
    s = clean_str(value)
    if not s:
        return None
    head = s.split(".", 1)[0]
    return head if ":" in head else None


# -- currency / unit lookups --------------------------------------------------

def currency_iso(curid: Any) -> str:
    """Legacy CURID (1..4) → ISO code (ILS / JOD / USD / EUR)."""
    s = clean_str(curid)
    if not s:
        return DEFAULT_CURRENCY
    return CURRENCY_BY_LEGACY_ID.get(s, DEFAULT_CURRENCY)


def normalize_uom(text: Any) -> str:
    """Free-text legacy UNIT → ERPnext UOM name. Empty → DEFAULT_UOM."""
    s = clean_str(text)
    return s or DEFAULT_UOM


# -- naming -------------------------------------------------------------------

def with_abbr(name: str, abbr: str) -> str:
    """Append the company abbreviation suffix Frappe autoname applies.

    Used for Account / Warehouse names so cross-document references resolve.
    """
    base = clean_str(name)
    suffix = clean_str(abbr)
    if not base:
        return ""
    if not suffix:
        return base
    return f"{base} - {suffix}"


# -- legacy ID encoders -------------------------------------------------------

def item_id(catid: Any) -> str:
    return f"ALA-{clean_str(catid)}"


def customer_id(account_id: Any) -> str:
    return f"CUST-{clean_str(account_id)}"


def supplier_id(account_id: Any) -> str:
    return f"SUPP-{clean_str(account_id)}"


def employee_id(empid: Any) -> str:
    return f"EMP-{clean_str(empid)}"


def cheque_id(chequeid: Any) -> str:
    return f"CHQ-{clean_str(chequeid)}"


WALKIN_CUSTOMER_ID = "CUST-WALKIN"


# -- iteration helpers --------------------------------------------------------

def index_by(rows: Iterable[dict], key: str) -> dict[str, dict]:
    """Build a row-by-key index, last-write-wins on collisions."""
    out: dict[str, dict] = {}
    for r in rows or []:
        k = clean_str(r.get(key))
        if k:
            out[k] = r
    return out


def group_by(rows: Iterable[dict], key: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows or []:
        k = clean_str(r.get(key))
        if k:
            out.setdefault(k, []).append(r)
    return out
