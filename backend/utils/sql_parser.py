import re
from typing import Any, Dict, List

# Normalized type mapping: SQL type prefix → internal type
DDL_TYPE_MAP: Dict[str, str] = {
    "varchar": "string",
    "text": "string",
    "char": "string",
    "nvarchar": "string",
    "nchar": "string",
    "clob": "string",
    "character varying": "string",
    "character": "string",
    "int": "integer",
    "integer": "integer",
    "bigint": "integer",
    "smallint": "integer",
    "tinyint": "integer",
    "serial": "integer",
    "bigserial": "integer",
    "decimal": "float",
    "numeric": "float",
    "real": "float",
    "double": "float",
    "double precision": "float",
    "float": "float",
    "money": "float",
    "boolean": "boolean",
    "bool": "boolean",
    "date": "date",
    "datetime": "date",
    "timestamp": "date",
    "timestamptz": "date",
    "time": "date",
}


class SQLParser:
    """Parse INSERT statements from a SQL dump into row dicts."""

    def __init__(self, content: str):
        self.content = content

    def parse(self) -> Dict[str, List[Dict]]:
        tables: Dict[str, List[Dict]] = {}

        # Match: INSERT INTO `table` (col1, col2) VALUES (v1, v2);
        # or:    INSERT INTO "table" (col1, col2) VALUES (v1, v2);
        insert_re = re.compile(
            r'INSERT\s+INTO\s+[`"\']?(\w+)[`"\']?\s*\(([^)]+)\)\s*VALUES\s*\(([^;]+)\)',
            re.IGNORECASE | re.DOTALL,
        )

        # Also handle multi-row: VALUES (...), (...), (...)
        multi_re = re.compile(
            r'INSERT\s+INTO\s+[`"\']?(\w+)[`"\']?\s*\(([^)]+)\)\s*VALUES\s*((?:\([^)]+\)[,\s]*)+)',
            re.IGNORECASE | re.DOTALL,
        )

        for m in multi_re.finditer(self.content):
            table = m.group(1)
            cols = [c.strip().strip("`\"' ") for c in m.group(2).split(",")]
            values_block = m.group(3)

            # Extract individual value tuples
            tuple_re = re.compile(r"\(([^)]+)\)")
            for tm in tuple_re.finditer(values_block):
                raw_vals = tm.group(1)
                vals = self._split_values(raw_vals)
                if len(vals) == len(cols):
                    row = {cols[i]: self._cast(vals[i]) for i in range(len(cols))}
                    tables.setdefault(table, []).append(row)

        # CREATE TABLE → extract column names for schema hint (no data)
        create_re = re.compile(
            r'CREATE\s+TABLE\s+[`"\']?(\w+)[`"\']?\s*\(([^;]+)\)',
            re.IGNORECASE | re.DOTALL,
        )
        for m in create_re.finditer(self.content):
            table = m.group(1)
            if table not in tables:
                tables.setdefault(table, [])

        return tables

    @staticmethod
    def _split_ddl_columns(body: str) -> List[str]:
        """Split CREATE TABLE body on commas, respecting parenthesized groups."""
        parts = []
        current: List[str] = []
        depth = 0
        for ch in body:
            if ch == "(":
                depth += 1
                current.append(ch)
            elif ch == ")":
                depth -= 1
                current.append(ch)
            elif ch == "," and depth == 0:
                parts.append("".join(current).strip())
                current = []
            else:
                current.append(ch)
        if current:
            parts.append("".join(current).strip())
        return parts

    def parse_ddl(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """Parse CREATE TABLE statements and return structured schema.

        Returns:
            {
                "table_name": {
                    "column_name": {
                        "inferred_type": "float",
                        "original_type": "DECIMAL(10,2)",
                        "nullable": True
                    }
                }
            }
        """
        result: Dict[str, Dict[str, Dict[str, Any]]] = {}

        # Match CREATE TABLE with multi-dialect identifiers
        # Use a greedy match for the body, then find the last closing paren
        create_re = re.compile(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
            r'[`"\[\']?(\w+)[`"\]\']?\s*\((.+)\)\s*;',
            re.IGNORECASE | re.DOTALL,
        )

        for m in create_re.finditer(self.content):
            table_name = m.group(1)
            body = m.group(2)

            columns: Dict[str, Dict[str, Any]] = {}
            # Split on commas not inside parentheses
            for line in self._split_ddl_columns(body):
                line = line.strip()
                if not line:
                    continue
                # Skip constraints
                upper = line.upper().lstrip()
                if any(
                    upper.startswith(kw)
                    for kw in (
                        "PRIMARY",
                        "FOREIGN",
                        "UNIQUE",
                        "CHECK",
                        "CONSTRAINT",
                        "INDEX",
                        "KEY",
                    )
                ):
                    continue

                # Parse: [identifier] TYPE[(precision)]
                # Type name can be multi-word (e.g. "double precision", "character varying")
                # but must stop before keywords like NOT, NULL, DEFAULT, PRIMARY, UNIQUE, CHECK, REFERENCES
                col_re = re.compile(
                    r'[`"\[\']?(\w+)[`"\]\']?\s+'
                    r"([A-Za-z]\w*(?:\s+(?!NOT\b|NULL\b|DEFAULT\b|PRIMARY\b|UNIQUE\b|CHECK\b|REFERENCES\b|AUTO_INCREMENT\b|GENERATED\b)[A-Za-z]\w*)*(?:\([^)]*\))?)",
                    re.IGNORECASE,
                )
                col_match = col_re.match(line)
                if not col_match:
                    continue

                col_name = col_match.group(1)
                original_type = col_match.group(2).strip()
                nullable = "NOT NULL" not in line.upper()
                inferred = self._normalize_type(original_type)

                columns[col_name] = {
                    "inferred_type": inferred,
                    "original_type": original_type,
                    "nullable": nullable,
                }

            if columns:
                result[table_name] = columns

        return result

    # ------------------------------------------------------------------
    @staticmethod
    def _split_values(raw: str) -> List[str]:
        """Split a VALUES tuple string handling quoted commas."""
        vals = []
        current = []
        in_quote = False
        quote_char = None
        for ch in raw:
            if in_quote:
                current.append(ch)
                if ch == quote_char:
                    in_quote = False
            elif ch in ("'", '"'):
                in_quote = True
                quote_char = ch
                current.append(ch)
            elif ch == ",":
                vals.append("".join(current).strip())
                current = []
            else:
                current.append(ch)
        if current:
            vals.append("".join(current).strip())
        return vals

    @staticmethod
    def _cast(val: str):
        val = val.strip()
        if val.upper() == "NULL":
            return None
        if val.startswith("'") and val.endswith("'"):
            return val[1:-1].replace("''", "'")
        try:
            return int(val)
        except ValueError:
            pass
        try:
            return float(val)
        except ValueError:
            pass
        return val

    @staticmethod
    def _normalize_type(raw_type: str) -> str:
        """Map a SQL type like 'VARCHAR(255)' to an internal type like 'string'."""
        # Strip parenthesized precision/length: "DECIMAL(10,2)" → "DECIMAL"
        base = re.sub(r"\(.*\)", "", raw_type).strip().lower()
        # Try exact match first
        if base in DDL_TYPE_MAP:
            return DDL_TYPE_MAP[base]
        # Try prefix match for multi-word types like "double precision"
        for key, val in DDL_TYPE_MAP.items():
            if base.startswith(key):
                return val
        return "string"
