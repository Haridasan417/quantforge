import math
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.data_service import DataUnavailableError, compute_indicators, get_candles_cached
from app.db import get_db
from app.schemas.candles import CandlesResponse

router = APIRouter(prefix="/api", tags=["candles"])


def _parse_indicators(indicators: str | None) -> list[str]:
    if not indicators:
        return []
    return [name.strip().lower() for name in indicators.split(",") if name.strip()]


def _clean(value: float) -> float | None:
    """NaN/inf aren't valid JSON; indicator warm-up rows produce NaN
    (e.g. the first 13 rows of a 14-period RSI) so we null them out."""
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return None
    return value


@router.get("/candles", response_model=CandlesResponse)
async def get_candles(
    symbol: str,
    start: datetime,
    end: datetime,
    interval: str = "1d",
    indicators: str | None = Query(
        default=None, description="Comma-separated: rsi,macd,ema"
    ),
    db: AsyncSession = Depends(get_db),
) -> CandlesResponse:
    indicator_list = _parse_indicators(indicators)

    try:
        df = await get_candles_cached(db, symbol, interval, start, end)
    except DataUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if indicator_list:
        df = compute_indicators(df, indicator_list)

    records = df.reset_index()
    records["ts"] = records["ts"].apply(lambda ts: ts.isoformat())
    candles = [
        {k: _clean(v) for k, v in row.items()} for row in records.to_dict(orient="records")
    ]

    return CandlesResponse(
        symbol=symbol,
        interval=interval,
        start=start,
        end=end,
        indicators=indicator_list,
        candles=candles,
    )
