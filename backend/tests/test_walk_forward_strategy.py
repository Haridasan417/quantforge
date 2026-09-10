"""WalkForwardStrategy (Phase 7 part A): the grid-search fitting logic
and the strategy's end-to-end BUY/SELL/HOLD behavior.

To test the live crossover behavior without the fit's grid search
picking an unpredictable pair, most tests below pin `fast_candidates`/
`slow_candidates` to a *single* valid pair (2, 4) — with only one
candidate, the "fit" step reduces to "is there enough history", making
the resulting trade sequence directly comparable to
`MACrossoverStrategy(fast_period=2, slow_period=4)`'s own test fixture
in test_strategy_engine.py (same `_MA_CLOSES`, same expected crossover
indices), just prefixed with a flat run so the fit's
`train_window`/`test_window` warm-up is satisfied first. A flat prefix
at the same starting price cannot itself trigger a crossover (fast MA
== slow MA the whole time it's in the rolling window), and a 2/4-period
rolling mean only ever looks at the trailing 4 bars, so the prefix
provably can't perturb the crossover indices inherited from
`_MA_CLOSES`.
"""
from __future__ import annotations

import pandas as pd
import pytest

from app.strategy_engine import Position, PositionSide, SignalAction, get_strategy
from app.strategy_engine.strategies.walk_forward import (
    WalkForwardConfig,
    WalkForwardStrategy,
    _best_params,
    _mechanical_return,
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


# Same crossover fixture as MACrossoverStrategy's own test (see
# test_strategy_engine.py): fast(2)/slow(4) crosses up at index 6 (BUY),
# back down at index 10 (SELL) -- prefixed here with 12 flat bars at the
# same starting price (10) so a train_window=11/test_window=1 config's
# warm-up requirement is satisfied well before the interesting bars.
_FLAT_PREFIX = [10.0] * 12
_MA_CLOSES = [10, 9, 8, 7, 6, 5, 12, 13, 14, 15, 10, 5, 3, 2]
_COMBINED = _FLAT_PREFIX + _MA_CLOSES

_SINGLE_PAIR_CONFIG = WalkForwardConfig(
    train_window=11, test_window=1, fast_candidates=[2], slow_candidates=[4]
)


def _strategy() -> WalkForwardStrategy:
    return WalkForwardStrategy(_SINGLE_PAIR_CONFIG)


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


def test_walk_forward_is_registered() -> None:
    assert get_strategy("walk_forward") is WalkForwardStrategy


# ---------------------------------------------------------------------------
# config validation
# ---------------------------------------------------------------------------


def test_config_rejects_a_grid_with_no_valid_fast_lt_slow_pair() -> None:
    with pytest.raises(ValueError):
        WalkForwardConfig(fast_candidates=[30, 40], slow_candidates=[10, 20])


def test_config_schema_exposes_json_schema() -> None:
    schema = WalkForwardStrategy.config_schema().model_json_schema()
    assert {"train_window", "test_window", "fast_candidates", "slow_candidates"}.issubset(schema["properties"])


# ---------------------------------------------------------------------------
# _mechanical_return / _best_params (the grid search itself)
# ---------------------------------------------------------------------------


def test_mechanical_return_is_zero_for_a_flat_series() -> None:
    closes = pd.Series([100.0] * 30)
    assert _mechanical_return(closes, 5, 10) == pytest.approx(0.0)


def test_best_params_picks_the_pair_that_warms_up_earliest_on_a_pure_uptrend() -> None:
    # A strictly increasing series: every valid (fast, slow) pair ends
    # up "always long" once its slow MA has enough data, so they tie on
    # mechanical return -- the fit should deterministically prefer the
    # smallest slow (fastest to warm up and start capturing the trend),
    # and among equal-slow candidates the smallest fast (first tried).
    closes = pd.Series([100.0 + 0.5 * i for i in range(90)])
    best = _best_params(closes, [5, 10, 15, 20], [20, 30, 40, 50])
    assert best == (5, 20)


def test_best_params_returns_none_when_no_candidate_has_enough_data() -> None:
    closes = pd.Series([100.0, 101.0, 102.0])  # far too short for any candidate
    assert _best_params(closes, [5, 10], [20, 30]) is None


# ---------------------------------------------------------------------------
# generate_signal (end to end, single-candidate config)
# ---------------------------------------------------------------------------


def test_holds_during_fit_warm_up() -> None:
    strategy = _strategy()
    df = _make_df(_COMBINED)
    # Fewer than train_window+test_window=12 bars -> can't fit yet.
    signal = strategy.generate_signal(df.iloc[:11], FLAT)
    assert signal.action == SignalAction.HOLD
    assert "warm-up" in signal.reason


def test_holds_before_the_crossover() -> None:
    strategy = _strategy()
    df = _make_df(_COMBINED)
    signal = strategy.generate_signal(df.iloc[:18], FLAT)
    assert signal.action == SignalAction.HOLD


def test_buys_on_the_fitted_upward_cross() -> None:
    strategy = _strategy()
    df = _make_df(_COMBINED)
    signal = strategy.generate_signal(df.iloc[:19], FLAT)
    assert signal.action == SignalAction.BUY
    assert "(2,4)" in signal.reason


def test_holds_when_already_long_at_the_same_cross() -> None:
    strategy = _strategy()
    df = _make_df(_COMBINED)
    signal = strategy.generate_signal(df.iloc[:19], LONG)
    assert signal.action == SignalAction.HOLD


def test_sells_on_the_fitted_downward_cross() -> None:
    strategy = _strategy()
    df = _make_df(_COMBINED)
    # Just before the down-cross: still long, still HOLD.
    signal = strategy.generate_signal(df.iloc[:22], LONG)
    assert signal.action == SignalAction.HOLD
    # At the down-cross: SELL.
    signal = strategy.generate_signal(df.iloc[:23], LONG)
    assert signal.action == SignalAction.SELL
    assert "(2,4)" in signal.reason


def test_sell_signal_ignored_when_already_flat() -> None:
    strategy = _strategy()
    df = _make_df(_COMBINED)
    signal = strategy.generate_signal(df.iloc[:23], FLAT)
    assert signal.action == SignalAction.HOLD
