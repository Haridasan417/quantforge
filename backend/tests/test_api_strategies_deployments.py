"""GET /api/strategies/deployments (Phase 9 follow-up) — lists every
strategies row that's been turned into a deployment (symbol set, per
POST /api/strategies/activate), active or paused. DB-free via a
MagicMock session returning canned rows, same convention as
test_trigger_service.py's `_fake_db_session`."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.models.strategy import Strategy as StrategyModel


def _fake_db_session(rows: list[StrategyModel]):
    db = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    db.execute = AsyncMock(return_value=result)
    return db


def _row(id_: int, type_: str, symbol: str, is_active: bool, config: dict | None = None) -> StrategyModel:
    row = StrategyModel(name=f"deployment-{id_}", type=type_, config=config or {}, symbol=symbol, is_active=is_active)
    row.id = id_
    return row


@pytest.fixture
def client_for():
    def _make(rows: list[StrategyModel]) -> TestClient:
        db = _fake_db_session(rows)

        async def override_get_db():
            yield db

        app.dependency_overrides[get_db] = override_get_db
        return TestClient(app)

    yield _make
    app.dependency_overrides.pop(get_db, None)


def test_lists_builtin_and_graph_deployments(client_for) -> None:
    rows = [
        _row(1, "ma_crossover", "RELIANCE.NS", True, config={"fast_period": 5}),
        _row(2, "graph", "TCS.NS", False, config={"nodes": [], "edges": []}),
    ]
    client = client_for(rows)

    resp = client.get("/api/strategies/deployments")

    assert resp.status_code == 200
    deployments = resp.json()["deployments"]
    assert len(deployments) == 2

    builtin, graph = deployments
    assert builtin == {
        "deployment_id": 1,
        "strategy_id": "ma_crossover",
        "symbol": "RELIANCE.NS",
        "is_active": True,
        "config": {"fast_period": 5},
    }
    # A graph row's `type` is always the literal "graph" — the registry
    # name has to be rebuilt as "graph:<id>", same convention
    # activate_strategy itself uses.
    assert graph["strategy_id"] == "graph:2"
    assert graph["is_active"] is False


def test_empty_when_nothing_deployed(client_for) -> None:
    client = client_for([])

    resp = client.get("/api/strategies/deployments")

    assert resp.status_code == 200
    assert resp.json() == {"deployments": []}
