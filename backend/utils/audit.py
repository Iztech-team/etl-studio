"""Audit trail for tracking data modifications and transformations."""

from typing import Any, Dict, List, Tuple
from datetime import datetime


class AuditTrail:
    """Track all modifications made to data during extraction and transformation.

    Aggregation strategy: per-cell `log_*` calls increment counters keyed
    by (event_type, table, column[, extra]). At flush time we expand each
    counter into a SINGLE event with the aggregated count. This is what
    makes the audit cost per-(table,column) instead of per-cell — without
    it, a 5M-row × 10-column transform would generate 50M event dicts and
    50M `datetime.utcnow()` syscalls. Now it generates ~10.
    """

    def __init__(self, source_type: str = "upload", source_name: str = ""):
        self.source_type = source_type  # "db", "csv", "excel", "sql"
        self.source_name = source_name
        self.created_at = datetime.utcnow().isoformat()
        self.events: List[Dict[str, Any]] = []
        self.stats = {
            "directional_marks_stripped": 0,
            "arabic_digits_normalized": 0,
            "encoding_fixed": 0,
            "null_normalized": 0,
            "type_coerced": 0,
            "reference_mapped": 0,
        }
        # (event_type, table, column, *extra) -> count
        self._counters: Dict[Tuple[Any, ...], int] = {}

    # ---- per-cell hot path: count, don't allocate event dicts -----------

    def log_directional_marks_stripped(self, table: str, column: str, count: int = 1):
        key = ("directional_marks_stripped", table, column)
        self._counters[key] = self._counters.get(key, 0) + count
        self.stats["directional_marks_stripped"] += count

    def log_arabic_digits_normalized(self, table: str, column: str, count: int = 1):
        key = ("arabic_digits_normalized", table, column)
        self._counters[key] = self._counters.get(key, 0) + count
        self.stats["arabic_digits_normalized"] += count

    def log_encoding_fixed(self, table: str, column: str, count: int = 1):
        key = ("encoding_fixed", table, column)
        self._counters[key] = self._counters.get(key, 0) + count
        self.stats["encoding_fixed"] += count

    def log_null_normalized(self, table: str, column: str, count: int = 1):
        key = ("null_normalized", table, column)
        self._counters[key] = self._counters.get(key, 0) + count
        self.stats["null_normalized"] += count

    def log_type_coerced(
        self, table: str, column: str, from_type: str, to_type: str, count: int = 1
    ):
        key = ("type_coerced", table, column, from_type, to_type)
        self._counters[key] = self._counters.get(key, 0) + count
        self.stats["type_coerced"] += count

    def log_reference_mapped(self, table: str, column: str, count: int = 1):
        key = ("reference_mapped", table, column)
        self._counters[key] = self._counters.get(key, 0) + count
        self.stats["reference_mapped"] += count

    # ---- expansion: turn counters into events ---------------------------

    def flush_counters_to_events(self) -> None:
        """Expand the per-(table,column,type) counters into one event per
        triple. Called by the transformer / extractor at the end of a run
        so the events list (and downstream DB inserts) stay small.

        Idempotent: clears counters after expansion so repeated calls
        don't double-count. Safe to call even when no counters are present.
        """
        if not self._counters:
            return
        now = datetime.utcnow().isoformat()
        for key, count in self._counters.items():
            ev_type = key[0]
            table = key[1]
            column = key[2]
            ev: Dict[str, Any] = {
                "timestamp": now,
                "type": ev_type,
                "table": table,
                "column": column,
                "count": count,
            }
            if ev_type == "type_coerced" and len(key) >= 5:
                ev["from_type"] = key[3]
                ev["to_type"] = key[4]
                ev["description"] = (
                    f"Coerced {count} value(s) from {key[3]} to {key[4]} "
                    f"in {table}.{column}"
                )
            else:
                ev["description"] = (
                    f"{ev_type.replace('_', ' ').capitalize()} "
                    f"applied to {count} value(s) in {table}.{column}"
                )
            self.events.append(ev)
        self._counters.clear()

    def log_extraction_started(self, db_type: str, table_count: int):
        """Log start of DB extraction."""
        self.events.insert(
            0,
            {
                "timestamp": datetime.utcnow().isoformat(),
                "type": "extraction_started",
                "db_type": db_type,
                "expected_tables": table_count,
                "description": f"Started extraction from {db_type} database",
            },
        )

    def log_extraction_completed(self, tables_extracted: List[str], total_rows: int):
        """Log successful extraction completion."""
        self.events.append(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "type": "extraction_completed",
                "tables_extracted": len(tables_extracted),
                "total_rows": total_rows,
                "tables": tables_extracted,
                "description": f"Successfully extracted {len(tables_extracted)} tables with {total_rows} total rows",
            }
        )

    def log_extraction_error(self, error: str):
        """Log extraction errors."""
        self.events.append(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "type": "extraction_error",
                "error": error,
                "description": f"Extraction failed: {error}",
            }
        )

    def log_schema_change(self, table: str, columns_added: int, columns_removed: int):
        """Log schema modifications."""
        if columns_added > 0 or columns_removed > 0:
            self.events.append(
                {
                    "timestamp": datetime.utcnow().isoformat(),
                    "type": "schema_change",
                    "table": table,
                    "columns_added": columns_added,
                    "columns_removed": columns_removed,
                    "description": f"Schema change in {table}: +{columns_added} columns, -{columns_removed} columns",
                }
            )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize audit trail to dictionary. Flushes any pending
        counters first so the aggregated events show up in the result."""
        self.flush_counters_to_events()
        return {
            "source_type": self.source_type,
            "source_name": self.source_name,
            "created_at": self.created_at,
            "stats": self.stats,
            "events": self.events,
            "total_events": len(self.events),
        }
