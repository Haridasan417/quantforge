"""Strategy engine: registry wiring plus each built-in strategy against
a small synthetic OHLCV series with a known crossover/threshold event.
"""
from __future__ import annotations

import pandas as pd
import pytest

from app.strategy_engine import Position, PositionSide, SignalAction, get_strategy, list_strategies
from app.strategy_engine.strategies.ma_crossover import MACrossoverConfig, MACrossoverStrategy
from app.strategy_engine.strategies.rsi_threshold import RSIThresholdConfig, RSIThresholdStrategy


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


FLAT = Position(side=PositionSide.FLAT)
LONG = Position(side=PositionSide.LONG, qty=1, avg_price=1.0)


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


def test_registry_has_both_builtin_strategies() -> None:
    registered = list_strategies()
    assert registered["ma_crossover"] is MACrossoverStrategy
    assert registered["rsi_threshold"] is RSIThresholdStrategy


def test_get_strategy_unknown_name_raises() -> None:
    with pytest.raises(KeyError):
        get_strategy("does_not_exist")


def test_config_schema_exposes_json_schema() -> None:
    schema = MACrossoverStrategy.config_schema().model_json_schema()
    assert "fast_period" in schema["properties"]
    assert "slow_period" in schema["properties"]


# ---------------------------------------------------------------------------
# MACrossoverStrategy
#
# closes chosen so a 2-period/4-period MA crossover happens at known rows:
# fast crosses above slow at index 6 (a BUY event), then crosses back
# below at index 10 (a SELL event) — verified by hand in the phase 3
# implementation notes, not just eyeballed.
# ---------------------------------------------------------------------------

_MA_CLOSES = [10, 9, 8, 7, 6, 5, 12, 13, 14, 15, 10, 5, 3, 2]


def test_ma_crossover_buys_on_upward_cross() -> None:
    strategy = MACrossoverStrategy(MACrossoverConfig(fast_period=2, slow_period=4))
    df = _make_df(_MA_CLOSES)

    # Before the cross (through index 5): fast MA is still below slow MA.
    signal = strategy.generate_signal(df.iloc[:6], FLAT)
    assert signal.action == SignalAction.HOLD

    # At index 6: fast MA crosses above slow MA -> BUY.
    signal = strategy.generate_signal(df.iloc[:7], FLAT)
    assert signal.action == SignalAction.BUY


def test_ma_crossover_holds_when_already_long() -> None:
    strategy = MACrossoverStrategy(MACrossoverConfig(fast_period=2, slow_period=4))
    df = _make_df(_MA_CLOSES)

    # Already long by the time of the same upward cross -> no repeat BUY.
    signal = strategy.generate_signal(df.iloc[:7], LONG)
    assert signal.action == SignalAction.HOLD


def test_ma_crossover_sells_on_downward_cross() -> None:
    strategy = MACrossoverStrategy(MACrossoverConfig(fast_period=2, slow_period=4))
    df = _make_df(_MA_CLOSES)

    # Just before index 10: fast MA is still above slow MA, still long -> HOLD.
    signal = strategy.generate_signal(df.iloc[:10], LONG)
    assert signal.action == SignalAction.HOLD

    # At index 10: fast MA crosses back below slow MA while long -> SELL.
    signal = strategy.generate_signal(df.iloc[:11], LONG)
    assert signal.action == SignalAction.SELL


def test_ma_crossover_config_rejects_fast_not_below_slow() -> None:
    with pytest.raises(ValueError):
        MACrossoverConfig(fast_period=30, slow_period=10)


# ---------------------------------------------------------------------------
# RSIThresholdStrategy
#
# A long sustained decline drives RSI toward 0 (well below the default
# oversold threshold); a long sustained rise afterward drives it toward
# 100 (well above the overbought threshold) — regardless of the exact
# smoothing pandas-ta uses internally, a strong enough one-directional
# run reliably crosses both thresholds.
# ---------------------------------------------------------------------------


def _trending_closes(start: float, step: float, n: int) -> list[float]:
    return [start + step * i for i in range(n)]


_RSI_CLOSES = _trending_closes(100, -1, 25) + _trending_closes(_trending_closes(100, -1, 25)[-1], 1, 25)[1:]


def test_rsi_threshold_holds_during_warmup() -> None:
    strategy = RSIThresholdStrategy(RSIThresholdConfig(length=14, buy_below=30, sell_above=70))
    df = _make_df(_RSI_CLOSES)

    signal = strategy.generate_signal(df.iloc[:5], FLAT)
    assert signal.action == SignalAction.HOLD
    assert signal.reason == "warm-up"


def test_rsi_threshold_buys_after_sustained_decline() -> None:
    strategy = RSIThresholdStrategy(RSIThresholdConfig(length=14, buy_below=30, sell_above=70))
    df = _make_df(_RSI_CLOSES)

    # After 25 straight down bars, RSI should be deep in oversold territory.
    signal = strategy.generate_signal(df.iloc[:25], FLAT)
    assert signal.action == SignalAction.BUY


def test_rsi_threshold_sells_after_sustained_rise_when_long() -> None:
    strategy = RSIThresholdStrategy(RSIThresholdConfig(length=14, buy_below=30, sell_above=70))
    df = _make_df(_RSI_CLOSES)

    # After the reversal, 24 more straight up bars should push RSI back
    # into overbought territory.
    signal = strategy.generate_signal(df.iloc[: len(_RSI_CLOSES)], LONG)
    assert signal.action == SignalAction.SELL


def test_rsi_threshold_config_rejects_buy_above_sell() -> None:
    with pytest.raises(ValueError):
        RSIThresholdConfig(length=14, buy_below=80, sell_above=20)
