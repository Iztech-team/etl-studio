from typing import Any, Dict, Optional

from fastapi import HTTPException

_sessions: Dict[str, Dict[str, Any]] = {}


async def get(session_id: str) -> Optional[Dict[str, Any]]:
    return _sessions.get(session_id)


async def require(session_id: str) -> Dict[str, Any]:
    s = _sessions.get(session_id)
    if s is None:
        raise HTTPException(404, "Session not found")
    return s


async def exists(session_id: str) -> bool:
    return session_id in _sessions


async def all_sessions() -> Dict[str, Dict[str, Any]]:
    return _sessions


async def put(session_id: str, session: Dict[str, Any]) -> None:
    _sessions[session_id] = session


async def update(session_id: str, **fields: Any) -> None:
    if session_id in _sessions:
        _sessions[session_id].update(fields)


async def remove(session_id: str) -> None:
    _sessions.pop(session_id, None)
