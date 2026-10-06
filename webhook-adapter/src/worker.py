"""Durable Redis Stream consumer and signed Bridge delivery."""

import asyncio
import json
import logging
import signal
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx
import redis.asyncio as redis_async
from prometheus_client import start_http_server

from .config import AdapterSettings, settings
from .lease import LeaseLost, RedisLease
from .metrics import (
    dead_letter_total,
    delivery_duration,
    delivery_total,
    lease_events_total,
    oldest_event_age,
    queue_depth,
    retry_total,
    worker_heartbeat,
)
from .queue import WebhookQueue
from .scheduler import ConversationScheduler, ScheduleDecision, ScheduledEvent
from .security import ordering_key_for, parse_json_object, sign_v2


logger = logging.getLogger("webhook_adapter.worker")
RETRY_DELAYS = (5, 15, 60, 300, 900)


@dataclass(frozen=True)
class DeliveryResult:
    action: Literal["complete", "retry", "dead_letter"]
    reason: str
    status_code: int | None = None


def classify_delivery(status_code: int | None, network_error: bool = False) -> DeliveryResult:
    if network_error or status_code is None:
        return DeliveryResult("retry", "network_error", status_code)
    if 200 <= status_code < 300:
        return DeliveryResult("complete", "success", status_code)
    if status_code in {408, 409, 429} or status_code >= 500:
        return DeliveryResult("retry", f"http_{status_code}", status_code)
    return DeliveryResult("dead_letter", f"http_{status_code}", status_code)


def _decode(value: Any) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


