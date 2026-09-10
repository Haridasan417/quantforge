"""Integration test (Phase 6): pushes a fake `{strategy_id, symbol}`
event through a real Redis-shaped queue and runs it through the actual
Executor against a real Postgres connection, asserting a simulated
`Trade` lands in the DB with correctly risk-adjusted sizing.

Every other test in this suite is DB-free by convention (see
CLAUDE.md's testing notes) — this is the one deliberate exception,
because `Trade`/`PortfolioSnapshot`/`Strategy` have real FK constraints,
JSONB columns, and `Numeric` precision that a fake session can't
meaningfully verify. It connects to whatever `DATABASE_URL` already
points at — the same env var `alembic upgrade head` uses — and skips
outright if that database isn't reachable, so it's a no-op wherever
Postgres isn't available (this was authored in a sandbox with no route
to a real DB) but runs for real against your migrated Neon DB when you
run `pytest` locally per the Phase 6 handoff.

`get_candles_cached` is still monkeypatched to synthetic OHLCV (same as
test_api_backtest.py) — exercising the *candle cache's* Postgres path
isn't this test's job, and its exact-match cache key can't be
pre-seeded against a dynamic `datetime.now()` window anyway.

Every row this test creates is deleted in a `finally` block, in FK-safe
order (Trade rows before their Strategy row), so repeated runs never
leave residue in a real database.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import fakeredis
import pandas as pd
import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.executor_service import run_executor_once
from app.executor_service.ltp_provider import FakeLTPProvider
from app.models.portfolio_snapshot import PortfolioSnapshot
from app.models.strategy import Strategy as StrategyModel
from app.models.trade import Trade
from app.queue import push_event
from app.risk_manager import RiskManager, RiskManagerSettings

SYMBOL = "RELIANCE.NS"

# Monotonically declining closes: RSIThresholdStrategy's default config
# (buy_below=30/sell_above=70, length=14) reliably reads the *last* bar
# as deeply oversold (RSI approaching 0) on a pure downtrend, which is
# what drives the BUY signal this test depends on -- position starts
# flat, so BUY is the only thing that can fire.
_CLOSES = [130.0 - i for i in range(30)]
_REFERENCE_PRICE = _CLOSES[-1]  # 101.0 -- what the Risk Manager sizes the order against
_LTP = 102.35  # deliberately different from the reference close, so the
# test can confirm the *fill* price comes from the LTP provider while
# *sizing* comes from the candle close (see app/executor_service/executor.py).

RISK_SETTINGS = RiskManagerSettings(stop_loss_pct=0.05, max_position_size_pct=0.20, max_total_exposure_pct=0.60)
STARTING_EQUITY = 100_000.0


def _synthetic_df() -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=len(_CLOSES), freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "open": _CLOSES,
            "high": [c + 0.5 for c in _CLOSES],
            "low": [c - 0.5 for c in _CLOSES],
            "close": _CLOSES,
            "volume": [1_000_000] * len(_CLOSES),
        },
        index=index,
    )


async def _db_reachable(engine) -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(settings.database_url, pool_pre_ping=True)
    if not await _db_reachable(eng):
        await eng.dispose()
        pytest.skip(f"Postgres not reachable at DATABASE_URL -- skipping integration test")
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine) -> AsyncSession:
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest.mark.asyncio
async def test_fake_event_through_queue_lands_a_risk_adjusted_trade(db: AsyncSession) -> None:
    created_trade_ids: list[int] = []
    created_snapshot_ids: list[int] = []
    deployment_row: StrategyModel | None = None

    try:
        # 1. A deployed strategy (what POST /api/strategies/activate creates).
        deployment_row = StrategyModel(
            name="integration-test deployment",
            type="rsi_threshold",
            config={},
            symbol=SYMBOL,
            is_active=True,
        )
        db.add(deployment_row)
        await db.commit()
        await db.refresh(deployment_row)

        # 2. A baseline portfolio snapshot, timestamped "now" so it's
        # unambiguously the latest row regardless of what else exists
        # in this database from other phases/tests.
        baseline = PortfolioSnapshot(
            timestamp=datetime.now(timezone.utc),
            cash=Decimal(str(STARTING_EQUITY)),
            holdings={},
            equity=Decimal(str(STARTING_EQUITY)),
        )
        db.add(baseline)
        await db.commit()
        await db.refresh(baseline)
        created_snapshot_ids.append(baseline.id)

        # 3. Push the fake event through a real (fakeredis-backed) queue.
        redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
        await push_event({"strategy_id": deployment_row.id, "symbol": SYMBOL}, client=redis_client)

        # 4. Run it through the real Executor, against this real DB
        # connection -- only the candle fetch is faked (see module
        # docstring).
        import app.executor_service.executor as executor_module

        async def fake_get_candles_cached(db_, symbol, interval, start, end):
            return _synthetic_df()

        original = executor_module.get_candles_cached
        executor_module.get_candles_cached = fake_get_candles_cached
        try:
            trades = await run_executor_once(
                db,
                ltp_provider=FakeLTPProvider(prices={SYMBOL: _LTP}),
                client=redis_client,
                risk_manager=RiskManager(settings=RISK_SETTINGS),
            )
        finally:
            executor_module.get_candles_cached = original

        # 5. Assert a real Trade row landed, sized against the Risk
        # Manager's rules (not just "a trade exists").
        assert len(trades) == 1
        trade = trades[0]
        created_trade_ids.append(trade.id)

        assert trade.strategy_id == deployment_row.id
        assert trade.symbol == SYMBOL
        assert trade.side.value == "BUY"
        assert trade.simulated is True
        # sizing: max_position_size_pct=0.20 of 100_000 equity = 20_000
        # budget, divided by the *reference* close (101.0, not the LTP)
        # and floored -> 198 shares.
        expected_qty = int((STARTING_EQUITY * RISK_SETTINGS.max_position_size_pct) // _REFERENCE_PRICE)
        assert expected_qty == 198
        assert trade.qty == Decimal(str(expected_qty))
        # fill price is the LTP, not the reference close.
        assert trade.price == Decimal(str(_LTP))

        # Re-read the row straight from Postgres (not the in-memory
        # object) to confirm it was actually persisted, Numeric
        # precision and all.
        reloaded = (await db.execute(select(Trade).where(Trade.id == trade.id))).scalar_one()
        assert reloaded.qty == Decimal(str(expected_qty))
        assert reloaded.price == Decimal(str(_LTP))

        # 6. The portfolio snapshot the Executor wrote reflects the fill.
        latest_snapshot = (
            await db.execute(select(PortfolioSnapshot).order_by(PortfolioSnapshot.timestamp.desc()).limit(1))
        ).scalar_one()
        created_snapshot_ids.append(latest_snapshot.id)
        assert latest_snapshot.holdings[SYMBOL]["qty"] == expected_qty
        assert float(latest_snapshot.holdings[SYMBOL]["avg_price"]) == _LTP
        expected_cash = STARTING_EQUITY - expected_qty * _LTP
        assert abs(float(latest_snapshot.cash) - expected_cash) < 0.01

    finally:
        # FK-safe cleanup: trades reference the strategy row.
        if created_trade_ids:
            await db.execute(delete(Trade).where(Trade.id.in_(created_trade_ids)))
        if created_snapshot_ids:
            await db.execute(delete(PortfolioSnapshot).where(PortfolioSnapshot.id.in_(created_snapshot_ids)))
        if deployment_row is not None and deployment_row.id is not None:
            await db.execute(delete(StrategyModel).where(StrategyModel.id == deployment_row.id))
        await db.commit()
