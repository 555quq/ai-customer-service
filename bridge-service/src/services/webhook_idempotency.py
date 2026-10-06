"""Redis-backed idempotency for authenticated webhook deliveries."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any, Literal


class WebhookIdempotencyUnavailable(RuntimeError):
    """Raised when the idempotency store cannot provide its safety guarantee."""


@dataclass(frozen=True)
class Claim:
    status: Literal["claimed", "duplicate", "in_progress"]
    owner: str | None = None


_COMPLETE_LUA = """
local current = redis.call('GET', KEYS[1])
if current == ARGV[1] then
  redis.call('SET', KEYS[2], '1', 'EX', ARGV[2])
  redis.call('DEL', KEYS[1])
  return 1
end
if redis.call('EXISTS', KEYS[2]) == 1 then
  return 2
end
return 0
"""

_RELEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


class WebhookIdempotency:
    def __init__(self, client: Any, lock_seconds: int = 600, done_seconds: int = 604800):
        self.client = client
        self.lock_seconds = lock_seconds
        self.done_seconds = done_seconds

    @staticmethod
    def _lock_key(event_id: str) -> str:
        return f"ai:bridge:webhook:lock:{event_id}"

    @staticmethod
    def _done_key(event_id: str) -> str:
        return f"ai:bridge:webhook:done:{event_id}"

    def _require_client(self) -> None:
        if self.client is None:
            raise WebhookIdempotencyUnavailable("Redis is unavailable")

    async def claim(self, event_id: str) -> Claim:
        self._require_client()
        try:
            if await self.client.exists(self._done_key(event_id)):
                return Claim("duplicate")
            owner = secrets.token_urlsafe(24)
            acquired = await self.client.set(
                self._lock_key(event_id), owner, ex=self.lock_seconds, nx=True
            )
            return Claim("claimed", owner) if acquired else Claim("in_progress")
        except Exception as exc:
            raise WebhookIdempotencyUnavailable("Redis idempotency claim failed") from exc

    async def complete(self, event_id: str, owner: str) -> None:
        self._require_client()
        try:
            result = await self.client.eval(
                _COMPLETE_LUA,
                2,
                self._lock_key(event_id),
                self._done_key(event_id),
                owner,
                str(self.done_seconds),
            )
        except Exception as exc:
            raise WebhookIdempotencyUnavailable("Redis idempotency completion failed") from exc
        if int(result) not in (1, 2):
            raise WebhookIdempotencyUnavailable("Webhook processing lock was lost")

    async def release(self, event_id: str, owner: str) -> None:
        self._require_client()
        try:
            await self.client.eval(
                _RELEASE_LUA, 1, self._lock_key(event_id), owner
            )
        except Exception as exc:
            raise WebhookIdempotencyUnavailable("Redis idempotency release failed") from exc
