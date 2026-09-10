from app.strategy_engine.base_strategy import Position, PositionSide, Signal, SignalAction, Strategy
from app.strategy_engine.graph_strategy import (
    COMPARATORS,
    INDICATOR_FIELDS,
    GraphStrategy,
    GraphStrategyConfig,
    GraphStrategyError,
)
from app.strategy_engine.registry import (
    get_strategy,
    get_strategy_instance,
    list_strategies,
    list_strategy_instances,
    register_strategy,
    register_strategy_instance,
    unregister_strategy_instance,
)

# Imported for its side effect: every module in `strategies/` registers
# itself with `@register_strategy` when imported. Anything that needs
# the class registry populated (the API layer, tests, the future
# backtest engine) should import from `app.strategy_engine`, not reach
# into `strategy_engine.strategies` directly. GraphStrategy instances
# are registered separately, at runtime (see graph_strategy.py) — this
# import doesn't touch that registry.
from app.strategy_engine import strategies  # noqa: F401,E402

__all__ = [
    "COMPARATORS",
    "INDICATOR_FIELDS",
    "GraphStrategy",
    "GraphStrategyConfig",
    "GraphStrategyError",
    "Position",
    "PositionSide",
    "Signal",
    "SignalAction",
    "Strategy",
    "get_strategy",
    "get_strategy_instance",
    "list_strategies",
    "list_strategy_instances",
    "register_strategy",
    "register_strategy_instance",
    "unregister_strategy_instance",
]
