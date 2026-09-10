from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.strategy import Strategy as StrategyModel
from app.schemas.strategies import (
    IndicatorField,
    SaveGraphStrategyRequest,
    StrategiesResponse,
    StrategyIndicatorsResponse,
    StrategyInfo,
)
from app.strategy_engine import (
    COMPARATORS,
    INDICATOR_FIELDS,
    GraphStrategy,
    GraphStrategyConfig,
    GraphStrategyError,
    list_strategies,
    list_strategy_instances,
    register_strategy_instance,
)

router = APIRouter(prefix="/api", tags=["strategies"])


@router.get("/strategies", response_model=StrategiesResponse)
async def get_strategies() -> StrategiesResponse:
    """Every registered strategy — built-in classes and saved Strategy
    Builder graphs alike — plus its config as JSON Schema. The Strategy
    Builder (Phase 4) and, later, the backtest/execution config forms
    (Phase 5/6) render straight from this, no per-strategy frontend
    code needed."""
    infos = [
        StrategyInfo(
            name=name,
            description=(cls.__doc__ or "").strip(),
            source="builtin",
            config_schema=cls.config_schema().model_json_schema(),
        )
        for name, cls in sorted(list_strategies().items())
    ]
    infos += [
        StrategyInfo(
            name=name,
            description=(type(instance).__doc__ or "").strip(),
            source="graph",
            config_schema=type(instance).config_schema().model_json_schema(),
            config=instance.config.model_dump(),
        )
        for name, instance in sorted(list_strategy_instances().items())
    ]
    return StrategiesResponse(strategies=infos)


@router.get("/strategies/indicators", response_model=StrategyIndicatorsResponse)
async def get_strategy_indicators() -> StrategyIndicatorsResponse:
    """What the Strategy Builder's ConditionNode dropdown offers,
    sourced from the same indicator implementations GraphStrategy
    actually evaluates against — the UI can never drift out of sync
    with what the backend can compute."""
    return StrategyIndicatorsResponse(
        indicators=[
            IndicatorField(field=field, label=meta["label"], params=meta["params"])
            for field, meta in INDICATOR_FIELDS.items()
        ],
        comparators=list(COMPARATORS.keys()),
        actions=["BUY", "SELL"],
    )


@router.post("/strategies/custom", response_model=StrategyInfo, status_code=201)
async def save_custom_strategy(
    payload: SaveGraphStrategyRequest,
    db: AsyncSession = Depends(get_db),
) -> StrategyInfo:
    """Persist a Strategy Builder graph and make it runnable immediately.

    Validates the graph up front (422 on a broken one, rather than
    discovering it later inside a backtest), stores it as a `strategies`
    row (`type="graph"`), and registers a `GraphStrategy` instance under
    `f"graph:{id}"` so it shows up in `GET /api/strategies` and is
    resolvable by name for backtest/execution — exactly like a built-in.
    """
    config = GraphStrategyConfig(nodes=payload.graph.nodes, edges=payload.graph.edges)

    try:
        GraphStrategy(config).validate_graph()
    except GraphStrategyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    row = StrategyModel(name=payload.name, type="graph", config=config.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)

    registry_name = f"graph:{row.id}"
    register_strategy_instance(registry_name, GraphStrategy(config))

    return StrategyInfo(
        name=registry_name,
        description=f"Visual strategy: {row.name}",
        source="graph",
        config_schema=GraphStrategy.config_schema().model_json_schema(),
        config=config.model_dump(),
    )
