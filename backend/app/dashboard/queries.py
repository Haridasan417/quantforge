"""DB reads behind the Dashboard (Phase 8) — pulled out of
`app/api/dashboard.py` so tests can monkeypatch these functions
directly (same convention `api/backtest.py`'s monkeypatched
`get_candles_cached` already established), rather than needing a
query-type-aware fake `AsyncSession`.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portfolio_snapshot import PortfolioSnapshot
from app.models.trade import Trade


async def fetch_portfolio_history(db: AsyncSession) -> list[PortfolioSnapshot]:
    """Every snapshot, oldest first — the equity curve *and* the P&L
    summary's "current" figures (the last row) both come from this one
    read."""
    stmt = select(PortfolioSnapshot).order_by(PortfolioSnapshot.timestamp.asc())
    return list((await db.execute(stmt)).scalars().all())


async def fetch_all_trades(db: AsyncSession) -> list[Trade]:
    """Every trade ever written, oldest first — used for the win-rate
    metric (`dashboard.metrics.compute_live_metrics`), which needs the
    *full* history to stay accurate; `fetch_recent_trades` below is a
    display-only subset and would quietly skew a win rate computed from
    it once trade history outgrows its `limit`."""
    stmt = select(Trade).order_by(Trade.executed_at.asc())
    return list((await db.execute(stmt)).scalars().all())


async def fetch_recent_trades(db: AsyncSession, limit: int = 200) -> list[Trade]:
    """Newest first, capped at `limit` — what the trade log table
    actually renders."""
    stmt = select(Trade).order_by(Trade.executed_at.desc()).limit(limit)
    return list((await db.execute(stmt)).scalars().all())
