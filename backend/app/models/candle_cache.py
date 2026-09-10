from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CandleCache(Base):
    """Caches the raw OHLCV response for one exact (symbol, interval,
    start, end) request, so a repeat request for that same range is
    served from Postgres instead of re-hitting yfinance/nsepy.

    See CLAUDE.md's "Data Service caching" note for why this is a
    Postgres table rather than a Redis TTL cache: historical bars don't
    change once the range is in the past, so there's nothing to expire,
    and Neon is already provisioned for the ORM models above.
    """

    __tablename__ = "candle_cache"
    __table_args__ = (
        UniqueConstraint("symbol", "interval", "start", "end", name="uq_candle_cache_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    interval: Mapped[str] = mapped_column(String(16))
    start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[list] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<CandleCache {self.symbol} {self.interval} {self.start}..{self.end}>"
