from typing import Any

from core.strategies.base import StrategyResult, TransformStrategy
from core.strategies.erpnext_mirror import ErpnextMirrorStrategy
from core.strategies.erpnext_native import ErpnextNativeStrategy

_STRATEGIES: dict[str, type[TransformStrategy]] = {
    ErpnextMirrorStrategy.name: ErpnextMirrorStrategy,
    ErpnextNativeStrategy.name: ErpnextNativeStrategy,
}


def get_strategy(name: str) -> TransformStrategy:
    cls = _STRATEGIES.get(name)
    if cls is None:
        known = ", ".join(_STRATEGIES) or "(none registered)"
        raise KeyError(f"Unknown strategy '{name}'. Known: {known}")
    return cls()


def list_strategies() -> list[dict[str, Any]]:
    return [_describe(cls) for cls in _STRATEGIES.values()]


def default_strategy_name() -> str:
    return next(iter(_STRATEGIES))


def _describe(cls: type[TransformStrategy]) -> dict[str, Any]:
    return {
        "name": cls.name,
        "label": cls.label,
        "description": cls.description,
        "config_schema": cls.config_schema,
        "tier": getattr(cls, "tier", ""),
        "kind": getattr(cls, "kind", "GENERIC"),
        "stats": getattr(cls, "stats", {}),
    }


__all__ = [
    "StrategyResult",
    "TransformStrategy",
    "default_strategy_name",
    "get_strategy",
    "list_strategies",
]
