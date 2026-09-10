from datetime import datetime

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
