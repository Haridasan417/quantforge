"""API layer for the strategy engine: the indicator catalogue, the
combined builtin+graph listing, and saving a graph strategy.

POST /api/strategies/custom writes a `strategies` row, so `get_db` is
overridden with a minimal in-memory stand-in for AsyncSession rather
than requiring a real Postgres in the test environment — consistent
with the rest of this suite (no test here touches a live DB).
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.strategy_engine.registry import list_strategy_instances, unregister_strategy_instance


class _FakeSession:
    """Just enough of AsyncSession's surface for an endpoint that does
    `db.add(row); await db.commit(); await db.refresh(row)` once, plus
    `execute(select(...))` — GET /api/strategies looks up each saved
    graph's row by id (to recover the user-given name for
    `StrategyInfo.display_name`; see api/strategies.py). Since these
    tests only ever save one graph at a time, `execute` just returns
    every row seen so far rather than actually interpreting the
    statement's WHERE clause."""

    def __init__(self) -> None:
        self._next_id = 1
        self._rows: dict[int, object] = {}

    def add(self, obj) -> None:
        self._pending = obj

    async def commit(self) -> None:
        pass

    async def refresh(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = self._next_id
            self._next_id += 1
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(timezone.utc)
        self._rows[obj.id] = obj

    async def execute(self, stmt):
        result = MagicMock()
        result.scalars.return_value.all.return_value = list(self._rows.values())
        return result


@pytest.fixture(autouse=True)
def _clear_instance_registry():
    for name in list(list_strategy_instances()):
        unregister_strategy_instance(name)
    yield
    for name in list(list_strategy_instances()):
        unregister_strategy_instance(name)


@pytest.fixture
def client():
    fake_session = _FakeSession()

    async def override_get_db():
        yield fake_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _and_chain_graph() -> dict:
    return {
        "nodes": [
            {"id": "c_above", "type": "condition", "data": {"indicator": "close", "comparator": ">", "threshold": 10}},
            {"id": "c_below", "type": "condition", "data": {"indicator": "close", "comparator": "<", "threshold": 100}},
            {"id": "a_buy", "type": "action", "data": {"action": "BUY"}},
        ],
        "edges": [
            {"source": "c_above", "target": "a_buy"},
            {"source": "c_below", "target": "a_buy"},
        ],
    }


def test_get_strategy_indicators(client: TestClient) -> None:
    response = client.get("/api/strategies/indicators")
    assert response.status_code == 200
    body = response.json()

    fields = {item["field"] for item in body["indicators"]}
    assert fields == {"close", "rsi", "ema", "macd_line", "macd_signal", "macd_hist"}
    assert set(body["comparators"]) == {"<", ">", "<=", ">=", "==", "!="}
    assert body["actions"] == ["BUY", "SELL"]


def test_get_strategies_lists_builtins(client: TestClient) -> None:
    response = client.get("/api/strategies")
    assert response.status_code == 200
    names = {item["name"] for item in response.json()["strategies"]}
    assert {"ma_crossover", "rsi_threshold"}.issubset(names)
    sources = {item["name"]: item["source"] for item in response.json()["strategies"]}
    assert sources["ma_crossover"] == "builtin"


def test_save_custom_strategy_then_lists_it(client: TestClient) -> None:
    response = client.post(
        "/api/strategies/custom",
        json={"name": "My AND strategy", "graph": _and_chain_graph()},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "graph:1"
    assert body["source"] == "graph"
    assert body["config"]["nodes"][0]["id"] == "c_above"
    # The save response's display_name is what the user actually typed,
    # not the registry key — regression coverage for a bug where the
    # Strategy Builder's "Strategy name" field appeared to do nothing:
    # it was saved to the DB but never surfaced back anywhere in the UI.
    assert body["display_name"] == "My AND strategy"

    listing = client.get("/api/strategies").json()["strategies"]
    graph_entries = [item for item in listing if item["source"] == "graph"]
    assert len(graph_entries) == 1
    assert graph_entries[0]["name"] == "graph:1"
    # GET /api/strategies (not just the save response) must also carry the
    # user-given name — this is what the Backtest/Deploy dropdowns and the
    # Strategy Builder's "Saved visual strategies" list actually render.
    assert graph_entries[0]["display_name"] == "My AND strategy"


def test_save_custom_strategy_rejects_malformed_graph(client: TestClient) -> None:
    graph = {"nodes": [{"id": "c1", "type": "condition", "data": {"indicator": "bogus", "comparator": ">", "threshold": 1}}], "edges": []}
    response = client.post("/api/strategies/custom", json={"name": "Bad", "graph": graph})
    assert response.status_code == 422

    # A rejected save must not leak a half-registered instance.
    assert list_strategy_instances() == {}


def test_save_custom_strategy_requires_a_name(client: TestClient) -> None:
    response = client.post("/api/strategies/custom", json={"name": "", "graph": _and_chain_graph()})
    assert response.status_code == 422
