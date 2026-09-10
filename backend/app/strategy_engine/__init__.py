from app.strategy_engine.base_strategy import Position, PositionSide, Signal, SignalAction, Strategy
from app.strategy_engine.registry import get_strategy, list_strategies, register_strategy

# Imported for its side effect: every module in `strategies/` registers
# itself with `@register_strategy` when imported. Anything that needs
# the registry populated (the API layer, tests, the future backtest
# engine) should import from `app.strategy_engine`, not reach into
# `strategy_engine.strategies` directly.
from app.strategy_engine import strategies  # noqa: F401,E402

__all__ = [
    "Position",
    "PositionSide",
    "Signal",
    "SignalAction",
    "Strategy",
    "get_strategy",
    "list_strategies",
    "register_strategy",
]
