from typing import Any

from pydantic import BaseModel, Field


class StrategyInfo(BaseModel):
    name: str
    description: str
    source: str  # "builtin" (registered class) | "graph" (saved Strategy Builder graph)
    config_schema: dict[str, Any]
    # Actual current config values — only populated for "graph" entries,
    # since a "builtin" entry describes a class (many possible configs),
    # not one instance. Lets the builder UI reload a saved graph.
    config: dict[str, Any] | None = None


class StrategiesResponse(BaseModel):
    strategies: list[StrategyInfo]


class IndicatorField(BaseModel):
    field: str
    label: str
    params: dict[str, Any]


class StrategyIndicatorsResponse(BaseModel):
    indicators: list[IndicatorField]
    comparators: list[str]
    actions: list[str]


class GraphPayload(BaseModel):
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


class SaveGraphStrategyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    graph: GraphPayload


class ActivateStrategyRequest(BaseModel):
    """Deploys `strategy_id` (a registry name — a built-in like
    "ma_crossover" or a saved graph's "graph:<id>") on `symbol`, making
    it visible to the Trigger service's poll. `is_active=False` deploys
    it in a paused state (or pauses an already-deployed one) without
    losing its saved config/symbol."""

    strategy_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1, max_length=32)
    is_active: bool = True
    # Only used for built-ins (a graph's config already lives on its
    # saved row) — validated against that strategy's config_schema, and
    # replaces any config from a previous activation of this deployment.
    config: dict[str, Any] | None = None


class ActivateStrategyResponse(BaseModel):
    deployment_id: int  # the `strategies.id` row Trade.strategy_id will reference
    strategy_id: str
    symbol: str
    is_active: bool
