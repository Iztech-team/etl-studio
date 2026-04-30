from typing import Any, Dict, Optional

_extraction_states: Dict[str, Dict[str, Any]] = {}


async def get(session_id: str) -> Optional[Dict[str, Any]]:
    return _extraction_states.get(session_id)


async def all_states() -> Dict[str, Dict[str, Any]]:
    return _extraction_states


async def put(session_id: str, state: Dict[str, Any]) -> None:
    _extraction_states[session_id] = state


async def update(session_id: str, **fields: Any) -> None:
    if session_id in _extraction_states:
        _extraction_states[session_id].update(fields)


async def remove(session_id: str) -> None:
    _extraction_states.pop(session_id, None)
