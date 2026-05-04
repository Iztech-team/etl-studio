"""Pure helpers shared across erpnext domain modules.

No I/O, no state. Each function is a small, named operation that the
domain modules compose. Anything stateful (lookups, config, result
accumulator) lives on Context (see context.py).
"""

import re
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

# Subset of ERPnext v16's 239 built-in UOMs that we actually map onto.
# (Verified from frappe/erpnext version-16 setup_wizard/data/uom_data.json.)
ERPNEXT_BUILTIN_UOMS: set[str] = {
    "Box",
    "Centimeter",
    "Cubic Centimeter",
    "Cubic Meter",
    "Cup",
    "Gram",
    "Hour",
    "Kg",
    "Litre",
    "Meter",
    "Minute",
    "Nos",
    "Ounce",
    "Pair",
    "Pound",
    "Set",
    "Square Centimeter",
    "Square Meter",
    "Tonne",
    "Unit",
}

# Map every legacy unit (Arabic free-text + UNITT English) to a v16
# built-in UOM. v16 ships 239 UOMs but most shape-specific ones (Can,
# Carton, Bottle, Packet, Bag, Jar, Piece, etc.) are NOT among them, so
# we collapse those to the closest built-in. Anything unmapped falls
# back to DEFAULT_UOM ('Nos').
UOM_CANONICAL: dict[str, str] = {
    # ---- v16 built-in matches (no emit needed) ----
    "Unit": "Unit",
    "وحدة": "Unit",
    "Kg": "Kg",
    "كيلو": "Kg",
    "كغم": "Kg",
    "Gram": "Gram",
    "Gr": "Gram",
    "غرام": "Gram",
    "Box": "Box",
    "صندوق": "Box",
    "Litre": "Litre",
    "Liter": "Litre",
    "لتر": "Litre",
    "Meter": "Meter",
    "متر": "Meter",
    "Pound": "Pound",
    "رطل": "Pound",
    "Rotl": "Pound",
    "Pair": "Pair",
    "اجوزة": "Pair",
    "اجوزيات": "Pair",
    "Set": "Set",
    "طقم": "Set",
    "Nos": "Nos",
    "Hour": "Hour",
    "Minute": "Minute",
    "Cup": "Cup",
    "كوب": "Cup",
    "كاسة": "Cup",
    "Tonne": "Tonne",
    "Ton": "Tonne",
    "طن": "Tonne",
    "Ounce": "Ounce",
    "Ouqiya": "Ounce",
    "وقية": "Ounce",
    "Square Meter": "Square Meter",
    "M2": "Square Meter",
    "م2": "Square Meter",
    "Square Centimeter": "Square Centimeter",
    "Cm2": "Square Centimeter",
    "سم2": "Square Centimeter",
    "Cubic Meter": "Cubic Meter",
    "M3": "Cubic Meter",
    "م3": "Cubic Meter",
    "Cubic Centimeter": "Cubic Centimeter",
    "Cm3": "Cubic Centimeter",
    "سم3": "Cubic Centimeter",
    "Centimeter": "Centimeter",
    "CM": "Centimeter",
    "سم": "Centimeter",
    # ---- Custom UOMs (emitted in 01_uom.csv before items import) ----
    # Container shapes
    "Carton": "Carton",
    "كرتون": "Carton",
    "كرتونة": "Carton",
    "كرتونه": "Carton",
    "كتونه": "Carton",
    "Can": "Can",
    "علبة": "Can",
    "علبه": "Can",
    "علب": "Can",
    "Tin": "Tin",
    "تنكة": "Tin",
    "تنكه": "Tin",
    "Crate": "Crate",
    "كروز": "Crate",
    "Pack": "Pack",
    "Packet": "Pack",
    "بكيت": "Pack",
    "بكييت": "Pack",
    "بيكت": "Pack",
    "وبكيت": "Pack",
    "عبوة": "Pack",
    "Bag": "Bag",
    "كيس": "Bag",
    "أكياس": "Bag",
    "شوال": "Bag",
    "Sack": "Bag",
    "Jar": "Jar",
    "مطربان": "Jar",
    # Volume containers
    "Bottle": "Bottle",
    "قنينة": "Bottle",
    "قنية": "Bottle",
    "قنيه": "Bottle",
    "قنيةى": "Bottle",
    "Jerrycan": "Jerrycan",
    "جركل": "Jerrycan",
    "Gallon": "Gallon",
    "جلن": "Gallon",
    "Pail": "Pail",
    "سطل": "Pail",
    # Discrete items
    "Piece": "Piece",
    "Pieces": "Piece",
    "قطعة": "Piece",
    "حبة": "Piece",
    "حبه": "Piece",
    "Bowl": "Bowl",
    "جاط": "Bowl",
    "Plate": "Plate",
    "صحن": "Plate",
    "Mug": "Mug",
    "كوز": "Mug",
    "Pitcher": "Pitcher",
    "ابريق": "Pitcher",
    "Vessel": "Vessel",
    "أنية": "Vessel",
    "انية": "Vessel",
    "Roll": "Roll",
    "رول": "Roll",
    "لفة": "Roll",
    "Slice": "Slice",
    "شرحة": "Slice",
    "Mould": "Mould",
    "قالب": "Mould",
    "Brush": "Brush",
    "فرشاية": "Brush",
    "Device": "Device",
    "جهاز": "Device",
    "Sprinkler": "Sprinkler",
    "مطرة": "Sprinkler",
    "Greenhouse": "Greenhouse",
    "صوبة": "Greenhouse",
    "Hanato": "Hanato",
    "هاناتو": "Hanato",
    # Groups
    "Bunch": "Bunch",
    "ربطة": "Bunch",
    "ربطه": "Bunch",
    "Bundle": "Bundle",
    "رزمة": "Bundle",
    "حزمة": "Bundle",
    "Dozen": "Dozen",
    "دزينة": "Dozen",
    "دزينه": "Dozen",
    "Quartet": "Quartet",
    "اربعات": "Quartet",
    # Cable (length-shaped, custom)
    "Cable": "Cable",
    "كابل": "Cable",
}

