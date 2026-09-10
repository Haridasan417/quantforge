from datetime import datetime
from typing import Any

from pydantic import BaseModel


class CandlesResponse(BaseModel):
    symbol: str
    interval: str
    start: datetime
    end: datetime
    indicators: list[str]
    candles: list[dict[str, Any]]
