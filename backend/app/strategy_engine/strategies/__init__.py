"""Importing this package registers every built-in strategy (each module
below calls `@register_strategy(...)` at import time) — nothing else in
the app should need to import a strategy module directly."""
from app.strategy_engine.strategies.ma_crossover import MACrossoverStrategy
from app.strategy_engine.strategies.rsi_threshold import RSIThresholdStrategy

__all__ = ["MACrossoverStrategy", "RSIThresholdStrategy"]
