import copy
from typing import Any, Dict, List
from utils.encoding import fix_encoding_str


class Transformer:
    """Applies encoding fixes, type conversions, reference mappings, null normalisation."""

    def __init__(self, raw: Dict[str, Any], config: Dict[str, Any]):
        self.tables: Dict[str, List[Dict]] = copy.deepcopy(raw.get("tables", {}))
        self.schema: Dict[str, Any] = raw.get("schema", {})
        self.config = config
        self.warnings: List[str] = []
        self._encoding_conversions = 0
        self._type_conversions = 0
        self._ref_mappings = 0
        self._null_normalizations = 0
        self._transformed: Dict[str, List[Dict]] = {}

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

                    # 1. Encoding fix
                    if isinstance(val, str):
                        fixed = fix_encoding_str(val)
                        if fixed != val:
                            self._encoding_conversions += 1
                        val = fixed

                    # 2. Null normalisation
                    if str(val).strip() in null_values:
                        val = None
                        self._null_normalizations += 1

                    # 3. Reference mapping
                    ref_map = cc.get("reference_map")
                    if ref_map and val in ref_map:
                        val = ref_map[val]
                        self._ref_mappings += 1

                    # 4. Type conversion
                    if val is not None:
                        dtype = cc.get("data_type") or (
                            self.schema.get(table_name, {})
                            .get(col, {})
                            .get("inferred_type", "string")
                        )
                        val, converted = self._coerce(val, dtype)
                        if converted:
                            self._type_conversions += 1

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

        return {
            "ok": True,
            "tables": self._transformed,
            "tables_transformed": len(self._transformed),
            "total_rows": total_rows,
            "encoding_conversions": self._encoding_conversions,
            "type_conversions": self._type_conversions,
            "reference_mappings": self._ref_mappings,
            "null_normalizations": self._null_normalizations,
            "warnings": self.warnings,
            "preview": {t: rows[:5] for t, rows in self._transformed.items()},
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _coerce(val: Any, dtype: str):
        dtype = dtype.lower()
        try:
            # Integer family
            if dtype in ("integer", "smallint", "bigint"):
                return int(float(str(val).replace(",", ""))), True
            # Float family
            if dtype in ("float", "real", "double", "numeric", "decimal"):
                return float(str(val).replace(",", "")), True
            # Boolean
            if dtype == "boolean":
                return str(val).lower() in ("true", "1", "yes"), True
            # String family
            if dtype in ("string", "text", "varchar", "char"):
                return str(val), False
            # Date/time family — keep as string but validate format
            if dtype in ("date", "time", "timestamp", "datetime"):
                s = str(val).strip()
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
