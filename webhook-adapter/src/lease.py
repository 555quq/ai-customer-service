"""Redis-backed singleton lease for the ordered webhook worker."""

import asyncio
import secrets


RENEW_LUA = r"""
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
"""

RELEASE_LUA = r"""
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


class LeaseLost(RuntimeError):
    """Raised when this process no longer owns the worker lease."""


class RedisLease:
    def __init__(
        self,
        redis,
        key: str,
        ttl_seconds: float,
        renew_seconds: float,
        token: str | None = None,
    ) -> None:
        self.redis = redis
        self.key = key
        self.ttl_seconds = ttl_seconds
        self.renew_seconds = renew_seconds
        self.token = token or secrets.token_hex(32)

    @property
    def ttl_milliseconds(self) -> int:
        return int(self.ttl_seconds * 1000)

    async def acquire(self) -> bool:
        result = await self.redis.set(
            self.key,
            self.token,
            nx=True,
            px=self.ttl_milliseconds,
        )
        return bool(result)

    async def renew(self) -> bool:
        result = await self.redis.eval(
            RENEW_LUA,
            1,
            self.key,
            self.token,
            self.ttl_milliseconds,
        )
        return int(result) == 1

    async def release(self) -> bool:
        result = await self.redis.eval(
            RELEASE_LUA,
            1,
            self.key,
            self.token,
        )
        return int(result) == 1

    async def maintain(self) -> None:
        while True:
            await asyncio.sleep(self.renew_seconds)
            if not await self.renew():
                raise LeaseLost("Webhook worker lease was lost")
