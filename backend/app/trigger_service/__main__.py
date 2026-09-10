"""Always-on deployment mode: `python -m app.trigger_service` runs the
Trigger loop forever, polling once every `TRIGGER_POLL_SECONDS` (default
60s). Intended for a persistent host (e.g. an Oracle Cloud Always-Free
VM) — see CLAUDE.md's "Free-tier notes" for why this isn't how the
Render-hosted API itself is deployed. For the cron/GitHub-Actions
deployment mode, hit `POST /trigger/run-once` instead (app/api/trigger.py).
"""
from __future__ import annotations

import asyncio
import logging
import os

from app.db import async_session_factory
from app.trigger_service.trigger import run_trigger_loop

logging.basicConfig(level=logging.INFO)


def main() -> None:
    interval = float(os.environ.get("TRIGGER_POLL_SECONDS", "60"))
    asyncio.run(run_trigger_loop(async_session_factory, interval_seconds=interval))


if __name__ == "__main__":
    main()
