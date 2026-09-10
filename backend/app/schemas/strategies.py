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
