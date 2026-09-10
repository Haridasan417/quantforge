from typing import Any

from pydantic import BaseModel


class PnLSummarySchema(BaseModel):
    initial_cash: float
    current_equity: float
    cash: float
    total_pnl: float
    total_pnl_pct: float
    holdings: dict[str, Any]


class LiveMetricsSchema(BaseModel):
    sharpe: float | None
    max_drawdown: float
    win_rate: float
    total_trades: int
    closed_trades: int


class EquityCurvePoint(BaseModel):
    ts: str
    equity: float


class DashboardOverviewResponse(BaseModel):
    pnl: PnLSummarySchema
    metrics: LiveMetricsSchema
    equity_curve: list[EquityCurvePoint]


class TradeLogEntry(BaseModel):
    id: int
    strategy_id: int
    symbol: str
    side: str
    qty: float
    price: float
    executed_at: str


class TradeLogResponse(BaseModel):
    trades: list[TradeLogEntry]
