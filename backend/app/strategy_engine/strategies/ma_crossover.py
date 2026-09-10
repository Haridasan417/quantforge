"""Fast/slow moving-average crossover — the textbook trend-following
rule: go long when the fast MA crosses above the slow MA, exit when it
crosses back below."""
from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, Field, model_validator

from app.strategy_engine.base_strategy import Position, PositionSide, Signal, SignalAction, Strategy
from app.strategy_engine.registry import register_strategy


class MACrossoverConfig(BaseModel):
    fast_period: int = Field(10, gt=0, description="Fast moving-average window, in bars")
    slow_period: int = Field(30, gt=0, description="Slow moving-average window, in bars")

    @model_validator(mode="after")
    def _fast_below_slow(self) -> "MACrossoverConfig":
        if self.fast_period >= self.slow_period:
            raise ValueError("fast_period must be smaller than slow_period")
        return self


@register_strategy("ma_crossover")
class MACrossoverStrategy(Strategy):
    """BUY when the fast MA crosses above the slow MA and we're not
    already long; SELL when it crosses back below and we are."""

    @classmethod
    def config_schema(cls) -> type[BaseModel]:
        return MACrossoverConfig

    def generate_signal(self, df: pd.DataFrame, position: Position) -> Signal:
        fast_period = self.config.fast_period
        slow_period = self.config.slow_period

        if len(df) < slow_period + 1:
            return Signal(action=SignalAction.HOLD, reason="insufficient data for slow MA")

        fast = df["close"].rolling(fast_period).mean()
        slow = df["close"].rolling(slow_period).mean()

        prev_fast, prev_slow = fast.iloc[-2], slow.iloc[-2]
        curr_fast, curr_slow = fast.iloc[-1], slow.iloc[-1]

        if pd.isna(prev_fast) or pd.isna(prev_slow) or pd.isna(curr_fast) or pd.isna(curr_slow):
            return Signal(action=SignalAction.HOLD, reason="warm-up")

        crossed_up = prev_fast <= prev_slow and curr_fast > curr_slow
        crossed_down = prev_fast >= prev_slow and curr_fast < curr_slow

        if crossed_up and position.side != PositionSide.LONG:
            return Signal(action=SignalAction.BUY, reason="fast MA crossed above slow MA")
        if crossed_down and position.side == PositionSide.LONG:
            return Signal(action=SignalAction.SELL, reason="fast MA crossed below slow MA")

        return Signal(action=SignalAction.HOLD, reason="no new crossover")
