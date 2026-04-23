"""
Composable column-level transform operations.

Each op is a pure function: (value, params) -> value
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


def apply_transforms(value: Any, transforms: list, column_name: str = "") -> Any:
    """Run a list of {op, params} transforms in order. Returns final value."""
    for t in transforms:
        op_name = t.get("op")
        params = t.get("params", {})
        fn = TRANSFORM_OPS.get(op_name)
        if fn is None:
            continue
        value = fn(value, params)
    return value


# ---------- ops ----------


@_register("normalize_phone")
def normalize_phone(value: Any, params: Dict) -> Any:
    """Strip non-digit chars, optionally add country prefix.

    params:
        strip: str - extra chars to strip beyond whitespace (default " -()")
        country_code: str - prefix to add if number has no international prefix (e.g. "+970")
        keep_plus: bool - keep leading + if present (default true)
    """
    if value is None:
        return value
    s = str(value).strip()
    if not s:
        return value

    strip_chars = params.get("strip", " -()/.")
    keep_plus = params.get("keep_plus", True)

    has_plus = s.startswith("+")
    # Strip specified characters
    cleaned = ""
    for ch in s:
        if ch.isdigit():
            cleaned += ch
        elif ch == "+" and keep_plus and not cleaned:
            cleaned += ch

    if not cleaned or cleaned == "+":
        return value

    # Add country code prefix if missing international prefix
    country_code = params.get("country_code", "")
    if country_code and not has_plus and not cleaned.startswith("00"):
        # Strip leading zero (local format)
        digits = cleaned.lstrip("0") if cleaned else cleaned
        cleaned = country_code + digits

    return cleaned


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
