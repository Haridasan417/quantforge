from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.strategy import Strategy as StrategyModel
from app.schemas.strategies import (
    ActivateStrategyRequest,
    ActivateStrategyResponse,
    DeploymentInfo,
    DeploymentsResponse,
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
    get_strategy,
    list_strategies,
    list_strategy_instances,
    register_strategy_instance,
)

router = APIRouter(prefix="/api", tags=["strategies"])


@router.get("/strategies", response_model=StrategiesResponse)
async def get_strategies(db: AsyncSession = Depends(get_db)) -> StrategiesResponse:
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

    # The in-memory instance registry only knows a graph strategy by its
    # "graph:<id>" key (see GraphStrategy/register_strategy_instance) — it
    # never carries the name the user actually typed into the Strategy
    # Builder's "Strategy name" field when saving. That name only lives on
    # the `strategies` row itself, so it has to be looked up here rather
    # than read off the instance; without this, every saved graph showed
    # up everywhere (this list, the Backtest/Deploy dropdowns) as the bare
    # "graph:<id>" registry key with no way to tell two saved graphs apart
    # by name.
    graph_ids = [int(name.split(":", 1)[1]) for name in list_strategy_instances() if name.startswith("graph:")]
    saved_names: dict[int, str] = {}
    if graph_ids:
        rows = (await db.execute(select(StrategyModel).where(StrategyModel.id.in_(graph_ids)))).scalars().all()
        saved_names = {row.id: row.name for row in rows}

    infos += [
        StrategyInfo(
            name=name,
            description=(type(instance).__doc__ or "").strip(),
            source="graph",
            config_schema=type(instance).config_schema().model_json_schema(),
            config=instance.config.model_dump(),
            display_name=saved_names.get(int(name.split(":", 1)[1])),
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
        display_name=row.name,
    )


@router.post("/strategies/activate", response_model=ActivateStrategyResponse)
async def activate_strategy(
    payload: ActivateStrategyRequest,
    db: AsyncSession = Depends(get_db),
) -> ActivateStrategyResponse:
    """Turns a registered strategy (built-in class or saved graph) into
    a *deployment* the Trigger service will poll: a `strategies` row
    with `symbol` set and `is_active=True`. Without this, `POST
    /trigger/run-once` (and the always-on Trigger loop) would have
    nothing to ever find — see CLAUDE.md's Phase 6 section.

    A saved graph (`"graph:<id>"`) already has its own row from `POST
    /api/strategies/custom`, so activating it updates that row in
    place. A built-in (e.g. "ma_crossover") has no row until it's
    deployed on a symbol for the first time; find-or-create is keyed on
    `(type, symbol)` so the same built-in can be deployed on multiple
    symbols as separate rows, and re-activating the same (type, symbol)
    pair updates it rather than duplicating it.
    """
    strategy_id = payload.strategy_id
    symbol = payload.symbol.strip().upper()

    if strategy_id.startswith("graph:"):
        try:
            row_id = int(strategy_id.split(":", 1)[1])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Malformed graph strategy id: {strategy_id!r}") from exc

        row = await db.get(StrategyModel, row_id)
        if row is None or row.type != "graph":
            raise HTTPException(status_code=404, detail=f"Unknown strategy: {strategy_id!r}")

        row.symbol = symbol
        row.is_active = payload.is_active
        if payload.config is not None:
            try:
                GraphStrategy(GraphStrategyConfig(**payload.config)).validate_graph()
            except (GraphStrategyError, ValidationError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            row.config = payload.config
    else:
        try:
            cls = get_strategy(strategy_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        config = payload.config if payload.config is not None else {}
        try:
            cls(config)  # validates against config_schema()
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid config for {strategy_id!r}: {exc}") from exc

        existing = (
            await db.execute(select(StrategyModel).where(StrategyModel.type == strategy_id, StrategyModel.symbol == symbol))
        ).scalar_one_or_none()

        if existing is None:
            row = StrategyModel(
                name=f"{strategy_id} / {symbol}",
                type=strategy_id,
                config=config,
                symbol=symbol,
                is_active=payload.is_active,
            )
            db.add(row)
        else:
            row = existing
            row.config = config
            row.is_active = payload.is_active

    await db.commit()
    await db.refresh(row)

    return ActivateStrategyResponse(
        deployment_id=row.id,
        strategy_id=strategy_id,
        symbol=symbol,
        is_active=row.is_active,
    )


@router.get("/strategies/deployments", response_model=DeploymentsResponse)
async def get_deployments(db: AsyncSession = Depends(get_db)) -> DeploymentsResponse:
    """Every strategy row that's been turned into a deployment (`symbol`
    set — see `POST /api/strategies/activate` above), active or paused.
    This is what a "Deploy Strategy" UI lists and lets a user
    pause/resume — the Trigger service itself only ever queries
    `is_active=True` rows (`app/trigger_service/trigger.py`), but a
    paused deployment is worth surfacing too so it can be resumed
    without re-entering its config from scratch.
    """
    rows = (
        (
            await db.execute(
                select(StrategyModel).where(StrategyModel.symbol.is_not(None)).order_by(StrategyModel.id.desc())
            )
        )
        .scalars()
        .all()
    )
    return DeploymentsResponse(
        deployments=[
            DeploymentInfo(
                deployment_id=row.id,
                # Mirrors activate_strategy's own strategy_id convention: a
                # graph row's `type` is always the literal "graph", so the
                # registry name has to be rebuilt as "graph:<id>"; every
                # other row's `type` already *is* the registry name (it was
                # set to `strategy_id` verbatim when the row was created).
                strategy_id=f"graph:{row.id}" if row.type == "graph" else row.type,
                symbol=row.symbol,
                is_active=row.is_active,
                config=row.config,
            )
            for row in rows
        ]
    )
