"""Raw OHLCV fetching: yfinance first, nsepy fallback for NSE symbols.

`fetch_candles` is the one function everything else in this module (and
the API layer) calls — it never touches the cache, so it's easy to test
with the network mocked out.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

OHLCV_COLUMNS = ["open", "high", "low", "close", "volume"]

# nsepy has no intraday history — only full trading days. yfinance's
# equivalent "give me daily bars" interval strings.
_DAILY_INTERVALS = {"1d", "1day", "daily"}


class DataUnavailableError(RuntimeError):
    """Raised when neither yfinance nor (if applicable) nsepy could
    produce data for the request."""


def _is_nse_symbol(symbol: str) -> bool:
    return symbol.upper().endswith(".NS")


def _localize_to_utc(index: pd.DatetimeIndex, *, assume_tz: str) -> pd.DatetimeIndex:
    """Normalize a possibly tz-naive index to UTC.

    yfinance usually returns tz-aware timestamps already (exchange-local);
    nsepy always returns tz-naive dates. Naive timestamps are assumed to be
    in `assume_tz` (the exchange's local time) before converting to UTC, so
    everything this module returns — and everything stored in the cache
    table — is unambiguous UTC.
    """
    if index.tz is None:
        return index.tz_localize(assume_tz).tz_convert("UTC")
    return index.tz_convert("UTC")


def _standardize(df: pd.DataFrame, *, assume_tz: str) -> pd.DataFrame:
    df = df.rename(columns=str.lower)
    df = df[[c for c in OHLCV_COLUMNS if c in df.columns]]
    df.index = _localize_to_utc(pd.DatetimeIndex(df.index), assume_tz=assume_tz)
    df.index.name = "ts"
    return df.sort_index()


def _fetch_from_yfinance(symbol: str, interval: str, start: datetime, end: datetime) -> pd.DataFrame:
    ticker = yf.Ticker(symbol)
    raw = ticker.history(start=start, end=end, interval=interval, auto_adjust=False)
    if raw.empty:
        return raw
    assume_tz = "Asia/Kolkata" if _is_nse_symbol(symbol) else "UTC"
    return _standardize(raw, assume_tz=assume_tz)


def _fetch_from_nsepy(symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
    # Imported lazily: nsepy pulls in a fair amount at import time and is
    # only ever needed for the NSE fallback path.
    from nsepy import get_history

    raw_symbol = symbol[: -len(".NS")] if _is_nse_symbol(symbol) else symbol
    raw = get_history(symbol=raw_symbol, start=start.date(), end=end.date())
    if raw.empty:
        return raw
    return _standardize(raw, assume_tz="Asia/Kolkata")


def fetch_candles(symbol: str, interval: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Fetch OHLCV bars for `symbol` between `start` and `end`.

    Tries yfinance first. Falls back to nsepy only for ".NS" symbols on a
    daily interval, since nsepy has no intraday data and covers NSE only.
    Returns a DataFrame indexed by a UTC "ts" DatetimeIndex with columns
    open/high/low/close/volume. Raises DataUnavailableError if nothing
    could be fetched.
    """
    try:
        df = _fetch_from_yfinance(symbol, interval, start, end)
    except Exception:
        df = pd.DataFrame()

    if not df.empty:
        return df

    if _is_nse_symbol(symbol) and interval.lower() in _DAILY_INTERVALS:
        try:
            df = _fetch_from_nsepy(symbol, start, end)
        except Exception as exc:
            raise DataUnavailableError(
                f"yfinance returned no data for {symbol!r} and the nsepy fallback failed: {exc}"
            ) from exc
        if not df.empty:
            return df

    raise DataUnavailableError(
        f"No candle data available for symbol={symbol!r} interval={interval!r} "
        f"between {start} and {end}"
    )
