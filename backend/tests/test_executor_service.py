"""Executor service (Phase 6) — DB-free unit tests, consistent with the
rest of the suite: `get_candles_cached` and the DB session are faked
(same pattern as test_api_backtest.py's `override_get_db` /
monkeypatched `get_candles_cached`), and `FakeLTPProvider` stands in for
SmartAPI. The one test that needs a *real* Postgres + Redis end-to-end
run is the separate integration test (test_executor_integration.py)."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from app.executor_service.executor import (
    ExecutorError,
    _apply_fill,
    _position_for_symbol,
    process_event,
    resolve_deployed_strategy,
    run_executor_once,
)
from app.executor_service.ltp_provider import FakeLTPProvider, LTPProviderError
from app.models.portfolio_snapshot import PortfolioSnapshot
from app.models.strategy import Strategy as StrategyModel
from app.risk_manager import ApprovedOrder, RiskManager, RiskManagerSettings
from app.strategy_engine import Position, PositionSide, Signal, SignalAction


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


class _StubStrategy:
    def __init__(self, signal: Signal) -> None:
        self._signal = signal
        self.last_call: tuple | None = None

    def generate_signal(self, df: pd.DataFrame, position: Position) -> Signal:
        self.last_call = (df, position)
        return self._signal


class FakeAsyncSession:
    """Minimal AsyncSession stand-in: `.get()` for
    `resolve_deployed_strategy`, `.execute()` for the latest-snapshot
    query, `.add()`/`.commit()`/`.refresh()` recorded for assertions."""

    def __init__(self, strategy_row: StrategyModel | None = None, latest_snapshot: PortfolioSnapshot | None = None):
        self._strategy_row = strategy_row
        self._latest_snapshot = latest_snapshot
        self.added: list = []
        self.committed = False
        self.refreshed: list = []
        self._next_id = 1

    async def get(self, model, pk):
        return self._strategy_row

    async def execute(self, stmt):
        result = MagicMock()
        result.scalar_one_or_none.return_value = self._latest_snapshot
        return result

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, obj) -> None:
        self.refreshed.append(obj)
        if getattr(obj, "id", None) is None:
            obj.id = self._next_id
            self._next_id += 1


def _strategy_row(id_: int = 1, type_: str = "ma_crossover", config: dict | None = None, symbol: str = "RELIANCE.NS") -> StrategyModel:
    row = StrategyModel(name="deployment", type=type_, config=config or {}, symbol=symbol, is_active=True)
    row.id = id_
    return row


# --- resolve_deployed_strategy -------------------------------------------


@pytest.mark.asyncio
async def test_resolve_deployed_strategy_builtin_uses_row_config() -> None:
    db = FakeAsyncSession(strategy_row=_strategy_row(type_="ma_crossover", config={"fast_period": 5, "slow_period": 20}))

    row, strategy = await resolve_deployed_strategy(db, 1)

    assert row.type == "ma_crossover"
    assert strategy.config.fast_period == 5
    assert strategy.config.slow_period == 20


@pytest.mark.asyncio
async def test_resolve_deployed_strategy_graph_type() -> None:
    db = FakeAsyncSession(strategy_row=_strategy_row(type_="graph", config={"nodes": [], "edges": []}))

    row, strategy = await resolve_deployed_strategy(db, 1)

    assert row.type == "graph"
    assert type(strategy).__name__ == "GraphStrategy"


@pytest.mark.asyncio
async def test_resolve_deployed_strategy_missing_row_raises() -> None:
    db = FakeAsyncSession(strategy_row=None)
    with pytest.raises(ExecutorError):
        await resolve_deployed_strategy(db, 999)


# --- _position_for_symbol / _apply_fill -----------------------------------


def test_position_for_symbol_flat_when_absent() -> None:
    pos = _position_for_symbol({}, "RELIANCE.NS")
    assert pos.is_flat


def test_position_for_symbol_long_when_present() -> None:
    pos = _position_for_symbol({"RELIANCE.NS": {"qty": 10, "avg_price": 100.0}}, "RELIANCE.NS")
    assert pos.side == PositionSide.LONG
    assert pos.qty == 10
    assert pos.avg_price == 100.0


def test_apply_fill_buy_creates_new_position() -> None:
    order = ApprovedOrder(side=SignalAction.BUY, symbol="RELIANCE.NS", qty=10, price=100.0, reason="")
    cash, holdings, equity = _apply_fill(10_000.0, {}, "RELIANCE.NS", order, 100.0)
    assert cash == 9_000.0
    assert holdings == {"RELIANCE.NS": {"qty": 10, "avg_price": 100.0}}
    assert equity == 10_000.0


def test_apply_fill_sell_closes_position() -> None:
    order = ApprovedOrder(side=SignalAction.SELL, symbol="RELIANCE.NS", qty=10, price=120.0, reason="")
    cash, holdings, equity = _apply_fill(9_000.0, {"RELIANCE.NS": {"qty": 10, "avg_price": 100.0}}, "RELIANCE.NS", order, 120.0)
    assert cash == 9_000.0 + 1_200.0
    assert holdings == {}
    assert equity == 10_200.0


# --- process_event ---------------------------------------------------------


@pytest.fixture
def risk_manager() -> RiskManager:
    return RiskManager(
        settings=RiskManagerSettings(stop_loss_pct=0.05, max_position_size_pct=0.20, max_total_exposure_pct=0.60)
    )


@pytest.mark.asyncio
async def test_process_event_buy_writes_trade_and_snapshot(
    monkeypatch: pytest.MonkeyPatch, risk_manager: RiskManager
) -> None:
    stub_strategy = _StubStrategy(Signal(action=SignalAction.BUY, reason="test buy"))
    row = _strategy_row(id_=7, symbol="RELIANCE.NS")

    monkeypatch.setattr(
        "app.executor_service.executor.resolve_deployed_strategy",
        AsyncMock(return_value=(row, stub_strategy)),
    )
    monkeypatch.setattr(
        "app.executor_service.executor.get_candles_cached",
        AsyncMock(return_value=_synthetic_df([100.0] * 30)),
    )

    db = FakeAsyncSession(latest_snapshot=None)  # no snapshot yet -> INITIAL_CASH
    ltp_provider = FakeLTPProvider(prices={"RELIANCE.NS": 101.5})

    trade = await process_event(db, {"strategy_id": 7, "symbol": "RELIANCE.NS"}, ltp_provider, risk_manager=risk_manager)

    assert trade is not None
    assert trade.strategy_id == 7
    assert trade.symbol == "RELIANCE.NS"
    assert trade.side.value == "BUY"
    assert trade.price == Decimal("101.5")
    # INITIAL_CASH=100_000, max_position_size_pct=0.20 -> budget 20_000 @ ref close 100.0 -> 200 shares
    assert trade.qty == Decimal("200")
    assert db.committed is True
    assert len(db.added) == 2  # Trade + PortfolioSnapshot
    snapshot = next(obj for obj in db.added if isinstance(obj, PortfolioSnapshot))
    assert snapshot.holdings == {"RELIANCE.NS": {"qty": 200, "avg_price": 101.5}}


@pytest.mark.asyncio
async def test_process_event_hold_signal_writes_nothing(monkeypatch: pytest.MonkeyPatch, risk_manager: RiskManager) -> None:
    stub_strategy = _StubStrategy(Signal(action=SignalAction.HOLD, reason="no signal"))
    row = _strategy_row()

    monkeypatch.setattr("app.executor_service.executor.resolve_deployed_strategy", AsyncMock(return_value=(row, stub_strategy)))
    monkeypatch.setattr("app.executor_service.executor.get_candles_cached", AsyncMock(return_value=_synthetic_df([100.0] * 30)))

    db = FakeAsyncSession()
    trade = await process_event(db, {"strategy_id": 1, "symbol": "RELIANCE.NS"}, FakeLTPProvider(default=100.0), risk_manager=risk_manager)

    assert trade is None
    assert db.added == []
    assert db.committed is False


@pytest.mark.asyncio
async def test_process_event_empty_candles_returns_none(monkeypatch: pytest.MonkeyPatch, risk_manager: RiskManager) -> None:
    stub_strategy = _StubStrategy(Signal(action=SignalAction.BUY))
    row = _strategy_row()

    monkeypatch.setattr("app.executor_service.executor.resolve_deployed_strategy", AsyncMock(return_value=(row, stub_strategy)))
    monkeypatch.setattr("app.executor_service.executor.get_candles_cached", AsyncMock(return_value=pd.DataFrame()))

    db = FakeAsyncSession()
    trade = await process_event(db, {"strategy_id": 1, "symbol": "RELIANCE.NS"}, FakeLTPProvider(default=100.0), risk_manager=risk_manager)

    assert trade is None
    assert db.added == []


@pytest.mark.asyncio
async def test_process_event_risk_rejection_returns_none_without_calling_ltp(
    monkeypatch: pytest.MonkeyPatch, risk_manager: RiskManager
) -> None:
    # Already long -> a second BUY signal is rejected by the risk manager.
    stub_strategy = _StubStrategy(Signal(action=SignalAction.BUY))
    row = _strategy_row()
    snapshot = PortfolioSnapshot(
        timestamp=datetime.now(timezone.utc),
        cash=Decimal("80000"),
        holdings={"RELIANCE.NS": {"qty": 100, "avg_price": 100.0}},
        equity=Decimal("100000"),
    )

    monkeypatch.setattr("app.executor_service.executor.resolve_deployed_strategy", AsyncMock(return_value=(row, stub_strategy)))
    monkeypatch.setattr("app.executor_service.executor.get_candles_cached", AsyncMock(return_value=_synthetic_df([100.0] * 30)))

    class _ExplodingLTPProvider(FakeLTPProvider):
        async def get_ltp(self, symbol: str) -> float:
            raise AssertionError("LTP should not be fetched when risk rejects the order")

    db = FakeAsyncSession(latest_snapshot=snapshot)
    trade = await process_event(db, {"strategy_id": 1, "symbol": "RELIANCE.NS"}, _ExplodingLTPProvider(), risk_manager=risk_manager)

    assert trade is None
    assert db.added == []


@pytest.mark.asyncio
async def test_process_event_propagates_ltp_provider_error(monkeypatch: pytest.MonkeyPatch, risk_manager: RiskManager) -> None:
    stub_strategy = _StubStrategy(Signal(action=SignalAction.BUY))
    row = _strategy_row()

    monkeypatch.setattr("app.executor_service.executor.resolve_deployed_strategy", AsyncMock(return_value=(row, stub_strategy)))
    monkeypatch.setattr("app.executor_service.executor.get_candles_cached", AsyncMock(return_value=_synthetic_df([100.0] * 30)))

    db = FakeAsyncSession()
    with pytest.raises(LTPProviderError):
        await process_event(db, {"strategy_id": 1, "symbol": "UNKNOWN.NS"}, FakeLTPProvider(), risk_manager=risk_manager)


# --- run_executor_once ------------------------------------------------------


@pytest.mark.asyncio
async def test_run_executor_once_drains_queue_up_to_max_events(monkeypatch: pytest.MonkeyPatch) -> None:
    import fakeredis

    from app.queue import push_event

    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    for i in range(5):
        await push_event({"strategy_id": i, "symbol": "RELIANCE.NS"}, client=client)

    processed_ids = []

    async def fake_process_event(db, event, ltp_provider, risk_manager=None):
        processed_ids.append(event["strategy_id"])
        return None

    monkeypatch.setattr("app.executor_service.executor.process_event", fake_process_event)

    db = FakeAsyncSession()
    trades = await run_executor_once(db, ltp_provider=FakeLTPProvider(), client=client, max_events=3)

    assert trades == []
    assert processed_ids == [0, 1, 2]  # stopped at max_events, FIFO order

    # remaining events still queued
    remaining = []
    while True:
        from app.queue import pop_event

        ev = await pop_event(client=client)
        if ev is None:
            break
        remaining.append(ev)
    assert [e["strategy_id"] for e in remaining] == [3, 4]


@pytest.mark.asyncio
async def test_run_executor_once_stops_when_queue_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    import fakeredis

    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    calls = 0

    async def fake_process_event(db, event, ltp_provider, risk_manager=None):
        nonlocal calls
        calls += 1
        return None

    monkeypatch.setattr("app.executor_service.executor.process_event", fake_process_event)

    db = FakeAsyncSession()
    trades = await run_executor_once(db, ltp_provider=FakeLTPProvider(), client=client, max_events=50)

    assert trades == []
    assert calls == 0
