from fastapi import APIRouter, HTTPException

import persistence.presets as presets_store

router = APIRouter()


@router.get("/transform-presets")
async def list_transform_presets():
    return {"presets": presets_store.list_presets()}


@router.get("/transform-presets/{preset_id}")
async def get_transform_preset(preset_id: str):
    preset = presets_store.get_preset(preset_id)
    if not preset:
        raise HTTPException(404, "Preset not found")
    return preset


@router.post("/transform-presets")
async def create_transform_preset(body: dict):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Preset name is required")
    table_names = body.get("table_names") or {}
    edits = body.get("edits") or {}
    if not isinstance(table_names, dict) or not isinstance(edits, dict):
        raise HTTPException(400, "table_names and edits must be objects")
    return presets_store.create_preset(
        name, table_names, edits,
        dropped_tables=body.get("dropped_tables") or [],
        table_options=body.get("table_options") or {},
        extra_configs=body.get("extra_configs") or [],
    )


@router.put("/transform-presets/{preset_id}")
async def update_transform_preset(preset_id: str, body: dict):
    name = body.get("name")
    table_names = body.get("table_names")
    edits = body.get("edits")
    updated = presets_store.update_preset(
        preset_id,
        name=name.strip() if isinstance(name, str) else None,
        table_names=table_names if isinstance(table_names, dict) else None,
        edits=edits if isinstance(edits, dict) else None,
        dropped_tables=body.get("dropped_tables"),
        table_options=body.get("table_options"),
        extra_configs=body.get("extra_configs"),
    )
    if not updated:
        raise HTTPException(404, "Preset not found")
    return updated


@router.delete("/transform-presets/{preset_id}")
async def delete_transform_preset(preset_id: str):
    if not presets_store.delete_preset(preset_id):
        raise HTTPException(404, "Preset not found")
    return {"ok": True}
