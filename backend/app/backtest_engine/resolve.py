"""Turns a `strategy_id` (whatever `GET /api/strategies` calls a
strategy's `name`) into a runnable `Strategy` instance — the one place
that needs to know built-ins and saved graphs live in two different
registries, so backtest (this module) and, later, execution (Phase 6)
don't each have to."""
from __future__ import annotations

from app.strategy_engine import Strategy, get_strategy, get_strategy_instance


def resolve_strategy(strategy_id: str) -> Strategy:
    """Built-ins are looked up as a class and instantiated with default
    config (there's no per-request config override in this phase — see
    CLAUDE.md); a saved graph (`"graph:<id>"`) is already a fully
    configured instance, registered at save time or on API startup.
    Raises KeyError if `strategy_id` isn't registered either way."""
    try:
        return get_strategy_instance(strategy_id)
    except KeyError:
        pass

    cls = get_strategy(strategy_id)  # raises KeyError if unknown, propagated as-is
    return cls()
