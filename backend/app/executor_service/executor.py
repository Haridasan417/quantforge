"""Consumes `{strategy_id, symbol}` events off the Redis queue: re-runs
the deployed strategy's `generate_signal` on fresh OHLCV data, passes
the result through the Risk Manager, and — if approved — fetches the
real LTP via `LTPProvider` and simulates a fill at that price, writing a
`Trade` row and an updated `PortfolioSnapshot`.

`strategy_id` here is always the integer primary key of a `strategies`
row (not the string name the API/registry uses elsewhere) — see
`resolve_deployed_strategy`. Position/portfolio state is read from the
single latest `PortfolioSnapshot.holdings` (account-wide, no per-strategy
book — see CLAUDE.md's Phase 6 section for why).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as redis_asyncio
from app.backtest_engine.runner import INITIAL_CASH
from app.data_service import get_candles_cached
from app.executor_service.ltp_provider import LTPProvider, SmartApiLTPProvider
from app.models.portfolio_snapshot import PortfolioSnapshot
from app.models.strategy import Strategy as StrategyModel
from app.models.trade import Trade, TradeSide
from app.queue import pop_event
from app.risk_manager import ApprovedOrder, PortfolioState, RiskManager
from app.strategy_engine import (
    GraphStrategy,
    GraphStrategyConfig,
    Position,
    PositionSide,
    SignalAction,
    Strategy,
    get_strategy,
)

logger = logging.getLogger(__name__)

# How much history to pull for `generate_signal` each cycle. Daily bars,
# generous enough for any built-in/graph indicator's lookback (the
# longest today is ma_crossover's default 30-period slow MA) with
# plenty of headroom.
EXECUTOR_LOOKBACK_DAYS = 180


class ExecutorError(RuntimeError):
    """Raised when a queued event can't be resolved to a runnable
    strategy (e.g. its `strategies` row was deleted after the event was
    queued)."""


async def resolve_deployed_strategy(db: AsyncSession, strategy_row_id: int) -> tuple[StrategyModel, Strategy]:
    """Turns an event's integer `strategy_id` into the DB row (for
    `Trade.strategy_id` and its `symbol`/`config`) and a runnable
    `Strategy` instance built from that row's *own* config — unlike
    `app.backtest_engine.resolve.resolve_strategy`, a built-in here is
    instantiated with the deployment's saved config, not the class
    default, since each deployment may have been activated with
    different parameters (see `POST /api/strategies/activate`)."""
    row = await db.get(StrategyModel, strategy_row_id)
    if row is None:
        raise ExecutorError(f"No strategy row with id={strategy_row_id}")

    if row.type == "graph":
        config = GraphStrategyConfig(**row.config)
        return row, GraphStrategy(config)

    cls = get_strategy(row.type)  # raises KeyError if unknown, propagated as-is
    return row, cls(row.config)


async def _latest_portfolio_snapshot(db: AsyncSession) -> PortfolioSnapshot | None:
    stmt = select(PortfolioSnapshot).order_by(PortfolioSnapshot.timestamp.desc()).limit(1)
    return (await db.execute(stmt)).scalar_one_or_none()


def _position_for_symbol(holdings: dict, symbol: str) -> Position:
    entry = holdings.get(symbol)
    if not entry or float(entry.get("qty", 0)) <= 0:
        return Position()
    return Position(side=PositionSide.LONG, qty=float(entry["qty"]), avg_price=float(entry["avg_price"]))


def _apply_fill(
    cash: float, holdings: dict, symbol: str, order: ApprovedOrder, fill_price: float
) -> tuple[float, dict, float]:
    """Updates the account-wide cash/holdings for one simulated fill.
    BUY merges into any existing position at a qty-weighted average
    cost (defensive — the Risk Manager already blocks a second BUY
    while long, so this normally only ever *creates* a fresh entry);
    SELL always closes the position outright (the Risk Manager never
    approves a partial-size SELL, see `RiskManager.evaluate`)."""
    holdings = dict(holdings)
    if order.side == SignalAction.BUY:
        cash -= order.qty * fill_price
        existing = holdings.get(symbol)
        if existing:
            total_qty = existing["qty"] + order.qty
            avg_price = (existing["qty"] * existing["avg_price"] + order.qty * fill_price) / total_qty
            holdings[symbol] = {"qty": total_qty, "avg_price": avg_price}
        else:
            holdings[symbol] = {"qty": order.qty, "avg_price": fill_price}
    else:  # SELL
        cash += order.qty * fill_price
        holdings.pop(symbol, None)

    equity = cash + sum(h["qty"] * h["avg_price"] for h in holdings.values())
    return cash, holdings, equity


async def process_event(
    db: AsyncSession,
    event: dict,
    ltp_provider: LTPProvider,
    *,
    risk_manager: RiskManager | None = None,
) -> Trade | None:
    """Handles exactly one `{strategy_id, symbol}` event end-to-end.
    Returns the written `Trade` row, or `None` if nothing fired (no
    data, a HOLD signal, or the Risk Manager rejected it) — the caller
    (`run_executor_once`) just skips a `None`."""
    risk_manager = risk_manager or RiskManager()
    strategy_row_id = event["strategy_id"]
    symbol = event["symbol"]

    row, strategy = await resolve_deployed_strategy(db, strategy_row_id)

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=EXECUTOR_LOOKBACK_DAYS)
    df = await get_candles_cached(db, symbol, "1d", start, end)
    if df.empty or len(df) < 2:
        logger.info("Executor: not enough candle data for %s (strategy_id=%s), skipping", symbol, strategy_row_id)
        return None

    snapshot = await _latest_portfolio_snapshot(db)
    cash = float(snapshot.cash) if snapshot is not None else INITIAL_CASH
    holdings: dict = dict(snapshot.holdings) if snapshot is not None and snapshot.holdings else {}

    position = _position_for_symbol(holdings, symbol)
    signal = strategy.generate_signal(df, position)
    reference_price = float(df["close"].iloc[-1])

    holdings_value = {s: float(h["qty"]) * float(h["avg_price"]) for s, h in holdings.items()}
    equity = cash + sum(holdings_value.values())
    portfolio_state = PortfolioState(cash=cash, equity=equity, holdings_value=holdings_value)

    decision = risk_manager.evaluate(signal, symbol, reference_price, position, portfolio_state)
    if decision.order is None:
        logger.info("Executor: %s/%s not approved (%s)", symbol, strategy_row_id, decision.reason)
        return None

    # Only fetch the real LTP once risk has approved something — no
    # point spending a SmartAPI call when the answer is "no trade".
    ltp = await ltp_provider.get_ltp(symbol)

    trade = Trade(
        strategy_id=row.id,
        symbol=symbol,
        side=TradeSide(decision.order.side.value),
        qty=Decimal(str(decision.order.qty)),
        price=Decimal(str(ltp)),
        simulated=True,
        executed_at=datetime.now(timezone.utc),
    )
    db.add(trade)

    new_cash, new_holdings, new_equity = _apply_fill(cash, holdings, symbol, decision.order, ltp)
    db.add(
        PortfolioSnapshot(
            timestamp=datetime.now(timezone.utc),
            cash=Decimal(str(new_cash)),
            holdings=new_holdings,
            equity=Decimal(str(new_equity)),
        )
    )

    await db.commit()
    await db.refresh(trade)
    return trade


async def run_executor_once(
    db: AsyncSession,
    *,
    ltp_provider: LTPProvider | None = None,
    client: redis_asyncio.Redis | None = None,
    max_events: int = 50,
    risk_manager: RiskManager | None = None,
) -> list[Trade]:
    """Drains up to `max_events` off the queue (never blocks waiting
    for more — an empty queue just means "nothing to do this cycle").
    `ltp_provider` defaults to a real `SmartApiLTPProvider` so this is
    ready to call as-is from `__main__`/`POST /trigger/run-once`; tests
    always pass a `FakeLTPProvider` explicitly."""
    ltp_provider = ltp_provider or SmartApiLTPProvider()
    trades: list[Trade] = []

    for _ in range(max_events):
        event = await pop_event(client=client)
        if event is None:
            break
        trade = await process_event(db, event, ltp_provider, risk_manager=risk_manager)
        if trade is not None:
            trades.append(trade)

    return trades


async def run_executor_loop(
    session_factory,
    *,
    ltp_provider: LTPProvider | None = None,
    interval_seconds: float = 60.0,
    client: redis_asyncio.Redis | None = None,
    iterations: int | None = None,
) -> None:
    """Always-on deployment mode counterpart to
    `app.trigger_service.run_trigger_loop` — polls the queue forever (or
    `iterations` times, for tests), sleeping between drains."""
    import asyncio

    ltp_provider = ltp_provider or SmartApiLTPProvider()
    count = 0
    while iterations is None or count < iterations:
        try:
            async with session_factory() as db:
                trades = await run_executor_once(db, ltp_provider=ltp_provider, client=client)
                if trades:
                    logger.info("Executor: wrote %d trade(s)", len(trades))
        except Exception:
            logger.exception("Executor loop iteration failed")
        count += 1
        if iterations is None or count < iterations:
            await asyncio.sleep(interval_seconds)
