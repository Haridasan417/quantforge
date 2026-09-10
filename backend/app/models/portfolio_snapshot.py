from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PortfolioSnapshot(Base):
    """A point-in-time view of the paper-trading portfolio, written by the
    Executor (Phase 6) after every simulated fill. The Dashboard (Phase 8)
    reads the history of these for the equity curve.
    """

    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    cash: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    holdings: Mapped[dict] = mapped_column(JSONB, default=dict)
    equity: Mapped[Decimal] = mapped_column(Numeric(18, 6))

    def __repr__(self) -> str:
        return f"<PortfolioSnapshot id={self.id} equity={self.equity} at={self.timestamp}>"
