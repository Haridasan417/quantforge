import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.backtest_engine import BacktestError, resolve_strategy, run_backtest
from app.data_service import DataUnavailableError, get_candles_cached
from app.db import get_db
from app.schemas.backtest import BacktestRequest, BacktestResponse

router = APIRouter(prefix="/api", tags=["backtest"])


@router.post("/backtest", response_model=BacktestResponse)
async def run_backtest_endpoint(
    payload: BacktestRequest,
    db: AsyncSession = Depends(get_db),
) -> BacktestResponse:
    """Resolve `strategy_id` (a built-in name or a saved `"graph:<id>"`),
    fetch its OHLCV history through the same cached path `/api/candles`
    uses, and run it through backtrader. `run_backtest` is synchronous
    (backtrader has no async API) and can take real time for a long
    date range, so it runs in a worker thread rather than blocking the
    event loop."""
    try:
        strategy = resolve_strategy(payload.strategy_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        df = await get_candles_cached(db, payload.symbol, payload.interval, payload.start, payload.end)
    except DataUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        result = await asyncio.to_thread(run_backtest, strategy, df)
    except BacktestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return BacktestResponse(
        strategy_id=payload.strategy_id,
        symbol=payload.symbol,
        interval=payload.interval,
        **result,
    )
