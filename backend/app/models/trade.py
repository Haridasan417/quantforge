import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class TradeSide(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class Trade(Base):
    """A simulated fill written by the Executor (Phase 6).

    `simulated` defaults to True and, per CLAUDE.md's non-negotiable rule,
    is expected to be True for every row this project ever writes — there
    is no live order-placement path anywhere in QuantForge.
    """

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    side: Mapped[TradeSide] = mapped_column(Enum(TradeSide, native_enum=False))
    qty: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    price: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    strategy: Mapped["Strategy"] = relationship(back_populates="trades")

    def __repr__(self) -> str:
        return f"<Trade id={self.id} {self.side} {self.qty} {self.symbol} @ {self.price}>"
