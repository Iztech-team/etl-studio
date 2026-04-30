import csv
import json
import os
from typing import Any, Dict, List, Set


def _toposort_self_ref(
    rows: List[Dict[str, Any]], parent_col: str, name_col: str
) -> List[Dict[str, Any]]:
    """Reorder rows so each row's `parent_col` value points to a row that
    appears earlier in the result. Used for self-referential tables like
    tabAccount where parent_account → name. Roots and orphans (parent
    pointing to a non-existent row) come out first / where they fit.

    DFS-based; cycles are tolerated (the cycle members fall back to input
    order among themselves). Rows missing the name column pass through at
    the end."""
    by_name: Dict[Any, Dict[str, Any]] = {}
    for r in rows:
        n = r.get(name_col)
        if n is not None and n not in by_name:
            by_name[n] = r

    visited: Set[Any] = set()
    in_stack: Set[Any] = set()
    result: List[Dict[str, Any]] = []

    def visit(name: Any) -> None:
        if name in visited or name in in_stack:
            return
        in_stack.add(name)
        row = by_name.get(name)
        if row is not None:
            parent = row.get(parent_col)
            if parent is not None and parent != name and parent in by_name:
                visit(parent)
            result.append(row)
        in_stack.discard(name)
        visited.add(name)

    for r in rows:
        n = r.get(name_col)
        if n is not None:
            visit(n)

    # Tail: rows without a usable name column — keep them in original
    # order at the end so they aren't silently dropped.
    for r in rows:
        if r.get(name_col) is None:
            result.append(r)
    return result


