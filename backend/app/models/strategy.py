from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Strategy(Base):
    """A registered strategy instance: built-in (Phase 3), a saved visual
    graph from the Strategy Builder (Phase 4), or an RL policy (Phase 7).
    `type` names which kind (e.g. "ma_crossover", "graph", "rl"); `config`
    holds whatever that type's config_schema validates.

    `symbol`/`is_active` (Phase 6) turn a registered strategy into a
    *deployment*: a specific strategy+config+symbol combination the
    Trigger service should poll. Most rows (backtest-only strategies,
    unsaved builtins) leave these null/false and are invisible to the
    Trigger service's query — see `app/trigger_service/trigger.py` and
    `POST /api/strategies/activate`.
    """

    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(100), index=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    trades: Mapped[list["Trade"]] = relationship(back_populates="strategy")
    checkpoints: Mapped[list["RLCheckpoint"]] = relationship(back_populates="strategy")

    def __repr__(self) -> str:
        return f"<Strategy id={self.id} name={self.name!r} type={self.type!r}>"
