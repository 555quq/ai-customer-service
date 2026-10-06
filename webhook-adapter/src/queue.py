"""Redis-backed durable webhook queue."""

from dataclasses import dataclass
from time import time
from typing import Any

from redis.asyncio import Redis

from .config import AdapterSettings


ENQUEUE_LUA = r"""
local dedupe_key = KEYS[1]
local payload_key = KEYS[2]
local stream_key = KEYS[3]
if redis.call('EXISTS', dedupe_key) == 1 then
  return {0, ''}
end
redis.call('SET', payload_key, ARGV[1], 'EX', ARGV[2])
local stream_id = redis.call(
  'XADD', stream_key, '*',
  'event_id', ARGV[3],
  'received_at', ARGV[4],
  'event_type', ARGV[5],
  'received_at_ms', ARGV[6],
  'ordering_key', ARGV[7]
)
redis.call('SET', dedupe_key, '1', 'EX', ARGV[2])
return {1, stream_id}
"""


@dataclass(frozen=True)
class EnqueueResult:
    queued: bool
    stream_id: str | None = None


class WebhookQueue:
    def __init__(self, redis: Redis, config: AdapterSettings) -> None:
        self.redis = redis
        self.config = config

    def payload_key(self, event_id: str) -> str:
        return f"ai:webhook-adapter:payload:{event_id}"

    def dedupe_key(self, event_id: str) -> str:
        return f"ai:webhook-adapter:queued:{event_id}"

    def attempts_key(self, event_id: str) -> str:
        return f"ai:webhook-adapter:attempts:{event_id}"

    def retry_at_key(self, event_id: str) -> str:
        return f"ai:webhook-adapter:retry-at:{event_id}"

    async def enqueue(
        self,
        event_id: str,
        event_type: str,
        raw_body: bytes,
        ordering_key: str,
    ) -> EnqueueResult:
        received_at = time()
        result = await self.redis.eval(
            ENQUEUE_LUA,
            3,
            self.dedupe_key(event_id),
            self.payload_key(event_id),
            self.config.stream_name,
            raw_body,
            str(self.config.payload_ttl_seconds),
            event_id,
            str(int(received_at)),
            event_type[:100],
            str(int(received_at * 1000)),
            ordering_key,
        )
        queued = int(result[0]) == 1
        stream_id_raw = result[1] if len(result) > 1 else None
        if isinstance(stream_id_raw, bytes):
            stream_id_raw = stream_id_raw.decode("ascii")
        return EnqueueResult(queued=queued, stream_id=stream_id_raw or None)

    async def ensure_group(self) -> None:
        try:
            await self.redis.xgroup_create(
                self.config.stream_name,
                self.config.consumer_group,
                id="0-0",
                mkstream=True,
            )
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def payload(self, event_id: str) -> bytes | None:
        value = await self.redis.get(self.payload_key(event_id))
        if value is None:
            return None
        return value if isinstance(value, bytes) else str(value).encode("utf-8")

    async def complete(self, stream_id: str, event_id: str) -> None:
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.xack(self.config.stream_name, self.config.consumer_group, stream_id)
            pipe.xdel(self.config.stream_name, stream_id)
            pipe.delete(
                self.payload_key(event_id),
                self.attempts_key(event_id),
                self.retry_at_key(event_id),
            )
            await pipe.execute()

    async def dead_letter(
        self,
        stream_id: str,
        event_id: str,
        attempts: int,
        reason: str,
        status_code: int | None,
    ) -> None:
        fields: dict[str, Any] = {
            "event_id": event_id,
            "attempts": str(attempts),
            "reason": reason[:100],
            "failed_at": str(int(time())),
            "payload_key": self.payload_key(event_id),
        }
        if status_code is not None:
            fields["status_code"] = str(status_code)
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.xadd(self.config.dead_letter_stream, fields, maxlen=10_000, approximate=True)
            pipe.xack(self.config.stream_name, self.config.consumer_group, stream_id)
            pipe.xdel(self.config.stream_name, stream_id)
            pipe.delete(self.attempts_key(event_id), self.retry_at_key(event_id))
            await pipe.execute()
