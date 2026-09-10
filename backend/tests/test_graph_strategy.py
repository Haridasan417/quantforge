"""GraphStrategy: walks a saved Strategy Builder graph against synthetic
OHLCV data, plus the standalone instance registry it plugs into."""
from __future__ import annotations

import pandas as pd
import pytest

from app.strategy_engine import Position, PositionSide, SignalAction
from app.strategy_engine.graph_strategy import GraphStrategy, GraphStrategyConfig, GraphStrategyError
from app.strategy_engine.registry import (
    get_strategy_instance,
    list_strategy_instances,
    register_strategy_instance,
    unregister_strategy_instance,
)

FLAT = Position(side=PositionSide.FLAT)
LONG = Position(side=PositionSide.LONG, qty=1, avg_price=1.0)


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


def _trending_closes(start: float, step: float, n: int) -> list[float]:
    return [start + step * i for i in range(n)]


# 25 straight down bars (100 -> 76), then 24 straight up bars back past
# 76 -- same construction as Phase 3's RSI test, reused here because it's
# a deterministic way to drive RSI to both extremes without hand-computing
# pandas-ta's smoothing.
_RSI_DOWN = _trending_closes(100, -1, 25)
_RSI_CLOSES = _RSI_DOWN + _trending_closes(_RSI_DOWN[-1], 1, 25)[1:]


def _rsi_buy_sell_graph() -> dict:
    return {
        "nodes": [
            {
                "id": "c_oversold",
                "type": "condition",
                "position": {"x": 0, "y": 0},
                "data": {"indicator": "rsi", "comparator": "<", "threshold": 30, "params": {"length": 14}},
            },
            {
                "id": "c_overbought",
                "type": "condition",
                "position": {"x": 0, "y": 150},
                "data": {"indicator": "rsi", "comparator": ">", "threshold": 70, "params": {"length": 14}},
            },
            {"id": "a_buy", "type": "action", "position": {"x": 250, "y": 0}, "data": {"action": "BUY"}},
            {"id": "a_sell", "type": "action", "position": {"x": 250, "y": 150}, "data": {"action": "SELL"}},
        ],
        "edges": [
            {"id": "e1", "source": "c_oversold", "target": "a_buy"},
            {"id": "e2", "source": "c_overbought", "target": "a_sell"},
        ],
    }


def _and_chain_graph() -> dict:
    """Two close-price conditions AND-ed into one BUY action — doesn't
    need any indicator warm-up, so it isolates the AND-chain logic
    itself from indicator computation."""
    return {
        "nodes": [
            {"id": "c_above", "type": "condition", "data": {"indicator": "close", "comparator": ">", "threshold": 10}},
            {"id": "c_below", "type": "condition", "data": {"indicator": "close", "comparator": "<", "threshold": 100}},
            {"id": "a_buy", "type": "action", "data": {"action": "BUY"}},
        ],
        "edges": [
            {"source": "c_above", "target": "a_buy"},
            {"source": "c_below", "target": "a_buy"},
        ],
    }


# ---------------------------------------------------------------------------
# AND-chain semantics
# ---------------------------------------------------------------------------


def test_and_chain_requires_all_conditions() -> None:
    strategy = GraphStrategy(GraphStrategyConfig(**_and_chain_graph()))

    # Only the "> 10" condition holds.
    signal = strategy.generate_signal(_make_df([5]), FLAT)
    assert signal.action == SignalAction.HOLD

    # Only the "< 100" condition holds.
    signal = strategy.generate_signal(_make_df([150]), FLAT)
    assert signal.action == SignalAction.HOLD

    # Both hold -> BUY.
    signal = strategy.generate_signal(_make_df([50]), FLAT)
    assert signal.action == SignalAction.BUY


def test_and_chain_does_not_rebuy_when_already_long() -> None:
    strategy = GraphStrategy(GraphStrategyConfig(**_and_chain_graph()))
    signal = strategy.generate_signal(_make_df([50]), LONG)
    assert signal.action == SignalAction.HOLD


# ---------------------------------------------------------------------------
# Multiple action nodes (BUY chain + SELL chain), indicator-backed
# ---------------------------------------------------------------------------


def test_graph_buys_after_sustained_decline() -> None:
    strategy = GraphStrategy(GraphStrategyConfig(**_rsi_buy_sell_graph()))
    df = _make_df(_RSI_CLOSES)

    signal = strategy.generate_signal(df.iloc[:25], FLAT)
    assert signal.action == SignalAction.BUY


