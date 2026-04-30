from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.strategies import get_strategy, list_strategies
from helpers import _auto_save
from state import session_store

router = APIRouter()


class StrategySelection(BaseModel):
    strategy_name: str
    config: dict[str, Any] = {}


@router.get("/strategies")
async def get_strategies():
    """List available transform strategies and their config schemas."""
    return {"strategies": list_strategies()}


@router.get("/strategies/{session_id}")
async def get_session_strategy(session_id: str):
    """Return the strategy + config currently selected for a session."""
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    s = await session_store.require(session_id)
    return {
        "strategy_name": s.get("strategy_name"),
        "config": s.get("strategy_config") or {},
    }


@router.post("/strategies/{session_id}")
async def set_session_strategy(session_id: str, body: StrategySelection):
    """Persist the chosen strategy + config on the session.

    Validates that the strategy exists; config schema enforcement is the
    strategy's own job during transform.
    """
    if not await session_store.exists(session_id):
        raise HTTPException(404, "Session not found")
    try:
        get_strategy(body.strategy_name)
    except KeyError as exc:
        raise HTTPException(400, str(exc)) from exc
    s = await session_store.require(session_id)
    s["strategy_name"] = body.strategy_name
    s["strategy_config"] = body.config
    await _auto_save(session_id, s.get("phase") or "configure")
    return {"ok": True, "strategy_name": body.strategy_name, "config": body.config}
