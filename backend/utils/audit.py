"""Audit trail for tracking data modifications and transformations."""

from typing import Any, Dict, List
from datetime import datetime


class AuditTrail:
    """Track all modifications made to data during extraction and transformation."""

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

    def log_directional_marks_stripped(self, table: str, column: str, count: int = 1):
        """Log removal of invisible Unicode directional marks."""
        self.events.append(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "type": "directional_marks_stripped",
                "table": table,
                "column": column,
                "count": count,
                "description": f"Removed invisible Unicode directional marks from {table}.{column}",
            }
        )
        self.stats["directional_marks_stripped"] += count

    def log_arabic_digits_normalized(self, table: str, column: str, count: int = 1):
        """Log conversion of Arabic/Persian digits to ASCII."""
        self.events.append(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "type": "arabic_digits_normalized",
                "table": table,
                "column": column,
                "count": count,
                "description": f"Converted Arabic/Persian digits to ASCII in {table}.{column}",
            }
        )
        self.stats["arabic_digits_normalized"] += count

    def log_encoding_fixed(self, table: str, column: str, count: int = 1):
        """Log mojibake repairs."""
        self.events.append(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "type": "encoding_fixed",
                "table": table,
                "column": column,
                "count": count,
                "description": f"Fixed encoding corruption in {table}.{column}",
            }
        )
        self.stats["encoding_fixed"] += count

    def log_null_normalized(self, table: str, column: str, count: int = 1):
        """Log null value standardization."""
        self.events.append(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "type": "null_normalized",
                "table": table,
                "column": column,
                "count": count,
                "description": f"Normalized null values in {table}.{column}",
            }
        )
        self.stats["null_normalized"] += count

    def log_type_coerced(self, table: str, column: str, from_type: str, to_type: str, count: int = 1):
        """Log type conversions."""
        self.events.append(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "type": "type_coerced",
                "table": table,
                "column": column,
                "from_type": from_type,
                "to_type": to_type,
                "count": count,
                "description": f"Coerced {count} value(s) from {from_type} to {to_type} in {table}.{column}",
            }
        )
        self.stats["type_coerced"] += count

    def log_reference_mapped(self, table: str, column: str, count: int = 1):
        """Log reference table mappings."""
        self.events.append(
            {
                "timestamp": datetime.utcnow().isoformat(),
                "type": "reference_mapped",
                "table": table,
                "column": column,
                "count": count,
                "description": f"Applied reference mapping to {count} value(s) in {table}.{column}",
            }
        )
        self.stats["reference_mapped"] += count

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
        """Serialize audit trail to dictionary."""
        return {
            "source_type": self.source_type,
            "source_name": self.source_name,
            "created_at": self.created_at,
            "stats": self.stats,
            "events": self.events,
            "total_events": len(self.events),
        }
