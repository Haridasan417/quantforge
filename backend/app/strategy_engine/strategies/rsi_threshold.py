"""RSI mean-reversion: buy when RSI drops below an oversold threshold,
sell when it climbs above an overbought one."""
from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, Field, model_validator

from app.data_service.indicators import rsi as compute_rsi
from app.strategy_engine.base_strategy import Position, PositionSide, Signal, SignalAction, Strategy
from app.strategy_engine.registry import register_strategy


class RSIThresholdConfig(BaseModel):
    length: int = Field(14, gt=1, description="RSI lookback period, in bars")
    buy_below: float = Field(30.0, ge=0, le=100, description="Go long when RSI drops below this")
    sell_above: float = Field(70.0, ge=0, le=100, description="Exit when RSI rises above this")

    @model_validator(mode="after")
    def _buy_below_sell(self) -> "RSIThresholdConfig":
        if self.buy_below >= self.sell_above:
            raise ValueError("buy_below must be smaller than sell_above")
        return self


@register_strategy("rsi_threshold")
class RSIThresholdStrategy(Strategy):
    """BUY when RSI < buy_below and we're not already long; SELL when
    RSI > sell_above and we are."""

    @classmethod
    def config_schema(cls) -> type[BaseModel]:
        return RSIThresholdConfig

    def generate_signal(self, df: pd.DataFrame, position: Position) -> Signal:
        # Reuse data_service's rsi() rather than recomputing — one
        # indicator implementation for the whole app (see CLAUDE.md).
        series = compute_rsi(df, length=self.config.length)

        if series.empty or pd.isna(series.iloc[-1]):
            return Signal(action=SignalAction.HOLD, reason="warm-up")

        latest = series.iloc[-1]

        if latest < self.config.buy_below and position.side != PositionSide.LONG:
            return Signal(action=SignalAction.BUY, reason=f"RSI {latest:.1f} < {self.config.buy_below}")
        if latest > self.config.sell_above and position.side == PositionSide.LONG:
            return Signal(action=SignalAction.SELL, reason=f"RSI {latest:.1f} > {self.config.sell_above}")

        return Signal(action=SignalAction.HOLD, reason=f"RSI {latest:.1f} within band")
