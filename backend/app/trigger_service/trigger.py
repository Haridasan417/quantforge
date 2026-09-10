"""For each symbol with an active strategy deployment, push an
`{strategy_id, symbol}` event onto the Redis queue for the Executor to
pick up — but only during NSE trading hours (9:15-15:30 IST, Mon-Fri).

`run_trigger_once` is the single deployment-agnostic core: it's called
either by `run_trigger_loop` below (an always-on process, e.g. an
Oracle Cloud Always-Free VM) or once per hit of `POST /trigger/run-once`
(a scheduled GitHub Action / external cron, for Render's free tier where
a long-running background process isn't an option — see CLAUDE.md's
"Free-tier notes"). Neither deployment mode is hard-coded here.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as redis_asyncio
from app.models.strategy import Strategy as StrategyModel
from app.queue import push_event

logger = logging.getLogger(__name__)

NSE_TZ = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)


def is_market_open(at: datetime | None = None) -> bool:
    """NSE regular trading session: 9:15-15:30 IST, Monday-Friday. Does
    not account for exchange holidays — out of scope for this phase
    (see CLAUDE.md)."""
    now = (at or datetime.now(tz=NSE_TZ)).astimezone(NSE_TZ)
    if now.weekday() >= 5:  # 5=Saturday, 6=Sunday
        return False
    return MARKET_OPEN <= now.time() <= MARKET_CLOSE


async def run_trigger_once(
    db: AsyncSession,
    *,
    force: bool = False,
    client: redis_asyncio.Redis | None = None,
) -> list[dict]:
    """Query every active strategy deployment (`is_active=True` with a
    `symbol` set) and push one evaluate-event per row.

    `force=True` bypasses the NSE-hours gate — used by tests and by a
    manual/demo trigger hit so the pipeline is exercisable outside
    market hours. The real cron/loop callers leave it False.

    Returns the events pushed (empty list if the market's closed or
    nothing is deployed), which callers can log/return as-is.
    """
    if not force and not is_market_open():
        return []

    stmt = select(StrategyModel).where(
        StrategyModel.is_active.is_(True),
        StrategyModel.symbol.is_not(None),
    )
    rows = (await db.execute(stmt)).scalars().all()

    events = [{"strategy_id": row.id, "symbol": row.symbol} for row in rows]
    for event in events:
        await push_event(event, client=client)

    return events


async def run_trigger_loop(
    session_factory,
    *,
    interval_seconds: float = 60.0,
    client: redis_asyncio.Redis | None = None,
    iterations: int | None = None,
) -> None:
    """Always-on deployment mode: poll forever (or `iterations` times,
    for tests), sleeping `interval_seconds` between checks.
    `session_factory` is typically `app.db.async_session_factory` — a
    fresh session per iteration, never held open across the sleep.
    """
    count = 0
    while iterations is None or count < iterations:
        try:
            async with session_factory() as db:
                events = await run_trigger_once(db, client=client)
                if events:
                    logger.info("Trigger: pushed %d event(s)", len(events))
        except Exception:
            logger.exception("Trigger loop iteration failed")
        count += 1
        if iterations is None or count < iterations:
            await asyncio.sleep(interval_seconds)
