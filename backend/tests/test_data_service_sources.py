"""fetch_candles: yfinance-first, nsepy-fallback logic, with every
network call mocked out.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.data_service.sources import DataUnavailableError, fetch_candles

START = datetime(2024, 1, 1, tzinfo=timezone.utc)
END = datetime(2024, 1, 5, tzinfo=timezone.utc)


def _yfinance_frame() -> pd.DataFrame:
    index = pd.DatetimeIndex(["2024-01-02", "2024-01-03"], tz="America/New_York")
    return pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [102.0, 103.0],
            "Low": [99.0, 100.0],
            "Close": [101.0, 102.0],
            "Volume": [1_000_000, 1_100_000],
            "Dividends": [0.0, 0.0],
            "Stock Splits": [0.0, 0.0],
        },
        index=index,
    )


def _nsepy_frame() -> pd.DataFrame:
    index = pd.to_datetime(["2024-01-02", "2024-01-03"])
    return pd.DataFrame(
        {
            "Symbol": ["RELIANCE", "RELIANCE"],
            "Series": ["EQ", "EQ"],
            "Open": [2500.0, 2510.0],
            "High": [2550.0, 2560.0],
            "Low": [2490.0, 2500.0],
            "Close": [2540.0, 2550.0],
            "Volume": [500_000, 520_000],
        },
        index=index,
    )


@patch("app.data_service.sources.yf.Ticker")
def test_fetch_candles_uses_yfinance_when_available(mock_ticker_cls: MagicMock) -> None:
    mock_ticker_cls.return_value.history.return_value = _yfinance_frame()

    df = fetch_candles("AAPL", "1d", START, END)

    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 2
    assert df.index.tz is not None
    assert str(df.index.tz) == "UTC"
    assert df["close"].tolist() == [101.0, 102.0]


@patch("nsepy.get_history")
@patch("app.data_service.sources.yf.Ticker")
def test_fetch_candles_falls_back_to_nsepy_for_nse_symbol(
    mock_ticker_cls: MagicMock, mock_get_history: MagicMock
) -> None:
    mock_ticker_cls.return_value.history.return_value = pd.DataFrame()
    mock_get_history.return_value = _nsepy_frame()

    df = fetch_candles("RELIANCE.NS", "1d", START, END)

    mock_get_history.assert_called_once()
    assert mock_get_history.call_args.kwargs["symbol"] == "RELIANCE"
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df["close"].tolist() == [2540.0, 2550.0]
    assert str(df.index.tz) == "UTC"


@patch("nsepy.get_history")
@patch("app.data_service.sources.yf.Ticker")
def test_fetch_candles_does_not_fall_back_for_non_nse_symbol(
    mock_ticker_cls: MagicMock, mock_get_history: MagicMock
) -> None:
    mock_ticker_cls.return_value.history.return_value = pd.DataFrame()

    with pytest.raises(DataUnavailableError):
        fetch_candles("AAPL", "1d", START, END)

    mock_get_history.assert_not_called()


@patch("nsepy.get_history")
@patch("app.data_service.sources.yf.Ticker")
def test_fetch_candles_does_not_fall_back_for_intraday_interval(
    mock_ticker_cls: MagicMock, mock_get_history: MagicMock
) -> None:
    # nsepy has no intraday data, so even an NSE symbol shouldn't trigger
    # the fallback when the requested interval isn't daily.
    mock_ticker_cls.return_value.history.return_value = pd.DataFrame()

    with pytest.raises(DataUnavailableError):
        fetch_candles("RELIANCE.NS", "1h", START, END)

    mock_get_history.assert_not_called()


@patch("nsepy.get_history")
@patch("app.data_service.sources.yf.Ticker")
def test_fetch_candles_raises_when_both_sources_empty(
    mock_ticker_cls: MagicMock, mock_get_history: MagicMock
) -> None:
    mock_ticker_cls.return_value.history.return_value = pd.DataFrame()
    mock_get_history.return_value = pd.DataFrame()

    with pytest.raises(DataUnavailableError):
        fetch_candles("RELIANCE.NS", "1d", START, END)


@patch("app.data_service.sources.yf.Ticker")
def test_fetch_candles_raises_when_yfinance_errors_outright(mock_ticker_cls: MagicMock) -> None:
    mock_ticker_cls.return_value.history.side_effect = ConnectionError("network down")

    with pytest.raises(DataUnavailableError):
        fetch_candles("AAPL", "1d", START, END)


@patch("app.data_service.sources.yf.Ticker")
def test_fetch_candles_drops_a_still_forming_bar_with_a_nan_price(mock_ticker_cls: MagicMock) -> None:
    # Regression coverage: yfinance reports today's not-yet-closed daily
    # bar with a real open/high/low/volume but NaN close, rather than
    # omitting the row. That NaN used to survive all the way into the
    # candle_cache JSONB insert as the literal (invalid-JSON) token `NaN`,
    # crashing every /api/candles request with a live "today" bar in
    # range -- see sqlalchemy.exc.DBAPIError: "invalid input syntax for
    # type json ... Token 'NaN' is invalid."
    frame = _yfinance_frame()
    frame.loc[frame.index[-1], "Close"] = float("nan")
    mock_ticker_cls.return_value.history.return_value = frame

    df = fetch_candles("AAPL", "1d", START, END)

    assert len(df) == 1
    assert df["close"].tolist() == [101.0]
    assert not df.isna().any().any()