class WebhookWorker:
    def __init__(
        self,
        redis,
        config: AdapterSettings,
        client: httpx.AsyncClient | None = None,
        lease: RedisLease | None = None,
    ) -> None:
        self.redis = redis
        self.config = config
        self.queue = WebhookQueue(redis, config)
        self.client = client or httpx.AsyncClient(timeout=config.request_timeout_seconds)
        self._owns_client = client is None
        self.lease = lease or RedisLease(
            redis,
            config.lease_key,
            config.lease_ttl_seconds,
            config.lease_renew_seconds,
        )
        self.scheduler = ConversationScheduler(
            self.process_scheduled,
            concurrency=config.concurrency,
            buffer_limit=config.buffer_limit,
        )
        self._submitted_stream_ids: set[str] = set()

    async def close(self) -> None:
        close_scheduler = getattr(self.scheduler, "close", None)
        if close_scheduler is not None:
            await close_scheduler(self.config.shutdown_grace_seconds)
        if self._owns_client:
            await self.client.aclose()

    async def heartbeat(self) -> None:
        now = int(time.time())
        await self.redis.set(self.config.heartbeat_key, str(now), ex=30)
        worker_heartbeat.set(now)
        queue_depth.set(await self.redis.xlen(self.config.stream_name))
        oldest_event_age.set(self.scheduler.oldest_event_age_seconds)

    async def deliver(self, event_id: str, raw_body: bytes) -> DeliveryResult:
        timestamp = str(int(time.time()))
        headers = {
            "Content-Type": "application/json",
            "X-Chatwoot-Signature-Version": "v2",
            "X-Chatwoot-Timestamp": timestamp,
            "X-Chatwoot-Event-Id": event_id,
            "X-Chatwoot-Signature": sign_v2(
                self.config.webhook_secret,
                timestamp,
                event_id,
                raw_body,
            ),
        }
        started = time.perf_counter()
        try:
            response = await self.client.post(self.config.bridge_url, content=raw_body, headers=headers)
        except httpx.HTTPError:
            return classify_delivery(None, network_error=True)
        finally:
            delivery_duration.observe(time.perf_counter() - started)
        return classify_delivery(response.status_code)

    async def process(self, stream_id: str, fields: dict[Any, Any]) -> DeliveryResult:
        event_id_raw = fields.get(b"event_id", fields.get("event_id"))
        event_id = _decode(event_id_raw)
        attempts = int(await self.redis.incr(self.queue.attempts_key(event_id)))
        await self.redis.expire(self.queue.attempts_key(event_id), self.config.payload_ttl_seconds)
        raw_body = await self.queue.payload(event_id)
        if raw_body is None:
            result = DeliveryResult("dead_letter", "payload_missing")
        else:
            result = await self.deliver(event_id, raw_body)
        if result.action == "complete":
            await self.queue.complete(stream_id, event_id)
            delivery_total.labels(result="success").inc()
            return result
        if result.action == "dead_letter" or attempts >= self.config.max_attempts:
            reason = result.reason if result.action == "dead_letter" else "attempts_exhausted"
            await self.queue.dead_letter(stream_id, event_id, attempts, reason, result.status_code)
            dead_letter_total.labels(reason=reason).inc()
            delivery_total.labels(result="dead_letter").inc()
            return DeliveryResult("dead_letter", reason, result.status_code)
        delay = RETRY_DELAYS[min(attempts - 1, len(RETRY_DELAYS) - 1)]
        await self.redis.set(
            self.queue.retry_at_key(event_id),
            str(int(time.time()) + delay),
            ex=self.config.payload_ttl_seconds,
        )
        retry_total.labels(reason=result.reason).inc()
        delivery_total.labels(result="retry").inc()
        return result

    async def _pending_due(self, fields: dict[Any, Any]) -> bool:
        event_id_raw = fields.get(b"event_id", fields.get("event_id"))
        event_id = _decode(event_id_raw)
        retry_at = await self.redis.get(self.queue.retry_at_key(event_id))
        return retry_at is None or int(_decode(retry_at)) <= int(time.time())

    async def to_scheduled_event(
        self,
        stream_id: str | bytes,
        fields: dict[Any, Any],
    ) -> ScheduledEvent:
        event_id_raw = fields.get(b"event_id", fields.get("event_id"))
        if event_id_raw is None:
            raise ValueError("Stream event is missing event_id")
        event_id = _decode(event_id_raw)
        ordering_key_raw = fields.get(b"ordering_key", fields.get("ordering_key"))
        ordering_key = _decode(ordering_key_raw).strip() if ordering_key_raw is not None else ""
        if not ordering_key:
            raw_body = await self.queue.payload(event_id)
            if raw_body is not None:
                try:
                    ordering_key = ordering_key_for(parse_json_object(raw_body), event_id)
                except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                    ordering_key = event_id
            else:
                ordering_key = event_id

        received_ms_raw = fields.get(b"received_at_ms", fields.get("received_at_ms"))
        received_seconds_raw = fields.get(b"received_at", fields.get("received_at"))
        try:
            if received_ms_raw is not None:
                received_at_ms = int(_decode(received_ms_raw))
            elif received_seconds_raw is not None:
                received_at_ms = int(float(_decode(received_seconds_raw)) * 1000)
            else:
                received_at_ms = int(time.time() * 1000)
        except ValueError:
            received_at_ms = int(time.time() * 1000)

        return ScheduledEvent(
            stream_id=_decode(stream_id),
            event_id=event_id,
            ordering_key=ordering_key[:128],
            received_at_ms=received_at_ms,
            fields=fields,
        )

    @staticmethod
    def _stream_sort_key(item: tuple[Any, dict[Any, Any]]) -> tuple[int, int]:
        raw_stream_id = _decode(item[0])
        milliseconds, sequence = raw_stream_id.split("-", 1)
        return int(milliseconds), int(sequence)

    async def submit_messages(self, messages: list[tuple[Any, dict[Any, Any]]]) -> None:
        for stream_id_raw, fields in sorted(messages, key=self._stream_sort_key):
            stream_id = _decode(stream_id_raw)
            if stream_id in self._submitted_stream_ids:
                continue
            scheduled = await self.to_scheduled_event(stream_id, fields)
            self._submitted_stream_ids.add(stream_id)
            try:
                await self.scheduler.submit(scheduled)
            except Exception:
                self._submitted_stream_ids.discard(stream_id)
                raise

    async def process_scheduled(self, event: ScheduledEvent) -> ScheduleDecision:
        retry_at = await self.redis.get(self.queue.retry_at_key(event.event_id))
        if retry_at is not None:
            retry_at_epoch = float(_decode(retry_at))
            if retry_at_epoch > time.time():
                return ScheduleDecision.retry_at(retry_at_epoch)

        result = await self.process(event.stream_id, event.fields)
        if result.action == "retry":
            retry_at = await self.redis.get(self.queue.retry_at_key(event.event_id))
            retry_at_epoch = float(_decode(retry_at)) if retry_at is not None else time.time() + 1
            return ScheduleDecision.retry_at(retry_at_epoch)
        self._submitted_stream_ids.discard(event.stream_id)
        return ScheduleDecision.complete()

    async def recover_one(self) -> bool:
        claimed = await self.redis.xautoclaim(
            self.config.stream_name,
            self.config.consumer_group,
            self.config.worker_name,
            min_idle_time=5_000,
            start_id="0-0",
            count=1,
        )
        messages = claimed[1] if len(claimed) > 1 else []
        if not messages:
            return False
        stream_id, fields = messages[0]
        stream_id = _decode(stream_id)
        if await self._pending_due(fields):
            await self.process(stream_id, fields)
        return True

    async def recover_pending(self) -> int:
        recovered = 0
        cursor = "0-0"
        while True:
            claimed = await self.redis.xautoclaim(
                self.config.stream_name,
                self.config.consumer_group,
                self.config.worker_name,
                min_idle_time=5_000,
                start_id=cursor,
                count=self.config.prefetch,
            )
            cursor = _decode(claimed[0])
            messages = claimed[1] if len(claimed) > 1 else []
            await self.submit_messages(messages)
            recovered += len(messages)
            if cursor == "0-0":
                return recovered

    async def read_one(self) -> bool:
        result = await self.redis.xreadgroup(
            self.config.consumer_group,
            self.config.worker_name,
            {self.config.stream_name: ">"},
            count=1,
            block=1_000,
        )
        if not result:
            return False
        _stream, messages = result[0]
        stream_id, fields = messages[0]
        await self.process(_decode(stream_id), fields)
        return True

    async def read_new_batch(self) -> bool:
        result = await self.redis.xreadgroup(
            self.config.consumer_group,
            self.config.worker_name,
            {self.config.stream_name: ">"},
            count=self.config.prefetch,
            block=1_000,
        )
        if not result:
            return False
        messages: list[tuple[Any, dict[Any, Any]]] = []
        for _stream, stream_messages in result:
            messages.extend(stream_messages)
        await self.submit_messages(messages)
        return bool(messages)

    async def _read_loop(self) -> None:
        while True:
            await self.read_new_batch()

    async def _heartbeat_loop(self) -> None:
        while True:
            await self.heartbeat()
            await asyncio.sleep(5)

    async def run(self) -> None:
        if not await self.lease.acquire():
            lease_events_total.labels(result="conflict").inc()
            raise RuntimeError("Another webhook worker is already active")
        lease_events_total.labels(result="acquired").inc()
        tasks: list[asyncio.Task[Any]] = []
        try:
            await self.queue.ensure_group()
            await self.recover_pending()
            tasks = [
                asyncio.create_task(self._read_loop(), name="webhook-stream-reader"),
                asyncio.create_task(self._heartbeat_loop(), name="webhook-heartbeat"),
                asyncio.create_task(self.lease.maintain(), name="webhook-worker-lease"),
                asyncio.create_task(self.scheduler.wait_failed(), name="webhook-scheduler-failure"),
            ]
            done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                try:
                    task.result()
                except LeaseLost:
                    lease_events_total.labels(result="lost").inc()
                    raise
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if await self.lease.release():
                lease_events_total.labels(result="released").inc()


