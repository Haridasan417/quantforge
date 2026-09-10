"""Dashboard (Phase 8): REST reads for the initial page load
(`GET /api/dashboard/overview`, `GET /api/dashboard/trades`) plus a
WebSocket (`/api/ws/dashboard`) that pushes every subsequent Executor
fill live, so the page never needs to poll for an update the way
`CandleChart` does (see CLAUDE.md's Charting section) — REST answers
"what's the state right now", the socket answers "tell me the moment
it changes".
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from app.dashboard.metrics import compute_live_metrics, compute_pnl_summary
from app.dashboard.queries import fetch_all_trades, fetch_portfolio_history, fetch_recent_trades
from app.db import get_db
from app.queue import DASHBOARD_UPDATES_CHANNEL, get_redis
from app.schemas.dashboard import (
    DashboardOverviewResponse,
    EquityCurvePoint,
    LiveMetricsSchema,
    PnLSummarySchema,
    TradeLogEntry,
    TradeLogResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard/overview", response_model=DashboardOverviewResponse)
async def get_dashboard_overview(db: AsyncSession = Depends(get_db)) -> DashboardOverviewResponse:
    """P&L summary + Sharpe/max-drawdown/win-rate cards + the equity
    curve, all computed over the *live* paper-trading history (not a
    backtest) — see `app.dashboard.metrics`."""
    snapshots = await fetch_portfolio_history(db)
    trades = await fetch_all_trades(db)

    pnl = compute_pnl_summary(snapshots)
    metrics = compute_live_metrics(snapshots, trades)

    return DashboardOverviewResponse(
        pnl=PnLSummarySchema(
            initial_cash=pnl.initial_cash,
            current_equity=pnl.current_equity,
            cash=pnl.cash,
            total_pnl=pnl.total_pnl,
            total_pnl_pct=pnl.total_pnl_pct,
            holdings=pnl.holdings,
        ),
        metrics=LiveMetricsSchema(
            sharpe=metrics.sharpe,
            max_drawdown=metrics.max_drawdown,
            win_rate=metrics.win_rate,
            total_trades=metrics.total_trades,
            closed_trades=metrics.closed_trades,
        ),
        equity_curve=[EquityCurvePoint(ts=s.timestamp.isoformat(), equity=float(s.equity)) for s in snapshots],
    )


@router.get("/dashboard/trades", response_model=TradeLogResponse)
async def get_dashboard_trades(limit: int = 200, db: AsyncSession = Depends(get_db)) -> TradeLogResponse:
    """The trade log table — newest first, capped at `limit` (default
    200; there's no pagination yet, matching this project's academic
    scope rather than a production trade blotter)."""
    trades = await fetch_recent_trades(db, limit=limit)
    return TradeLogResponse(
        trades=[
            TradeLogEntry(
                id=t.id,
                strategy_id=t.strategy_id,
                symbol=t.symbol,
                side=t.side.value,
                qty=float(t.qty),
                price=float(t.price),
                executed_at=t.executed_at.isoformat(),
            )
            for t in trades
        ]
    )


@router.websocket("/ws/dashboard")
async def dashboard_updates_ws(websocket: WebSocket) -> None:
    """Forwards every message published to `DASHBOARD_UPDATES_CHANNEL`
    (see `app.queue.publish_update`, called from
    `executor_service.process_event` right after each fill is committed)
    verbatim to this one connected client — the message is already the
    JSON text the Executor built (`{"type": "execution", "trade": {...},
    "portfolio": {...}}`), so this never re-serializes it; the frontend
    merges it straight into whatever `GET /api/dashboard/overview`
    already loaded.

    Purely server-push — the client has nothing meaningful to send —
    but a concurrent receive loop still runs alongside the forward loop:
    it's the only reliable way to notice the client disconnected, since
    `websocket.send_text` alone doesn't consistently raise on a closed
    socket."""
    await websocket.accept()
    pubsub = get_redis().pubsub()
    await pubsub.subscribe(DASHBOARD_UPDATES_CHANNEL)

    async def _forward() -> None:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"])

    async def _watch_for_disconnect() -> None:
        while True:
            await websocket.receive_text()  # the client sends nothing; this just detects a close

    forward_task = asyncio.ensure_future(_forward())
    watch_task = asyncio.ensure_future(_watch_for_disconnect())
    try:
        await asyncio.wait({forward_task, watch_task}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (forward_task, watch_task):
            task.cancel()
        await asyncio.gather(forward_task, watch_task, return_exceptions=True)
        try:
            await pubsub.unsubscribe(DASHBOARD_UPDATES_CHANNEL)
            await pubsub.aclose()
        except Exception:
            logger.warning("dashboard ws: error cleaning up pubsub", exc_info=True)
