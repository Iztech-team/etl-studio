import re
from typing import Any, Dict, List


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
