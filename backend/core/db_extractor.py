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
    extractors = {
        "sqlite": _extract_sqlite,
        "firebird": _extract_firebird,
        "access": _extract_access,
        "dbase": _extract_dbase,
    }

    extractor = extractors.get(db_type)
    if not extractor:
        raise ValueError(f"Unsupported database type: {db_type}")

    tables = extractor(db_path, password)
    csv_files = []

    for table_name, columns, rows in tables:
        safe_name = table_name.replace("/", "_").replace("\\", "_")
        csv_path = os.path.join(output_dir, f"{safe_name}.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            writer.writerows(rows)
        csv_files.append(f"{safe_name}.csv")

    return csv_files


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
    try:
        import firebird.driver as fdb
    except ImportError:
        try:
            import fdb as fdb_legacy

            return _extract_firebird_legacy(fdb_legacy, db_path, password)
        except ImportError:
            raise ImportError(
                "Firebird support requires 'firebird-driver' or 'fdb' package. "
                "Install with: pip install firebird-driver"
            )

    connect_args: Dict = {"database": db_path}
    if password:
        connect_args["password"] = password
        connect_args["user"] = "SYSDBA"
    else:
        connect_args["user"] = "SYSDBA"
        connect_args["password"] = "masterkey"

    conn = fdb.connect(**connect_args)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT RDB$RELATION_NAME FROM RDB$RELATIONS "
            "WHERE RDB$SYSTEM_FLAG = 0 AND RDB$VIEW_BLF IS NULL"
        )
        table_names = [row[0].strip() for row in cursor.fetchall()]

        results = []
        for table in table_names:
            cursor.execute(
                "SELECT RDB$FIELD_NAME FROM RDB$RELATION_FIELDS "
                "WHERE RDB$RELATION_NAME = ? ORDER BY RDB$FIELD_POSITION",
                (table,),
            )
            columns = [row[0].strip() for row in cursor.fetchall()]

            cursor.execute(f'SELECT * FROM "{table}"')
            rows = cursor.fetchall()
            results.append((table, columns, rows))

        return results
    finally:
        conn.close()


def _extract_firebird_legacy(
    fdb_module, db_path: str, password: Optional[str]
) -> List[tuple]:
    connect_args: Dict = {"dsn": db_path}
    if password:
        connect_args["password"] = password
        connect_args["user"] = "SYSDBA"
    else:
        connect_args["user"] = "SYSDBA"
        connect_args["password"] = "masterkey"

    conn = fdb_module.connect(**connect_args)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT RDB$RELATION_NAME FROM RDB$RELATIONS "
            "WHERE RDB$SYSTEM_FLAG = 0 AND RDB$VIEW_BLF IS NULL"
        )
        table_names = [row[0].strip() for row in cursor.fetchall()]

        results = []
        for table in table_names:
            cursor.execute(
                "SELECT RDB$FIELD_NAME FROM RDB$RELATION_FIELDS "
                "WHERE RDB$RELATION_NAME = ? ORDER BY RDB$FIELD_POSITION",
                (table,),
            )
            columns = [row[0].strip() for row in cursor.fetchall()]

            cursor.execute(f'SELECT * FROM "{table}"')
            rows = cursor.fetchall()
            results.append((table, columns, rows))

        return results
    finally:
        conn.close()


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
