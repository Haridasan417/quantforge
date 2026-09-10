"""Module-level registry mapping a strategy's short name (used in the
`strategies.type` DB column, API payloads, and Strategy Builder node
types) to its class.

Strategies register themselves via the `@register_strategy("name")`
decorator at import time — see `strategy_engine/strategies/__init__.py`,
which imports every concrete strategy module purely for that side
effect. Nothing here imports `strategies/` itself, so there's no import
cycle between this module and the strategies that use it.
"""
from __future__ import annotations

from app.strategy_engine.base_strategy import Strategy

_REGISTRY: dict[str, type[Strategy]] = {}


def register_strategy(name: str):
    """Class decorator: `@register_strategy("ma_crossover")`."""

    def decorator(cls: type[Strategy]) -> type[Strategy]:
        if name in _REGISTRY and _REGISTRY[name] is not cls:
            raise ValueError(f"Strategy name {name!r} is already registered to {_REGISTRY[name]!r}")
        _REGISTRY[name] = cls
        return cls

    return decorator


def get_strategy(name: str) -> type[Strategy]:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"No strategy registered under {name!r}") from None


def list_strategies() -> dict[str, type[Strategy]]:
    """A copy of the registry — safe for callers to iterate without
    risking a mutation of the real thing."""
    return dict(_REGISTRY)
