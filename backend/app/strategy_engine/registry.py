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


# ---------------------------------------------------------------------------
# Instance registry
#
# The class registry above is for strategies with one fixed set of
# tunable parameters per *class* (MACrossoverStrategy, RSIThresholdStrategy
# — registered once, at import time, via the decorator). A saved Strategy
# Builder graph (Phase 4) doesn't fit that: each save produces its own
# nodes/edges, so there's one already-configured *instance* per saved
# graph, not a class shared across them. This is a separate registry so
# `list_strategies()` (schemas/config forms) and callers that need an
# actual runnable strategy (backtest, execution) stay decoupled.
# ---------------------------------------------------------------------------

_INSTANCES: dict[str, Strategy] = {}


def register_strategy_instance(name: str, instance: Strategy) -> None:
    """Register an already-configured Strategy *instance* under `name`
    (e.g. `f"graph:{strategy_id}"`) — used for strategies built at
    runtime rather than declared as a class. Overwrites any existing
    instance under the same name, so re-saving/re-loading a graph is
    just calling this again."""
    _INSTANCES[name] = instance


def unregister_strategy_instance(name: str) -> None:
    _INSTANCES.pop(name, None)


def get_strategy_instance(name: str) -> Strategy:
    try:
        return _INSTANCES[name]
    except KeyError:
        raise KeyError(f"No strategy instance registered under {name!r}") from None


def list_strategy_instances() -> dict[str, Strategy]:
    """A copy of the instance registry — see `list_strategies()`."""
    return dict(_INSTANCES)
