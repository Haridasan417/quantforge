"""Always-on deployment mode: `python -m app.executor_service` runs the
Executor loop forever, draining the Redis queue once every
`EXECUTOR_POLL_SECONDS` (default 60s). Pairs with `python -m
app.trigger_service` on the same persistent host; for the
cron/GitHub-Actions deployment mode, `POST /trigger/run-once` runs both
the trigger and one executor drain in a single request instead.
"""
from __future__ import annotations

import asyncio
import logging
import os

from app.db import async_session_factory
from app.executor_service.executor import run_executor_loop

logging.basicConfig(level=logging.INFO)


def main() -> None:
    interval = float(os.environ.get("EXECUTOR_POLL_SECONDS", "60"))
    asyncio.run(run_executor_loop(async_session_factory, interval_seconds=interval))


if __name__ == "__main__":
    main()
