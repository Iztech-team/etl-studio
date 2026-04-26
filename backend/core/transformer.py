import copy
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from utils.encoding import (
    fix_encoding_str,
    normalize_arabic_digits,
    strip_directional_marks,
)
from utils.audit import AuditTrail
from core.column_transforms import apply_transforms


_CONCAT_PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")


def _apply_value_generator(
    gen: Optional[Dict[str, Any]],
    row_index: int,
    new_row: Dict[str, Any],
    fallback: Any,
) -> Any:
    """Compute the value for an added column from its `generator` config.

    Mirrors frontend's GeneratorEditor / renderAddedCellPreview in
    retro/Pipeline.tsx. If `gen` is None or unrecognised, returns
    `fallback` (which is the legacy default_value path).
    """
    if not gen or not isinstance(gen, dict):
        return fallback
    kind = gen.get("kind")
    if kind == "fixed":
        v = gen.get("value", "")
        return v if v != "" else fallback
    if kind == "uuid_v4":
        return str(uuid.uuid4())
    if kind == "increment":
        try:
            start = int(gen.get("start", 1))
        except (TypeError, ValueError):
            start = 1
        try:
            step = int(gen.get("step", 1))
        except (TypeError, ValueError):
            step = 1
        return start + row_index * step
    if kind == "now":
        return datetime.now(timezone.utc).isoformat()
    if kind == "from_column":
        src = gen.get("source_column")
        if src and src in new_row:
            return new_row[src]
        return fallback
    if kind == "concat":
        tpl = gen.get("template", "") or ""
        if not tpl:
            return fallback

        def replace(match: "re.Match[str]") -> str:
            key = match.group(1)
            v = new_row.get(key)
            return "" if v is None else str(v)

        return _CONCAT_PLACEHOLDER_RE.sub(replace, tpl)
    return fallback


