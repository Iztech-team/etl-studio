"""Extract InterBase / Firebird .IB tables via the bundled isql.exe.

We invoke isql as a subprocess instead of using a Python driver
(firebird-driver / fdb) because those drivers require fbclient.dll on
the host and fail on IB 2009's wire protocol. isql.exe ships with
InterBase itself, so it works unconditionally — we pay one subprocess
per table for isolation.

Decoding: the source database is declared CHARACTER SET NONE but its
bytes are actually Windows-1256 (Arabic). isql gives us raw bytes via
SET LIST ON; we decode in Python with cp1256 (overridable per column).
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_DEFAULT_ISQL_PATHS = (
    r"C:\Program Files\Embarcadero\InterBase\bin\isql.exe",
    r"C:\Program Files (x86)\Embarcadero\InterBase\bin\isql.exe",
    r"C:\Program Files\Borland\InterBase\bin\isql.exe",
    r"C:\Program Files (x86)\Borland\InterBase\bin\isql.exe",
    r"C:\CodeGear\InterBase\bin\isql.exe",
    r"C:\CodeGear\InterBase (x86)\bin\isql.exe",
)

_LIST_FIELD_RE = re.compile(rb"^(\S+)\s+(.*?)\s*$")


def _find_isql() -> str:
    explicit = os.environ.get("ISQL_PATH")
    if explicit:
        if not Path(explicit).exists():
            raise FileNotFoundError(
                f"ISQL_PATH env var points to {explicit!r} but no file is there."
            )
        return explicit
    for candidate in _DEFAULT_ISQL_PATHS:
        if Path(candidate).exists():
            return candidate
    raise FileNotFoundError(
        "isql.exe not found. Install InterBase or set the ISQL_PATH env var "
        "to the full path of isql.exe (typically "
        r"C:\Program Files\Embarcadero\InterBase\bin\isql.exe)."
    )


def _run_script(
    isql_path: str,
    db_path: str,
    user: str,
    password: str,
    sql_body: str,
    output_file: Optional[Path] = None,
    timeout: int = 300,
) -> Tuple[bytes, bytes, int]:
    """Run a SQL script through isql and return (stdout, stderr, returncode).

    isql's -user/-password flags are honoured inconsistently on IB 2009,
    and stdin-piped input doesn't auto-attach. A temp script file with an
    inline CONNECT is the most reliable pattern.
    """
    pw = password.replace("'", "''")
    db_escaped = db_path.replace("'", "''")

    lines = [f"CONNECT '{db_escaped}' USER '{user}' PASSWORD '{pw}';"]
    if output_file is not None:
        out_escaped = str(output_file).replace("'", "''")
        lines.append(f"OUTPUT '{out_escaped}';")
    lines.append(sql_body.rstrip())
    if output_file is not None:
        lines.append("OUTPUT;")
    lines.append("EXIT;")
    script = "\n".join(lines) + "\n"

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".sql", delete=False, encoding="cp1256"
    ) as f:
        f.write(script)
        script_path = f.name
    try:
        result = subprocess.run(
            [isql_path, "-i", script_path],
            capture_output=True,
            timeout=timeout,
        )
        return result.stdout, result.stderr, result.returncode
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


def _script_failed(stdout: bytes, stderr: bytes, code: int) -> str:
    """Return a short failure message if the script errored, else ''."""
    if code != 0:
        return (
            f"isql exited {code}: "
            f"{stderr.decode('cp1256', errors='replace').strip()}"
        )
    combined = (stdout + stderr).decode("cp1256", errors="replace")
    if "Statement failed" in combined or "SQLCODE = -" in combined:
        for line in combined.splitlines():
            if "Statement failed" in line or "SQLCODE" in line:
                return line.strip()
        return combined[:200]
    return ""


def _list_user_tables(
    isql_path: str, db_path: str, user: str, password: str, scratch_dir: Path
) -> List[str]:
    tables_file = scratch_dir / "_ib_tables.txt"
    if tables_file.exists():
        tables_file.unlink()
    out, err, code = _run_script(
        isql_path,
        db_path,
        user,
        password,
        "SET LIST ON;\n"
        "SELECT RDB$RELATION_NAME AS NAME FROM RDB$RELATIONS\n"
        "  WHERE RDB$SYSTEM_FLAG = 0 AND RDB$VIEW_BLR IS NULL\n"
        "  ORDER BY RDB$RELATION_NAME;",
        output_file=tables_file,
    )
    msg = _script_failed(out, err, code)
    if msg:
        raise RuntimeError(f"Failed to list tables: {msg}")
    names: List[str] = []
    if tables_file.exists():
        data = tables_file.read_bytes()
        for line in data.split(b"\r\n"):
            line = line.strip()
            if not line:
                continue
            m = re.match(rb"^NAME\s+(\S+)\s*$", line)
            if m:
                names.append(m.group(1).decode("ascii", errors="replace"))
        try:
            tables_file.unlink()
        except OSError:
            pass
    return names


def _parse_list_records(data: bytes) -> List[Dict[str, Optional[bytes]]]:
    """Parse isql SET LIST ON output into [{field_name: raw_bytes_or_None}, ...].

    Format:
        FIELD_NAME<padding><value>\r\n
        FIELD_NAME<padding><value>\r\n
        \r\n           <-- record separator
        ...

    NULL arrives as the literal string '<null>' and becomes None.
    """
    records: List[Dict[str, Optional[bytes]]] = []
    current: Dict[str, Optional[bytes]] = {}
    for line in data.split(b"\r\n"):
        if not line.strip():
            if current:
                records.append(current)
                current = {}
            continue
        m = _LIST_FIELD_RE.match(line)
        if not m:
            continue
        name = m.group(1).decode("ascii", errors="replace")
        value = m.group(2)
        if value == b"<null>":
            current[name] = None
        else:
            current[name] = bytes(value)
    if current:
        records.append(current)
    return records


def _decode_value(
    val: Optional[bytes],
    col_key: str,
    default_enc: str,
    overrides: Dict[str, str],
) -> Optional[str]:
    if val is None:
        return None
    enc = overrides.get(col_key.upper(), default_enc)
    return bytes(val).decode(enc, errors="replace")


def extract_ib_tables_iter(
    db_path: str,
    password: Optional[str] = None,
    user: Optional[str] = None,
    source_encoding: Optional[str] = None,
    charset_overrides: Optional[Dict[str, str]] = None,
):
    """Generator version of extract_ib_tables.

    Yields (event_type, payload) tuples so callers can surface progress.
    Event types:
      'listing'     payload={}                        about to list tables
      'start'       payload={'tables': [...]}         tables enumerated
      'table_done'  payload={'name': str,
                             'rows': int,
                             'index': int (1-based),
                             'total': int,
                             'columns': List[str],
                             'data': List[Tuple]}     one table finished;
                                                      callers can write a CSV
                                                      immediately from columns+data
      'done'        payload={}                        all tables done
    """
    isql_path = _find_isql()
    user = user or os.environ.get("IB_USER", "SYSDBA")
    env_pw = os.environ.get("IB_PASSWORD")
    pw = password or env_pw or "masterkey"
    pw_source = (
        "form"
        if password
        else "IB_PASSWORD env var" if env_pw else "default 'masterkey'"
    )
    default_enc = source_encoding or os.environ.get("IB_SOURCE_ENCODING", "cp1256")
    overrides = {k.upper(): v for k, v in (charset_overrides or {}).items()}

    scratch = Path(db_path).parent
    yield "listing", {}
    try:
        tables = _list_user_tables(isql_path, db_path, user, pw, scratch)
    except RuntimeError as e:
        if "-902" in str(e) and pw_source == "default 'masterkey'":
            raise RuntimeError(
                f"{e}. No password was supplied — fell back to 'masterkey', "
                "which this database rejects. Enter the InterBase password "
                "in the upload form, or set IB_PASSWORD as an environment "
                "variable before starting the backend."
            ) from None
        raise

    yield "start", {"tables": tables}

    results: List[Tuple[str, List[str], List[Tuple]]] = []
    total = len(tables)
    for i, table in enumerate(tables, start=1):
        raw_path = scratch / f"_ib_{table}.raw"
        if raw_path.exists():
            raw_path.unlink()
        sql = (
            "SET NAMES NONE;\n"
            "SET LIST ON;\n"
            "SET BLOBDISPLAY ALL;\n"
            f'SELECT * FROM "{table}";'
        )
        out, err, code = _run_script(
            isql_path, db_path, user, pw, sql, output_file=raw_path
        )
        msg = _script_failed(out, err, code)
        if msg:
            try:
                if raw_path.exists():
                    raw_path.unlink()
            except OSError:
                pass
            raise RuntimeError(f"Failed to extract table {table}: {msg}")

        if not raw_path.exists():
            results.append((table, [], []))
            yield "table_done", {
                "name": table,
                "rows": 0,
                "index": i,
                "total": total,
                "columns": [],
                "data": [],
            }
            continue

        records = _parse_list_records(raw_path.read_bytes())
        try:
            raw_path.unlink()
        except OSError:
            pass

        if not records:
            results.append((table, [], []))
            yield "table_done", {
                "name": table,
                "rows": 0,
                "index": i,
                "total": total,
                "columns": [],
                "data": [],
            }
            continue

        cols = list(records[0].keys())
        seen = set(cols)
        for r in records[1:]:
            for k in r:
                if k not in seen:
                    cols.append(k)
                    seen.add(k)

        rows: List[Tuple] = []
        for r in records:
            rows.append(
                tuple(
                    _decode_value(r.get(c), f"{table}.{c}", default_enc, overrides)
                    for c in cols
                )
            )
        results.append((table, cols, rows))
        yield "table_done", {
            "name": table,
            "rows": len(rows),
            "index": i,
            "total": total,
            "columns": cols,
            "data": rows,
        }

    yield "done", {}


def extract_ib_tables(
    db_path: str,
    password: Optional[str] = None,
    user: Optional[str] = None,
    source_encoding: Optional[str] = None,
    charset_overrides: Optional[Dict[str, str]] = None,
) -> List[Tuple[str, List[str], List[Tuple]]]:
    """Synchronous wrapper around extract_ib_tables_iter.

    Drains the generator and returns the final results list. Use the
    iter version directly when you want to stream progress events.
    """
    results: List[Tuple[str, List[str], List[Tuple]]] = []
    for event_type, payload in extract_ib_tables_iter(
        db_path, password, user, source_encoding, charset_overrides
    ):
        if event_type == "table_done":
            results.append((payload["name"], payload["columns"], payload["data"]))
    return results
