"""Redis-backed queue connecting the Trigger service (producer) and the
Executor service (consumer).

A single list key, FIFO via RPUSH/LPOP — no consumer groups, no
ack/retry machinery. That's deliberate: at this project's scale a
dropped event just waits for the next Trigger poll to re-evaluate the
same strategy/symbol anyway, since strategies are re-evaluated on a
timer (or a single cron hit), not edge-triggered — losing one event
isn't a correctness problem, just a missed cycle.

Lives at the top of `app/` (a sibling of `db.py`/`config.py`) rather
than nested inside `trigger_service/` or `executor_service/`, since both
of those packages need to agree on the same key/encoding without an
awkward cross-import between sibling service packages.
"""
from __future__ import annotations

import json
from typing import Any

import redis.asyncio as redis

from app.config import settings

# Phase 8: a pub/sub channel (not a list) -- unlike the FIFO queue
# above, a dashboard update has no "consumer" to hand off to and no
# reason to persist if nobody's listening right this second. PUBLISH
# to a channel with zero subscribers is a normal no-op, not an error
# -- exactly "nobody's watching the dashboard right now", which is
# fine.
EVENT_QUEUE_KEY = "quantforge:trigger-events"
DASHBOARD_UPDATES_CHANNEL = "quantforge:dashboard-updates"

_redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """Lazily-created module-level client, reused across calls in a
    long-running process (the loop deployment mode). Tests never touch
    this — they pass `client=` explicitly (typically a `fakeredis`
    instance) to every function below."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


async def push_event(event: dict[str, Any], *, client: redis.Redis | None = None) -> None:
    """Producer side (Trigger service): enqueue one `{strategy_id,
    symbol}` event."""
    await (client or get_redis()).rpush(EVENT_QUEUE_KEY, json.dumps(event))


async def pop_event(*, client: redis.Redis | None = None) -> dict[str, Any] | None:
    """Consumer side (Executor service): dequeue the oldest event, or
    `None` if the queue is empty."""
    raw = await (client or get_redis()).lpop(EVENT_QUEUE_KEY)
    return json.loads(raw) if raw else None


async def queue_length(*, client: redis.Redis | None = None) -> int:
    return await (client or get_redis()).llen(EVENT_QUEUE_KEY)


async def publish_update(event: dict[str, Any], *, client: redis.Redis | None = None) -> None:
    """Producer side (Executor's `process_event`, Phase 8): broadcast one
    `{"type": "execution", "trade": {...}, "portfolio": {...}}` event to
    every dashboard currently subscribed (`GET /api/ws/dashboard`).
    Fire-and-forget by design -- callers wrap this so a Redis hiccup
    never blocks or fails an already-committed trade, only the live
    push is missed (the next `GET /api/dashboard/*` request on refresh
    still reflects it, since Postgres is the durable record either
    way)."""
    await (client or get_redis()).publish(DASHBOARD_UPDATES_CHANNEL, json.dumps(event, default=str))
