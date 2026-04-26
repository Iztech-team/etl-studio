"""
Composable column-level transform operations.

Each op is a pure function: (value, params, ctx) -> value
ctx is an optional dict carrying {row, column_name} for row-aware ops.
No DB calls, no side effects, no imports beyond stdlib.
"""

import re
import uuid
from typing import Any, Dict, Optional


# ---------- registry ----------

TRANSFORM_OPS: Dict[str, callable] = {}


def _register(name: str):
    def decorator(fn):
        TRANSFORM_OPS[name] = fn
        return fn

    return decorator


def apply_transforms(
    value: Any,
    transforms: list,
    column_name: str = "",
    row: Optional[Dict[str, Any]] = None,
    state: Optional[Dict[str, Any]] = None,
    exceptions: Optional[Dict[str, list]] = None,
    table: str = "",
) -> Any:
    """Run a list of {op, params} transforms in order. Returns final value.

    Row-aware ops (concat_template) read sibling cells from `row`.
    Stateful ops (row_number) accumulate counters via `state` (caller passes a
    fresh dict per table so counters reset between tables).
    Ops can record review-needed cases by appending to ctx['exceptions'][category].
    Legacy ops accepting (value, params) still work — extra ctx arg is optional.
    """
    ctx = {
        "row": row or {},
        "column": column_name,
        "state": state if state is not None else {},
        "exceptions": exceptions if exceptions is not None else {},
        "table": table,
    }
    for t in transforms:
        op_name = t.get("op")
        params = t.get("params", {})
        fn = TRANSFORM_OPS.get(op_name)
        if fn is None:
            continue
        try:
            value = fn(value, params, ctx)
        except TypeError:
            value = fn(value, params)
    return value


# ---------- ops ----------


@_register("normalize_phone")
def normalize_phone(value: Any, params: Dict) -> Any:
    """Normalize phone to international format. Handles +, 00, and local forms.

    params:
        country_code: str - prefix to add when number has no international prefix
                            (e.g. '+970'). If empty, leaves local-form numbers as-is.
        keep_plus: bool - keep leading + on output (default true)
    """
    if value is None:
        return value
    s = str(value).strip()
    if not s:
        return value

    keep_plus = params.get("keep_plus", True)
    country_code = params.get("country_code", "")

    has_plus = s.startswith("+")
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return value

    # Tier 1 — already international: strip 00 prefix and re-emit with +
    if has_plus:
        return ("+" if keep_plus else "") + digits
    if digits.startswith("00"):
        digits = digits[2:]
        return ("+" if keep_plus else "") + digits

    # Local form — prepend the configured country code if any
    if country_code:
        local = digits.lstrip("0")
        cc_digits = country_code.lstrip("+")
        return (("+" if keep_plus else "") + cc_digits + local) if cc_digits else digits

    return digits


