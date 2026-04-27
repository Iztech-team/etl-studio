"""Transform-preset persistence.

Presets are saved as JSON files under data/presets/. Each preset captures
the per-source-table/per-source-column transform configuration the user
built in the Transform stage so it can be re-applied to a different
project that has the same schema (which, for our customer base, is most
of them — they all run the same AlArabi build).

Format on disk:
    data/presets/{preset_id}.json

The schema_signature field is a sorted list of source table names the
preset was originally built against. The frontend uses it to show how
much overlap a preset has with the current project, so the user can
pick the right one.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PRESETS_DIR = Path(__file__).parent / "data" / "presets"


def _ensure_dir() -> None:
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)


def _path(preset_id: str) -> Path:
    return PRESETS_DIR / f"{preset_id}.json"


def list_presets() -> List[Dict[str, Any]]:
    """Return all presets, light fields only (no `edits` body) for
    fast list rendering. The frontend fetches a specific preset by id
    when the user actually applies one."""
    _ensure_dir()
    out: List[Dict[str, Any]] = []
    for f in sorted(PRESETS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            out.append(
                {
                    "id": data.get("id"),
                    "name": data.get("name"),
                    "schema_signature": data.get("schema_signature", []),
                    "table_count": len(data.get("edits", {})),
                    "created_at": data.get("created_at"),
                    "updated_at": data.get("updated_at"),
                }
            )
        except Exception:
            # Skip corrupt files rather than failing the whole list.
            continue
    return out


def get_preset(preset_id: str) -> Optional[Dict[str, Any]]:
    path = _path(preset_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def create_preset(
    name: str,
    table_names: Dict[str, str],
    edits: Dict[str, List[Dict[str, Any]]],
    dropped_tables: Optional[List[str]] = None,
    table_options: Optional[Dict[str, Dict[str, Any]]] = None,
    extra_configs: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    _ensure_dir()
    now = datetime.now(timezone.utc).isoformat()
    preset = {
        "id": str(uuid.uuid4()),
        "name": name,
        "schema_signature": sorted(edits.keys()),
        "table_names": table_names,
        "edits": edits,
        # Optional new fields. Backwards-compatible: presets without them
        # behave exactly as before.
        "dropped_tables": dropped_tables or [],
        "table_options": table_options or {},
        "extra_configs": extra_configs or [],
        "created_at": now,
        "updated_at": now,
    }
    _path(preset["id"]).write_text(
        json.dumps(preset, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return preset


def update_preset(
    preset_id: str,
    name: Optional[str] = None,
    table_names: Optional[Dict[str, str]] = None,
    edits: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    dropped_tables: Optional[List[str]] = None,
    table_options: Optional[Dict[str, Dict[str, Any]]] = None,
    extra_configs: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    existing = get_preset(preset_id)
    if not existing:
        return None
    if name is not None:
        existing["name"] = name
    if table_names is not None:
        existing["table_names"] = table_names
    if edits is not None:
        existing["edits"] = edits
        existing["schema_signature"] = sorted(edits.keys())
    if dropped_tables is not None:
        existing["dropped_tables"] = dropped_tables
    if table_options is not None:
        existing["table_options"] = table_options
    if extra_configs is not None:
        existing["extra_configs"] = extra_configs
    existing["updated_at"] = datetime.now(timezone.utc).isoformat()
    _path(preset_id).write_text(
        json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return existing


def delete_preset(preset_id: str) -> bool:
    path = _path(preset_id)
    if not path.exists():
        return False
    try:
        os.remove(path)
        return True
    except OSError:
        return False
