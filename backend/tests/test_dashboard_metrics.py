"""app.dashboard.metrics (Phase 8) — pure functions over plain
PortfolioSnapshot/Trade rows, no DB involved (see test_api_dashboard.py
for the endpoint-level tests, which monkeypatch app.dashboard.queries
instead)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.dashboard.metrics import compute_live_metrics, compute_pnl_summary
from app.models.portfolio_snapshot import PortfolioSnapshot
from app.models.trade import Trade, TradeSide

_T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _snapshot(days: int, equity: float, cash: float | None = None, holdings: dict | None = None) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        timestamp=_T0 + timedelta(days=days),
        cash=Decimal(str(cash if cash is not None else equity)),
        holdings=holdings or {},
        equity=Decimal(str(equity)),
    )


def _trade(days: int, side: TradeSide, price: float, symbol: str = "RELIANCE.NS", qty: float = 10.0) -> Trade:
    t = Trade(
        strategy_id=1,
        symbol=symbol,
        side=side,
        qty=Decimal(str(qty)),
        price=Decimal(str(price)),
        simulated=True,
        executed_at=_T0 + timedelta(days=days),
    )
    return t


# --- compute_pnl_summary ----------------------------------------------------


def test_pnl_summary_with_no_history_is_flat_at_initial_cash() -> None:
    summary = compute_pnl_summary([], initial_cash=100_000.0)
    assert summary.current_equity == 100_000.0
    assert summary.cash == 100_000.0
    assert summary.total_pnl == 0.0
    assert summary.total_pnl_pct == 0.0
    assert summary.holdings == {}


def test_pnl_summary_uses_the_latest_snapshot() -> None:
    snapshots = [
        _snapshot(0, equity=100_000.0),
        _snapshot(1, equity=98_000.0, cash=88_000.0, holdings={"RELIANCE.NS": {"qty": 100, "avg_price": 100.0}}),
        _snapshot(2, equity=102_000.0, cash=92_000.0, holdings={"RELIANCE.NS": {"qty": 100, "avg_price": 100.0}}),
    ]
    summary = compute_pnl_summary(snapshots, initial_cash=100_000.0)
    assert summary.current_equity == 102_000.0
    assert summary.cash == 92_000.0
    assert summary.total_pnl == 2_000.0
    assert summary.total_pnl_pct == pytest.approx(0.02)
    assert summary.holdings == {"RELIANCE.NS": {"qty": 100, "avg_price": 100.0}}


# --- compute_live_metrics: sharpe/max_drawdown ------------------------------


def test_live_metrics_sharpe_is_none_with_too_little_history() -> None:
    metrics = compute_live_metrics([_snapshot(0, 100_000.0), _snapshot(1, 101_000.0)], [])
    assert metrics.sharpe is None


def test_live_metrics_sharpe_is_none_with_zero_variance_returns() -> None:
    # Equity never moves -> every period return is exactly 0 -> zero variance.
    snapshots = [_snapshot(i, 100_000.0) for i in range(5)]
    metrics = compute_live_metrics(snapshots, [])
    assert metrics.sharpe is None


def test_live_metrics_sharpe_is_positive_for_a_steadily_rising_equity_curve() -> None:
    snapshots = [_snapshot(i, 100_000.0 * (1.001**i)) for i in range(30)]
    metrics = compute_live_metrics(snapshots, [])
    assert metrics.sharpe is not None
    assert metrics.sharpe > 0


def test_live_metrics_max_drawdown_from_a_known_equity_curve() -> None:
    # 100k -> 110k (peak) -> 88k (a 20% drawdown from the 110k peak) -> 99k
    snapshots = [_snapshot(0, 100_000.0), _snapshot(1, 110_000.0), _snapshot(2, 88_000.0), _snapshot(3, 99_000.0)]
    metrics = compute_live_metrics(snapshots, [])
    assert metrics.max_drawdown == pytest.approx(0.2)


def test_live_metrics_max_drawdown_zero_for_empty_history() -> None:
    metrics = compute_live_metrics([], [])
    assert metrics.max_drawdown == 0.0


# --- compute_live_metrics: win_rate ------------------------------------------


def test_live_metrics_win_rate_counts_profitable_round_trips() -> None:
    trades = [
        _trade(0, TradeSide.BUY, 100.0),
        _trade(1, TradeSide.SELL, 110.0),  # win
        _trade(2, TradeSide.BUY, 100.0),
        _trade(3, TradeSide.SELL, 90.0),  # loss
        _trade(4, TradeSide.BUY, 100.0),
        _trade(5, TradeSide.SELL, 105.0),  # win
    ]
    metrics = compute_live_metrics([], trades)
    assert metrics.closed_trades == 3
    assert metrics.win_rate == pytest.approx(2 / 3)
    assert metrics.total_trades == 6


def test_live_metrics_win_rate_zero_with_no_closed_trades() -> None:
    metrics = compute_live_metrics([], [_trade(0, TradeSide.BUY, 100.0)])
    assert metrics.closed_trades == 0
    assert metrics.win_rate == 0.0
    assert metrics.total_trades == 1


def test_live_metrics_win_rate_pairs_fifo_across_symbols_independently() -> None:
    trades = [
        _trade(0, TradeSide.BUY, 100.0, symbol="RELIANCE.NS"),
        _trade(1, TradeSide.BUY, 50.0, symbol="TCS.NS"),
        _trade(2, TradeSide.SELL, 120.0, symbol="RELIANCE.NS"),  # win
        _trade(3, TradeSide.SELL, 40.0, symbol="TCS.NS"),  # loss
    ]
    metrics = compute_live_metrics([], trades)
    assert metrics.closed_trades == 2
    assert metrics.win_rate == pytest.approx(0.5)


def test_live_metrics_win_rate_ignores_out_of_order_input_list() -> None:
    # Same trades as the profitable-round-trips test, shuffled -- pairing
    # must sort by executed_at itself, not rely on input order.
    trades = [
        _trade(3, TradeSide.SELL, 90.0),
        _trade(0, TradeSide.BUY, 100.0),
        _trade(5, TradeSide.SELL, 105.0),
        _trade(2, TradeSide.BUY, 100.0),
        _trade(1, TradeSide.SELL, 110.0),
        _trade(4, TradeSide.BUY, 100.0),
    ]
    metrics = compute_live_metrics([], trades)
    assert metrics.closed_trades == 3
    assert metrics.win_rate == pytest.approx(2 / 3)
