import asyncio
import time

import pytest
from prometheus_client import generate_latest

from src.metrics import (
    active_conversations,
    buffered_events,
    inflight,
    queue_wait,
)
from src.scheduler import ConversationScheduler, ScheduleDecision, ScheduledEvent


@pytest.mark.asyncio
async def test_scheduler_updates_concurrency_gauges_and_queue_wait():
    release = asyncio.Event()
    both_started = asyncio.Event()
    starts = 0

    async def process(_item):
        nonlocal starts
        starts += 1
        if starts == 2:
            both_started.set()
        await release.wait()
        return ScheduleDecision.complete()

    before_wait_sum = queue_wait._sum.get()
    scheduler = ConversationScheduler(process, concurrency=2, buffer_limit=4)
    now_ms = int(time.time() * 1000) - 10
    await scheduler.submit(ScheduledEvent("1-0", "one", "one", now_ms, {}))
    await scheduler.submit(ScheduledEvent("2-0", "two", "two", now_ms, {}))

    await asyncio.wait_for(both_started.wait(), 1)
    assert inflight._value.get() == 2
    assert active_conversations._value.get() == 2
    assert buffered_events._value.get() == 2

    release.set()
    await scheduler.join()
    assert inflight._value.get() == 0
    assert active_conversations._value.get() == 0
    assert buffered_events._value.get() == 0
    assert queue_wait._sum.get() > before_wait_sum
    await scheduler.close(1)


def test_concurrency_metric_names_are_exported():
    output = generate_latest().decode()
    for name in (
        "webhook_adapter_inflight",
        "webhook_adapter_active_conversations",
        "webhook_adapter_buffered_events",
        "webhook_adapter_oldest_event_age_seconds",
        "webhook_adapter_queue_wait_seconds",
        "webhook_adapter_delivery_duration_seconds",
        "webhook_adapter_lease_events_total",
    ):
        assert name in output
