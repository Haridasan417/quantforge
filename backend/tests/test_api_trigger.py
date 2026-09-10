"""POST /trigger/run-once (Phase 6) — the combined single-hit
deployment mode. `run_trigger_once`/`run_executor_once` are
monkeypatched at the module boundary (same convention as
test_api_backtest.py monkeypatching `get_candles_cached`), so this only
checks the endpoint's own wiring/shape, not the pipeline internals
(covered by test_trigger_service.py / test_executor_service.py)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.executor_service.ltp_provider import LTPProviderError
from app.main import app


@pytest.fixture
def client():
    async def override_get_db():
        yield None  # never touched: every test monkeypatches both calls

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_run_once_reports_events_and_trades(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_trigger_once(db, *, force=False, client=None):
        return [{"strategy_id": 1, "symbol": "RELIANCE.NS"}]

    async def fake_run_executor_once(db, **kwargs):
        return [object(), object()]  # two "trades"

    monkeypatch.setattr("app.api.trigger.run_trigger_once", fake_run_trigger_once)
    monkeypatch.setattr("app.api.trigger.run_executor_once", fake_run_executor_once)
    monkeypatch.setattr("app.api.trigger.is_market_open", lambda: True)

    response = client.post("/trigger/run-once")
    assert response.status_code == 200
    body = response.json()
    assert body == {"market_open": True, "events_pushed": 1, "trades_executed": 2}


def test_run_once_market_closed_skips_trigger_but_still_reports(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_trigger_once(db, *, force=False, client=None):
        assert force is False
        return []  # NSE-hours gate inside run_trigger_once itself would return []

    async def fake_run_executor_once(db, **kwargs):
        return []

    monkeypatch.setattr("app.api.trigger.run_trigger_once", fake_run_trigger_once)
    monkeypatch.setattr("app.api.trigger.run_executor_once", fake_run_executor_once)
    monkeypatch.setattr("app.api.trigger.is_market_open", lambda: False)

    response = client.post("/trigger/run-once")
    assert response.status_code == 200
    assert response.json() == {"market_open": False, "events_pushed": 0, "trades_executed": 0}


def test_run_once_force_reports_market_open_true_even_when_closed(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_trigger_once(db, *, force=False, client=None):
        assert force is True
        return [{"strategy_id": 1, "symbol": "RELIANCE.NS"}]

    async def fake_run_executor_once(db, **kwargs):
        return []

    monkeypatch.setattr("app.api.trigger.run_trigger_once", fake_run_trigger_once)
    monkeypatch.setattr("app.api.trigger.run_executor_once", fake_run_executor_once)
    monkeypatch.setattr("app.api.trigger.is_market_open", lambda: False)

    response = client.post("/trigger/run-once?force=true")
    assert response.status_code == 200
    assert response.json()["market_open"] is True


def test_run_once_ltp_provider_error_is_502(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_trigger_once(db, *, force=False, client=None):
        return []

    async def fake_run_executor_once(db, **kwargs):
        raise LTPProviderError("SMARTAPI_KEY / SMARTAPI_CLIENT_ID are not configured")

    monkeypatch.setattr("app.api.trigger.run_trigger_once", fake_run_trigger_once)
    monkeypatch.setattr("app.api.trigger.run_executor_once", fake_run_executor_once)
    monkeypatch.setattr("app.api.trigger.is_market_open", lambda: True)

    response = client.post("/trigger/run-once")
    assert response.status_code == 502
