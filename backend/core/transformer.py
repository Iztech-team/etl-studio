import copy
from typing import Any, Dict, List, Optional
from utils.encoding import (
    fix_encoding_str,
    normalize_arabic_digits,
    strip_directional_marks,
)
from utils.audit import AuditTrail
from core.column_transforms import apply_transforms


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
                        val = apply_transforms(val, col_transforms, col)

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
                    if cc.get("nullable", True) and cc.get("default_value") is None:
                        val = None
                    else:
                        val = cc.get("default_value")
                        if val is not None:
                            val, _ = self._coerce(val, cc.get("data_type", "string"))
                    col_transforms = cc.get("transforms", [])
                    if col_transforms:
                        val = apply_transforms(val, col_transforms, cc_name)
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
                        val = apply_transforms(val, col_transforms, cc_name)

                    new_row[target_col] = val

                new_rows.append(new_row)

            target_name = tc.get("target_table") or table_name
            self._transformed[target_name] = new_rows
            total_rows += len(new_rows)

        # tables not in config pass through unchanged
        for t, rows in self.tables.items():
            tc = table_configs.get(t, {})
            target = tc.get("target_table") or t
            if target not in self._transformed:
                self._transformed[target] = rows
                total_rows += len(rows)

        # Deduplicate rows based on target DDL unique/PK constraints
        total_rows = 0
        for target_name, rows in self._transformed.items():
            constraints = ddl_constraints.get(target_name, {})
            deduped = self._deduplicate(target_name, rows, constraints)
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

    def _deduplicate(
        self,
        table_name: str,
        rows: List[Dict],
        constraints: Dict[str, Any],
    ) -> List[Dict]:
        """Remove duplicate rows that would violate PK or UNIQUE constraints from the target DDL.

        Strategy: keep-first — the first occurrence wins, later duplicates are dropped.
        Each constraint (PK, each UNIQUE set) is checked independently.
        """
        if not rows or not constraints:
            return rows

        pk_cols: List[str] = constraints.get("primary_key", [])
        unique_sets: List[List[str]] = constraints.get("unique", [])

        # Combine all constraint sets to check
        constraint_sets: List[List[str]] = []
        if pk_cols:
            constraint_sets.append(pk_cols)
        for uq in unique_sets:
            if uq:
                constraint_sets.append(uq)

        if not constraint_sets:
            return rows

        # For each constraint set, track seen keys
        seen_per_constraint: List[set] = [set() for _ in constraint_sets]
        deduped: List[Dict] = []
        removed = 0

        for row in rows:
            is_dup = False
            for i, cols in enumerate(constraint_sets):
                # Build key from the constraint columns
                key_vals = []
                all_none = True
                for col in cols:
                    val = row.get(col)
                    key_vals.append(val)
                    if val is not None:
                        all_none = False
                # NULL keys don't violate unique constraints in SQL
                if all_none:
                    continue
                key = tuple(key_vals)
                if key in seen_per_constraint[i]:
                    is_dup = True
                    break
                seen_per_constraint[i].add(key)

            if is_dup:
                removed += 1
            else:
                deduped.append(row)

        if removed > 0:
            self._dedup_removed += removed
            self.warnings.append(
                f"{table_name}: removed {removed} duplicate row(s) "
                f"that would violate unique constraints"
            )
            self.audit_trail.log_schema_change(table_name, 0, removed)

        return deduped
