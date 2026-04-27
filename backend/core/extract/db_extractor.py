"""
Extract tables from database files into CSV files.

Supported formats:
  - SQLite (.sqlite, .sqlite3, .db)
  - Firebird / Interbase (.fdb, .gdb, .ib)
  - MS Access (.mdb, .accdb)
  - dBase (.dbf)
"""

import csv
import os
import sqlite3
from typing import Dict, List, Optional


def extract_db_to_csvs(
    db_path: str,
    db_type: str,
    output_dir: str,
    password: Optional[str] = None,
) -> List[str]:
    """
    Open a database file, read all user tables, and write each as a CSV
    in output_dir. Returns list of created CSV filenames.
    """
    csv_files: List[str] = []
    for event_type, payload in extract_db_to_csvs_iter(
        db_path, db_type, output_dir, password
    ):
        if event_type == "done":
            csv_files = payload["csv_files"]
    return csv_files


def extract_db_to_csvs_iter(
    db_path: str,
    db_type: str,
    output_dir: str,
    password: Optional[str] = None,
):
    """Generator version that yields progress events while extracting.

    Event shapes:
      ('listing', {})                                 about to enumerate tables
      ('start',   {'tables': [...]})                  table list known
      ('table_done', {'name', 'rows', 'index', 'total', 'csv'})
                                                      one table written to disk
      ('done',    {'csv_files': [...]})               final list of csv names
    """
    if db_type == "firebird":
        yield from _iter_firebird_to_csvs(db_path, output_dir, password)
        return

    extractors = {
        "sqlite": _extract_sqlite,
        "access": _extract_access,
        "dbase": _extract_dbase,
    }
    extractor = extractors.get(db_type)
    if not extractor:
        raise ValueError(f"Unsupported database type: {db_type}")

    yield "listing", {}
    tables = extractor(db_path, password)
    table_names = [t[0] for t in tables]
    yield "start", {"tables": table_names}

    csv_files: List[str] = []
    total = len(tables)
    for i, (table_name, columns, rows) in enumerate(tables, start=1):
        safe_name = table_name.replace("/", "_").replace("\\", "_")
        csv_name = f"{safe_name}.csv"
        csv_path = os.path.join(output_dir, csv_name)
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            writer.writerows(rows)
        csv_files.append(csv_name)
        yield "table_done", {
            "name": table_name,
            "rows": len(rows) if hasattr(rows, "__len__") else 0,
            "index": i,
            "total": total,
            "csv": csv_name,
        }

    yield "done", {"csv_files": csv_files}


def _iter_firebird_to_csvs(db_path: str, output_dir: str, password: Optional[str]):
    """Stream IB extraction events through, writing each table's CSV
    as it lands. Strips the heavy 'columns'/'data' fields from
    'table_done' events before forwarding so they stay JSON-light.
    """
    from core.extract.ib_isql_extract import extract_ib_tables_iter

    csv_files: List[str] = []
    for event_type, payload in extract_ib_tables_iter(db_path, password=password):
        if event_type == "table_done":
            table_name = payload["name"]
            columns = payload["columns"]
            data = payload["data"]
            safe_name = table_name.replace("/", "_").replace("\\", "_")
            csv_name = f"{safe_name}.csv"
            csv_path = os.path.join(output_dir, csv_name)
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if columns:
                    writer.writerow(columns)
                writer.writerows(data)
            csv_files.append(csv_name)
            yield "table_done", {
                "name": table_name,
                "rows": payload["rows"],
                "index": payload["index"],
                "total": payload["total"],
                "csv": csv_name,
            }
        elif event_type == "done":
            yield "done", {"csv_files": csv_files}
            return
        else:
            yield event_type, payload
    yield "done", {"csv_files": csv_files}


def _extract_sqlite(db_path: str, password: Optional[str] = None) -> List[tuple]:
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        table_names = [row[0] for row in cursor.fetchall()]

        results = []
        for table in table_names:
            cursor.execute(f"PRAGMA table_info([{table}])")
            columns = [row[1] for row in cursor.fetchall()]

            cursor.execute(f"SELECT * FROM [{table}]")
            rows = cursor.fetchall()
            results.append((table, columns, rows))

        return results
    finally:
        conn.close()


def _extract_firebird(db_path: str, password: Optional[str] = None) -> List[tuple]:
    """Extract every user table from a Firebird/InterBase .IB file.

    Uses isql.exe as a subprocess instead of a Python driver — drivers
    need fbclient.dll, which isn't available on most hosts and fails on
    IB 2009's wire protocol. See core/ib_isql_extract.py for details.
    """
    from core.extract.ib_isql_extract import extract_ib_tables

    return extract_ib_tables(db_path, password=password)


def _extract_access(db_path: str, password: Optional[str] = None) -> List[tuple]:
    try:
        import pyodbc
    except ImportError:
        raise ImportError(
            "MS Access support requires 'pyodbc' package. "
            "Install with: pip install pyodbc"
        )

    conn_str = f"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={db_path};"
    if password:
        conn_str += f"PWD={password};"

    conn = pyodbc.connect(conn_str)
    try:
        cursor = conn.cursor()
        table_names = [
            row.table_name
            for row in cursor.tables(tableType="TABLE")
            if not row.table_name.startswith("MSys")
        ]

        results = []
        for table in table_names:
            cursor.execute(f"SELECT * FROM [{table}]")
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            results.append((table, columns, [tuple(row) for row in rows]))

        return results
    finally:
        conn.close()


def _extract_dbase(db_path: str, password: Optional[str] = None) -> List[tuple]:
    try:
        from dbfread import DBF
    except ImportError:
        raise ImportError(
            "dBase support requires 'dbfread' package. "
            "Install with: pip install dbfread"
        )

    table_name = os.path.splitext(os.path.basename(db_path))[0]
    dbf = DBF(db_path, encoding="utf-8", ignore_missing_memofile=True)
    columns = dbf.field_names
    rows = [tuple(record[col] for col in columns) for record in dbf]

    return [(table_name, columns, rows)]