class Loader:
    """Writes transformed data to JSON or SQL dump files. No destructive DB ops."""

    def __init__(
        self,
        transformed: Dict[str, Any],
        config: Dict[str, Any],
        out_dir: str,
        fk_edges: List[tuple] | None = None,
        self_refs: Dict[str, str] | None = None,
        name_column: str = "name",
    ):
        self.tables: Dict[str, List[Dict]] = transformed.get("tables", {})
        self.exceptions: Dict[str, List[Dict]] = transformed.get("exceptions", {}) or {}
        self.config = config
        self.out_dir = out_dir
        self.fk_edges = fk_edges or []
        # target_table -> parent column. For each table named here, rows
        # are sorted topologically on (parent_column → name_column) before
        # writing so parent rows precede child rows.
        self.self_refs: Dict[str, str] = self_refs or {}
        self.name_column = name_column

    # ------------------------------------------------------------------
    def _ordered_rows(self, table: str) -> List[Dict[str, Any]]:
        """Return rows for `table`, topologically sorted on the parent
        column if the table is self-referential. Otherwise the original
        order (already insertion-ordered from the transformer)."""
        rows = self.tables.get(table, [])
        parent_col = self.self_refs.get(table)
        if not parent_col or not rows:
            return rows
        return _toposort_self_ref(rows, parent_col, self.name_column)

    def run(self) -> Dict[str, Any]:
        fmt = self.config.get("output_format", "json")
        respect_fk = self.config.get("respect_fk_order", True)
        errors: List[str] = []
        output_files: List[str] = []
        rows_written: Dict[str, int] = {}

        table_order = list(self.tables.keys())
        if respect_fk:
            table_order = self._fk_sort(table_order)

        if fmt == "json":
            for table in table_order:
                rows = self._ordered_rows(table)
                fname = f"{table}.json"
                path = os.path.join(self.out_dir, fname)
                try:
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(rows, f, indent=2, default=str)
                    output_files.append(fname)
                    rows_written[table] = len(rows)
                except Exception as e:
                    errors.append(f"{table}: {e}")

            # also write combined
            combined_path = os.path.join(self.out_dir, "all_tables.json")
            combined = {t: self._ordered_rows(t) for t in table_order}
            with open(combined_path, "w", encoding="utf-8") as f:
                json.dump(combined, f, indent=2, default=str)
            output_files.append("all_tables.json")

        elif fmt == "csv":
            for table in table_order:
                rows = self._ordered_rows(table)
                if not rows:
                    continue
                fname = f"{table}.csv"
                path = os.path.join(self.out_dir, fname)
                try:
                    cols = list(rows[0].keys())
                    with open(path, "w", encoding="utf-8", newline="") as f:
                        writer = csv.DictWriter(f, fieldnames=cols)
                        writer.writeheader()
                        writer.writerows(rows)
                    output_files.append(fname)
                    rows_written[table] = len(rows)
                except Exception as e:
                    errors.append(f"{table}: {e}")

        elif fmt == "sql":
            sql_lines: List[str] = []
            sql_lines.append("-- ETL Legacy SQL Dump")
            sql_lines.append("-- Generated by ETL Legacy")
            sql_lines.append("BEGIN;")
            sql_lines.append("")

            for table in table_order:
                rows = self._ordered_rows(table)
                if not rows:
                    continue
                cols = list(rows[0].keys())
                col_list = ", ".join(f'"{c}"' for c in cols)
                sql_lines.append(f"-- Table: {table}")
                for row in rows:
                    vals = ", ".join(self._sql_val(row.get(c)) for c in cols)
                    sql_lines.append(
                        f'INSERT INTO "{table}" ({col_list}) VALUES ({vals});'
                    )
                sql_lines.append("")
                rows_written[table] = len(rows)

            # Spec 7.5 — counter resets so new orders don't collide with migrated numbers
            counter_resets = self.config.get("counter_resets") or []
            if counter_resets:
                sql_lines.append("-- Counter resets (spec 7.5)")
                for cr in counter_resets:
                    ct = cr.get("counter_table")
                    cc = cr.get("counter_column", "value")
                    st = cr.get("source_table")
                    sc = cr.get("source_column")
                    where = cr.get("where_clause")
                    if not (ct and st and sc):
                        continue
                    where_sql = f" WHERE {where}" if where else ""
                    sql_lines.append(
                        f'UPDATE "{ct}" SET "{cc}" = '
                        f'(SELECT COALESCE(MAX("{sc}"), 0) + 1 FROM "{st}"{where_sql});'
                    )
                sql_lines.append("")

            post_load = self.config.get("post_load_sql") or []
            if post_load:
                sql_lines.append("-- Post-load SQL")
                sql_lines.extend(stmt.rstrip(";") + ";" for stmt in post_load if stmt)
                sql_lines.append("")

            sql_lines.append("COMMIT;")
            fname = "dump.sql"
            path = os.path.join(self.out_dir, fname)
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(sql_lines))
            output_files.append(fname)

        # Spec 3.4 / 3.12 / 4 — write per-category exception CSVs for review
        exception_files = self._write_exceptions()
        output_files.extend(exception_files)

        return {
            "ok": len(errors) == 0,
            "output_files": output_files,
            "rows_written": rows_written,
            "staging_used": self.config.get("use_staging", False),
            "transaction_wrapped": fmt == "sql",
            "errors": errors,
            "exceptions_written": exception_files,
        }

    def _write_exceptions(self) -> List[str]:
        """Emit one CSV per exception category under outputs/exceptions/."""
        if not self.exceptions:
            return []
        out_paths: List[str] = []
        excs_dir = os.path.join(self.out_dir, "exceptions")
        os.makedirs(excs_dir, exist_ok=True)
        for category, records in self.exceptions.items():
            if not records:
                continue
            fname = f"exceptions/{category}.csv"
            path = os.path.join(self.out_dir, fname)
            cols = sorted({k for rec in records for k in rec.keys()})
            try:
                with open(path, "w", encoding="utf-8", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=cols)
                    writer.writeheader()
                    writer.writerows(records)
                out_paths.append(fname)
            except Exception:
                continue
        return out_paths

    @staticmethod
    def _sql_val(v: Any) -> str:
        if v is None:
            return "NULL"
        if isinstance(v, bool):
            return "TRUE" if v else "FALSE"
        if isinstance(v, (int, float)):
            return str(v)
        escaped = str(v).replace("'", "''")
        return f"'{escaped}'"

    def _fk_sort(self, tables: List[str]) -> List[str]:
        """Topological sort based on FK dependency edges.

        Parents (referenced tables) come before children (referencing tables).
        Falls back to alphabetical for tables with no FK info or on cycles.
        """
        table_set = set(tables)

        # Build adjacency: child -> set of parents it depends on
        deps: Dict[str, Set[str]] = {t: set() for t in tables}
        for child, parent in self.fk_edges:
            if child in table_set and parent in table_set and child != parent:
                deps[child].add(parent)

        # Kahn's algorithm (topological sort)
        result: List[str] = []
        ready = sorted([t for t in tables if not deps[t]])
        remaining = {t: set(parents) for t, parents in deps.items() if parents}

        while ready:
            node = ready.pop(0)
            result.append(node)
            to_remove = []
            for child, parents in remaining.items():
                parents.discard(node)
                if not parents:
                    to_remove.append(child)
            for child in sorted(to_remove):
                del remaining[child]
                ready.append(child)

        # If there are remaining tables (cycle), append them alphabetically
        if remaining:
            result.extend(sorted(remaining.keys()))

        return result
