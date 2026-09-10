import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api.backtest import router as backtest_router
from app.api.candles import router as candles_router
from app.api.strategies import router as strategies_router
from app.config import settings
from app.db import async_session_factory
from app.models.strategy import Strategy as StrategyModel
from app.strategy_engine import GraphStrategy, GraphStrategyConfig, register_strategy_instance

logger = logging.getLogger(__name__)


async def _load_saved_graph_strategies() -> None:
    """Re-register every saved Strategy Builder graph (`type="graph"`)
    on boot. The instance registry (`strategy_engine.registry`) lives in
    process memory and starts empty on every restart, but the graphs
    themselves are durable in Postgres — without this, a saved strategy
    would silently vanish from `GET /api/strategies` (and be unusable by
    backtest/execution) the moment the API process restarted.
    """
    try:
        async with async_session_factory() as session:
            result = await session.execute(select(StrategyModel).where(StrategyModel.type == "graph"))
            rows = result.scalars().all()
    except Exception:
        # Missing/unreachable DB shouldn't prevent the API from booting
        # (e.g. running the test suite or a quick local check without
        # Postgres up) — just start with no saved graphs registered.
        logger.warning("Could not load saved graph strategies on startup", exc_info=True)
        return

    for row in rows:
        try:
            config = GraphStrategyConfig(**row.config)
            instance = GraphStrategy(config)
            instance.validate_graph()
        except Exception:
            logger.warning("Skipping malformed saved graph strategy id=%r", row.id, exc_info=True)
            continue
        register_strategy_instance(f"graph:{row.id}", instance)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await _load_saved_graph_strategies()
    yield


app = FastAPI(title="QuantForge API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(candles_router)
app.include_router(strategies_router)
app.include_router(backtest_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
