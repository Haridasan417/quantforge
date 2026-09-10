"""DELETE /api/strategies/{strategy_id} — deleting a saved Strategy
Builder graph. DB-free via a MagicMock session, same convention as
test_api_strategies_deployments.py.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.db import get_db
from app.main import app
from app.models.strategy import Strategy as StrategyModel
from app.strategy_engine.registry import list_strategy_instances, register_strategy_instance, unregister_strategy_instance
from app.strategy_engine.graph_strategy import GraphStrategy, GraphStrategyConfig


def _graph_row(id_: int, name: str = "My strategy") -> StrategyModel:
    row = StrategyModel(name=name, type="graph", config={"nodes": [], "edges": []})
    row.id = id_
    return row


def _builtin_row(id_: int) -> StrategyModel:
    row = StrategyModel(name="ma_crossover / RELIANCE.NS", type="ma_crossover", config={}, symbol="RELIANCE.NS")
    row.id = id_
    return row


def _fake_db_session(row: StrategyModel | None, *, commit_raises: Exception | None = None):
    db = MagicMock()
    db.get = AsyncMock(return_value=row)
    db.delete = AsyncMock()
    db.rollback = AsyncMock()
    if commit_raises is not None:
        db.commit = AsyncMock(side_effect=commit_raises)
    else:
        db.commit = AsyncMock()
    return db


@pytest.fixture(autouse=True)
def _clear_instance_registry():
    for name in list(list_strategy_instances()):
        unregister_strategy_instance(name)
    yield
    for name in list(list_strategy_instances()):
        unregister_strategy_instance(name)


@pytest.fixture
def client_for():
    def _make(db) -> TestClient:
        async def override_get_db():
            yield db

        app.dependency_overrides[get_db] = override_get_db
        return TestClient(app)

    yield _make
    app.dependency_overrides.pop(get_db, None)


def test_deletes_a_saved_graph(client_for) -> None:
    row = _graph_row(7)
    db = _fake_db_session(row)
    register_strategy_instance("graph:7", GraphStrategy(GraphStrategyConfig(nodes=[], edges=[])))
    client = client_for(db)

    resp = client.delete("/api/strategies/graph:7")

    assert resp.status_code == 204
    db.delete.assert_awaited_once_with(row)
    db.commit.assert_awaited_once()
    # The in-memory instance registry entry must be gone too, or a
    # backtest/deploy could still resolve a strategy whose DB row is gone.
    assert "graph:7" not in list_strategy_instances()


def test_rejects_builtin_strategy_ids(client_for) -> None:
    db = _fake_db_session(None)
    client = client_for(db)

    resp = client.delete("/api/strategies/ma_crossover")

    assert resp.status_code == 400
    db.get.assert_not_called()


def test_404_for_unknown_graph_id(client_for) -> None:
    db = _fake_db_session(None)
    client = client_for(db)

    resp = client.delete("/api/strategies/graph:999")

    assert resp.status_code == 404


def test_404_when_id_belongs_to_a_non_graph_row(client_for) -> None:
    # A malicious/incorrect "graph:<id>" pointing at a builtin-deployment
    # row (type != "graph") must not be deletable through this path.
    row = _builtin_row(3)
    db = _fake_db_session(row)
    client = client_for(db)

    resp = client.delete("/api/strategies/graph:3")

    assert resp.status_code == 404


def test_malformed_graph_id_is_422(client_for) -> None:
    db = _fake_db_session(None)
    client = client_for(db)

    resp = client.delete("/api/strategies/graph:not-a-number")

    assert resp.status_code == 422


def test_conflict_when_strategy_has_existing_trades(client_for) -> None:
    row = _graph_row(9)
    db = _fake_db_session(row, commit_raises=IntegrityError("stmt", {}, Exception("fk violation")))
    register_strategy_instance("graph:9", GraphStrategy(GraphStrategyConfig(nodes=[], edges=[])))
    client = client_for(db)

    resp = client.delete("/api/strategies/graph:9")

    assert resp.status_code == 409
    assert "pause" in resp.json()["detail"].lower()
    db.rollback.assert_awaited_once()
    # A failed delete must leave the instance registry untouched — the
    # strategy is still fully usable, the DB delete never committed.
    assert "graph:9" in list_strategy_instances()
