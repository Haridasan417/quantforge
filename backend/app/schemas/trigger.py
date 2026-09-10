from pydantic import BaseModel


class TriggerRunResponse(BaseModel):
    # False when the NSE-hours gate skipped the trigger poll (and
    # `force` wasn't set) — the caller (a cron dashboard, or a manual
    # demo click) can tell a market-hours no-op apart from "nothing was
    # deployed".
    market_open: bool
    events_pushed: int
    trades_executed: int
