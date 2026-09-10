"""Trigger service (Phase 6) — `is_market_open` is pure and tested
directly; `run_trigger_once`'s DB query is exercised against a small
fake AsyncSession stub (consistent with the rest of the suite staying
DB-free — see test_api_backtest.py's `override_get_db`), with a
`fakeredis` client standing in for Redis."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import fakeredis
import pytest

from app.models.strategy import Strategy as StrategyModel
from app.queue import pop_event, queue_length
from app.trigger_service import is_market_open, run_trigger_loop, run_trigger_once

IST = ZoneInfo("Asia/Kolkata")


# --- is_market_open ---------------------------------------------------


def test_market_open_on_weekday_during_hours() -> None:
    # Wednesday, 12:00 IST
    assert is_market_open(datetime(2025, 1, 8, 12, 0, tzinfo=IST)) is True


def test_market_open_exactly_at_open_boundary() -> None:
    assert is_market_open(datetime(2025, 1, 8, 9, 15, tzinfo=IST)) is True


def test_market_open_exactly_at_close_boundary() -> None:
    assert is_market_open(datetime(2025, 1, 8, 15, 30, tzinfo=IST)) is True


def test_market_closed_before_open() -> None:
    assert is_market_open(datetime(2025, 1, 8, 9, 0, tzinfo=IST)) is False


def test_market_closed_after_close() -> None:
    assert is_market_open(datetime(2025, 1, 8, 15, 31, tzinfo=IST)) is False


def test_market_closed_on_saturday() -> None:
    # 2025-01-11 is a Saturday
    assert is_market_open(datetime(2025, 1, 11, 12, 0, tzinfo=IST)) is False


def test_market_closed_on_sunday() -> None:
    # 2025-01-12 is a Sunday
    assert is_market_open(datetime(2025, 1, 12, 12, 0, tzinfo=IST)) is False


def test_market_open_handles_non_ist_input_timezone() -> None:
    # 2025-01-08 04:00 UTC == 09:30 IST, well inside market hours
    utc = ZoneInfo("UTC")
    assert is_market_open(datetime(2025, 1, 8, 4, 0, tzinfo=utc)) is True


# --- run_trigger_once ---------------------------------------------------


def _fake_db_session(rows: list[StrategyModel]):
    db = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    db.execute = AsyncMock(return_value=result)
    return db


def _strategy_row(id_: int, symbol: str | None, is_active: bool) -> StrategyModel:
    row = StrategyModel(name=f"deployment-{id_}", type="ma_crossover", config={}, symbol=symbol, is_active=is_active)
    row.id = id_
    return row


@pytest.fixture
def redis_client():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.mark.asyncio
async def test_run_trigger_once_pushes_one_event_per_active_deployment(redis_client) -> None:
    rows = [_strategy_row(1, "RELIANCE.NS", True), _strategy_row(2, "TCS.NS", True)]
    db = _fake_db_session(rows)

    events = await run_trigger_once(db, force=True, client=redis_client)

    assert events == [
        {"strategy_id": 1, "symbol": "RELIANCE.NS"},
        {"strategy_id": 2, "symbol": "TCS.NS"},
    ]
    assert await pop_event(client=redis_client) == {"strategy_id": 1, "symbol": "RELIANCE.NS"}
    assert await pop_event(client=redis_client) == {"strategy_id": 2, "symbol": "TCS.NS"}
    assert await pop_event(client=redis_client) is None


@pytest.mark.asyncio
async def test_run_trigger_once_no_deployments_pushes_nothing(redis_client) -> None:
    db = _fake_db_session([])
    events = await run_trigger_once(db, force=True, client=redis_client)
    assert events == []
    assert await pop_event(client=redis_client) is None


@pytest.mark.asyncio
async def test_run_trigger_once_skips_when_market_closed(redis_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.trigger_service.trigger.is_market_open", lambda: False)
    db = _fake_db_session([_strategy_row(1, "RELIANCE.NS", True)])

    events = await run_trigger_once(db, client=redis_client)  # force defaults to False

    assert events == []
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_run_trigger_once_force_bypasses_market_hours_gate(redis_client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.trigger_service.trigger.is_market_open", lambda: False)
    db = _fake_db_session([_strategy_row(1, "RELIANCE.NS", True)])

    events = await run_trigger_once(db, force=True, client=redis_client)

    assert events == [{"strategy_id": 1, "symbol": "RELIANCE.NS"}]


# --- run_trigger_loop ---------------------------------------------------


@pytest.mark.asyncio
async def test_run_trigger_loop_runs_fixed_iterations_and_pushes_each_time(
    redis_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.trigger_service.trigger.is_market_open", lambda: True)
    rows = [_strategy_row(1, "RELIANCE.NS", True)]
    db = _fake_db_session(rows)

    class _FakeSessionFactory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return db

        async def __aexit__(self, *exc):
            return False

    await run_trigger_loop(
        _FakeSessionFactory(),
        interval_seconds=0,
        client=redis_client,
        iterations=3,
    )

    assert await queue_length(client=redis_client) == 3