@_register("detect_country_code")
def detect_country_code(value: Any, params: Dict, ctx: Optional[Dict] = None) -> Any:
    """4-tier country dial-code detection from a phone string (spec 3.4).

    Tier 1: leading + or 00 → strip and lookup in dial_codes (longest-match)
    Tier 2: leading local digits → match prefix_table
    Tier 3: fallback by shop currency → currency_fallback[currency]
    Tier 4: unresolved → return params['unresolved'] (default None)

    params:
        source_field: str - row column to read the phone from when this op runs
                            on an is_new column (value is None). Falls back to
                            `value` if unset.
        prefix_table: dict {local_prefix: dial_code}
                      e.g. {'059': '+970', '05': '+970', '077': '+962',
                            '078': '+962', '079': '+962',
                            '052': '+972', '054': '+972', '058': '+972'}
        dial_codes: list of known dial codes for tier-1 longest-match
                    e.g. ['+970','+962','+972','+1','+44']
        currency_fallback: dict {currency_code: dial_code}
                            e.g. {'JOD':'+962','NIS':'+970','ILS':'+970','USD':'+1'}
        currency: str - the shop's primary currency (tier-3 input)
        currency_field: str - row column to read currency from when `currency`
                              is not provided
        unresolved: str | None - return value when nothing matches (default None)
    """
    src_field = params.get("source_field")
    if value is None and src_field:
        row_for_src = (ctx or {}).get("row") or {}
        value = row_for_src.get(src_field)
    if value is None:
        return params.get("unresolved")
    s = str(value).strip()
    if not s:
        return params.get("unresolved")

    digits = "".join(ch for ch in s if ch.isdigit())
    has_plus = s.startswith("+")
    has_00 = digits.startswith("00")

    # --- Tier 1: international form ---
    if has_plus or has_00:
        intl = digits[2:] if has_00 else digits
        dial_codes = params.get("dial_codes") or []
        # longest-match first
        for dc in sorted({d.lstrip("+") for d in dial_codes}, key=len, reverse=True):
            if dc and intl.startswith(dc):
                return "+" + dc

    # --- Tier 2: local prefix table ---
    prefix_table = params.get("prefix_table") or {}
    if digits and prefix_table:
        for prefix in sorted(prefix_table.keys(), key=len, reverse=True):
            if digits.startswith(prefix):
                return prefix_table[prefix]

    # --- Tier 3: currency fallback ---
    currency_fallback = params.get("currency_fallback") or {}
    currency = params.get("currency")
    if not currency:
        cur_field = params.get("currency_field")
        row = (ctx or {}).get("row") or {}
        if cur_field:
            currency = row.get(cur_field)
    if currency and currency in currency_fallback:
        return currency_fallback[currency]

    # --- Tier 4: unresolved ---
    excs = (ctx or {}).get("exceptions")
    if excs is not None:
        excs.setdefault("country_code_unresolved", []).append(
            {
                "table": (ctx or {}).get("table", ""),
                "column": (ctx or {}).get("column", ""),
                "value": s,
                "currency": currency,
            }
        )
    return params.get("unresolved")


@_register("split_name")
def split_name(value: Any, params: Dict) -> Any:
    """Extract a part of a name string by position.

    params:
        part: "first" | "last" | "all_but_last" | "all_but_first" | "word_N" (0-indexed)
        separator: str (default " ")
        default: fallback if the requested part doesn't exist
    """
    if value is None:
        return params.get("default", value)
    s = str(value).strip()
    if not s:
        return params.get("default", value)

    sep = params.get("separator", " ")
    parts = [p for p in s.split(sep) if p]
    default = params.get("default", s)
    part = params.get("part", "first")

    if not parts:
        return default

    if part == "first":
        return parts[0]
    if part == "last":
        return parts[-1]
    if part == "all_but_last":
        return sep.join(parts[:-1]) if len(parts) > 1 else default
    if part == "all_but_first":
        return sep.join(parts[1:]) if len(parts) > 1 else default
    if part.startswith("word_"):
        try:
            idx = int(part.split("_", 1)[1])
            return parts[idx] if idx < len(parts) else default
        except (ValueError, IndexError):
            return default

    return default


@_register("map_values")
def map_values(value: Any, params: Dict) -> Any:
    """Map value through a lookup dict with optional default.

    params:
        mapping: dict - key->value pairs (keys compared as strings)
        default: "original" to keep original value, or any literal fallback
        case_insensitive: bool (default false)
    """
    if value is None:
        return params.get("default_null", value)

    mapping = params.get("mapping", {})
    default = params.get("default", "original")
    case_insensitive = params.get("case_insensitive", False)

    lookup_key = str(value)
    if case_insensitive:
        lookup_key = lookup_key.lower()
        mapping = {str(k).lower(): v for k, v in mapping.items()}

    if lookup_key in mapping:
        return mapping[lookup_key]

    # String keys from JSON always — also try original value directly
    if value in mapping:
        return mapping[value]

    if default == "original":
        return value
    return default