def test_graph_sells_after_sustained_rise_when_long() -> None:
    strategy = GraphStrategy(GraphStrategyConfig(**_rsi_buy_sell_graph()))
    df = _make_df(_RSI_CLOSES)

    signal = strategy.generate_signal(df.iloc[: len(_RSI_CLOSES)], LONG)
    assert signal.action == SignalAction.SELL


def test_graph_holds_during_indicator_warmup() -> None:
    strategy = GraphStrategy(GraphStrategyConfig(**_rsi_buy_sell_graph()))
    df = _make_df(_RSI_CLOSES)

    signal = strategy.generate_signal(df.iloc[:5], FLAT)
    assert signal.action == SignalAction.HOLD
    assert signal.reason == "warm-up"


def test_graph_on_empty_df_holds() -> None:
    strategy = GraphStrategy(GraphStrategyConfig(**_rsi_buy_sell_graph()))
    signal = strategy.generate_signal(_make_df([]), FLAT)
    assert signal.action == SignalAction.HOLD


# ---------------------------------------------------------------------------
# validate_graph
# ---------------------------------------------------------------------------


def test_validate_graph_accepts_well_formed_graph() -> None:
    GraphStrategy(GraphStrategyConfig(**_and_chain_graph())).validate_graph()  # should not raise


def test_validate_graph_rejects_missing_action_node() -> None:
    graph = {
        "nodes": [{"id": "c1", "type": "condition", "data": {"indicator": "close", "comparator": ">", "threshold": 1}}],
        "edges": [],
    }
    with pytest.raises(GraphStrategyError, match="no action node"):
        GraphStrategy(GraphStrategyConfig(**graph)).validate_graph()


def test_validate_graph_rejects_action_with_no_conditions() -> None:
    graph = {"nodes": [{"id": "a1", "type": "action", "data": {"action": "BUY"}}], "edges": []}
    with pytest.raises(GraphStrategyError, match="No action node"):
        GraphStrategy(GraphStrategyConfig(**graph)).validate_graph()


def test_validate_graph_rejects_unknown_indicator() -> None:
    graph = {
        "nodes": [
            {"id": "c1", "type": "condition", "data": {"indicator": "not_a_real_field", "comparator": ">", "threshold": 1}},
            {"id": "a1", "type": "action", "data": {"action": "BUY"}},
        ],
        "edges": [{"source": "c1", "target": "a1"}],
    }
    with pytest.raises(GraphStrategyError, match="unknown indicator"):
        GraphStrategy(GraphStrategyConfig(**graph)).validate_graph()


def test_validate_graph_rejects_dangling_edge() -> None:
    graph = {
        "nodes": [
            {"id": "c1", "type": "condition", "data": {"indicator": "close", "comparator": ">", "threshold": 1}},
            {"id": "a1", "type": "action", "data": {"action": "BUY"}},
        ],
        "edges": [{"source": "c1", "target": "does-not-exist"}],
    }
    with pytest.raises(GraphStrategyError, match="doesn't exist"):
        GraphStrategy(GraphStrategyConfig(**graph)).validate_graph()


def test_validate_graph_rejects_bad_action_value() -> None:
    graph = {
        "nodes": [
            {"id": "c1", "type": "condition", "data": {"indicator": "close", "comparator": ">", "threshold": 1}},
            {"id": "a1", "type": "action", "data": {"action": "HODL"}},
        ],
        "edges": [{"source": "c1", "target": "a1"}],
    }
    with pytest.raises(GraphStrategyError, match="BUY or SELL"):
        GraphStrategy(GraphStrategyConfig(**graph)).validate_graph()


# ---------------------------------------------------------------------------
# instance registry
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_instance_registry():
    for name in list(list_strategy_instances()):
        unregister_strategy_instance(name)
    yield
    for name in list(list_strategy_instances()):
        unregister_strategy_instance(name)


def test_register_and_fetch_strategy_instance() -> None:
    instance = GraphStrategy(GraphStrategyConfig(**_and_chain_graph()))
    register_strategy_instance("graph:1", instance)

    assert get_strategy_instance("graph:1") is instance
    assert list_strategy_instances() == {"graph:1": instance}


def test_get_unknown_strategy_instance_raises() -> None:
    with pytest.raises(KeyError):
        get_strategy_instance("graph:does-not-exist")


def test_register_strategy_instance_overwrites() -> None:
    first = GraphStrategy(GraphStrategyConfig(**_and_chain_graph()))
    second = GraphStrategy(GraphStrategyConfig(**_rsi_buy_sell_graph()))

    register_strategy_instance("graph:1", first)
    register_strategy_instance("graph:1", second)

    assert get_strategy_instance("graph:1") is second
