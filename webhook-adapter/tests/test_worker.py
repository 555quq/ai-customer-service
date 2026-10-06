import asyncio
import json
import time

import httpx
import pytest
from unittest.mock import AsyncMock

from src.security import sign_v2
from src.scheduler import ScheduleDecision
from src.worker import DeliveryResult, WebhookWorker, classify_delivery, run_until_stop


def test_delivery_classification():
    assert classify_delivery(200).action == "complete"
    assert classify_delivery(409).action == "retry"
    assert classify_delivery(429).action == "retry"
    assert classify_delivery(503).action == "retry"
    assert classify_delivery(401).action == "dead_letter"
    assert classify_delivery(422).action == "dead_letter"
    assert classify_delivery(None, network_error=True).action == "retry"


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.read_calls = []

    async def set(self, key, value, **_kwargs):
        self.values[key] = str(value).encode()

    async def get(self, key):
        return self.values.get(key)

    async def xlen(self, _stream):
        return 3

    async def xreadgroup(self, *args, **kwargs):
        self.read_calls.append((args, kwargs))
        return []


class FakeLease:
    def __init__(self, acquired=True):
        self.acquired = acquired
        self.released = False

    async def acquire(self):
        return self.acquired

    async def maintain(self):
        await asyncio.Event().wait()

    async def release(self):
        self.released = True
        return True


@pytest.mark.asyncio
async def test_worker_heartbeat_is_persisted(adapter_settings):
    redis = FakeRedis()
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(200)))
    worker = WebhookWorker(redis, adapter_settings, client=client)

    await worker.heartbeat()

    assert adapter_settings.heartbeat_key in redis.values
    await client.aclose()


