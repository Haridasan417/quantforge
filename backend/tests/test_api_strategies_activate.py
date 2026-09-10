"""POST /api/strategies/activate (Phase 6) — turns a registered
strategy into a Trigger-pollable deployment. DB-free via a minimal fake
AsyncSession, same convention as test_api_strategies.py."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.models.strategy import Strategy as StrategyModel


class _FakeSession:
    """`db.get()` looks up by id (for the graph-activation path);
    `db.execute()` always returns whatever `existing_row` is currently
    set to (for the built-in find-or-create path) — a test sets it
    before the request to simulate "a deployment already exists"."""

    def __init__(self) -> None:
        self._next_id = 1
        self._by_id: dict[int, StrategyModel] = {}
        self.existing_row: StrategyModel | None = None

    def seed(self, row: StrategyModel) -> StrategyModel:
        if row.id is None:
            row.id = self._next_id
            self._next_id += 1
        self._by_id[row.id] = row
        return row

    def add(self, obj) -> None:
        self._pending = obj

    async def commit(self) -> None:
        pass

    async def refresh(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = self._next_id
            self._next_id += 1
            self._by_id[obj.id] = obj
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(timezone.utc)

    async def get(self, model, pk):
        return self._by_id.get(pk)

    async def execute(self, stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = self.existing_row
        return result


@pytest.fixture
def fake_session() -> _FakeSession:
    return _FakeSession()


@pytest.fixture
def client(fake_session: _FakeSession):
    async def override_get_db():
        yield fake_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def _activate(client: TestClient, **overrides) -> dict:
    body = {"strategy_id": "ma_crossover", "symbol": "reliance.ns"}
    body.update(overrides)
    return client.post("/api/strategies/activate", json=body)


def test_activate_builtin_creates_new_deployment(client: TestClient) -> None:
    response = _activate(client)
    assert response.status_code == 200
    body = response.json()
    assert body["deployment_id"] == 1
    assert body["strategy_id"] == "ma_crossover"
    assert body["symbol"] == "RELIANCE.NS"  # normalized to uppercase
    assert body["is_active"] is True


def test_activate_builtin_updates_existing_deployment(client: TestClient, fake_session: _FakeSession) -> None:
    existing = fake_session.seed(
        StrategyModel(name="old", type="ma_crossover", config={"fast_period": 10, "slow_period": 30}, symbol="RELIANCE.NS", is_active=True)
    )
    fake_session.existing_row = existing

    response = _activate(client, is_active=False, config={"fast_period": 5, "slow_period": 15})
    assert response.status_code == 200
    body = response.json()
    assert body["deployment_id"] == existing.id
    assert body["is_active"] is False
    assert existing.config == {"fast_period": 5, "slow_period": 15}


def test_activate_builtin_rejects_invalid_config(client: TestClient) -> None:
    response = _activate(client, config={"fast_period": 30, "slow_period": 10})  # fast must be < slow
    assert response.status_code == 422


def test_activate_unknown_builtin_is_404(client: TestClient) -> None:
    response = _activate(client, strategy_id="not_a_real_strategy")
    assert response.status_code == 404


def test_activate_graph_requires_existing_row(client: TestClient) -> None:
    response = _activate(client, strategy_id="graph:1")
    assert response.status_code == 404


def test_activate_graph_updates_existing_row(client: TestClient, fake_session: _FakeSession) -> None:
    row = fake_session.seed(StrategyModel(name="my graph", type="graph", config={"nodes": [], "edges": []}, symbol=None, is_active=False))

    response = _activate(client, strategy_id=f"graph:{row.id}", symbol="tcs.ns")
    assert response.status_code == 200
    body = response.json()
    assert body["deployment_id"] == row.id
    assert body["symbol"] == "TCS.NS"
    assert body["is_active"] is True
    assert row.symbol == "TCS.NS"
    assert row.is_active is True


def test_activate_malformed_graph_id_is_422(client: TestClient) -> None:
    response = _activate(client, strategy_id="graph:not-a-number")
    assert response.status_code == 422