async def run_until_stop(worker: WebhookWorker, stop: asyncio.Event) -> None:
    """Run the worker until it fails or the process receives a stop signal."""
    worker_task = asyncio.create_task(worker.run(), name="webhook-worker")
    stop_task = asyncio.create_task(stop.wait(), name="webhook-stop-signal")
    try:
        done, _pending = await asyncio.wait(
            (worker_task, stop_task),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if worker_task in done:
            await worker_task
            return
        worker_task.cancel()
        await asyncio.gather(worker_task, return_exceptions=True)
    finally:
        stop_task.cancel()
        await asyncio.gather(stop_task, return_exceptions=True)


async def async_main() -> None:
    settings.validate_worker()
    redis = redis_async.from_url(
        settings.redis_url,
        password=settings.redis_password,
        decode_responses=False,
    )
    worker = WebhookWorker(redis, settings)
    start_http_server(settings.worker_metrics_port)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed_signals: list[signal.Signals] = []
    for candidate in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(candidate, stop.set)
            installed_signals.append(candidate)
        except (NotImplementedError, RuntimeError):
            pass
    try:
        await run_until_stop(worker, stop)
    finally:
        for candidate in installed_signals:
            loop.remove_signal_handler(candidate)
        await worker.close()
        await redis.aclose()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
