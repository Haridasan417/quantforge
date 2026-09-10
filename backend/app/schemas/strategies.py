from typing import Any

from pydantic import BaseModel


class StrategyInfo(BaseModel):
    name: str
    description: str
    config_schema: dict[str, Any]


class StrategiesResponse(BaseModel):
    strategies: list[StrategyInfo]