DEFAULT_UOM = "Nos"


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


_HIERARCHY_SEPARATOR = re.compile(r"\s*[\\\/]\s*")
_WHITESPACE_RUN = re.compile(r"\s+")


def safe_account_name(raw: Any) -> str:
    """Normalize a legacy account NAME for Frappe-safe autonames.

    Legacy ALArabi uses '\\' or '/' as an inline hierarchy separator on leaf
    names — e.g. 'صندوق الشيكات\\شيكل' = 'cheque box \\ shekel' or
    'محمد أبو جانتي / موظف' = 'Mohamed Abu Janti / Employee'.
    Frappe v15+ has a confirmed query-builder bug where frappe.db.count() /
    validate_link_and_fetch can't match a docname containing '\\' inside an
    Arabic string. The link picker shows the account in search results but
    silently drops the selection because the validator returns {} (verified
    empirically). Replacing both '\\' and '/' with ' - ' preserves the
    hierarchy visually, dodges the encoding round-trip, and keeps the name
    URL-safe in every other context.
    """
    s = clean_str(raw)
    if not s:
        return ""
    s = _HIERARCHY_SEPARATOR.sub(" - ", s)
    s = _WHITESPACE_RUN.sub(" ", s)
    return s.strip()


_PHONE_RUN = re.compile(r"\+?[0-9][0-9 \-]*")


def normalize_phone(value: Any) -> str:
    """Extract the digit-only phone number from possibly-dirty input.

    Legacy CONTACTST sometimes embeds Arabic names or notes inside the
    phone field (e.g. '0597640262شادي'). We grab the first contiguous
    run of digits (with optional '+' prefix and embedded dashes/spaces)
    and strip everything else.
    """
    s = clean_str(value)
    if not s:
        return ""
    match = _PHONE_RUN.search(s)
    if not match:
        return ""
    return "".join(c for c in match.group(0) if c.isdigit() or c == "+")


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
    """Force-map legacy UNIT (Arabic free-text or English) to one of
    ERPnext's 12 built-in UOMs. Unmapped or empty inputs fall back to
    DEFAULT_UOM ('Nos') so every Item.stock_uom resolves to something
    Frappe already knows about — no UOM CSV emit required.
    """
    s = clean_str(text)
    if not s:
        return DEFAULT_UOM
    canonical = UOM_CANONICAL.get(s)
    if canonical:
        return canonical
    return DEFAULT_UOM


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


# -- account name resolution (shared between strategies) ----------------------


def account_full_name(ctx, account_id) -> str:
    """Return the autonamed Account form for a legacy ACCOUNTID.

    Matches Frappe's get_autoname_with_number(): when account_number is
    set, the autoname is '{number} - {name} - {abbr}'. The name part is
    normalised via safe_account_name() to swap the legacy '\\'
    hierarchy separator for ' - ' so Frappe's validate_link_and_fetch
    can match against the stored row.
    """
    aid = clean_str(account_id)
    row = ctx.accounts_by_id.get(aid)
    if not row:
        return ""
    name = safe_account_name(pick(row, "NAME", "NAMEE", "NAMEH"))
    if not name:
        return ""
    parts = [aid, name] if aid else [name]
    suffix = clean_str(ctx.config.company_abbr)
    if suffix and suffix not in parts[-1]:
        parts.append(suffix)
    return " - ".join(parts)


# -- legacy tree walk (shared: mirror emits the tree, native classifies) ------

# Map from legacy ROOT ACCOUNTID → ERPnext (root_type, report_type). These are
# the 6 hand-curated Al Arabi roots plus the ACCOUNTID=0 placeholder (treated
# as Asset). Used both to build the mirror CoA and to classify legacy accounts
# into ERPnext buckets in native.
ROOT_TYPE_BY_ID: dict[str, tuple[str, str]] = {
    "0": ("Asset", "Balance Sheet"),  # غير محدد (placeholder)
    "1": ("Asset", "Balance Sheet"),  # الموجودات
    "2": ("Liability", "Balance Sheet"),  # المطلوبات
    "3": ("Equity", "Balance Sheet"),  # راس المال
    "4": ("Expense", "Profit and Loss"),  # المشتريات والمصاريف
    "5": ("Income", "Profit and Loss"),  # الايرادات
    "6": ("Asset", "Balance Sheet"),  # الذمم (memo / receivables)
}


def walk_to_root(account_id: str, by_id: dict) -> str:
    """Walk FATHERID up to find an ACCOUNTT row's root ACCOUNTID."""
    cur = clean_str(account_id)
    seen: set[str] = set()
    for _ in range(20):
        if not cur or cur in seen:
            break
        seen.add(cur)
        if cur in ROOT_TYPE_BY_ID:
            return cur
        father = clean_str((by_id.get(cur) or {}).get("FATHERID"))
        if not father or father == cur:
            break
        cur = father
    return clean_str(account_id)