@_register("concat_template")
def concat_template(value: Any, params: Dict, ctx: Optional[Dict] = None) -> Any:
    """Build a string from a template using the current row's fields.

    Used for: notes traceability ('[PAYDOC #{docserial}] {notes}'), supplier
    address concat, fullName rebuild from firstName/lastName, cheque info into
    notes ('CHQ#{chequeno} BANK:{cbank}').

    params:
        template: str - format string with {column_name} placeholders.
                  Use {value} to reference the current cell.
                  Missing/None columns substitute with `null_as` (default '').
        null_as: str - replacement for None / missing fields (default '')
        skip_if_all_null: bool - return None if every referenced field is null
                                  (default false). Useful for fully-optional concats.
        strip: bool - strip leading/trailing whitespace from result (default true)
    """
    template = params.get("template", "")
    if not template:
        return value
    null_as = params.get("null_as", "")
    skip_if_all_null = params.get("skip_if_all_null", False)
    strip = params.get("strip", True)

    row = (ctx or {}).get("row") or {}
    placeholders = re.findall(r"\{([^{}]+)\}", template)

    all_null = True
    subs: Dict[str, str] = {}
    for key in placeholders:
        if key == "value":
            v = value
        else:
            v = row.get(key)
        if v is not None and str(v) != "":
            all_null = False
            subs[key] = str(v)
        else:
            subs[key] = null_as

    if skip_if_all_null and all_null:
        return None

    result = template
    for key, sub in subs.items():
        result = result.replace("{" + key + "}", sub)
    return result.strip() if strip else result


@_register("generate_uuid")
def generate_uuid(value: Any, params: Dict) -> Any:
    """Generate a UUID. Deterministic mode produces stable UUIDs from input value.

    params:
        deterministic: bool (default false) - if true, same input -> same UUID
        namespace: str (default "etl-legacy") - namespace for deterministic UUIDs
        keep_original: bool (default false) - if true, only fill NULLs
    """
    if params.get("keep_original", False) and value is not None:
        return value

    if params.get("deterministic", False):
        ns = params.get("namespace", "etl-legacy")
        ns_uuid = uuid.uuid5(uuid.NAMESPACE_DNS, ns)
        return str(uuid.uuid5(ns_uuid, str(value) if value is not None else ""))

    return str(uuid.uuid4())


@_register("default_if_null")
def default_if_null(value: Any, params: Dict) -> Any:
    """Replace null or empty values with a default.

    params:
        value: the default to use
        treat_empty_as_null: bool (default true) - also replace "" and whitespace-only
    """
    treat_empty = params.get("treat_empty_as_null", True)

    if value is None:
        return params.get("value")
    if treat_empty and isinstance(value, str) and not value.strip():
        return params.get("value")
    return value


@_register("conditional")
def conditional(value: Any, params: Dict) -> Any:
    """Apply if/then rules to map values conditionally.

    params:
        rules: list of {when: value_or_list, then: value}
        default: value if no rule matches ("original" to keep, or a literal)
        case_insensitive: bool (default false)
    """
    rules = params.get("rules", [])
    default = params.get("default", "original")
    case_insensitive = params.get("case_insensitive", False)

    check = str(value).lower() if case_insensitive and value is not None else value

    for rule in rules:
        when = rule.get("when")
        then = rule.get("then")
        # "when" can be a single value or a list of values
        if isinstance(when, list):
            targets = [str(w).lower() if case_insensitive else w for w in when]
            if check in targets:
                return then
        else:
            target = str(when).lower() if case_insensitive else when
            if check == target or str(value) == str(when):
                return then

    if default == "original":
        return value
    return default


@_register("row_number")
def row_number(value: Any, params: Dict, ctx: Optional[Dict] = None) -> Any:
    """Sequential numbering, optionally per partition. Spec 3.2 category.displayOrder.

    Counts rows in their input order. To replicate ROW_NUMBER() OVER (ORDER BY x),
    sort the source rows by `x` before transformation.

    params:
        partition_by: list[str] - row column names that define a partition; the
                                  counter resets per unique tuple. Empty = global.
        start: int - first value to emit (default 1)
        keep_original: bool - if true, leave non-null cells alone and only fill
                              nulls with the generated number (default false)
    """
    if params.get("keep_original", False) and value is not None:
        return value

    state = (ctx or {}).get("state")
    if state is None:
        state = {}
    counters = state.setdefault("__row_number_counters__", {})

    partition_by = params.get("partition_by") or []
    row = (ctx or {}).get("row") or {}
    key = tuple(row.get(c) for c in partition_by)

    start = int(params.get("start", 1))
    next_val = counters.get(key, start)
    counters[key] = next_val + 1
    return next_val
