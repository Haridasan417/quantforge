"""Import every model module here so Base.metadata (and therefore
`alembic revision --autogenerate`) sees all of them, and so relationship()
string references between models resolve.
"""
from app.models.base import Base
from app.models.candle_cache import CandleCache
from app.models.portfolio_snapshot import PortfolioSnapshot
from app.models.rl_checkpoint import RLCheckpoint
from app.models.strategy import Strategy
from app.models.trade import Trade, TradeSide

__all__ = [
    "Base",
    "CandleCache",
    "PortfolioSnapshot",
    "RLCheckpoint",
    "Strategy",
    "Trade",
    "TradeSide",
]
