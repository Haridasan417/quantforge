from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.executor_service import run_executor_once
from app.executor_service.ltp_provider import LTPProviderError
from app.schemas.trigger import TriggerRunResponse
from app.trigger_service import is_market_open, run_trigger_once

# Deliberately NOT under the `/api` prefix the other routers use —
# CLAUDE.md's "Free-tier notes" documents this exact path
# ("hitting a `/trigger/run-once` endpoint") as the single-hit
# deployment mode for a scheduled GitHub Action / external cron
# (e.g. cron-job.org) on Render's free tier, where a long-running
# Trigger/Executor loop process isn't an option.
router = APIRouter(prefix="/trigger", tags=["trigger"])


@router.post("/run-once", response_model=TriggerRunResponse)
async def trigger_run_once(
    force: bool = False,
    db: AsyncSession = Depends(get_db),
) -> TriggerRunResponse:
    """Runs one full Trigger+Executor cycle synchronously in a single
    request: poll deployed strategies (skipped outside NSE hours unless
    `force=true`), push their evaluate-events, then immediately drain
    the queue through the Executor. This is the entire "single external
    trigger hit" deployment mode — the always-on alternative is `python
    -m app.trigger_service` / `python -m app.executor_service` running
    as persistent loops instead (see those packages' `__main__.py`).
    """
    market_open = force or is_market_open()

    events = await run_trigger_once(db, force=force)

    try:
        trades = await run_executor_once(db)
    except LTPProviderError as exc:
        # Expected when SmartAPI isn't configured yet (no API key, or no
        # symboltoken for the symbol that got approved) — surfaced as a
        # clear 502 rather than an opaque 500, since the Trigger side of
        # this request already succeeded.
        raise HTTPException(status_code=502, detail=f"LTP provider unavailable: {exc}") from exc

    return TriggerRunResponse(
        market_open=market_open,
        events_pushed=len(events),
        trades_executed=len(trades),
    )
