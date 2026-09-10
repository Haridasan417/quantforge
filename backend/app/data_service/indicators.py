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


def _nan_series(df: pd.DataFrame, name: str) -> pd.Series:
    return pd.Series(float("nan"), index=df.index, name=name)


def rsi(df: pd.DataFrame, length: int = DEFAULT_RSI_LENGTH) -> pd.Series:
    result = df.ta.rsi(length=length)
    # pandas-ta's DataFrame accessor falls back to handing back the
    # *original* df (not None, not a Series) when there isn't enough
    # data for the requested length — quietly returning that would blow
    # up every caller expecting a Series. Normalize it to an all-NaN
    # series of the same shape a short/warm-up window would produce.
    if not isinstance(result, pd.Series):
        return _nan_series(df, name=f"RSI_{length}")
    return result


def ema(df: pd.DataFrame, length: int = DEFAULT_EMA_LENGTH) -> pd.Series:
    result = df.ta.ema(length=length)
    if not isinstance(result, pd.Series):
        return _nan_series(df, name=f"EMA_{length}")
    return result


def macd(
    df: pd.DataFrame,
    fast: int = DEFAULT_MACD_FAST,
    slow: int = DEFAULT_MACD_SLOW,
    signal: int = DEFAULT_MACD_SIGNAL,
) -> pd.DataFrame:
    result = df.ta.macd(fast=fast, slow=slow, signal=signal)
    expected_cols = {
        f"MACD_{fast}_{slow}_{signal}",
        f"MACDh_{fast}_{slow}_{signal}",
        f"MACDs_{fast}_{slow}_{signal}",
    }
    if not isinstance(result, pd.DataFrame) or not expected_cols.issubset(result.columns):
        return pd.DataFrame({col: _nan_series(df, name=col) for col in sorted(expected_cols)})
    return result


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
