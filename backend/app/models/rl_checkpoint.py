from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class RLCheckpoint(Base):
    """Metadata for a trained RL policy (Phase 7). Per CLAUDE.md's free-tier
    note, the binary itself lives in Drive or a release asset — only
    `file_path` (a pointer to it) and metrics live in Postgres.
    """

    __tablename__ = "rl_checkpoints"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"), index=True)
    version: Mapped[int]
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)
    file_path: Mapped[str] = mapped_column(String(500))

    strategy: Mapped["Strategy"] = relationship(back_populates="checkpoints")

    def __repr__(self) -> str:
        return f"<RLCheckpoint id={self.id} strategy_id={self.strategy_id} v{self.version}>"
