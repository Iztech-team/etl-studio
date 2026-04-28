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

# ERPnext ships with these built-in UOMs by default. We map every legacy
# unit string to one of these — nothing else — so the strategy never
# needs to emit a UOM CSV. Items / invoice lines simply reference the
# pre-existing built-ins.
ERPNEXT_BUILTIN_UOMS: set[str] = {
    "Box", "Gram", "Hour", "Kg", "Litre", "Meter",
    "Minute", "Nos", "Pair", "Pound", "Set", "Unit",
}

# Force-map from legacy units (Arabic free-text + UNITT English) to one
# of the 12 ERPnext built-ins. Loses some semantic precision (Carton vs
# Box vs Can all become 'Box') in exchange for zero UOM-setup work in
# ERPnext after migration. Anything unmapped falls back to DEFAULT_UOM.
UOM_CANONICAL: dict[str, str] = {
    # ---- Direct built-in matches ----
    "Unit": "Unit", "وحدة": "Unit",
    "Kg": "Kg", "كيلو": "Kg", "كغم": "Kg",
    "Gram": "Gram", "Gr": "Gram", "غرام": "Gram",
    "Box": "Box", "صندوق": "Box",
    "Litre": "Litre", "Liter": "Litre", "لتر": "Litre",
    "Meter": "Meter", "متر": "Meter",
    "Pound": "Pound", "رطل": "Pound",
    "Pair": "Pair", "اجوزة": "Pair", "اجوزيات": "Pair",
    "Set": "Set", "طقم": "Set",
    "Nos": "Nos",
    "Hour": "Hour", "Minute": "Minute",
    # ---- Container-shaped → Box ----
    "Carton": "Box", "كرتون": "Box", "كرتونة": "Box", "كرتونه": "Box", "كتونه": "Box",
    "Can": "Box", "علبة": "Box", "علبه": "Box", "علب": "Box",
    "Tin": "Box", "تنكة": "Box", "تنكه": "Box",
    "Crate": "Box", "كروز": "Box",
    "Pack": "Box", "Packet": "Box",
    "بكيت": "Box", "بكييت": "Box", "بيكت": "Box", "وبكيت": "Box", "عبوة": "Box",
    "Bag": "Box", "كيس": "Box", "أكياس": "Box", "شوال": "Box", "Sack": "Box",
    "Jar": "Box", "مطربان": "Box",
    # ---- Discrete count → Nos ----
    "Piece": "Nos", "Pieces": "Nos", "قطعة": "Nos", "حبة": "Nos", "حبه": "Nos",
    "Bowl": "Nos", "جاط": "Nos",
    "Plate": "Nos", "صحن": "Nos",
    "Cup": "Nos", "كوب": "Nos", "كاسة": "Nos",
    "Mug": "Nos", "كوز": "Nos",
    "Pitcher": "Nos", "ابريق": "Nos",
    "Vessel": "Nos", "أنية": "Nos", "انية": "Nos",
    "Bottle": "Nos", "قنينة": "Nos", "قنية": "Nos", "قنيه": "Nos", "قنيةى": "Nos",
    "Pail": "Nos", "سطل": "Nos",
    "Roll": "Nos", "رول": "Nos", "لفة": "Nos",
    "Slice": "Nos", "شرحة": "Nos",
    "Mould": "Nos", "قالب": "Nos",
    "Brush": "Nos", "فرشاية": "Nos",
    "Device": "Nos", "جهاز": "Nos",
    "Sprinkler": "Nos", "مطرة": "Nos",
    "Greenhouse": "Nos", "صوبة": "Nos",
    "Hanato": "Nos", "هاناتو": "Nos",
    # ---- Group-of-things → Set ----
    "Bunch": "Set", "ربطة": "Set", "ربطه": "Set",
    "Bundle": "Set", "رزمة": "Set", "حزمة": "Set",
    "Dozen": "Set", "دزينة": "Set", "دزينه": "Set",
    "Quartet": "Set", "اربعات": "Set",
    # ---- Volume containers → Litre ----
    "Jerrycan": "Litre", "جركل": "Litre",
    "Gallon": "Litre", "جلن": "Litre",
    "Cubic Meter": "Litre", "M3": "Litre", "م3": "Litre",
    "Cubic Centimeter": "Litre", "Cm3": "Litre", "سم3": "Litre",
    # ---- Length / area → Meter ----
    "Square Meter": "Meter", "M2": "Meter", "م2": "Meter",
    "Square Centimeter": "Meter", "Cm2": "Meter", "سم2": "Meter",
    "Centimeter": "Meter", "CM": "Meter", "سم": "Meter",
    "Cable": "Meter", "كابل": "Meter",
    # ---- Weight without a built-in fit ----
    "Ton": "Kg",
    "Rotl": "Pound",
    "Ouqiya": "Pound", "وقية": "Pound",
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
