"""features.py (Phase 7 part A): the shared feature-engineering
function reused by RL training (`ml/envs/trading_env.py`) and, once
Phase 7 part B exists, backtest/live inference too."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.strategy_engine.features import (
    FEATURE_COLUMNS,
    FEATURE_WINDOW,
    OBSERVATION_SIZE,
    build_features,
    build_observation,
    observation_at,
)


def _make_df(closes: list[float]) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=len(closes), freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1.0 for c in closes],
            "low": [c - 1.0 for c in closes],
            "close": closes,
            "volume": [1_000_000] * len(closes),
        },
        index=index,
    )


def test_observation_size_is_window_times_columns() -> None:
    assert OBSERVATION_SIZE == FEATURE_WINDOW * len(FEATURE_COLUMNS)


def test_build_features_same_index_and_expected_columns() -> None:
    df = _make_df([100.0 + i for i in range(60)])
    features = build_features(df)
    assert list(features.columns) == FEATURE_COLUMNS
    assert features.index.equals(df.index)
    assert len(features) == len(df)


def test_build_features_warms_up_with_nan_then_stabilizes() -> None:
    df = _make_df([100.0 + i for i in range(60)])
    features = build_features(df)
    # The very first row can never have a `ret` (no prior close).
    assert pd.isna(features["ret"].iloc[0])
    # By the end of a 60-bar run, every indicator (rsi/ema/macd, longest
    # default lookback 26) should be fully warmed up.
    assert not features.iloc[-1].isna().any()


def test_observation_at_none_before_window_is_full() -> None:
    df = _make_df([100.0 + i for i in range(60)])
    features = build_features(df)
    # Even though later rows exist, index 0 can't look back `window` bars.
    assert observation_at(features, 0) is None
    assert observation_at(features, FEATURE_WINDOW - 2) is None


def test_observation_at_none_while_indicators_still_nan() -> None:
    df = _make_df([100.0 + i for i in range(60)])
    features = build_features(df)
    # Index FEATURE_WINDOW-1 has a full window of *rows*, but the
    # trailing rows are still NaN (RSI/EMA/MACD warm-up outlasts
    # FEATURE_WINDOW=20 by design -- MACD's slow EMA needs 26).
    assert observation_at(features, FEATURE_WINDOW - 1) is None


def test_observation_at_returns_flat_float32_vector_once_warmed_up() -> None:
    df = _make_df([100.0 + i for i in range(60)])
    features = build_features(df)
    obs = observation_at(features, len(features) - 1)
    assert obs is not None
    assert obs.shape == (OBSERVATION_SIZE,)
    assert obs.dtype == np.float32
    assert np.isfinite(obs).all()


def test_observation_at_out_of_range_index_is_none() -> None:
    df = _make_df([100.0 + i for i in range(60)])
    features = build_features(df)
    assert observation_at(features, len(features)) is None
    assert observation_at(features, -1) is None


def test_build_observation_matches_observation_at_on_last_row() -> None:
    df = _make_df([100.0 + i for i in range(60)])
    features = build_features(df)
    expected = observation_at(features, len(features) - 1)
    actual = build_observation(df)
    assert actual is not None
    np.testing.assert_array_equal(actual, expected)


def test_build_observation_none_on_too_short_a_frame() -> None:
    df = _make_df([100.0, 101.0, 102.0])
    assert build_observation(df) is None


def test_build_observation_none_on_empty_frame() -> None:
    df = _make_df([])
    assert build_observation(df) is None


def test_scale_free_columns_stay_in_sane_ranges() -> None:
    # rsi is rescaled to 0-1; the other columns are ratios/percentages
    # that should stay small for a gently-moving synthetic series --
    # this is really a smoke test that the /close and /100 scaling
    # didn't get dropped or duplicated.
    df = _make_df([100.0 + np.sin(i / 5) for i in range(80)])
    features = build_features(df)
    tail = features.iloc[-1]
    assert 0.0 <= tail["rsi"] <= 1.0
    assert abs(tail["ret"]) < 0.1
    assert abs(tail["ema_dist"]) < 0.1
