"""POST /api/backtest — `get_candles_cached` is monkeypatched to return
synthetic OHLCV directly, so this suite never touches a real Postgres
or the network (consistent with the rest of the test suite)."""
from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app

# 25 straight down bars then 24 straight up bars -- same construction
# used in Phase 3/4's RSI tests, reliable enough to push a default
# RSIThresholdStrategy (buy_below=30/sell_above=70, length=14) through
# both a BUY and a SELL regardless of the exact smoothing pandas-ta
# uses internally. ma_crossover's default fast=10/slow=30 needs a much
# longer, more careful series to guarantee a crossover — its exact
# math is already covered by Phase 3's unit tests, so the API test
# below just checks the endpoint's shape/wiring with it instead.
_RSI_CLOSES = [100 - i for i in range(25)] + [76 + i for i in range(1, 25)]


def _synthetic_df(closes: list[float]) -> pd.DataFrame:
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


@pytest.fixture
def client():
    async def override_get_db():
        # Never actually queried: every test here monkeypatches
        # get_candles_cached before the endpoint gets a chance to use it.
        yield None

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _request_body(strategy_id: str = "ma_crossover") -> dict:
    return {
        "strategy_id": strategy_id,
        "symbol": "TEST.NS",
        "start": "2024-01-01T00:00:00Z",
        "end": "2024-02-14T00:00:00Z",
    }


def test_post_backtest_returns_metrics_and_records_trades(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_get_candles_cached(db, symbol, interval, start, end):
        return _synthetic_df(_RSI_CLOSES)

    monkeypatch.setattr("app.api.backtest.get_candles_cached", fake_get_candles_cached)

    response = client.post("/api/backtest", json=_request_body(strategy_id="rsi_threshold"))
    assert response.status_code == 200
    body = response.json()

    assert body["strategy_id"] == "rsi_threshold"
    assert body["symbol"] == "TEST.NS"
    assert body["interval"] == "1d"
    assert 0.0 <= body["win_rate"] <= 1.0
    assert body["max_drawdown"] >= 0.0
    assert len(body["equity_curve"]) == len(_RSI_CLOSES)
    assert len(body["trades"]) >= 1
    assert body["trades"][0]["side"] == "BUY"


def test_post_backtest_works_for_default_config_ma_crossover(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Endpoint shape/wiring check for the other built-in — its exact
    crossover math is already covered by Phase 3's unit tests, so this
    doesn't assert a trade fires, just that the request completes."""

    async def fake_get_candles_cached(db, symbol, interval, start, end):
        return _synthetic_df(_RSI_CLOSES)

    monkeypatch.setattr("app.api.backtest.get_candles_cached", fake_get_candles_cached)

    response = client.post("/api/backtest", json=_request_body(strategy_id="ma_crossover"))
    assert response.status_code == 200
    body = response.json()
    assert body["strategy_id"] == "ma_crossover"
    assert len(body["equity_curve"]) == len(_RSI_CLOSES)


def test_post_backtest_unknown_strategy_is_404(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_candles_cached(db, symbol, interval, start, end):
        return _synthetic_df(_RSI_CLOSES)

    monkeypatch.setattr("app.api.backtest.get_candles_cached", fake_get_candles_cached)

    response = client.post("/api/backtest", json=_request_body(strategy_id="not_a_real_strategy"))
    assert response.status_code == 404


def test_post_backtest_no_data_is_404(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.data_service import DataUnavailableError

    async def fake_get_candles_cached(db, symbol, interval, start, end):
        raise DataUnavailableError("no data")

    monkeypatch.setattr("app.api.backtest.get_candles_cached", fake_get_candles_cached)

    response = client.post("/api/backtest", json=_request_body())
    assert response.status_code == 404


def test_post_backtest_too_short_range_is_422(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_candles_cached(db, symbol, interval, start, end):
        return _synthetic_df(_RSI_CLOSES).iloc[:1]

    monkeypatch.setattr("app.api.backtest.get_candles_cached", fake_get_candles_cached)

    response = client.post("/api/backtest", json=_request_body())
    assert response.status_code == 422


def test_post_backtest_applies_a_config_override(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # Phase 7 part B: `config` is now threaded through to the resolved
    # built-in (see backtest_engine/resolve.py) -- this is what lets
    # RLStrategy's required `checkpoint_name` be specified per request.
    # Exercised here with ma_crossover (no heavy stable-baselines3
    # dependency needed) since it's purely a wiring/shape check.
    async def fake_get_candles_cached(db, symbol, interval, start, end):
        return _synthetic_df(_RSI_CLOSES)

    monkeypatch.setattr("app.api.backtest.get_candles_cached", fake_get_candles_cached)

    body = _request_body(strategy_id="ma_crossover")
    body["config"] = {"fast_period": 3, "slow_period": 9}
    response = client.post("/api/backtest", json=body)
    assert response.status_code == 200


def test_post_backtest_invalid_config_is_422_not_500(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    # RLStrategy's checkpoint_name has no default -- requesting it with
    # no config must be a clean 422 (a bad request), never an unhandled
    # 500 from a pydantic ValidationError escaping resolve_strategy.
    async def fake_get_candles_cached(db, symbol, interval, start, end):
        return _synthetic_df(_RSI_CLOSES)

    monkeypatch.setattr("app.api.backtest.get_candles_cached", fake_get_candles_cached)

    response = client.post("/api/backtest", json=_request_body(strategy_id="rl"))
    assert response.status_code == 422
