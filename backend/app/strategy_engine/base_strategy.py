"""The one interface every strategy — rule-based, walk-forward, RL, or a
saved visual graph from the builder (Phase 4) — implements.

Backtest (Phase 5), live execution (Phase 6), and the builder UI all go
through `Strategy.generate_signal`; nothing outside this package should
need to know which kind of strategy it's actually talking to.
"""
from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd
from pydantic import BaseModel


class PositionSide(str, enum.Enum):
    FLAT = "FLAT"
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass(frozen=True)
class Position:
    """A strategy's view of its current holding in one symbol.

    Deliberately minimal — just enough for a strategy to decide "am I
    already in this trade" without reaching into portfolio/trade
    bookkeeping (that's the Executor's job in Phase 6).
    """

    side: PositionSide = PositionSide.FLAT
    qty: float = 0.0
    avg_price: float = 0.0

    @property
    def is_flat(self) -> bool:
        return self.side is PositionSide.FLAT


class SignalAction(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(frozen=True)
class Signal:
    """A strategy's output for the latest row of `df`.

    `confidence` and `size` are optional so simple rule-based strategies
    can ignore them (defaults mean "fully confident, let the risk
    manager decide sizing") while RL/walk-forward strategies (Phase 7)
    can attach real values without changing the interface.
    """

    action: SignalAction
    confidence: float = 1.0
    size: float | None = None
    reason: str = ""


class Strategy(ABC):
    """Base class for every strategy. Concrete subclasses register
    themselves with `@register_strategy("name")` (see registry.py) and
    are driven entirely by the Pydantic model `config_schema()` returns
    — the Strategy Builder UI (Phase 4) renders a form straight from
    that schema, and this class never needs new hard-coded parameters.
    """

    def __init__(self, config: BaseModel | dict | None = None) -> None:
        schema = self.config_schema()
        if config is None:
            self.config = schema()
        elif isinstance(config, schema):
            self.config = config
        else:
            self.config = schema(**config)

    @classmethod
    @abstractmethod
    def config_schema(cls) -> type[BaseModel]:
        """A Pydantic model describing this strategy's tunable
        parameters (with defaults, bounds, and descriptions) — used both
        to validate `config` here and to build the config form / node
        parameters in the Strategy Builder (Phase 4)."""

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame, position: Position) -> Signal:
        """Decide an action for the *latest* row of `df`.

        `df` is OHLCV data (columns open/high/low/close/volume, indexed
        by timestamp, ascending) up to and including "now" — a strategy
        must only look at data it already has, never at future rows, so
        the same code works unchanged in a backtest and in live
        inference. `position` is the caller's current holding in this
        symbol, so a strategy can avoid signaling BUY when already long,
        etc.
        """
