"""Postgres-backed cache in front of `fetch_candles`.

Keyed on the exact (symbol, interval, start, end) request. A repeat
request for the same range is served straight from `candle_cache`
without touching yfinance/nsepy; a request for a different range (even
an overlapping one) is treated as a cache miss and fetched fresh. See
CandleCache's docstring and CLAUDE.md's "Data Service caching" note for
why this is a Postgres table rather than a Redis TTL cache.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.data_service.sources import fetch_candles
from app.models.candle_cache import CandleCache


def _df_to_payload(df: pd.DataFrame) -> list[dict]:
    records = df.reset_index()
    records["ts"] = records["ts"].apply(lambda ts: ts.isoformat())
    return records.to_dict(orient="records")


def _payload_to_df(payload: list[dict]) -> pd.DataFrame:
    if not payload:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(payload)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.set_index("ts")


async def get_candles_cached(
    db: AsyncSession, symbol: str, interval: str, start: datetime, end: datetime
) -> pd.DataFrame:
    stmt = select(CandleCache).where(
        CandleCache.symbol == symbol,
        CandleCache.interval == interval,
        CandleCache.start == start,
        CandleCache.end == end,
    )
    cached = (await db.execute(stmt)).scalar_one_or_none()
    if cached is not None:
        return _payload_to_df(cached.payload)

    df = fetch_candles(symbol, interval, start, end)

    # ON CONFLICT DO NOTHING: two concurrent requests for the same new
    # range both fetch from source (acceptable), but only one persists —
    # the unique constraint on (symbol, interval, start, end) prevents a
    # duplicate-row race rather than raising an IntegrityError.
    stmt = (
        pg_insert(CandleCache)
        .values(
            symbol=symbol,
            interval=interval,
            start=start,
            end=end,
            payload=_df_to_payload(df),
        )
        .on_conflict_do_nothing(constraint="uq_candle_cache_range")
    )
    await db.execute(stmt)
    await db.commit()

    return df
