"""Extract-cache: persist parsed CSV rows so resume doesn't re-parse 1 GB+
on every page open, AND so resume itself is metadata-only.

The cache is split into two parts:

  extract_cache_meta.json   — schema, stats, preview, ddl_schema, table list.
                              Small (KB to low-MB even for 135-table projects).
                              Loaded synchronously on every resume.

  extract_cache_rows/<TABLE>.pkl — one pickle per table holding that table's
                                   row dicts. Loaded lazily, per-table, only
                                   when an endpoint actually needs the rows
                                   (transform, table-data view, etc).

  extract_cache.sig.json    — file fingerprint of `uploads/`. The cache is
                              considered fresh iff the live signature equals
                              the saved one.

This means resume responds in metadata-load time (<100 ms typical) regardless
of whether the underlying CSVs are 50 MB or 5 GB. Heavy work is deferred until
the user actually triggers it.
"""

from __future__ import annotations

import json
import os
import pickle
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _project_root(project_id: str) -> Path:
    return DATA_DIR / "projects" / project_id


def cache_meta_path(project_id: str) -> Path:
    return _project_root(project_id) / "extract_cache_meta.json"


def cache_rows_dir(project_id: str) -> Path:
    return _project_root(project_id) / "extract_cache_rows"


def cache_table_path(project_id: str, table: str) -> Path:
    return cache_rows_dir(project_id) / f"{_safe(table)}.pkl"


def cache_table_path_jsonl(project_id: str, table: str) -> Path:
    return cache_rows_dir(project_id) / f"{_safe(table)}.jsonl"


def signature_path(project_id: str) -> Path:
    return _project_root(project_id) / "extract_cache.sig.json"


def _safe(name: str) -> str:
    """Make `name` safe to use as a filename. Tables with names like
    'Sales/2026' would otherwise create directories."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)


def _signature(uploads_dir: str) -> Dict[str, Any]:
    files = []
    if os.path.isdir(uploads_dir):
        for f in sorted(os.listdir(uploads_dir)):
            full = os.path.join(uploads_dir, f)
            if os.path.isfile(full):
                files.append([f, os.path.getsize(full), os.path.getmtime(full)])
    return {"files": files}


def is_fresh(project_id: str, uploads_dir: str) -> bool:
    """Cache is fresh when (a) the signature matches the live uploads dir
    AND (b) the metadata file is on disk. We don't validate every per-table
    pickle here — they're checked lazily on read_table_rows."""
    sig = signature_path(project_id)
    meta = cache_meta_path(project_id)
    if not (sig.exists() and meta.exists()):
        return False
    try:
        saved = json.loads(sig.read_text(encoding="utf-8"))
        return saved == _signature(uploads_dir)
    except Exception:
        return False


