from fastapi import APIRouter

from app.schemas.strategies import StrategiesResponse, StrategyInfo
from app.strategy_engine import list_strategies

router = APIRouter(prefix="/api", tags=["strategies"])


@router.get("/strategies", response_model=StrategiesResponse)
async def get_strategies() -> StrategiesResponse:
    """Every registered strategy plus its config as JSON Schema — the
    Strategy Builder (Phase 4) renders config forms / node parameters
    directly from this, no per-strategy frontend code needed."""
    strategies = [
        StrategyInfo(
            name=name,
            description=(cls.__doc__ or "").strip(),
            config_schema=cls.config_schema().model_json_schema(),
        )
        for name, cls in sorted(list_strategies().items())
    ]
    return StrategiesResponse(strategies=strategies)
