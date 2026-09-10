"""RSI / MACD / EMA helpers, built on pandas-ta.

Every strategy, the backtester, and RL feature engineering (Phases 3-7)
should compute indicators through these functions rather than reaching
for pandas-ta directly, so the parameters (periods, etc.) stay in one
place.
"""
from __future__ import annotations

import pandas as pd
import pandas_ta as ta

DEFAULT_RSI_LENGTH = 14
DEFAULT_EMA_LENGTH = 20
DEFAULT_MACD_FAST = 12
DEFAULT_MACD_SLOW = 26
DEFAULT_MACD_SIGNAL = 9

SUPPORTED_INDICATORS = {"rsi", "ema", "macd"}


def rsi(df: pd.DataFrame, length: int = DEFAULT_RSI_LENGTH) -> pd.Series:
    return df.ta.rsi(length=length)


def ema(df: pd.DataFrame, length: int = DEFAULT_EMA_LENGTH) -> pd.Series:
    return df.ta.ema(length=length)


def macd(
    df: pd.DataFrame,
    fast: int = DEFAULT_MACD_FAST,
    slow: int = DEFAULT_MACD_SLOW,
    signal: int = DEFAULT_MACD_SIGNAL,
) -> pd.DataFrame:
    return df.ta.macd(fast=fast, slow=slow, signal=signal)


def compute_indicators(df: pd.DataFrame, indicators: list[str]) -> pd.DataFrame:
    """Return `df` (OHLCV, needs a `close` column) with the requested
    indicator columns appended. Unknown indicator names are ignored.
    """
    out = df.copy()
    requested = {name.strip().lower() for name in indicators}

    if "rsi" in requested:
        out["rsi"] = rsi(df)
    if "ema" in requested:
        out["ema"] = ema(df)
    if "macd" in requested:
        out = out.join(macd(df))

    return out