def write(project_id: str, raw: Dict[str, Any], uploads_dir: str) -> None:
    """Persist the parsed extraction. Metadata as JSON (so it can be
    introspected); rows as one pickle per table (so per-table lazy load
    is cheap). Best-effort: failures are swallowed by the caller so a
    cache write can never break a real request."""
    meta_path = cache_meta_path(project_id)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    rows_dir = cache_rows_dir(project_id)
    rows_dir.mkdir(parents=True, exist_ok=True)

    tables = raw.get("tables", {}) or {}
    table_names = list(tables.keys())

    meta = {
        "version": 2,
        "schema": raw.get("schema", {}),
        "stats": raw.get("stats", {}),
        "preview": raw.get("preview", {}),
        "ddl_schema": raw.get("ddl_schema", {}),
        "all_table_names": table_names,
    }

    # Write metadata atomically: temp file + rename.
    meta_tmp = meta_path.with_suffix(".json.tmp")
    meta_tmp.write_text(
        json.dumps(meta, ensure_ascii=False, default=str), encoding="utf-8"
    )
    os.replace(meta_tmp, meta_path)

    # Per-table row persistence has two paths:
    #   - JSONL staging files exist on disk (CSV streamed-extract path).
    #     Move them to the cache dir; rows never need to enter Python's
    #     memory just to be re-pickled.
    #   - Rows are in `tables[name]` (Excel/SQL paths). Pickle them as
    #     before.
    staged_rows = raw.get("staged_rows") or {}
    for tname in table_names:
        rows = tables.get(tname) or []
        staged_path = staged_rows.get(tname)
        if staged_path and os.path.exists(staged_path):
            dest = cache_table_path_jsonl(project_id, tname)
            tmp = dest.with_suffix(".jsonl.tmp")
            shutil.move(staged_path, tmp)
            os.replace(tmp, dest)
            continue
        path = cache_table_path(project_id, tname)
        tmp = path.with_suffix(".pkl.tmp")
        with tmp.open("wb") as f:
            pickle.dump(rows, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, path)
    # Sweep stray rows files from a prior write that aren't in this set.
    keep = {f"{_safe(t)}.pkl" for t in table_names} | {
        f"{_safe(t)}.jsonl" for t in table_names
    }
    for p in list(rows_dir.glob("*.pkl")) + list(rows_dir.glob("*.jsonl")):
        if p.name not in keep:
            try:
                p.unlink()
            except OSError:
                pass

    # Signature LAST so that a partial cache (meta written, rows partial)
    # never appears fresh on the next read.
    signature_path(project_id).write_text(
        json.dumps(_signature(uploads_dir)), encoding="utf-8"
    )


def read_meta(project_id: str) -> Dict[str, Any]:
    """Return metadata only — schema, stats, preview, ddl_schema, table
    names. Fast (KB-MB JSON parse) and the only thing resume needs."""
    return json.loads(cache_meta_path(project_id).read_text(encoding="utf-8"))


def read_table_rows(project_id: str, table: str) -> Optional[List[Dict[str, Any]]]:
    """Lazily load one table's rows from disk.

    Prefers the JSONL form (written by the streaming CSV path) and
    falls back to the legacy pickle form (Excel / SQL extraction or
    older caches). Returns None if neither exists.
    """
    jsonl = cache_table_path_jsonl(project_id, table)
    if jsonl.exists():
        try:
            with jsonl.open("r", encoding="utf-8") as f:
                return [json.loads(line) for line in f if line.strip()]
        except Exception:
            pass
    pkl = cache_table_path(project_id, table)
    if not pkl.exists():
        return None
    try:
        with pkl.open("rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def read_all_rows(project_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """Load every table's rows. Slow path — use only when the caller
    actually needs the full dataset (e.g. /api/transform). Prefer
    read_table_rows when you only need one table."""
    meta = read_meta(project_id)
    out: Dict[str, List[Dict[str, Any]]] = {}
    for name in meta.get("all_table_names", []):
        rows = read_table_rows(project_id, name)
        if rows is not None:
            out[name] = rows
    return out


def read(project_id: str) -> Dict[str, Any]:
    """Backwards-compatible: return the same shape `Extractor.extract_all`
    would. Loads ALL rows; prefer `read_meta` + lazy `read_table_rows`
    when you don't need the full row set."""
    meta = read_meta(project_id)
    return {
        "tables": read_all_rows(project_id),
        "schema": meta.get("schema", {}),
        "stats": meta.get("stats", {}),
        "preview": meta.get("preview", {}),
        "ddl_schema": meta.get("ddl_schema", {}),
    }


def invalidate(project_id: str) -> None:
    """Delete cache files. Idempotent."""
    for p in (cache_meta_path(project_id), signature_path(project_id)):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    rows_dir = cache_rows_dir(project_id)
    if rows_dir.exists():
        for p in rows_dir.glob("*.pkl"):
            try:
                p.unlink()
            except OSError:
                pass
        try:
            rows_dir.rmdir()
        except OSError:
            pass