class Transformer:
    """Applies encoding fixes, type conversions, reference mappings, null normalisation."""

    def __init__(
        self,
        raw: Dict[str, Any],
        config: Dict[str, Any],
        audit_trail: Optional[AuditTrail] = None,
    ):
        self.tables: Dict[str, List[Dict]] = copy.deepcopy(raw.get("tables", {}))
        self.schema: Dict[str, Any] = raw.get("schema", {})
        self.config = config
        self.audit_trail = audit_trail or AuditTrail()
        self.warnings: List[str] = []
        self._encoding_conversions = 0
        self._type_conversions = 0
        self._ref_mappings = 0
        self._null_normalizations = 0
        self._dedup_removed = 0
        self._transformed: Dict[str, List[Dict]] = {}
        self.fk_edges: List[tuple] = []
        # Spec 3.4 / 3.12 / 4 — exceptions surface for human review
        self.exceptions: Dict[str, List[Dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    def _build_fk_lookups(self, table_configs: Dict[str, Any]) -> Dict[tuple, Dict]:
        """Pre-build lookup dicts for FK columns across all table configs."""
        fk_lookups: Dict[tuple, Dict] = {}
        for tc in table_configs.values():
            for cc in tc.get("columns", []):
                fk_table = cc.get("fk_source_table")
                fk_source_col = cc.get("fk_source_column")
                fk_match_col = cc.get("fk_match_column")
                if not (fk_table and fk_source_col and fk_match_col):
                    continue
                key = (fk_table, fk_match_col, fk_source_col)
                if key in fk_lookups:
                    continue
                source_rows = self.tables.get(fk_table, [])
                lookup: Dict[Any, Any] = {}
                for row in source_rows:
                    match_val = row.get(fk_match_col)
                    if match_val is not None:
                        lookup[match_val] = row.get(fk_source_col)
                fk_lookups[key] = lookup
                if not source_rows:
                    self.warnings.append(f"FK lookup: table '{fk_table}' has no rows")
        return fk_lookups

    # ------------------------------------------------------------------
    def run(self) -> Dict[str, Any]:
        null_values = set(
            self.config.get("null_values", ["", "NULL", "null", "N/A", "n/a"])
        )
        table_configs = {tc["source_table"]: tc for tc in self.config.get("tables", [])}

        fk_lookups = self._build_fk_lookups(table_configs)

        # Collect FK edges for dependency-aware load ordering
        self.fk_edges = []
        for tc in table_configs.values():
            child_table = tc.get("target_table") or tc.get("source_table")
            for cc in tc.get("columns", []):
                fk_table = cc.get("fk_source_table")
                if fk_table and child_table:
                    self.fk_edges.append((child_table, fk_table))

        # Build dedup constraints from DDL schema
        ddl_constraints = self.config.get("ddl_constraints", {})

        total_rows = 0
        for table_name, rows in self.tables.items():
            tc = table_configs.get(table_name, {})
            col_configs = {cc["name"]: cc for cc in tc.get("columns", [])}

            new_rows = []
            transform_state: Dict[str, Any] = {}
            for row in rows:
                new_row: Dict[str, Any] = {}

                # --- process existing columns ---
                for col, val in row.items():
                    cc = col_configs.get(col, {})
                    if not cc.get("include", True):
                        continue
                    if cc.get("is_new"):
                        continue  # handled below

                    target_col = cc.get("target_name") or col

                    # 1. Strip directional marks
                    if isinstance(val, str):
                        clean = strip_directional_marks(val)
                        if clean != val:
                            self.audit_trail.log_directional_marks_stripped(
                                table_name, col
                            )
                            val = clean

                    # 2. Encoding fix
                    if isinstance(val, str):
                        fixed = fix_encoding_str(val)
                        if fixed != val:
                            self._encoding_conversions += 1
                            self.audit_trail.log_encoding_fixed(table_name, col)
                        val = fixed

                    # 3. Null normalisation
                    if str(val).strip() in null_values:
                        val = None
                        self._null_normalizations += 1
                        self.audit_trail.log_null_normalized(table_name, col)

                    # 4. Reference mapping
                    ref_map = cc.get("reference_map")
                    if ref_map and val in ref_map:
                        val = ref_map[val]
                        self._ref_mappings += 1
                        self.audit_trail.log_reference_mapped(table_name, col)

                    # 5. Type conversion
                    if val is not None:
                        dtype = cc.get("data_type") or (
                            self.schema.get(table_name, {})
                            .get(col, {})
                            .get("inferred_type", "string")
                        )
                        old_dtype = "string"
                        try:
                            if isinstance(val, (int, float)):
                                old_dtype = "numeric"
                            elif isinstance(val, bool):
                                old_dtype = "boolean"
                        except:
                            pass
                        val, converted = self._coerce(val, dtype)
                        if converted:
                            self._type_conversions += 1
                            self.audit_trail.log_type_coerced(
                                table_name, col, old_dtype, dtype
                            )

                    # 6. Column transforms pipeline
                    col_transforms = cc.get("transforms", [])
                    if col_transforms:
                        val = apply_transforms(
                            val,
                            col_transforms,
                            col,
                            row=row,
                            state=transform_state,
                            exceptions=self.exceptions,
                            table=table_name,
                        )

                    new_row[target_col] = val

                # --- process new columns (is_new=True, no FK) ---
                for cc_name, cc in col_configs.items():
                    if not cc.get("is_new"):
                        continue
                    if not cc.get("include", True):
                        continue
                    if cc.get("fk_source_table"):
                        continue  # FK columns handled next

                    target_col = cc.get("target_name") or cc_name

                    # Compute the seed value: prefer explicit generator over
                    # legacy default_value. The generator runs first; if it
                    # produces a value, that wins. Falls back to default_value
                    # (or None for nullable columns) if no generator is set.
                    if cc.get("nullable", True) and cc.get("default_value") is None:
                        fallback: Any = None
                    else:
                        fallback = cc.get("default_value")

                    val = _apply_value_generator(
                        cc.get("generator"), row_index, new_row, fallback
                    )

                    if val is not None:
                        val, _ = self._coerce(val, cc.get("data_type", "string"))

                    col_transforms = cc.get("transforms", [])
                    if col_transforms:
                        val = apply_transforms(
                            val,
                            col_transforms,
                            cc_name,
                            row=row,
                            state=transform_state,
                            exceptions=self.exceptions,
                            table=table_name,
                        )
                    new_row[target_col] = val

                # --- process FK columns ---
                for cc_name, cc in col_configs.items():
                    if not cc.get("is_new"):
                        continue
                    if not cc.get("include", True):
                        continue
                    fk_table = cc.get("fk_source_table")
                    fk_source_col = cc.get("fk_source_column")
                    fk_match_col = cc.get("fk_match_column")
                    fk_local_col = cc.get("fk_local_column")
                    if not (
                        fk_table and fk_source_col and fk_match_col and fk_local_col
                    ):
                        continue

                    target_col = cc.get("target_name") or cc_name
                    lookup_key = (fk_table, fk_match_col, fk_source_col)
                    lookup = fk_lookups.get(lookup_key, {})
                    local_val = row.get(fk_local_col)
                    val = lookup.get(local_val)

                    if val is not None:
                        dtype = cc.get("data_type", "string")
                        val, converted = self._coerce(val, dtype)
                        if converted:
                            self._type_conversions += 1

                    col_transforms = cc.get("transforms", [])
                    if col_transforms:
                        val = apply_transforms(
                            val,
                            col_transforms,
                            cc_name,
                            row=row,
                            state=transform_state,
                            exceptions=self.exceptions,
                            table=table_name,
                        )

                    new_row[target_col] = val

                # --- inject global columns (spec 7.2 shopId/createdBy/updatedBy + 6) ---
                target_name_local = tc.get("target_table") or table_name
                self._inject_globals(new_row, row, target_name_local)

                new_rows.append(new_row)

            target_name = tc.get("target_table") or table_name
            self._transformed[target_name] = new_rows
            total_rows += len(new_rows)

        # tables not in config pass through unchanged (still get global columns)
        for t, rows in self.tables.items():
            tc = table_configs.get(t, {})
            target = tc.get("target_table") or t
            if target not in self._transformed:
                injected = []
                for r in rows:
                    new_row = dict(r)
                    self._inject_globals(new_row, r, target)
                    injected.append(new_row)
                self._transformed[target] = injected
                total_rows += len(injected)

        # Deduplicate rows based on target DDL unique/PK constraints
        total_rows = 0
        target_to_tc = {
            (tc.get("target_table") or tc.get("source_table")): tc
            for tc in table_configs.values()
        }
        for target_name, rows in self._transformed.items():
            constraints = ddl_constraints.get(target_name, {})
            tc = target_to_tc.get(target_name, {})
            deduped = self._deduplicate(target_name, rows, constraints, tc)
            self._transformed[target_name] = deduped
            total_rows += len(deduped)

        return {
            "ok": True,
            "tables": self._transformed,
            "tables_transformed": len(self._transformed),
            "total_rows": total_rows,
            "encoding_conversions": self._encoding_conversions,
            "type_conversions": self._type_conversions,
            "reference_mappings": self._ref_mappings,
            "null_normalizations": self._null_normalizations,
            "dedup_removed": self._dedup_removed,
            "warnings": self.warnings,
            "exceptions": self.exceptions,
            "preview": {t: rows[:5] for t, rows in self._transformed.items()},
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _coerce(val: Any, dtype: str):
        dtype = dtype.lower()
        try:
            # Integer family
            clean = normalize_arabic_digits(str(val)).replace(",", "")
            if dtype in ("integer", "smallint", "bigint"):
                return int(float(clean)), True
            # Float family
            if dtype in ("float", "real", "double", "numeric", "decimal"):
                return float(clean), True
            # Boolean
            if dtype == "boolean":
                return str(clean).lower() in ("true", "1", "yes"), True
            # String family
            if dtype in ("string", "text", "varchar", "char"):
                return str(val), False
            # Date/time family — keep as string but validate format
            if dtype in ("date", "time", "timestamp", "datetime"):
                s = normalize_arabic_digits(str(val)).strip()
                if dtype == "date":
                    from datetime import date as _d

                    _d.fromisoformat(s[:10])
                elif dtype == "time":
                    from datetime import time as _t

                    _t.fromisoformat(s)
                elif dtype in ("timestamp", "datetime"):
                    from datetime import datetime as _dt

                    _dt.fromisoformat(s)
                return s, True
            # UUID — validate and normalize
            if dtype == "uuid":
                import uuid as _uuid

                return str(_uuid.UUID(str(val))), True
            # JSON — parse to validate, keep as string
            if dtype == "json":
                import json

                if isinstance(val, str):
                    json.loads(val)
                    return val, False
                return json.dumps(val, default=str), True
            # Blob — pass through as-is
            if dtype == "blob":
                return val, False
        except Exception:
            pass
        return val, False

    def _inject_globals(
        self, new_row: Dict[str, Any], source_row: Dict[str, Any], target_table: str
    ) -> None:
        """Apply global_columns from config (spec 7.2 + 6) to a single output row."""
        globals_cfg = self.config.get("global_columns", []) or []
        for gc in globals_cfg:
            apply_to = gc.get("apply_to")
            if apply_to and target_table not in apply_to:
                continue
            if target_table in (gc.get("exclude_tables") or []):
                continue
            name = gc.get("name")
            if not name:
                continue
            if (not gc.get("overwrite", False)) and name in new_row:
                continue
            src_col = gc.get("source_column")
            if src_col:
                new_row[name] = source_row.get(src_col)
            else:
                new_row[name] = gc.get("value")

    def _deduplicate(
        self,
        table_name: str,
        rows: List[Dict],
        constraints: Dict[str, Any],
        table_config: Optional[Dict[str, Any]] = None,
    ) -> List[Dict]:
        """Resolve duplicate rows that would violate PK / UNIQUE constraints.

        Strategy controlled by table_config['on_duplicate']:
          - 'drop'   (default) — keep-first; later duplicates dropped.
          - 'suffix' — keep all rows; suffix the configured column with a counter
                       so the constraint becomes satisfiable. Used for item.name
                       UNIQUE per shopId (spec 4 PRE-LOAD).
        """
        if not rows or not constraints:
            return rows

        pk_cols: List[str] = constraints.get("primary_key", [])
        unique_sets: List[List[str]] = constraints.get("unique", [])
        constraint_sets: List[List[str]] = []
        if pk_cols:
            constraint_sets.append(pk_cols)
        for uq in unique_sets:
            if uq:
                constraint_sets.append(uq)
        if not constraint_sets:
            return rows

        tc = table_config or {}
        mode = tc.get("on_duplicate", "drop")
        suffix_col = tc.get("duplicate_suffix_column")
        suffix_fmt = tc.get("duplicate_suffix_format", "{value}_{n}")

        seen_per_constraint: List[Dict[tuple, int]] = [{} for _ in constraint_sets]
        result: List[Dict] = []
        removed = 0
        suffixed = 0

        for row in rows:
            is_dup = False
            dup_constraint_idx = -1
            for i, cols in enumerate(constraint_sets):
                key_vals = [row.get(c) for c in cols]
                if all(v is None for v in key_vals):
                    continue
                key = tuple(key_vals)
                if key in seen_per_constraint[i]:
                    is_dup = True
                    dup_constraint_idx = i
                    break
                seen_per_constraint[i][key] = 1

            if not is_dup:
                result.append(row)
                continue

            if mode == "suffix" and suffix_col and suffix_col in row:
                # Keep the row; mutate the suffix column until unique.
                base = "" if row.get(suffix_col) is None else str(row[suffix_col])
                cols = constraint_sets[dup_constraint_idx]
                seen = seen_per_constraint[dup_constraint_idx]
                base_key = tuple(row.get(c) for c in cols)
                n = seen.get(base_key, 1) + 1
                while True:
                    new_val = suffix_fmt.format(value=base, n=n)
                    row[suffix_col] = new_val
                    new_key = tuple(row.get(c) for c in cols)
                    if new_key not in seen:
                        seen[new_key] = 1
                        seen[base_key] = n
                        break
                    n += 1
                result.append(row)
                suffixed += 1
                self.exceptions.setdefault("dedup_suffixed", []).append(
                    {
                        "table": table_name,
                        "column": suffix_col,
                        "original": base,
                        "renamed_to": row[suffix_col],
                    }
                )
            else:
                removed += 1
                self.exceptions.setdefault("dedup_dropped", []).append(
                    {
                        "table": table_name,
                        "key_columns": ",".join(constraint_sets[dup_constraint_idx]),
                        "key_values": ",".join(
                            "" if row.get(c) is None else str(row.get(c))
                            for c in constraint_sets[dup_constraint_idx]
                        ),
                    }
                )

        if removed > 0:
            self._dedup_removed += removed
            self.warnings.append(
                f"{table_name}: removed {removed} duplicate row(s) "
                f"that would violate unique constraints"
            )
            self.audit_trail.log_schema_change(table_name, 0, removed)
        if suffixed > 0:
            self.warnings.append(
                f"{table_name}: suffixed {suffixed} duplicate value(s) in "
                f"'{suffix_col}' to satisfy unique constraint"
            )

        return result
