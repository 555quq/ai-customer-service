"""Worker heartbeat healthcheck command."""

import asyncio
import time

import redis.asyncio as redis_async

from .config import settings


async def check() -> int:
    redis = redis_async.from_url(
        settings.redis_url,
        password=settings.redis_password,
        decode_responses=True,
    )
    try:
        value = await redis.get(settings.heartbeat_key)
        if value is None or int(value) < int(time.time()) - 30:
            return 1
        if not await redis.exists(settings.lease_key):
            return 1
        return 0
    finally:
        await redis.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(check()))
