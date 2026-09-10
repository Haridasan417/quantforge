"""Indicator math, checked against small, hand-computable datasets rather
than just asserting "some column got added."
"""
import pandas as pd
import pytest

from app.data_service.indicators import compute_indicators, ema, macd, rsi


def _sma_seeded_ema(values: list[float], length: int) -> list[float | None]:
    """Reference EMA implementation (SMA-seeded recursive formula) used to
    independently verify `ema()`'s output below."""
    k = 2 / (length + 1)
    out: list[float | None] = [None] * (length - 1)
    seed = sum(values[:length]) / length
    out.append(seed)
    prev = seed
    for v in values[length:]:
        prev = v * k + prev * (1 - k)
        out.append(prev)
    return out


def test_ema_matches_hand_computed_values() -> None:
    closes = [10.0, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25]
    df = pd.DataFrame({"close": closes})
    length = 5

    result = ema(df, length=length)
    expected = _sma_seeded_ema(closes, length)

    for got, want in zip(result.tolist(), expected, strict=True):
        if want is None:
            assert pd.isna(got)
        else:
            assert got == pytest.approx(want)


def test_rsi_is_100_for_an_all_gains_series() -> None:
    # No losses at all -> average loss is 0 -> RSI saturates at 100.
    df = pd.DataFrame({"close": list(range(1, 30))})
    result = rsi(df, length=14)
    assert result.iloc[-1] == pytest.approx(100.0)


def test_rsi_is_0_for_an_all_losses_series() -> None:
    # No gains at all -> average gain is 0 -> RSI saturates at 0.
    df = pd.DataFrame({"close": list(range(30, 1, -1))})
    result = rsi(df, length=14)
    assert result.iloc[-1] == pytest.approx(0.0)


def test_rsi_is_bounded() -> None:
    closes = [10, 11, 10.5, 12, 11.5, 13, 12.8, 14, 13.5, 15, 14.7, 16, 15.9, 17, 16.5, 18]
    df = pd.DataFrame({"close": closes})
    result = rsi(df, length=14).dropna()
    assert ((result >= 0) & (result <= 100)).all()


def test_macd_histogram_equals_macd_minus_signal() -> None:
    df = pd.DataFrame({"close": list(range(1, 60))})
    result = macd(df, fast=12, slow=26, signal=9).dropna()

    histogram = result["MACDh_12_26_9"]
    computed = result["MACD_12_26_9"] - result["MACDs_12_26_9"]

    assert histogram.tolist() == pytest.approx(computed.tolist())


def test_compute_indicators_adds_requested_columns_only() -> None:
    df = pd.DataFrame({"close": list(range(1, 40))})

    out = compute_indicators(df, ["rsi", "ema"])

    assert "rsi" in out.columns
    assert "ema" in out.columns
    assert "MACD_12_26_9" not in out.columns


def test_compute_indicators_ignores_unknown_names() -> None:
    df = pd.DataFrame({"close": list(range(1, 20))})
    out = compute_indicators(df, ["not_a_real_indicator"])
    assert list(out.columns) == list(df.columns)
