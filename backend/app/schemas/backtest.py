from datetime import datetime
from typing import Any

from pydantic import BaseModel


class BacktestRequest(BaseModel):
    strategy_id: str
    symbol: str
    start: datetime
    end: datetime
    # Not in the phase brief's literal request shape, but there's no
    # other way to say what granularity to backtest on — defaults to
    # daily bars, same as the Chart page's default interval.
    interval: str = "1d"
    # Also not in the original phase brief's literal shape — added in
    # Phase 7 part B. Overrides a built-in's default config (validated
    # against its own config_schema()); ignored for a saved
    # "graph:<id>" strategy, whose config lives on its saved row
    # instead. Every built-in before RLStrategy had sane defaults for
    # every field, so this went unused until RLStrategy's
    # `checkpoint_name` (no sensible default — which checkpoint to run
    # is never guessable) needed a way to be specified per backtest.
    config: dict[str, Any] | None = None


class EquityPoint(BaseModel):
    ts: str
    equity: float


class TradeMarker(BaseModel):
    ts: str
    side: str
    price: float
    qty: float


class BacktestResponse(BaseModel):
    strategy_id: str
    symbol: str
    interval: str
    sharpe: float | None
    max_drawdown: float
    win_rate: float
    final_equity: float
    equity_curve: list[EquityPoint]
    trades: list[TradeMarker]
