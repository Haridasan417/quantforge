"""Runs a QuantForge `Strategy` through backtrader over historical OHLCV
data and reduces the result to the metrics/series the API needs.
`run_backtest` is synchronous and CPU-bound (backtrader has no async
API) — callers on the request path should run it via
`asyncio.to_thread` rather than awaiting it directly, see
`app/api/backtest.py`.
"""
from __future__ import annotations

import backtrader as bt
import pandas as pd

from app.backtest_engine.bridge import StrategyBridge
from app.strategy_engine import Strategy

# Simple, documented defaults rather than a pile of new tunable
# parameters — this is a "run the strategy as-is over history" engine,
# not a portfolio simulator with its own config surface (yet).
INITIAL_CASH = 100_000.0
COMMISSION = 0.001  # 0.1% per fill, backtrader's own examples' usual default
POSITION_SIZE_PERCENT = 95  # go (almost) all-in per BUY; headroom covers commission


class BacktestError(RuntimeError):
    """Raised when there isn't enough data to run a backtest."""


def run_backtest(strategy: Strategy, df: pd.DataFrame) -> dict:
    """`df` is raw OHLCV (open/high/low/close/volume), ascending,
    exactly like `data_service.get_candles_cached` returns. Returns a
    dict shaped for `schemas.backtest.BacktestResponse` (minus the
    request-echo fields the API layer adds)."""
    if df.empty:
        raise BacktestError("No candle data available for the requested symbol/date range")
    if len(df) < 2:
        raise BacktestError("Not enough bars to run a backtest (need at least 2)")

    # backtrader's PandasData feed expects naive datetimes; our candles
    # are UTC-aware (see data_service.sources._localize_to_utc). Bars
    # stay in the same order either way, so this only drops the tz
    # label, not any information the backtest needs.
    feed_df = df.copy()
    if feed_df.index.tz is not None:
        feed_df.index = feed_df.index.tz_localize(None)

    cerebro = bt.Cerebro()
    cerebro.broker.setcash(INITIAL_CASH)
    cerebro.broker.setcommission(commission=COMMISSION)
    cerebro.addsizer(bt.sizers.PercentSizer, percents=POSITION_SIZE_PERCENT, retint=True)
    cerebro.adddata(bt.feeds.PandasData(dataname=feed_df))
    cerebro.addstrategy(StrategyBridge, qf_strategy=strategy, full_df=feed_df)

    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", timeframe=bt.TimeFrame.Days, annualize=True)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")

    results = cerebro.run()
    strat = results[0]

    sharpe = strat.analyzers.sharpe.get_analysis().get("sharperatio")
    drawdown = strat.analyzers.drawdown.get_analysis()
    trade_stats = strat.analyzers.trades.get_analysis()

    max_drawdown_pct = drawdown.get("max", {}).get("drawdown", 0.0) or 0.0
    total_closed = trade_stats.get("total", {}).get("closed", 0) or 0
    won = trade_stats.get("won", {}).get("total", 0) or 0

    return {
        # backtrader reports a sharpe of None when returns have zero
        # variance (e.g. the strategy never traded) rather than 0 —
        # kept as None here (not coerced to 0.0) so the frontend can
        # tell "no trades" apart from "a real Sharpe of zero".
        "sharpe": float(sharpe) if sharpe is not None else None,
        "max_drawdown": float(max_drawdown_pct) / 100,
        "win_rate": (won / total_closed) if total_closed else 0.0,
        "final_equity": float(cerebro.broker.getvalue()),
        "equity_curve": strat.equity_curve,
        "trades": strat.trade_log,
    }
