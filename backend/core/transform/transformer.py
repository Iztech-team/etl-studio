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
from core.transform.column_transforms import apply_transforms

_CONCAT_PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")


def _apply_value_generator(
    gen: Optional[Dict[str, Any]],
    row_index: int,
    new_row: Dict[str, Any],
    fallback: Any,
    source_row: Optional[Dict[str, Any]] = None,
) -> Any:
    """Compute the value for an added column from its `generator` config.

    Mirrors frontend's GeneratorEditor in retro/Pipeline.tsx. `from_column`
    and `concat` look in `new_row` first then fall back to the original
    source row, so users can reference a source column even if dropped.
    """
    if not gen or not isinstance(gen, dict):
        return fallback
    src_row = source_row or {}
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
        if src and src in src_row:
            return src_row[src]
        return fallback
    if kind == "concat":
        tpl = gen.get("template", "") or ""
        if not tpl:
            return fallback

        def replace(match: "re.Match[str]") -> str:
            key = match.group(1)
            v = new_row[key] if key in new_row else src_row.get(key)
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
        progress_cb: Optional[Any] = None,
        persist_target_cb: Optional[Any] = None,
        row_loader: Optional[Any] = None,
    ):
        # Shallow copy of the outer dict so releasing per-table rows during
        # processing (lazy mode) doesn't reach back and clear the caller's
        # session["raw"]["tables"][name]. Inner row lists are NOT deep-copied;
        # we never mutate them — every output row is freshly built.
        _src_tables = raw.get("tables", {}) or {}
        self.tables: Dict[str, List[Dict]] = dict(_src_tables)
        self.schema: Dict[str, Any] = raw.get("schema", {})
        self.config = config
        self.audit_trail = audit_trail or AuditTrail()
        self.progress_cb = progress_cb
        self.persist_target_cb = persist_target_cb
        self.row_loader = row_loader
        self.warnings: List[str] = []
        self._encoding_conversions = 0
        self._type_conversions = 0
        self._ref_mappings = 0
        self._null_normalizations = 0
        self._transformed: Dict[str, List[Dict]] = {}
        self.fk_edges: List[tuple] = []
        self.self_refs: Dict[str, str] = {}
        self.exceptions: Dict[str, List[Dict[str, Any]]] = {}

    def _get_table_rows(self, name: str) -> List[Dict[str, Any]]:
        rows = self.tables.get(name)
        if rows:
            return rows
        if self.row_loader is None:
            return rows or []
        try:
            loaded = self.row_loader(name) or []
        except Exception as e:
            self.warnings.append(f"row_loader failed for '{name}': {e}")
            return []
        self.tables[name] = loaded
        return loaded

    def _release_table_rows(self, name: str) -> None:
        if name in self.tables:
            self.tables[name] = []

    def _build_fk_lookups(
        self, table_configs: List[Dict[str, Any]]
    ) -> Dict[tuple, Dict]:
        """Pre-build (table, match_col, source_col) lookup dicts referenced by
        FK columns and chain hops. Without this, each transform iteration
        would re-scan source tables — quadratic in catalog size."""
        fk_lookups: Dict[tuple, Dict] = {}
        per_table_keys: Dict[str, List[tuple]] = {}
        for tc in table_configs:
            if tc.get("drop_table"):
                continue
            for cc in tc.get("columns", []):
                fk_table = cc.get("fk_source_table")
                if fk_table:
                    per_table_keys.setdefault(fk_table, []).append(
                        (cc.get("fk_match_column"), cc.get("fk_source_column"))
                    )
                for hop in cc.get("fk_chain") or []:
                    htbl = hop.get("table")
                    if htbl:
                        per_table_keys.setdefault(htbl, []).append(
                            (hop.get("match_column"), hop.get("source_column"))
                        )

        for fk_table, key_pairs in per_table_keys.items():
            unique_pairs = {(m, s) for (m, s) in key_pairs if m and s}
            if not unique_pairs:
                continue
            source_rows = self._get_table_rows(fk_table)
            if not source_rows:
                self.warnings.append(f"FK lookup: table '{fk_table}' has no rows")
            for match_col, source_col in unique_pairs:
                key = (fk_table, match_col, source_col)
                lookup: Dict[Any, Any] = {}
                for row in source_rows:
                    match_val = row.get(match_col)
                    if match_val is not None:
                        lookup[match_val] = row.get(source_col)
                fk_lookups[key] = lookup
            # FK source rows stay cached: many also serve as real sources in
            # the main loop (e.g. ACCOUNTT → tabAccount AND FK source for
            # customer.customer_name). The main loop releases them after.

        return fk_lookups

    def _build_relationships(
        self, table_configs: List[Dict[str, Any]]
    ) -> None:
        """Populate self.fk_edges and self.self_refs from configs.

        Edges feed dependency-aware load ordering. Self-references (target →
        same target) become entries in self_refs so the loader does an
        in-table topological sort instead of cross-table ordering.
        """
        source_to_target: Dict[str, str] = {}
        for tc in table_configs:
            if tc.get("drop_table"):
                continue
            src = tc.get("source_table")
            tgt = tc.get("target_table") or src
            if src and tgt:
                source_to_target.setdefault(src, tgt)

        for tc in table_configs:
            if tc.get("drop_table"):
                continue
            child_table = tc.get("target_table") or tc.get("source_table")
            for cc in tc.get("columns", []):
                fk_table = cc.get("fk_source_table")
                if fk_table and child_table:
                    fk_target = source_to_target.get(fk_table, fk_table)
                    if fk_target == child_table:
                        parent_col = cc.get("target_name") or cc.get("name")
                        if parent_col:
                            self.self_refs[child_table] = parent_col
                    else:
                        self.fk_edges.append((child_table, fk_target))
                for hop in cc.get("fk_chain") or []:
                    hop_tbl = hop.get("table")
                    if hop_tbl and child_table:
                        hop_target = source_to_target.get(hop_tbl, hop_tbl)
                        if hop_target != child_table:
                            self.fk_edges.append((child_table, hop_target))
            for parent in tc.get("load_after") or []:
                if parent and child_table and parent != child_table:
                    self.fk_edges.append((child_table, parent))
            sr_col = tc.get("self_reference_parent_column")
            if sr_col and child_table:
                self.self_refs[child_table] = sr_col

    def _plan(
        self, table_configs: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Index configs by source, identify dropped sources, pre-compute
        per-target dependencies. Returns a plan dict consumed by run().
        """
        configs_by_source: Dict[str, List[Dict[str, Any]]] = {}
        dropped_sources: set = set()
        target_to_pending_sources: Dict[str, set] = {}
        for tc in table_configs:
            if tc.get("drop_table"):
                src = tc.get("source_table")
                if src:
                    dropped_sources.add(src)
                continue
            src = tc.get("source_table")
            if not src:
                continue
            configs_by_source.setdefault(src, []).append(tc)
            tgt = tc.get("target_table") or src
            target_to_pending_sources.setdefault(tgt, set()).add(src)

        candidate_sources = list(self.tables.keys()) or list(self.schema.keys())
        for tc in table_configs:
            src = tc.get("source_table")
            if src and src not in candidate_sources:
                candidate_sources.append(src)
        total_sources = sum(
            1
            for t in candidate_sources
            if not (t in dropped_sources and t not in configs_by_source)
        )
        return {
            "configs_by_source": configs_by_source,
            "dropped_sources": dropped_sources,
            "target_to_pending_sources": target_to_pending_sources,
            "candidate_sources": candidate_sources,
            "total_sources": total_sources,
        }

    def _flatten_active_cols(
        self, col_configs: Dict[str, Dict], table_name: str, rows_iter
    ):
        """Pre-flatten existing-column configs into tuples of bound locals.
        The per-row loop iterates this list instead of doing five `cc.get(...)`
        calls per cell — saves ~25M dict lookups for a 5M-row table.

        Tuple shape: (col, target_col, dtype, ref_map, transforms_cfg)
        """
        schema_for_table = self.schema.get(table_name, {})
        active_cols: List[tuple] = []
        if col_configs:
            for col, cc in col_configs.items():
                if cc.get("is_new") or not cc.get("include", True):
                    continue
                target_col = cc.get("target_name") or col
                dtype = cc.get("data_type") or schema_for_table.get(col, {}).get(
                    "inferred_type", "string"
                )
                active_cols.append(
                    (col, target_col, dtype, cc.get("reference_map"),
                     cc.get("transforms") or None)
                )
            return active_cols, rows_iter

        # No explicit config → pass every column through under its original
        # name. Use schema as canonical column list; fall back to first row.
        cols = list(schema_for_table.keys())
        if not cols:
            first_row = next(iter(rows_iter), None) if rows_iter else None
            if first_row:
                cols = list(first_row.keys())
                rest = list(rows_iter) if rows_iter else []
                rows_iter = [first_row, *rest]
        for col in cols:
            dtype = schema_for_table.get(col, {}).get("inferred_type", "string")
            active_cols.append((col, col, dtype, None, None))
        return active_cols, rows_iter

    def _process_existing_cols(
        self,
        row: Dict[str, Any],
        new_row: Dict[str, Any],
        active_cols: List[tuple],
        null_values: set,
        table_name: str,
        transform_state: Dict[str, Any],
    ) -> None:
        # Bind module-level functions to locals for tight-loop speed.
        _strip_marks = strip_directional_marks
        _fix_enc = fix_encoding_str
        _coerce = self._coerce
        _audit = self.audit_trail
        for col, target_col, dtype, ref_map, transforms_cfg in active_cols:
            val = row.get(col)
            if isinstance(val, str):
                clean = _strip_marks(val)
                if clean is not val and clean != val:
                    _audit.log_directional_marks_stripped(table_name, col)
                    val = clean
                fixed = _fix_enc(val)
                if fixed is not val and fixed != val:
                    self._encoding_conversions += 1
                    _audit.log_encoding_fixed(table_name, col)
                    val = fixed

            if val is None:
                pass
            elif isinstance(val, str):
                if val.strip() in null_values:
                    val = None
                    self._null_normalizations += 1
                    _audit.log_null_normalized(table_name, col)
            elif val == "" or str(val).strip() in null_values:
                val = None
                self._null_normalizations += 1
                _audit.log_null_normalized(table_name, col)

            if ref_map and val in ref_map:
                val = ref_map[val]
                self._ref_mappings += 1
                _audit.log_reference_mapped(table_name, col)

            if val is not None:
                old_dtype = "string"
                if isinstance(val, bool):
                    old_dtype = "boolean"
                elif isinstance(val, (int, float)):
                    old_dtype = "numeric"
                val, converted = _coerce(val, dtype)
                if converted:
                    self._type_conversions += 1
                    _audit.log_type_coerced(table_name, col, old_dtype, dtype)

            if transforms_cfg:
                val = apply_transforms(
                    val, transforms_cfg, col,
                    row=row, state=transform_state, exceptions=self.exceptions,
                    table=table_name, new_row=new_row,
                )
            new_row[target_col] = val

    def _process_fk_cols(
        self,
        row: Dict[str, Any],
        new_row: Dict[str, Any],
        col_configs: Dict[str, Dict],
        fk_lookups: Dict[tuple, Dict],
        table_name: str,
        transform_state: Dict[str, Any],
    ) -> None:
        """Walk single-hop and multi-hop FK chains. Runs before generators
        so concat/from_column generators can reference resolved FK values."""
        for cc_name, cc in col_configs.items():
            if not cc.get("is_new") or not cc.get("include", True):
                continue
            fk_local_col = cc.get("fk_local_column")
            if not fk_local_col:
                continue
            fk_chain = cc.get("fk_chain") or []
            if not fk_chain:
                fk_table = cc.get("fk_source_table")
                fk_source_col = cc.get("fk_source_column")
                fk_match_col = cc.get("fk_match_column")
                if not (fk_table and fk_source_col and fk_match_col):
                    continue
                fk_chain = [{
                    "table": fk_table,
                    "match_column": fk_match_col,
                    "source_column": fk_source_col,
                }]

            target_col = cc.get("target_name") or cc_name
            val: Any = row.get(fk_local_col)
            for hop in fk_chain:
                if val is None:
                    break
                key = (hop.get("table"), hop.get("match_column"),
                       hop.get("source_column"))
                val = fk_lookups.get(key, {}).get(val)

            if val is not None:
                val, converted = self._coerce(val, cc.get("data_type", "string"))
                if converted:
                    self._type_conversions += 1

            transforms_cfg = cc.get("transforms", [])
            if transforms_cfg:
                val = apply_transforms(
                    val, transforms_cfg, cc_name,
                    row=row, state=transform_state, exceptions=self.exceptions,
                    table=table_name, new_row=new_row,
                )
            new_row[target_col] = val

    def _process_generated_cols(
        self,
        row: Dict[str, Any],
        new_row: Dict[str, Any],
        col_configs: Dict[str, Dict],
        row_index: int,
        table_name: str,
        transform_state: Dict[str, Any],
    ) -> None:
        """Run AFTER FK lookups so concat_template / compute / from_column
        generators can reference FK-resolved values like {customer_name}."""
        for cc_name, cc in col_configs.items():
            if not cc.get("is_new") or not cc.get("include", True):
                continue
            if cc.get("fk_source_table") or cc.get("fk_chain"):
                continue
            target_col = cc.get("target_name") or cc_name
            if cc.get("nullable", True) and cc.get("default_value") is None:
                fallback: Any = None
            else:
                fallback = cc.get("default_value")
            val = _apply_value_generator(
                cc.get("generator"), row_index, new_row, fallback, source_row=row,
            )
            if val is not None:
                val, _ = self._coerce(val, cc.get("data_type", "string"))
            transforms_cfg = cc.get("transforms", [])
            if transforms_cfg:
                val = apply_transforms(
                    val, transforms_cfg, cc_name,
                    row=row, state=transform_state, exceptions=self.exceptions,
                    table=table_name, new_row=new_row,
                )
            new_row[target_col] = val

    def _process_source_table(
        self,
        table_name: str,
        tcs_for_table: List[Dict[str, Any]],
        fk_lookups: Dict[tuple, Dict],
        null_values: set,
    ) -> int:
        """Process every TableConfig that targets `table_name`. Returns the
        number of rows produced across all configs."""
        rows = self._get_table_rows(table_name)
        produced = 0
        for tc in tcs_for_table:
            col_configs = {cc["name"]: cc for cc in tc.get("columns", [])}
            row_filter_cfg = tc.get("row_filter")

            agg_cfg = tc.get("aggregate")
            if agg_cfg and (agg_cfg.get("group_by") or rows):
                rows_iter = self._aggregate(rows, agg_cfg)
            else:
                rows_iter = rows

            active_cols, rows_iter = self._flatten_active_cols(
                col_configs, table_name, rows_iter
            )

            new_rows: List[Dict[str, Any]] = []
            transform_state: Dict[str, Any] = {}
            for row_index, row in enumerate(rows_iter):
                new_row: Dict[str, Any] = {}
                self._process_existing_cols(
                    row, new_row, active_cols, null_values, table_name, transform_state
                )
                self._process_fk_cols(
                    row, new_row, col_configs, fk_lookups, table_name, transform_state
                )
                self._process_generated_cols(
                    row, new_row, col_configs, row_index, table_name, transform_state
                )

                if row_filter_cfg and not self._row_passes_filter(
                    new_row, row, row_filter_cfg
                ):
                    continue

                target_name_local = tc.get("target_table") or table_name
                self._inject_globals(new_row, row, target_name_local)
                new_rows.append(new_row)

            target_name = tc.get("target_table") or table_name
            # UNION ALL: two configs targeting the same table extend rather
            # than overwrite (used by product_barcodes).
            if target_name in self._transformed:
                self._transformed[target_name].extend(new_rows)
            else:
                self._transformed[target_name] = new_rows
            produced += len(new_rows)
        return produced

    def _persist_complete_targets(
        self,
        target_to_pending: Dict[str, set],
        sources_processed: set,
        targets_persisted: set,
    ) -> None:
        """Fire persist_target_cb for any target whose feeding sources have all
        been processed. Lets a downstream crash retain finished tables."""
        if self.persist_target_cb is None:
            return
        for tgt, pending in target_to_pending.items():
            if tgt in targets_persisted:
                continue
            if pending.issubset(sources_processed):
                targets_persisted.add(tgt)
                try:
                    self.persist_target_cb(tgt, self._transformed.get(tgt, []))
                except Exception as e:
                    self.warnings.append(
                        f"persist_target_cb failed for '{tgt}': {e}"
                    )

    def run(self) -> Dict[str, Any]:
        null_values = set(
            self.config.get("null_values", ["", "NULL", "null", "N/A", "n/a"])
        )
        # A single source may appear in multiple TableConfigs (UNION ALL).
        table_configs_list: List[Dict[str, Any]] = list(self.config.get("tables", []))

        fk_lookups = self._build_fk_lookups(table_configs_list)
        self._build_relationships(table_configs_list)
        plan = self._plan(table_configs_list)

        configs_by_source = plan["configs_by_source"]
        dropped_sources = plan["dropped_sources"]
        target_to_pending = plan["target_to_pending_sources"]
        candidate_sources = plan["candidate_sources"]
        total_sources = plan["total_sources"]

        sources_processed: set = set()
        targets_persisted: set = set()
        total_rows = 0
        done_sources = 0

        for table_name in candidate_sources:
            if table_name in dropped_sources and table_name not in configs_by_source:
                continue

            if self.progress_cb:
                try:
                    self.progress_cb(table_name, done_sources, total_sources)
                except Exception:
                    pass

            tcs_for_table = configs_by_source.get(
                table_name, [{"source_table": table_name}]
            )
            total_rows += self._process_source_table(
                table_name, tcs_for_table, fk_lookups, null_values
            )

            self._release_table_rows(table_name)
            done_sources += 1
            sources_processed.add(table_name)

            if self.progress_cb:
                try:
                    self.progress_cb(table_name, done_sources, total_sources)
                except Exception:
                    pass

            self._persist_complete_targets(
                target_to_pending, sources_processed, targets_persisted
            )

        # Convert per-cell audit counters into one event per (type, table,
        # column) — without this the downstream flush would insert tens of
        # millions of DB rows for a real project.
        self.audit_trail.flush_counters_to_events()

        return {
            "ok": True,
            "tables": self._transformed,
            "tables_transformed": len(self._transformed),
            "total_rows": total_rows,
            "encoding_conversions": self._encoding_conversions,
            "type_conversions": self._type_conversions,
            "reference_mappings": self._ref_mappings,
            "null_normalizations": self._null_normalizations,
            "dedup_removed": 0,
            "warnings": self.warnings,
            "exceptions": self.exceptions,
            "preview": {t: rows[:5] for t, rows in self._transformed.items()},
        }

    @staticmethod
    def _coerce(val: Any, dtype: str):
        dtype = dtype.lower()
        try:
            clean = normalize_arabic_digits(str(val)).replace(",", "")
            if dtype in ("integer", "smallint", "bigint"):
                return int(float(clean)), True
            if dtype in ("float", "real", "double", "numeric", "decimal"):
                return float(clean), True
            if dtype == "boolean":
                return str(clean).lower() in ("true", "1", "yes"), True
            if dtype in ("string", "text", "varchar", "char"):
                return str(val), False
            if dtype in ("date", "time", "timestamp", "datetime"):
                s = normalize_arabic_digits(str(val)).strip()
                if dtype == "date":
                    from datetime import date as _d
                    _d.fromisoformat(s[:10])
                elif dtype == "time":
                    from datetime import time as _t
                    _t.fromisoformat(s)
                else:
                    from datetime import datetime as _dt
                    _dt.fromisoformat(s)
                return s, True
            if dtype == "uuid":
                import uuid as _uuid
                return str(_uuid.UUID(str(val))), True
            if dtype == "json":
                import json
                if isinstance(val, str):
                    json.loads(val)
                    return val, False
                return json.dumps(val, default=str), True
            if dtype == "blob":
                return val, False
        except Exception:
            pass
        return val, False

    @staticmethod
    def _aggregate(
        rows: List[Dict[str, Any]], agg_cfg: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """GROUP BY `group_by` columns, reducing other columns with the
        configured aggregator (default: 'first'). Empty group_by means
        DISTINCT on every column."""
        group_by: List[str] = agg_cfg.get("group_by", []) or []
        aggs: Dict[str, str] = agg_cfg.get("aggregations", {}) or {}
        sep = agg_cfg.get("concat_separator", ", ")

        if not rows:
            return []

        if not group_by:
            seen = {}
            for row in rows:
                key = tuple(sorted(row.items()))
                if key not in seen:
                    seen[key] = dict(row)
            return list(seen.values())

        buckets: Dict[tuple, List[Dict[str, Any]]] = {}
        order: List[tuple] = []
        for row in rows:
            key = tuple(row.get(c) for c in group_by)
            if key not in buckets:
                buckets[key] = []
                order.append(key)
            buckets[key].append(row)

        def reduce_col(name: str, group: List[Dict[str, Any]]) -> Any:
            op = aggs.get(name, "first")
            vals = [r.get(name) for r in group]
            non_null = [v for v in vals if v is not None and v != ""]
            if op == "first":
                return vals[0] if vals else None
            if op == "last":
                return vals[-1] if vals else None
            if op == "count":
                return len(group)
            if op == "concat":
                return sep.join(str(v) for v in non_null)
            if op in ("sum", "min", "max"):
                nums = []
                for v in non_null:
                    try:
                        nums.append(float(v))
                    except (TypeError, ValueError):
                        continue
                if not nums:
                    return 0 if op == "sum" else None
                if op == "sum":
                    s = sum(nums)
                    return int(s) if s.is_integer() else s
                return min(nums) if op == "min" else max(nums)
            return vals[0] if vals else None

        out: List[Dict[str, Any]] = []
        all_cols = list(rows[0].keys())
        for key in order:
            group = buckets[key]
            row: Dict[str, Any] = {}
            for col in all_cols:
                row[col] = group[0].get(col) if col in group_by else reduce_col(col, group)
            out.append(row)
        return out

    @staticmethod
    def _row_passes_filter(
        new_row: Dict[str, Any],
        source_row: Dict[str, Any],
        row_filter: Dict[str, Any],
    ) -> bool:
        """Filters can reference renamed (target) columns, falling back to
        source columns. mode='keep' keeps rows where every condition is true;
        mode='drop' drops them."""
        def get(col: str) -> Any:
            return new_row[col] if col in new_row else source_row.get(col)

        conditions = row_filter.get("conditions", []) or []
        if not conditions:
            return True

        all_true = True
        for cond in conditions:
            col = cond.get("column")
            op = cond.get("op")
            target = cond.get("value")
            actual = get(col) if col else None

            if op == "is_null":
                ok = actual is None or actual == ""
            elif op == "is_not_null":
                ok = actual is not None and actual != ""
            elif op == "eq":
                ok = str(actual) == str(target)
            elif op == "ne":
                ok = str(actual) != str(target)
            elif op == "in":
                ok = actual in (target or [])
            elif op == "not_in":
                ok = actual not in (target or [])
            elif op in ("gt", "lt", "ge", "le"):
                try:
                    a, b = float(actual), float(target)
                    ok = (a > b) if op == "gt" else (a < b) if op == "lt" else (a >= b) if op == "ge" else (a <= b)
                except (TypeError, ValueError):
                    ok = False
            elif op == "contains":
                ok = actual is not None and str(target) in str(actual)
            elif op == "starts_with":
                ok = actual is not None and str(actual).startswith(str(target))
            else:
                ok = True

            if not ok:
                all_true = False
                break

        return (not all_true) if row_filter.get("mode", "keep") == "drop" else all_true

    def _inject_globals(
        self, new_row: Dict[str, Any], source_row: Dict[str, Any], target_table: str
    ) -> None:
        """Apply global_columns to a single output row (spec 7.2 + 6)."""
        for gc in self.config.get("global_columns", []) or []:
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
            new_row[name] = source_row.get(src_col) if src_col else gc.get("value")
