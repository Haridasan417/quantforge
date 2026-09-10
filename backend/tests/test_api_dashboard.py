"""GET /api/dashboard/overview, GET /api/dashboard/trades, and the
/api/ws/dashboard WebSocket (Phase 8).

DB-free: `app.dashboard.queries`'s `fetch_*` functions are monkeypatched
directly, same convention `test_api_backtest.py`'s monkeypatched
`get_candles_cached` already established (see that module and
`app/dashboard/queries.py`'s own docstring for why — a query-type-aware
fake `AsyncSession` would be more fragile here than just faking the read
functions).

The WebSocket test fakes `app.api.dashboard.get_redis` with a tiny
in-memory pubsub double rather than exercising a real/fakeredis
connection across TestClient's background event loop, which is
unreliable to assert on (two separately-constructed fakeredis clients
don't share pub/sub state, and a shared client's async primitives are
bound to whichever event loop created them) — the double still exercises
the endpoint's real subscribe/forward/cleanup code path.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.models.portfolio_snapshot import PortfolioSnapshot
from app.models.trade import Trade, TradeSide

_T0 = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _snapshot(days: int, equity: float) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        timestamp=_T0 + timedelta(days=days), cash=Decimal(str(equity)), holdings={}, equity=Decimal(str(equity))
    )


def _trade(id_: int, days: int, side: TradeSide, price: float) -> Trade:
    t = Trade(
        strategy_id=1,
        symbol="RELIANCE.NS",
        side=side,
        qty=Decimal("10"),
        price=Decimal(str(price)),
        simulated=True,
        executed_at=_T0 + timedelta(days=days),
    )
    t.id = id_
    return t


@pytest.fixture
def client():
    async def override_get_db():
        yield None  # never touched -- every test monkeypatches app.dashboard.queries's fetch_* functions

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


# --- GET /api/dashboard/overview --------------------------------------------


def test_overview_reflects_pnl_and_metrics(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    snapshots = [_snapshot(0, 100_000.0), _snapshot(1, 105_000.0)]
    trades = [_trade(1, 0, TradeSide.BUY, 100.0)]

    async def fake_fetch_portfolio_history(db):
        return snapshots

    async def fake_fetch_all_trades(db):
        return trades

    monkeypatch.setattr("app.api.dashboard.fetch_portfolio_history", fake_fetch_portfolio_history)
    monkeypatch.setattr("app.api.dashboard.fetch_all_trades", fake_fetch_all_trades)

    response = client.get("/api/dashboard/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["pnl"]["current_equity"] == 105_000.0
    assert body["pnl"]["total_pnl"] == 5_000.0
    assert body["metrics"]["total_trades"] == 1
    assert len(body["equity_curve"]) == 2
    assert body["equity_curve"][0]["equity"] == 100_000.0


def test_overview_empty_history_is_flat(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch_portfolio_history(db):
        return []

    async def fake_fetch_all_trades(db):
        return []

    monkeypatch.setattr("app.api.dashboard.fetch_portfolio_history", fake_fetch_portfolio_history)
    monkeypatch.setattr("app.api.dashboard.fetch_all_trades", fake_fetch_all_trades)

    response = client.get("/api/dashboard/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["pnl"]["total_pnl"] == 0.0
    assert body["equity_curve"] == []
    assert body["metrics"]["sharpe"] is None


# --- GET /api/dashboard/trades -----------------------------------------------


def test_trades_endpoint_returns_recent_trades_newest_first(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    trades = [_trade(2, 1, TradeSide.SELL, 110.0), _trade(1, 0, TradeSide.BUY, 100.0)]
    captured_limit = {}

    async def fake_fetch_recent_trades(db, limit=200):
        captured_limit["value"] = limit
        return trades

    monkeypatch.setattr("app.api.dashboard.fetch_recent_trades", fake_fetch_recent_trades)

    response = client.get("/api/dashboard/trades?limit=50")
    assert response.status_code == 200
    body = response.json()
    assert captured_limit["value"] == 50
    assert [t["id"] for t in body["trades"]] == [2, 1]
    assert body["trades"][0]["side"] == "SELL"


def test_trades_endpoint_defaults_limit_to_200(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    captured_limit = {}

    async def fake_fetch_recent_trades(db, limit=200):
        captured_limit["value"] = limit
        return []

    monkeypatch.setattr("app.api.dashboard.fetch_recent_trades", fake_fetch_recent_trades)

    response = client.get("/api/dashboard/trades")
    assert response.status_code == 200
    assert captured_limit["value"] == 200


# --- /api/ws/dashboard --------------------------------------------------------


class _FakePubSub:
    def __init__(self, messages: list[str]) -> None:
        self._messages = messages
        self.subscribed_to: str | None = None
        self.unsubscribed = False
        self.closed = False

    async def subscribe(self, channel: str) -> None:
        self.subscribed_to = channel

    async def listen(self):
        for data in self._messages:
            yield {"type": "message", "data": data}
        await asyncio.Event().wait()  # idle "forever" (until the task is cancelled) once drained

    async def unsubscribe(self, channel: str) -> None:
        self.unsubscribed = True

    async def aclose(self) -> None:
        self.closed = True


class _FakeRedis:
    def __init__(self, messages: list[str]) -> None:
        self.last_pubsub: _FakePubSub | None = None
        self._messages = messages

    def pubsub(self) -> _FakePubSub:
        self.last_pubsub = _FakePubSub(self._messages)
        return self.last_pubsub


def test_dashboard_ws_subscribes_to_the_dashboard_channel(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_redis = _FakeRedis([])
    monkeypatch.setattr("app.api.dashboard.get_redis", lambda: fake_redis)

    with client.websocket_connect("/api/ws/dashboard"):
        pass

    assert fake_redis.last_pubsub is not None
    assert fake_redis.last_pubsub.subscribed_to == "quantforge:dashboard-updates"


def test_dashboard_ws_forwards_a_published_update_verbatim(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    event = {"type": "execution", "trade": {"symbol": "RELIANCE.NS", "side": "BUY"}}
    fake_redis = _FakeRedis([json.dumps(event)])
    monkeypatch.setattr("app.api.dashboard.get_redis", lambda: fake_redis)

    with client.websocket_connect("/api/ws/dashboard") as ws:
        received = json.loads(ws.receive_text())

    assert received == event


def test_dashboard_ws_forwards_multiple_updates_in_order(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = [{"type": "execution", "seq": i} for i in range(3)]
    fake_redis = _FakeRedis([json.dumps(e) for e in events])
    monkeypatch.setattr("app.api.dashboard.get_redis", lambda: fake_redis)

    with client.websocket_connect("/api/ws/dashboard") as ws:
        received = [json.loads(ws.receive_text()) for _ in range(3)]

    assert received == events
