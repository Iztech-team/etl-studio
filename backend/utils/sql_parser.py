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
        # Use string-based parsing to handle backtick names with spaces
        content_upper = self.content.upper()
        pos = 0
        while True:
            idx = content_upper.find("CREATE TABLE", pos)
            if idx == -1:
                break

            search_start = idx + len("CREATE TABLE")
            if_match = re.match(
                r"\s+IF\s+NOT\s+EXISTS\s+", self.content[search_start:], re.IGNORECASE
            )
            if if_match:
                search_start += if_match.end()

            name_match = re.match(
                r"\s*(?:`([^`]+)`|\"([^\"]+)\"|([^\s(]+))\s*\(",
                self.content[search_start:],
            )
            if not name_match:
                pos = idx + 1
                continue

            table = name_match.group(1) or name_match.group(2) or name_match.group(3)
            if table not in tables:
                tables.setdefault(table, [])

            pos = idx + len("CREATE TABLE") + 1

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
                        "nullable": True,
                        "primary_key": False,
                        "unique": False,
                    }
                }
            }

        Also populates self.constraints and self.foreign_keys after parsing.
        """
        result: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self.constraints: Dict[str, Dict[str, Any]] = {}
        self.foreign_keys: List[Dict[str, str]] = []

        content_upper = self.content.upper()
        pos = 0

        while True:
            idx = content_upper.find("CREATE TABLE", pos)
            if idx == -1:
                break

            search_start = idx + len("CREATE TABLE")

            # Skip IF NOT EXISTS if present
            if_match = re.match(
                r"\s+IF\s+NOT\s+EXISTS\s+", self.content[search_start:], re.IGNORECASE
            )
            if if_match:
                search_start += if_match.end()

            # Extract table name (handle backticks with spaces, quotes, or plain)
            name_match = re.match(
                r"\s*(?:`([^`]+)`|\"([^\"]+)\"|([^\s(]+))\s*\(",
                self.content[search_start:],
            )
            if not name_match:
                pos = idx + 1
                continue

            table_name = (
                name_match.group(1) or name_match.group(2) or name_match.group(3)
            )
            paren_start = (
                search_start + name_match.start(0) + name_match.group(0).index("(")
            )

            # Find matching closing parenthesis
            depth = 0
            paren_end = None
            for i in range(paren_start, len(self.content)):
                if self.content[i] == "(":
                    depth += 1
                elif self.content[i] == ")":
                    depth -= 1
                    if depth == 0:
                        paren_end = i
                        break

            if paren_end is None:
                pos = idx + 1
                continue

            body = self.content[paren_start + 1 : paren_end]
            pos = paren_end + 1

            columns: Dict[str, Dict[str, Any]] = {}
            pk_cols: List[str] = []
            unique_sets: List[List[str]] = []

            for line in self._split_ddl_columns(body):
                line = line.strip()
                if not line:
                    continue
                upper = line.upper().lstrip()

                # Table-level PRIMARY KEY (col1, col2)
                pk_match = re.match(
                    r"(?:CONSTRAINT\s+\w+\s+)?PRIMARY\s+KEY\s*\(([^)]+)\)",
                    line,
                    re.IGNORECASE,
                )
                if pk_match:
                    pk_cols.extend(
                        c.strip().strip("`\"'[] ") for c in pk_match.group(1).split(",")
                    )
                    continue

                # Table-level UNIQUE (col1, col2)
                uq_match = re.match(
                    r"(?:CONSTRAINT\s+\w+\s+)?UNIQUE\s*\(([^)]+)\)",
                    line,
                    re.IGNORECASE,
                )
                if uq_match:
                    cols = [
                        c.strip().strip("`\"'[] ") for c in uq_match.group(1).split(",")
                    ]
                    unique_sets.append(cols)
                    continue

                # FOREIGN KEY (col) REFERENCES parent(col)
                fk_match = re.match(
                    r'(?:CONSTRAINT\s+\w+\s+)?FOREIGN\s+KEY\s*\(([^)]+)\)\s*REFERENCES\s+[`"\[\']?(\w+)[`"\]\']?\s*\(([^)]+)\)',
                    line,
                    re.IGNORECASE,
                )
                if fk_match:
                    local_cols = [
                        c.strip().strip("`\"'[] ") for c in fk_match.group(1).split(",")
                    ]
                    ref_table = fk_match.group(2)
                    ref_cols = [
                        c.strip().strip("`\"'[] ") for c in fk_match.group(3).split(",")
                    ]
                    self.foreign_keys.append(
                        {
                            "child_table": table_name,
                            "child_columns": local_cols,
                            "parent_table": ref_table,
                            "parent_columns": ref_cols,
                        }
                    )
                    continue

                # Skip other constraint lines
                if any(
                    upper.startswith(kw)
                    for kw in ("CHECK", "CONSTRAINT", "INDEX", "KEY")
                ):
                    continue

                # Parse column definition
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

                is_pk = bool(re.search(r"\bPRIMARY\s+KEY\b", line, re.IGNORECASE))
                is_unique = bool(re.search(r"\bUNIQUE\b", line, re.IGNORECASE))

                if is_pk:
                    pk_cols.append(col_name)

                # Inline REFERENCES on column
                ref_match = re.search(
                    r'REFERENCES\s+[`"\[\']?(\w+)[`"\]\']?\s*\(([^)]+)\)',
                    line,
                    re.IGNORECASE,
                )
                if ref_match:
                    self.foreign_keys.append(
                        {
                            "child_table": table_name,
                            "child_columns": [col_name],
                            "parent_table": ref_match.group(1),
                            "parent_columns": [
                                ref_match.group(2).strip().strip("`\"'[] ")
                            ],
                        }
                    )

                columns[col_name] = {
                    "inferred_type": inferred,
                    "original_type": original_type,
                    "nullable": nullable,
                    "primary_key": is_pk,
                    "unique": is_unique,
                }

            # Apply table-level PK to column entries
            for col_name in pk_cols:
                if col_name in columns:
                    columns[col_name]["primary_key"] = True

            # Apply table-level UNIQUE to column entries (single-column uniques)
            for uq_set in unique_sets:
                if len(uq_set) == 1 and uq_set[0] in columns:
                    columns[uq_set[0]]["unique"] = True

            if columns:
                result[table_name] = columns
                self.constraints[table_name] = {
                    "primary_key": pk_cols,
                    "unique": unique_sets,
                }

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
