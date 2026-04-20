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
    def run(self) -> Dict[str, Any]:
        null_values = set(self.config.get("null_values", ["", "NULL", "null", "N/A", "n/a"]))
        table_configs = {tc["source_table"]: tc for tc in self.config.get("tables", [])}

        total_rows = 0
        for table_name, rows in self.tables.items():
            tc = table_configs.get(table_name, {})
            col_configs = {cc["name"]: cc for cc in tc.get("columns", [])}

            new_rows = []
            for row in rows:
                new_row: Dict[str, Any] = {}
                for col, val in row.items():
                    cc = col_configs.get(col, {})
                    if not cc.get("include", True):
                        continue

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
                            self.schema.get(table_name, {}).get(col, {}).get("inferred_type", "string")
                        )
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
        try:
            if dtype == "integer":
                return int(float(str(val).replace(",", ""))), True
            if dtype == "float":
                return float(str(val).replace(",", "")), True
            if dtype == "boolean":
                return str(val).lower() in ("true", "1", "yes"), True
            if dtype == "string":
                return str(val), False
        except Exception:
            pass
        return val, False
