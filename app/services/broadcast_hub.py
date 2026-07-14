"""Cross-instance broadcast hub for WebSocket messages.

In a single-process deployment (the default) messages are delivered directly to
the in-process ``ConnectionManager``. When ``REDIS_URL`` is configured the hub
uses Redis pub/sub so messages reach WebSocket connections on *every* running
instance — required once the app is scaled to more than one worker.

The hub is intentionally transport-agnostic: ``ConnectionManager`` only calls
``publish(conversation_id, message)`` and registers a local delivery callback.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable, Optional

from app.core.config import settings

log = logging.getLogger("broadcast")

_CHANNEL = "servicesync:ws"

# Local delivery callback registered by ConnectionManager:
#   (conversation_id, message, exclude_user_id) -> None
LocalDeliverer = Callable[[int, str, Optional[int]], Awaitable[None]]
_local_deliver: Optional[LocalDeliverer] = None

_redis = None
_pubsub = None
_redis_task = None


async def startup() -> None:
    """Connect to Redis (if configured) and start the subscriber loop."""
    global _redis, _pubsub, _redis_task
    if not settings.REDIS_URL:
        return
    try:
        import redis.asyncio as aioredis
    except ImportError:
        log.warning("REDIS_URL set but 'redis' package not installed; using in-memory broadcast")
        return
    try:
        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        _pubsub = _redis.pubsub()
        await _pubsub.subscribe(_CHANNEL)
        _redis_task = asyncio.create_task(_listen())
        log.info("Redis pub/sub broadcast connected")
    except Exception as e:  # network failure shouldn't crash boot
        log.warning("Redis connection failed, falling back to in-memory: %s", e)
        _redis = None


async def shutdown() -> None:
    global _redis, _pubsub, _redis_task
    if _pubsub is not None:
        try:
            await _pubsub.unsubscribe(_CHANNEL)
            await _pubsub.close()
        except Exception:
            pass
    if _redis is not None:
        try:
            await _redis.close()
        except Exception:
            pass
    if _redis_task is not None:
        _redis_task.cancel()
    _redis = _pubsub = _redis_task = None


def register_local_deliverer(fn: LocalDeliverer) -> None:
    global _local_deliver
    _local_deliver = fn


async def publish(conversation_id: int, message: str, exclude_user_id: Optional[int] = None) -> None:
    """Broadcast a message to all instances (Redis) or just this one (memory)."""
    if _redis is not None:
        payload = json.dumps({
            "conversation_id": conversation_id,
            "message": message,
            "exclude_user_id": exclude_user_id,
        })
        try:
            await _redis.publish(_CHANNEL, payload)
        except Exception:
            if _local_deliver:
                await _local_deliver(conversation_id, message, exclude_user_id)
    else:
        if _local_deliver:
            await _local_deliver(conversation_id, message, exclude_user_id)


async def _listen() -> None:
    assert _pubsub is not None
    async for raw in _pubsub.listen():
        if raw.get("type") != "message":
            continue
        try:
            data = json.loads(raw["data"])
            if _local_deliver:
                await _local_deliver(
                    int(data["conversation_id"]), data["message"], data.get("exclude_user_id")
                )
        except Exception:
            continue
