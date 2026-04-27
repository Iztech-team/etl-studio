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
    source_row: Optional[Dict[str, Any]] = None,
) -> Any:
    """Compute the value for an added column from its `generator` config.

    Mirrors frontend's GeneratorEditor / renderAddedCellPreview in
    retro/Pipeline.tsx. If `gen` is None or unrecognised, returns
    `fallback` (which is the legacy default_value path).

    `source_row` is the original CSV row, before any column processing.
    `from_column` and `concat` generators look in `new_row` first (so they
    can reference renamed / FK-resolved values) but fall back to
    `source_row` so the user can refer to a source column even if it was
    dropped from the output.
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
            if key in new_row:
                v = new_row[key]
            else:
                v = src_row.get(key)
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
        # No deepcopy: we never mutate `tables`, `rows`, or any individual
        # row dict — every output row is freshly built into `new_row`. For
        # 1 GB / millions-of-rows projects the deepcopy alone was costing
        # 5–15 s and a full-data memory burst.
        # We DO take a shallow copy of the outer dict so that releasing a
        # table's rows during processing (memory optimisation in lazy
        # mode) doesn't reach back and clear the caller's
        # session["raw"]["tables"][name].
        _src_tables = raw.get("tables", {}) or {}
        self.tables: Dict[str, List[Dict]] = dict(_src_tables)
        self.schema: Dict[str, Any] = raw.get("schema", {})
        self.config = config
        self.audit_trail = audit_trail or AuditTrail()
        # Optional callback invoked after each source table is processed:
        #   progress_cb(table_name, done_count, total_count)
        # Used by /api/transform to surface per-table progress to the
        # navbar dock without holding the asyncio loop hostage.
        self.progress_cb = progress_cb
        # Optional callback fired the moment a target table becomes COMPLETE
        # — i.e. every source feeding it has finished processing.
        # Signature: persist_target_cb(target_name, rows). The /api/transform
        # endpoint passes a callback that writes the rows to disk, so a
        # mid-run crash leaves already-completed targets safely persisted
        # rather than losing the whole batch.
        self.persist_target_cb = persist_target_cb
        # Optional lazy row loader. When set, the transformer doesn't need
        # `tables` to be pre-populated — it calls `row_loader(table_name)`
        # to fetch rows just before processing each source, and frees them
        # afterward so memory peaks at roughly one source's worth instead
        # of the full dataset. Signature: row_loader(name) -> List[Dict].
        # Used by /api/transform to read tables straight from the per-table
        # cache pickles.
        self.row_loader = row_loader
        self.warnings: List[str] = []
        self._encoding_conversions = 0
        self._type_conversions = 0
        self._ref_mappings = 0
        self._null_normalizations = 0
        self._dedup_removed = 0
        self._transformed: Dict[str, List[Dict]] = {}
        self.fk_edges: List[tuple] = []
        # Per-target self-reference info for the loader: target_table -> the
        # column on the output row that holds the parent's identifier. Used
        # by the loader to sort rows so parents are written before children
        # (e.g. tabAccount.parent_account → tabAccount.name).
        self.self_refs: Dict[str, str] = {}
        # Spec 3.4 / 3.12 / 4 — exceptions surface for human review
        self.exceptions: Dict[str, List[Dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    def _get_table_rows(self, name: str) -> List[Dict[str, Any]]:
        """Return rows for `name`, lazy-loading via `row_loader` if the
        in-memory copy is empty. Used everywhere the transformer needs to
        touch a source table's rows so the caller (e.g. /api/transform)
        only ever has one table's worth of data in RAM at a time."""
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
        # Cache so repeated reads in the same source iteration don't re-load
        # — caller frees by setting self.tables[name] = [] after processing.
        self.tables[name] = loaded
        return loaded

    def _release_table_rows(self, name: str) -> None:
        """Drop a table's rows so the GC can reclaim them. Called after a
        source has been fully processed AND it isn't an FK source still
        needed for lookups (FK source tables are released earlier, by
        _build_fk_lookups itself, after their lookup dict is built)."""
        if name in self.tables:
            self.tables[name] = []

    def _build_fk_lookups(
        self, table_configs: List[Dict[str, Any]]
    ) -> Dict[tuple, Dict]:
        """Pre-build lookup dicts for every (table, match_col, source_col)
        triple referenced by any FK column or FK-chain hop in the config.

        We pre-build because each transform iteration would otherwise scan
        the source table for every row — quadratic in catalog size.

        With a lazy `row_loader`, we load each FK source table on demand
        here, build all the lookup dicts that need it, then release the
        rows. The lookup dict itself is small (one entry per match-col
        value) so we keep it in RAM for the duration of run()."""
        fk_lookups: Dict[tuple, Dict] = {}

        # Group lookups by FK source table so we load each table at most
        # once during this build.
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
            # Deduplicate (match_col, source_col) pairs so we don't scan
            # the same table twice.
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
            # NOTE: we deliberately do NOT release fk_table's rows here.
            # If the table is also iterated as a real source in the main
            # loop (very common — e.g. ACCOUNTT is both an FK source for
            # customer.customer_name AND a real source mapping to
            # tabAccount), releasing now would force a second row_loader
            # call later. Leaving them cached costs a few MB for a typical
            # lookup table; the main loop frees them after iteration.

        return fk_lookups

        for tc in table_configs:
            if tc.get("drop_table"):
                continue
            for cc in tc.get("columns", []):
                # Single-hop FK
                remember(
                    cc.get("fk_source_table"),
                    cc.get("fk_match_column"),
                    cc.get("fk_source_column"),
                )
                # Multi-hop FK: pre-build a lookup dict for every hop
                for hop in cc.get("fk_chain") or []:
                    remember(
                        hop.get("table"),
                        hop.get("match_column"),
                        hop.get("source_column"),
                    )
        return fk_lookups

    # ------------------------------------------------------------------
    def run(self) -> Dict[str, Any]:
        null_values = set(
            self.config.get("null_values", ["", "NULL", "null", "N/A", "n/a"])
        )
        # NB: a single source table may appear in multiple TableConfigs — that's
        # how UNION ALL is expressed. So we keep the configs as a list.
        table_configs_list: List[Dict[str, Any]] = list(self.config.get("tables", []))

        # Tables that some config explicitly drops. Used at the very end to
        # filter the pass-through fall-back so a dropped table doesn't sneak
        # back in just because it had no other config.
        dropped_sources = {
            tc["source_table"] for tc in table_configs_list if tc.get("drop_table")
        }

        fk_lookups = self._build_fk_lookups(table_configs_list)

        # Collect FK edges for dependency-aware load ordering. Sources of
        # edges:
        #   1. Single-hop FK columns (fk_source_table)
        #   2. Multi-hop FK chain (every hop's table is a dependency)
        #   3. Explicit `load_after` declarations from the preset
        # Self-references (target → same target) become entries in
        # self_refs instead of cross-table edges, so the loader can do an
        # within-table sort on the parent column.
        self.fk_edges = []
        self.self_refs = {}
        # Map source table -> target table so we can resolve FK source-table
        # references to their post-rename target names. ERPnext expects
        # dependencies between TARGET tables (tabAccount, tabItem), not
        # between source tables (ACCOUNTT, CATEGORYT).
        source_to_target: Dict[str, str] = {}
        for tc in table_configs_list:
            if tc.get("drop_table"):
                continue
            src = tc.get("source_table")
            tgt = tc.get("target_table") or src
            if src and tgt:
                source_to_target.setdefault(src, tgt)

        for tc in table_configs_list:
            if tc.get("drop_table"):
                continue
            src = tc.get("source_table")
            child_table = tc.get("target_table") or src
            for cc in tc.get("columns", []):
                # Single-hop FK
                fk_table = cc.get("fk_source_table")
                if fk_table and child_table:
                    fk_target = source_to_target.get(fk_table, fk_table)
                    if fk_target == child_table:
                        # Self-reference: record the parent column name on
                        # the OUTPUT row (post-rename).
                        parent_col = cc.get("target_name") or cc.get("name")
                        if parent_col:
                            self.self_refs[child_table] = parent_col
                    else:
                        self.fk_edges.append((child_table, fk_target))
                # Multi-hop FK: each intermediate table is a dependency.
                # Self-references through chains are unusual and we treat
                # all hops as cross-table dependencies.
                for hop in cc.get("fk_chain") or []:
                    hop_tbl = hop.get("table")
                    if hop_tbl and child_table:
                        hop_target = source_to_target.get(hop_tbl, hop_tbl)
                        if hop_target != child_table:
                            self.fk_edges.append((child_table, hop_target))
            # Explicit load_after declarations
            for parent in tc.get("load_after") or []:
                if parent and child_table and parent != child_table:
                    self.fk_edges.append((child_table, parent))
            # Explicit self-reference from TableConfig
            sr_col = tc.get("self_reference_parent_column")
            if sr_col and child_table:
                self.self_refs[child_table] = sr_col

        # Build dedup constraints from DDL schema
        ddl_constraints = self.config.get("ddl_constraints", {})

        # Index configs by source table so we can find every config a source
        # contributes to (one source can feed multiple targets — see
        # CATEGORYT → products and CATEGORYT → product_barcodes).
        configs_by_source: Dict[str, List[Dict[str, Any]]] = {}
        for tc in table_configs_list:
            if tc.get("drop_table"):
                continue
            configs_by_source.setdefault(tc["source_table"], []).append(tc)

        # Per-target dependency tracking: which sources feed each target,
        # so we know when a target is fully built and safe to persist.
        # Two sources targeting the same name (UNION ALL) means the target
        # isn't complete until BOTH of those sources have run.
        target_to_pending_sources: Dict[str, set] = {}
        for tc in table_configs_list:
            if tc.get("drop_table"):
                continue
            tgt = tc.get("target_table") or tc.get("source_table")
            src = tc.get("source_table")
            if tgt and src:
                target_to_pending_sources.setdefault(tgt, set()).add(src)
        sources_processed: set = set()
        targets_persisted: set = set()

        total_rows = 0
        # Build the master list of source tables we plan to process. Use
        # the SCHEMA keys when self.tables is empty (lazy-load mode); fall
        # back to whatever's in self.tables otherwise.
        candidate_sources = list(self.tables.keys())
        if not candidate_sources:
            # Lazy mode: schema is the only thing populated on resume.
            candidate_sources = list(self.schema.keys())
        # Add any source named in a TableConfig that isn't already in the
        # list — defensive against missing schema entries.
        for tc in table_configs_list:
            src = tc.get("source_table")
            if src and src not in candidate_sources:
                candidate_sources.append(src)
        total_sources = sum(
            1
            for t in candidate_sources
            if not (t in dropped_sources and t not in configs_by_source)
        )
        done_sources = 0
        for table_name in candidate_sources:
            if table_name in dropped_sources and table_name not in configs_by_source:
                continue  # explicitly dropped, no other config keeps it

            if self.progress_cb:
                try:
                    self.progress_cb(table_name, done_sources, total_sources)
                except Exception:
                    pass  # never let a UI hook break the pipeline

            # Lazy-load this source's rows just before processing. After
            # the configs that consume them all run, we release the rows
            # so memory peaks at roughly one table's worth.
            rows = self._get_table_rows(table_name)

            tcs_for_table = configs_by_source.get(
                table_name, [{"source_table": table_name}]
            )
            for tc in tcs_for_table:
                col_configs = {cc["name"]: cc for cc in tc.get("columns", [])}
                row_filter_cfg = tc.get("row_filter")

                # Aggregation runs BEFORE per-row column transforms, so
                # the rows the column pipeline sees are already grouped.
                # Used by the ERPnext preset for Brand seed (DISTINCT
                # MANUFACTURER), Mode of Payment seed (DISTINCT PAYTYPE),
                # and Payment Entry parent (GROUP BY DOCSERIAL+DOCCLASS).
                agg_cfg = tc.get("aggregate")
                if agg_cfg and (agg_cfg.get("group_by") or rows):
                    rows_iter = self._aggregate(rows, agg_cfg)
                else:
                    rows_iter = rows

                # Pre-flatten the existing-column config into tuples of
                # bound locals. The per-row loop now iterates a small list
                # instead of doing five `cc.get(...)` calls per cell. For
                # a 5M-row table that's ~25M dict lookups saved.
                #
                # Tuple shape: (col, target_col, dtype, ref_map, transforms)
                # - col          : source column name
                # - target_col   : target column name (rename target)
                # - dtype        : type to coerce to (or None to skip)
                # - ref_map      : value-to-value lookup dict (or None)
                # - transforms   : list of column transforms (or None)
                schema_for_table = self.schema.get(table_name, {})
                active_cols: List[tuple] = []
                if col_configs:
                    for col, cc in col_configs.items():
                        if cc.get("is_new") or not cc.get("include", True):
                            continue
                        target_col = cc.get("target_name") or col
                        dtype = cc.get("data_type") or schema_for_table.get(
                            col, {}
                        ).get("inferred_type", "string")
                        ref_map = cc.get("reference_map")
                        transforms_cfg = cc.get("transforms") or None
                        active_cols.append(
                            (col, target_col, dtype, ref_map, transforms_cfg)
                        )
                else:
                    # No explicit config — pass every column through under
                    # its original name. Use the schema as the canonical
                    # column list (works even when rows is empty); fall
                    # back to the first row's keys.
                    cols = list(schema_for_table.keys())
                    if not cols:
                        first_row = next(iter(rows_iter), None) if rows_iter else None
                        if first_row:
                            cols = list(first_row.keys())
                            # Re-include the row we just consumed: rows_iter
                            # is now drained; convert it back to a list with
                            # first_row prepended.
                            rest = list(rows_iter) if rows_iter else []
                            rows_iter = [first_row, *rest]
                    for col in cols:
                        dtype = schema_for_table.get(col, {}).get(
                            "inferred_type", "string"
                        )
                        active_cols.append((col, col, dtype, None, None))
                # Bind module-level functions to locals for tight-loop speed
                _strip_marks = strip_directional_marks
                _fix_enc = fix_encoding_str
                _coerce = self._coerce
                _audit = self.audit_trail
                _audit_log_marks = _audit.log_directional_marks_stripped
                _audit_log_enc = _audit.log_encoding_fixed
                _audit_log_null = _audit.log_null_normalized
                _audit_log_ref = _audit.log_reference_mapped
                _audit_log_coerce = _audit.log_type_coerced

                new_rows: List[Dict[str, Any]] = []
                transform_state: Dict[str, Any] = {}
                for row_index, row in enumerate(rows_iter):
                    new_row: Dict[str, Any] = {}

                    # --- process existing columns ---
                    # Iterate the pre-flattened list rather than the row's
                    # dict. Columns not in active_cols (i.e. dropped or
                    # marked is_new) never reach this loop.
                    for col, target_col, dtype, ref_map, transforms_cfg in active_cols:
                        val = row.get(col)

                        # 1. Strip directional marks (string-only).
                        if isinstance(val, str):
                            clean = _strip_marks(val)
                            if clean is not val and clean != val:
                                _audit_log_marks(table_name, col)
                                val = clean
                            # 2. Encoding fix
                            fixed = _fix_enc(val)
                            if fixed is not val and fixed != val:
                                self._encoding_conversions += 1
                                _audit_log_enc(table_name, col)
                                val = fixed

                        # 3. Null normalisation
                        if val is None:
                            pass
                        elif isinstance(val, str):
                            stripped = val.strip()
                            if stripped in null_values:
                                val = None
                                self._null_normalizations += 1
                                _audit_log_null(table_name, col)
                        elif val == "" or str(val).strip() in null_values:
                            val = None
                            self._null_normalizations += 1
                            _audit_log_null(table_name, col)

                        # 4. Reference mapping
                        if ref_map and val in ref_map:
                            val = ref_map[val]
                            self._ref_mappings += 1
                            _audit_log_ref(table_name, col)

                        # 5. Type conversion
                        if val is not None:
                            old_dtype = "string"
                            if isinstance(val, bool):
                                old_dtype = "boolean"
                            elif isinstance(val, (int, float)):
                                old_dtype = "numeric"
                            val, converted = _coerce(val, dtype)
                            if converted:
                                self._type_conversions += 1
                                _audit_log_coerce(table_name, col, old_dtype, dtype)

                        # 6. Column transforms pipeline
                        if transforms_cfg:
                            val = apply_transforms(
                                val,
                                transforms_cfg,
                                col,
                                row=row,
                                state=transform_state,
                                exceptions=self.exceptions,
                                table=table_name,
                                new_row=new_row,
                            )

                        new_row[target_col] = val

                    # --- process FK columns FIRST ---
                    # FK lookups only read from the SOURCE row, so they
                    # don't depend on anything else. Doing them first means
                    # downstream generators (concat_template etc.) can
                    # reference the FK-resolved values in new_row — useful
                    # for things like Bin.name = "{warehouse}-{item_code}".
                    for cc_name, cc in col_configs.items():
                        if not cc.get("is_new"):
                            continue
                        if not cc.get("include", True):
                            continue
                        fk_local_col = cc.get("fk_local_column")
                        fk_chain = cc.get("fk_chain") or []
                        # Single-hop config provides fk_source_table etc.
                        # Multi-hop config provides fk_chain instead.
                        if not fk_local_col:
                            continue
                        if not fk_chain:
                            fk_table = cc.get("fk_source_table")
                            fk_source_col = cc.get("fk_source_column")
                            fk_match_col = cc.get("fk_match_column")
                            if not (fk_table and fk_source_col and fk_match_col):
                                continue
                            fk_chain = [
                                {
                                    "table": fk_table,
                                    "match_column": fk_match_col,
                                    "source_column": fk_source_col,
                                }
                            ]

                        target_col = cc.get("target_name") or cc_name
                        # Walk the chain. Each hop reads the previous value
                        # and produces the next one. None-out and stop early
                        # if any hop misses — that's an unresolved FK.
                        val: Any = row.get(fk_local_col)
                        for hop in fk_chain:
                            if val is None:
                                break
                            lookup_key = (
                                hop.get("table"),
                                hop.get("match_column"),
                                hop.get("source_column"),
                            )
                            val = fk_lookups.get(lookup_key, {}).get(val)

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
                                new_row=new_row,
                            )

                        new_row[target_col] = val

                    # --- process non-FK is_new columns (generators) ---
                    # Runs AFTER FK lookups so concat_template / compute /
                    # from_column generators can reference FK-resolved
                    # values like {warehouse} or {customer_name}.
                    for cc_name, cc in col_configs.items():
                        if not cc.get("is_new"):
                            continue
                        if not cc.get("include", True):
                            continue
                        if cc.get("fk_source_table") or cc.get("fk_chain"):
                            continue  # FK columns already handled above

                        target_col = cc.get("target_name") or cc_name

                        if cc.get("nullable", True) and cc.get("default_value") is None:
                            fallback: Any = None
                        else:
                            fallback = cc.get("default_value")

                        val = _apply_value_generator(
                            cc.get("generator"),
                            row_index,
                            new_row,
                            fallback,
                            source_row=row,
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
                                new_row=new_row,
                            )
                        new_row[target_col] = val

                    # --- row filter (after column transforms see renamed cols) ---
                    if row_filter_cfg and not self._row_passes_filter(
                        new_row, row, row_filter_cfg
                    ):
                        continue

                    # --- inject global columns ---
                    target_name_local = tc.get("target_table") or table_name
                    self._inject_globals(new_row, row, target_name_local)

                    new_rows.append(new_row)

                target_name = tc.get("target_table") or table_name
                # Append rather than overwrite: two configs hitting the same
                # target_table get UNIONed (used for product_barcodes).
                if target_name in self._transformed:
                    self._transformed[target_name].extend(new_rows)
                else:
                    self._transformed[target_name] = new_rows
                total_rows += len(new_rows)

            # Free the source rows now that every TableConfig consuming
            # them has finished. Memory peaks at roughly one source's
            # worth of rows during transform instead of the whole dataset.
            self._release_table_rows(table_name)

            done_sources += 1
            sources_processed.add(table_name)
            if self.progress_cb:
                try:
                    self.progress_cb(table_name, done_sources, total_sources)
                except Exception:
                    pass

            # Per-target persistence: a target is "complete" when every
            # source that feeds it has been processed. Fire the persist
            # callback the moment that's true so a downstream crash never
            # loses already-finished tables.
            if self.persist_target_cb is not None:
                for tgt, pending in target_to_pending_sources.items():
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

        # Deduplicate rows based on target DDL unique/PK constraints
        total_rows = 0
        target_to_tc: Dict[str, Dict[str, Any]] = {}
        for tc in table_configs_list:
            if tc.get("drop_table"):
                continue
            key = tc.get("target_table") or tc.get("source_table")
            target_to_tc.setdefault(key, tc)
        for target_name, rows in self._transformed.items():
            constraints = ddl_constraints.get(target_name, {})
            tc = target_to_tc.get(target_name, {})
            deduped = self._deduplicate(target_name, rows, constraints, tc)
            self._transformed[target_name] = deduped
            total_rows += len(deduped)

        # Convert per-cell audit counters to one event per (type, table,
        # column) triple. Without this, downstream `_flush_audit_events`
        # would insert tens of millions of DB rows for a real project.
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

    @staticmethod
    def _aggregate(
        rows: List[Dict[str, Any]], agg_cfg: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Group rows by `group_by` columns and reduce non-grouped columns
        with the configured aggregator (default: 'first')."""
        group_by: List[str] = agg_cfg.get("group_by", []) or []
        aggs: Dict[str, str] = agg_cfg.get("aggregations", {}) or {}
        sep = agg_cfg.get("concat_separator", ", ")

        if not rows:
            return []

        # Empty group_by means "DISTINCT every column" — collapse byte-equal
        # rows into one. We treat the whole row as the key.
        if not group_by:
            seen = {}
            for row in rows:
                key = tuple(sorted(row.items()))
                if key not in seen:
                    seen[key] = dict(row)
            return list(seen.values())

        # Real GROUP BY: bucket rows by the key tuple, then reduce.
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
                if op == "min":
                    return min(nums)
                if op == "max":
                    return max(nums)
            # Unknown aggregator → fall back to first
            return vals[0] if vals else None

        out: List[Dict[str, Any]] = []
        all_cols = list(rows[0].keys())
        for key in order:
            group = buckets[key]
            row: Dict[str, Any] = {}
            for col in all_cols:
                if col in group_by:
                    row[col] = group[0].get(col)
                else:
                    row[col] = reduce_col(col, group)
            out.append(row)
        return out

    @staticmethod
    def _row_passes_filter(
        new_row: Dict[str, Any],
        source_row: Dict[str, Any],
        row_filter: Dict[str, Any],
    ) -> bool:
        """Evaluate a RowFilter.

        Filters can reference renamed (target) column names — e.g. is_active —
        with a fall-back to source columns so users may also reference legacy
        names like CACTIVE. mode='keep' keeps rows where every condition is
        true; mode='drop' drops them.
        """

        def get(col: str) -> Any:
            if col in new_row:
                return new_row[col]
            return source_row.get(col)

        conditions = row_filter.get("conditions", []) or []
        if not conditions:
            return True

        all_true = True
        for cond in conditions:
            col = cond.get("column")
            op = cond.get("op")
            target = cond.get("value")
            actual = get(col) if col else None

            ok: bool
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
                    a = float(actual)
                    b = float(target)
                    ok = (
                        (a > b)
                        if op == "gt"
                        else (
                            (a < b)
                            if op == "lt"
                            else (a >= b) if op == "ge" else (a <= b)
                        )
                    )
                except (TypeError, ValueError):
                    ok = False
            elif op == "contains":
                ok = actual is not None and str(target) in str(actual)
            elif op == "starts_with":
                ok = actual is not None and str(actual).startswith(str(target))
            else:
                ok = True  # unknown ops are no-ops

            if not ok:
                all_true = False
                break

        mode = row_filter.get("mode", "keep")
        if mode == "drop":
            return not all_true
        return all_true

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
