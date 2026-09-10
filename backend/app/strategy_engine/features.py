"""One feature-engineering function, reused everywhere data feeds a
model: RL training (`ml/envs/trading_env.py`'s per-step observations),
and — once Phase 7 part B wires a trained checkpoint into a live
`RLStrategy` — backtesting and live inference too. Train-time and
serve-time features must never drift apart (see CLAUDE.md's
Conventions), so all three call the *same* code here rather than each
recomputing their own notion of "the state".

Every column `build_features` produces is already scale-free (a
percent change, a ratio, or a bounded oscillator) — deliberately, so
the same feature vector generalizes across symbols and price levels
without a separate normalization/scaling step (and without a scaler
that would need fitting on training data and then kept in sync with
inference, another way train/serve can drift).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.data_service.indicators import ema, macd, rsi

# Bars of trailing history folded into one observation. Chosen to
# comfortably cover this project's longest built-in indicator lookback
# (MACrossoverStrategy's default 30-period slow MA) while staying small
# enough that an RL policy's input layer doesn't dwarf the amount of
# training data a few years of daily bars provides.
FEATURE_WINDOW = 20

# Per-bar columns, in the fixed order they're flattened in. Keeping the
# list here (not just column names on the returned DataFrame) is what
# lets `observation_at` flatten deterministically and lets callers
# assert `OBSERVATION_SIZE` without recomputing anything.
FEATURE_COLUMNS = ["ret", "high_low_range", "rsi", "ema_dist", "macd_hist"]

OBSERVATION_SIZE = FEATURE_WINDOW * len(FEATURE_COLUMNS)


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """OHLCV (open/high/low/close/volume, ascending) -> one row of
    model-ready features per input row, same index as `df`.

    Columns:
      - `ret`: close-to-close pct change — price *action*, independent
        of the symbol's absolute price level.
      - `high_low_range`: (high-low)/close — intrabar volatility.
      - `rsi`: `data_service.indicators.rsi` rescaled from 0-100 to 0-1.
      - `ema_dist`: (close-ema)/close — distance from trend, scale-free.
      - `macd_hist`: the MACD histogram divided by close, so it's
        comparable across symbols/price levels the way the raw
        histogram (an absolute price-unit quantity) isn't.

    The first bars are NaN while RSI/EMA/MACD are warming up (and the
    very first row's `ret` is always NaN) — `observation_at` below is
    what turns that into an explicit "not enough data yet" rather than
    silently feeding a model a partially-NaN or zero-filled window.
    """
    close = df["close"]

    features = pd.DataFrame(index=df.index)
    features["ret"] = close.pct_change()
    features["high_low_range"] = (df["high"] - df["low"]) / close
    features["rsi"] = rsi(df) / 100.0

    ema_series = ema(df)
    features["ema_dist"] = (close - ema_series) / close

    macd_df = macd(df)
    hist_col = next(c for c in macd_df.columns if c.startswith("MACDh"))
    features["macd_hist"] = macd_df[hist_col] / close

    return features[FEATURE_COLUMNS]


def observation_at(features_df: pd.DataFrame, index: int, window: int = FEATURE_WINDOW) -> np.ndarray | None:
    """Flattens the `window` rows ending at `index` (inclusive) into one
    1D observation vector, oldest bar first, each bar's `FEATURE_COLUMNS`
    in order (so the vector is `window * len(FEATURE_COLUMNS)` long —
    `OBSERVATION_SIZE`).

    Returns `None` if there isn't a full, fully warmed-up `window` of
    history ending at `index` yet — a caller treats that as "can't form
    an observation here", never as an all-zero vector, which would look
    like a real (if strange) market state to a trained policy instead
    of "no data".
    """
    if index < 0 or index >= len(features_df) or index + 1 < window:
        return None
    window_slice = features_df.iloc[index + 1 - window : index + 1]
    if window_slice.isna().any().any():
        return None
    return window_slice.to_numpy(dtype=np.float32).flatten()


def build_observation(df: pd.DataFrame, window: int = FEATURE_WINDOW) -> np.ndarray | None:
    """Convenience wrapper for a caller that only wants the *latest*
    observation — recomputes `build_features` fresh from `df` and
    returns the vector for its last row (or `None` during warm-up).

    Backtest/live inference (Phase 7 part B's `RLStrategy`) call this
    once per new bar, same as any other strategy's `generate_signal`.
    `ml/envs/trading_env.py` does *not* call this — an RL training
    episode needs one observation per timestep across a whole
    historical run, so it calls `build_features` once up front and
    `observation_at` per step instead of recomputing every indicator
    from scratch on every step.
    """
    if df.empty:
        return None
    features_df = build_features(df)
    return observation_at(features_df, len(features_df) - 1, window=window)
