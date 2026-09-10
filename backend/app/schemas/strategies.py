from typing import Any

from pydantic import BaseModel, Field


class StrategyInfo(BaseModel):
    name: str  # registry name: a built-in's class name, or "graph:<id>"
    description: str
    source: str  # "builtin" (registered class) | "graph" (saved Strategy Builder graph)
    config_schema: dict[str, Any]
    # Actual current config values — only populated for "graph" entries,
    # since a "builtin" entry describes a class (many possible configs),
    # not one instance. Lets the builder UI reload a saved graph.
    config: dict[str, Any] | None = None
    # The name the user gave this strategy when saving it in the Strategy
    # Builder (SaveGraphStrategyRequest.name) — only set for "graph"
    # entries; a built-in has no such user-chosen name. `name` above has
    # to stay the stable "graph:<id>" registry key (backtest/activate/etc.
    # all address a graph strategy by it), so this is a separate field
    # rather than replacing `name` outright — the frontend shows
    # `display_name ?? name` wherever a strategy's label appears, but
    # still sends `name` in any request.
    display_name: str | None = None


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


class DeploymentInfo(BaseModel):
    """One `strategies` row that's been turned into a deployment (see
    `ActivateStrategyRequest`) — active or paused. Mirrors
    `ActivateStrategyResponse` plus the stored `config`, so a "Deploy
    Strategy" UI can list existing deployments and re-post a toggle
    (pause/resume) without the caller needing to already know or
    re-enter that deployment's config."""

    deployment_id: int
    strategy_id: str
    symbol: str
    is_active: bool
    config: dict[str, Any]


class DeploymentsResponse(BaseModel):
    deployments: list[DeploymentInfo]
