"""backtest_engine: the backtrader bridge, run_backtest's metrics, and
strategy_id resolution — all against synthetic OHLCV data, no network
or real Postgres involved."""
from __future__ import annotations

import pandas as pd
import pytest
from pydantic import BaseModel

from app.backtest_engine import BacktestError, resolve_strategy, run_backtest
from app.strategy_engine import Position, PositionSide, Signal, SignalAction, Strategy
from app.strategy_engine.graph_strategy import GraphStrategy, GraphStrategyConfig
from app.strategy_engine.registry import register_strategy_instance, unregister_strategy_instance
from app.strategy_engine.strategies.ma_crossover import MACrossoverConfig, MACrossoverStrategy


def _make_df(closes: list[float]) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=len(closes), freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [1_000_000] * len(closes),
        },
        index=index,
    )


# Down then up then down again, long enough for a 2/4-period MA
# crossover to fire in both directions — same shape of construction as
# Phase 3's MACrossoverStrategy test, just longer so backtrader has
# more than one round trip to report on.
_CLOSES = (
    [100 - i for i in range(15)]  # 100 -> 86
    + [85 + i for i in range(15)]  # 85 -> 99, crosses back up
    + [100 - i for i in range(15)]  # 100 -> 86 again, crosses back down
)


class _EmptyConfig(BaseModel):
    pass


class _AlwaysHoldStrategy(Strategy):
    """A strategy that never trades — used to check run_backtest's
    output shape when there are zero trades."""

    @classmethod
    def config_schema(cls):
        return _EmptyConfig

    def generate_signal(self, df: pd.DataFrame, position: Position) -> Signal:
        return Signal(action=SignalAction.HOLD)


class _BuyOnceStrategy(Strategy):
    """Buys on the 3rd bar and never sells — used to check a single
    open (never-closed) position doesn't blow up the analyzers."""

    @classmethod
    def config_schema(cls):
        return _EmptyConfig

    def generate_signal(self, df: pd.DataFrame, position: Position) -> Signal:
        if len(df) == 3 and position.side != PositionSide.LONG:
            return Signal(action=SignalAction.BUY)
        return Signal(action=SignalAction.HOLD)


# ---------------------------------------------------------------------------
# run_backtest
# ---------------------------------------------------------------------------


def test_run_backtest_rejects_empty_df() -> None:
    with pytest.raises(BacktestError):
        run_backtest(MACrossoverStrategy(MACrossoverConfig(fast_period=2, slow_period=4)), _make_df([]))


def test_run_backtest_rejects_too_short_df() -> None:
    with pytest.raises(BacktestError):
        run_backtest(MACrossoverStrategy(MACrossoverConfig(fast_period=2, slow_period=4)), _make_df([100]))


def test_run_backtest_with_no_trades_has_sane_defaults() -> None:
    result = run_backtest(_AlwaysHoldStrategy(), _make_df(_CLOSES))

    assert result["trades"] == []
    assert result["win_rate"] == 0.0
    assert result["max_drawdown"] == 0.0
    assert result["final_equity"] == pytest.approx(100_000.0)
    assert len(result["equity_curve"]) == len(_CLOSES)
    # No variance in returns (nothing ever traded) -> backtrader reports
    # sharpe as None, not 0 -- the API layer passes this through as-is.
    assert result["sharpe"] is None


def test_run_backtest_records_a_round_trip() -> None:
    strategy = MACrossoverStrategy(MACrossoverConfig(fast_period=2, slow_period=4))
    result = run_backtest(strategy, _make_df(_CLOSES))

    assert len(result["trades"]) >= 2
    assert result["trades"][0]["side"] == "BUY"
    assert all(t["qty"] > 0 for t in result["trades"])
    assert 0.0 <= result["win_rate"] <= 1.0
    assert result["max_drawdown"] >= 0.0
    assert len(result["equity_curve"]) == len(_CLOSES)
    # Every fill should show up as an equity change by the following bar.
    assert result["final_equity"] != pytest.approx(100_000.0)


def test_run_backtest_handles_a_position_left_open_at_the_end() -> None:
    result = run_backtest(_BuyOnceStrategy(), _make_df(_CLOSES))
    assert len(result["trades"]) == 1
    assert result["trades"][0]["side"] == "BUY"
    # An open (never-closed) position isn't in TradeAnalyzer's "closed"
    # bucket, so win_rate must not divide by zero.
    assert result["win_rate"] == 0.0


def test_run_backtest_works_with_a_graph_strategy() -> None:
    graph = {
        "nodes": [
            {"id": "c1", "type": "condition", "data": {"indicator": "close", "comparator": "<", "threshold": 90}},
            {"id": "a1", "type": "action", "data": {"action": "BUY"}},
        ],
        "edges": [{"source": "c1", "target": "a1"}],
    }
    strategy = GraphStrategy(GraphStrategyConfig(**graph))
    result = run_backtest(strategy, _make_df(_CLOSES))
    assert len(result["trades"]) >= 1
    assert result["trades"][0]["side"] == "BUY"


# ---------------------------------------------------------------------------
# resolve_strategy
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_instance_registry():
    yield
    unregister_strategy_instance("graph:resolve-test")


def test_resolve_strategy_builtin_returns_a_fresh_instance() -> None:
    strategy = resolve_strategy("ma_crossover")
    assert isinstance(strategy, MACrossoverStrategy)


def test_resolve_strategy_graph_instance_returns_the_registered_object() -> None:
    instance = GraphStrategy(
        GraphStrategyConfig(
            nodes=[
                {"id": "c1", "type": "condition", "data": {"indicator": "close", "comparator": ">", "threshold": 0}},
                {"id": "a1", "type": "action", "data": {"action": "BUY"}},
            ],
            edges=[{"source": "c1", "target": "a1"}],
        )
    )
    register_strategy_instance("graph:resolve-test", instance)
    assert resolve_strategy("graph:resolve-test") is instance


def test_resolve_strategy_unknown_id_raises() -> None:
    with pytest.raises(KeyError):
        resolve_strategy("not_a_real_strategy")
