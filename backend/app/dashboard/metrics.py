"""Pure P&L / risk metrics computed over the *live* paper-trading
history — actual `PortfolioSnapshot`/`Trade` rows the Executor (Phase 6)
has written — rather than a backtest. Deliberately not backtrader
(unlike `backtest_engine/runner.py`): there's no strategy to replay
here, the equity curve and fills already *are* the ground truth of what
happened, so this is direct arithmetic over already-recorded history,
not a simulation. Every function here is DB-free and takes plain ORM
rows (or nothing), so it's testable without touching Postgres — see
`app/dashboard/queries.py` for the DB reads that feed these.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from app.backtest_engine.runner import INITIAL_CASH
from app.models.portfolio_snapshot import PortfolioSnapshot
from app.models.trade import Trade, TradeSide

# Standard trading-days-per-year annualization factor — same convention
# backtrader's own `SharpeRatio(annualize=True)` uses for daily bars
# (see backtest_engine/runner.py), so a live Sharpe and a backtest
# Sharpe stay on the same scale and are comparable at a glance.
TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class PnLSummary:
    initial_cash: float
    current_equity: float
    cash: float
    total_pnl: float
    total_pnl_pct: float
    holdings: dict[str, Any]


@dataclass(frozen=True)
class LiveMetrics:
    # `None` (not 0.0) means "not enough history yet / zero variance" —
    # same convention as BacktestResponse.sharpe, so the frontend can
    # tell that apart from "a real Sharpe of zero".
    sharpe: float | None
    max_drawdown: float
    win_rate: float
    total_trades: int
    closed_trades: int


def compute_pnl_summary(snapshots: list[PortfolioSnapshot], *, initial_cash: float = INITIAL_CASH) -> PnLSummary:
    """`snapshots` ascending by time (callers: `queries.fetch_portfolio_history`
    already returns them that way) — only the last one (the current
    state) is actually used here. An empty history means no Executor
    fill has ever landed, so P&L is flat at the starting paper cash —
    same `INITIAL_CASH` the Executor itself falls back to when no
    snapshot exists yet (see `executor_service/executor.py`)."""
    if not snapshots:
        return PnLSummary(
            initial_cash=initial_cash,
            current_equity=initial_cash,
            cash=initial_cash,
            total_pnl=0.0,
            total_pnl_pct=0.0,
            holdings={},
        )

    latest = snapshots[-1]
    equity = float(latest.equity)
    pnl = equity - initial_cash
    return PnLSummary(
        initial_cash=initial_cash,
        current_equity=equity,
        cash=float(latest.cash),
        total_pnl=pnl,
        total_pnl_pct=(pnl / initial_cash) if initial_cash else 0.0,
        holdings=latest.holdings or {},
    )


def _sharpe_from_equity_curve(equities: list[float]) -> float | None:
    if len(equities) < 3:
        return None
    returns = [
        (equities[i] - equities[i - 1]) / equities[i - 1] for i in range(1, len(equities)) if equities[i - 1] != 0
    ]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(variance)
    if std == 0:
        return None
    return (mean / std) * math.sqrt(TRADING_DAYS_PER_YEAR)


def _max_drawdown_from_equity_curve(equities: list[float]) -> float:
    """Fraction (0-1) — same units as `BacktestResponse.max_drawdown`."""
    if not equities:
        return 0.0
    peak = equities[0]
    max_dd = 0.0
    for value in equities:
        peak = max(peak, value)
        if peak > 0:
            max_dd = max(max_dd, (peak - value) / peak)
    return max_dd


def _win_rate_from_trades(trades: list[Trade]) -> tuple[float, int]:
    """Pairs each symbol's BUYs with its next SELL, FIFO, chronologically
    — matches the Executor's own position rules (a SELL always closes
    the *whole* held position, see `executor_service/executor.py`'s
    `_apply_fill`), so under normal operation there's at most one open
    BUY per symbol at a time; FIFO pairing is just the defensive general
    case. A round trip "wins" if its exit price beat its entry price
    (quantity is constant across a round trip under those same rules,
    so comparing prices alone is equivalent to comparing P&L). Returns
    `(win_rate, closed_trade_count)`."""
    pending: dict[str, list[Trade]] = {}
    total_closed = 0
    won = 0

    for trade in sorted(trades, key=lambda t: t.executed_at):
        if trade.side == TradeSide.BUY:
            pending.setdefault(trade.symbol, []).append(trade)
        else:  # SELL
            queue = pending.get(trade.symbol)
            if not queue:
                continue  # a SELL with no matching BUY in this window -- can't score it, skip
            entry = queue.pop(0)
            total_closed += 1
            if float(trade.price) > float(entry.price):
                won += 1

    win_rate = (won / total_closed) if total_closed else 0.0
    return win_rate, total_closed


def compute_live_metrics(snapshots: list[PortfolioSnapshot], trades: list[Trade]) -> LiveMetrics:
    """`snapshots`/`trades` both ascending by time (see
    `queries.fetch_portfolio_history`/`fetch_all_trades`)."""
    equities = [float(s.equity) for s in snapshots]
    win_rate, closed = _win_rate_from_trades(trades)
    return LiveMetrics(
        sharpe=_sharpe_from_equity_curve(equities),
        max_drawdown=_max_drawdown_from_equity_curve(equities),
        win_rate=win_rate,
        total_trades=len(trades),
        closed_trades=closed,
    )
