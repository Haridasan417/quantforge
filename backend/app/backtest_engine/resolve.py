"""Turns a `strategy_id` (whatever `GET /api/strategies` calls a
strategy's `name`) into a runnable `Strategy` instance — the one place
that needs to know built-ins and saved graphs live in two different
registries, so backtest (this module) and, later, execution (Phase 6)
don't each have to."""
from __future__ import annotations

from typing import Any

from app.strategy_engine import Strategy, get_strategy, get_strategy_instance


def resolve_strategy(strategy_id: str, config: dict[str, Any] | None = None) -> Strategy:
    """Built-ins are looked up as a class and instantiated with
    `config` (validated against that class's `config_schema()` —
    `Strategy.__init__` already falls back to schema defaults for any
    field `config` doesn't set, and to an all-defaults instance if
    `config` is `None` entirely). `config` is ignored for a saved graph
    (`"graph:<id>"`) — that's already a fully configured instance,
    registered at save time or on API startup, and a graph's config
    lives on its own saved row rather than being overridden per-request.

    `config` started out unused here (every early built-in — MA
    crossover, RSI threshold, walk-forward — has sane defaults for
    every field, so `cls()` alone was enough); `RLStrategy` (Phase 7
    part B) is the first built-in with a field that has no sensible
    default (`checkpoint_name` — which checkpoint to run is never a
    guessable default), which is what this parameter exists for.

    Raises KeyError if `strategy_id` isn't registered either way, or
    `pydantic.ValidationError` if `config` doesn't validate against a
    built-in's schema (`api/backtest.py` turns that into a 422)."""
    try:
        return get_strategy_instance(strategy_id)
    except KeyError:
        pass

    cls = get_strategy(strategy_id)  # raises KeyError if unknown, propagated as-is
    return cls(config)