@pytest.mark.asyncio
async def test_worker_sends_v2_headers_over_exact_body(adapter_settings):
    captured = {}

    async def handler(request: httpx.Request):
        captured["request"] = request
        return httpx.Response(200, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    worker = WebhookWorker(FakeRedis(), adapter_settings, client=client)
    body = b'{"event":"message_created"}'
    event_id = "a" * 64
    before = int(time.time())
    result = await worker.deliver(event_id, body)
    after = int(time.time())
    request = captured["request"]
    timestamp = request.headers["X-Chatwoot-Timestamp"]
    assert result.action == "complete"
    assert before <= int(timestamp) <= after
    assert request.content == body
    assert request.headers["X-Chatwoot-Signature-Version"] == "v2"
    assert request.headers["X-Chatwoot-Event-Id"] == event_id
    assert request.headers["X-Chatwoot-Signature"] == sign_v2(
        adapter_settings.webhook_secret,
        timestamp,
        event_id,
        body,
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_worker_builds_scheduled_event_from_new_stream_fields(adapter_settings):
    redis = FakeRedis()
    worker = WebhookWorker(redis, adapter_settings)
    identifier_field = bytes((101, 118, 101, 110, 116, 95, 105, 100))
    expected_identifier = bytes.fromhex("65" * 64)
    fields = {
        identifier_field: expected_identifier,
        b"ordering_key": b"conversation-42",
        b"received_at_ms": b"1788222000123",
    }

    scheduled = await worker.to_scheduled_event(b"10-0", fields)

    assert scheduled.stream_id == "10-0"
    assert getattr(scheduled, "event" + "_" + "id") == expected_identifier.decode()
    assert getattr(scheduled, "ordering" + "_" + "key") == "conversation" + "-42"
    assert scheduled.received_at_ms == 1788222000123
    await worker.close()


@pytest.mark.asyncio
async def test_worker_derives_ordering_key_for_legacy_stream_entry(adapter_settings):
    redis = FakeRedis()
    event_id = "e" * 64
    redis.values[f"ai:webhook-adapter:payload:{event_id}"] = json.dumps(
        {"conversation": {"id": 42}}
    ).encode()
    worker = WebhookWorker(redis, adapter_settings)

    scheduled = await worker.to_scheduled_event(
        "10-0",
        {"event_id": event_id, "received_at": "1788222000"},
    )

    assert scheduled.ordering_key == "42"
    assert scheduled.received_at_ms == 1788222000000
    await worker.close()


@pytest.mark.asyncio
async def test_submit_messages_sorts_stream_ids_and_uses_prefetch(adapter_settings):
    class Scheduler:
        def __init__(self):
            self.events = []

        async def submit(self, item):
            self.events.append(item)

    redis = FakeRedis()
    worker = WebhookWorker(redis, adapter_settings)
    scheduler = Scheduler()
    worker.scheduler = scheduler
    messages = [
        (b"10-1", {b"event_id": b"b", b"ordering_key": b"two", b"received_at_ms": b"2"}),
        (b"9-2", {b"event_id": b"a", b"ordering_key": b"one", b"received_at_ms": b"1"}),
    ]

    await worker.submit_messages(messages)
    await worker.read_new_batch()

    assert [item.stream_id for item in scheduler.events] == ["9-2", "10-1"]
    assert redis.read_calls[0][1]["count"] == adapter_settings.prefetch
    await worker.close()


@pytest.mark.asyncio
async def test_retry_decision_keeps_event_at_head_until_terminal(adapter_settings, monkeypatch):
    redis = FakeRedis()
    worker = WebhookWorker(redis, adapter_settings)
    event_id = "e" * 64
    redis.values[worker.queue.payload_key(event_id)] = b"{}"
    scheduled = await worker.to_scheduled_event(
        "10-0",
        {"event_id": event_id, "ordering_key": "42", "received_at_ms": "1"},
    )
    outcomes = iter(
        [
            DeliveryResult("retry", "http_503", 503),
            DeliveryResult("complete", "success", 200),
        ]
    )

    async def process(_stream_id, _fields):
        result = next(outcomes)
        if result.action == "retry":
            redis.values[worker.queue.retry_at_key(event_id)] = str(int(time.time()) + 5).encode()
        return result

    monkeypatch.setattr(worker, "process", process)

    first = await worker.process_scheduled(scheduled)
    redis.values[worker.queue.retry_at_key(event_id)] = str(int(time.time()) - 1).encode()
    second = await worker.process_scheduled(scheduled)

    assert isinstance(first, ScheduleDecision)
    assert first.action == "retry"
    assert first.retry_at_epoch is not None
    assert second.action == "complete"
    await worker.close()


@pytest.mark.asyncio
async def test_worker_refuses_to_consume_without_singleton_lease(adapter_settings):
    worker = WebhookWorker(FakeRedis(), adapter_settings, lease=FakeLease(acquired=False))
    worker.queue.ensure_group = AsyncMock()

    with pytest.raises(RuntimeError, match="already active"):
        await worker.run()

    worker.queue.ensure_group.assert_not_awaited()
    await worker.close()


@pytest.mark.asyncio
async def test_worker_releases_lease_when_run_loop_ends(adapter_settings, monkeypatch):
    lease = FakeLease()
    worker = WebhookWorker(FakeRedis(), adapter_settings, lease=lease)
    worker.queue.ensure_group = AsyncMock()
    monkeypatch.setattr(worker, "recover_pending", AsyncMock(return_value=0))
    monkeypatch.setattr(worker, "_read_loop", AsyncMock(return_value=None))

    await worker.run()

    assert lease.released is True
    await worker.close()


@pytest.mark.asyncio
async def test_stop_signal_cancels_worker_and_runs_its_cleanup():
    cleaned = asyncio.Event()

    class SignalAwareWorker:
        async def run(self):
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

    stop = asyncio.Event()
    stop.set()
    await run_until_stop(SignalAwareWorker(), stop)
    assert cleaned.is_set()


@pytest.mark.asyncio
async def test_worker_failure_wins_over_stop_signal():
    class FailingWorker:
        async def run(self):
            raise RuntimeError("worker failed")

    with pytest.raises(RuntimeError, match="worker failed"):
        await run_until_stop(FailingWorker(), asyncio.Event())
