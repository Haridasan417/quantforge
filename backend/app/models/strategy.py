from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Strategy(Base):
    """A registered strategy instance: built-in (Phase 3), a saved visual
    graph from the Strategy Builder (Phase 4), or an RL policy (Phase 7).
    `type` names which kind (e.g. "ma_crossover", "graph", "rl"); `config`
    holds whatever that type's config_schema validates.
    """

    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(100), index=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    trades: Mapped[list["Trade"]] = relationship(back_populates="strategy")
    checkpoints: Mapped[list["RLCheckpoint"]] = relationship(back_populates="strategy")

    def __repr__(self) -> str:
        return f"<Strategy id={self.id} name={self.name!r} type={self.type!r}>"
