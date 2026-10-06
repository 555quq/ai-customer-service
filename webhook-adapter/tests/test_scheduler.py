import asyncio
import time

import pytest

from src.scheduler import ConversationScheduler, ScheduleDecision, ScheduledEvent


def event(sequence: int, conversation: str) -> ScheduledEvent:
    return ScheduledEvent(
        stream_id=f"{sequence}-0",
        event_id=f"event-{sequence}",
        ordering_key=conversation,
        received_at_ms=int(time.time() * 1000),
        fields={"sequence": sequence},
    )


@pytest.mark.asyncio
async def test_same_conversation_is_strict_fifo():
    observed = []

    async def process(item):
        observed.append(item.fields["sequence"])
        await asyncio.sleep(0)
        return ScheduleDecision.complete()

    scheduler = ConversationScheduler(process, concurrency=8, buffer_limit=32)
    for sequence in range(20):
        await scheduler.submit(event(sequence, "same"))

    await scheduler.join()
    assert observed == list(range(20))
    assert scheduler.active_conversations == 0
    assert scheduler.buffered_events == 0
    await scheduler.close(1)


@pytest.mark.asyncio
async def test_different_conversations_run_in_parallel_with_global_limit():
    active = 0
    peak = 0
    release = asyncio.Event()
    started = asyncio.Event()

    async def process(_item):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if peak == 3:
            started.set()
        await release.wait()
        active -= 1
        return ScheduleDecision.complete()

    scheduler = ConversationScheduler(process, concurrency=3, buffer_limit=16)
    for sequence in range(8):
        await scheduler.submit(event(sequence, f"conversation-{sequence}"))

    await asyncio.wait_for(started.wait(), 1)
    assert peak == 3
    release.set()
    await scheduler.join()
    assert peak == 3
    await scheduler.close(1)


@pytest.mark.asyncio
async def test_retry_blocks_only_its_conversation_and_releases_slot():
    observed = []
    attempts = {}

    async def process(item):
        attempts[item.event_id] = attempts.get(item.event_id, 0) + 1
        observed.append((item.event_id, attempts[item.event_id]))
        if item.event_id == "event-1" and attempts[item.event_id] == 1:
            return ScheduleDecision.retry_at(time.time() + 0.05)
        return ScheduleDecision.complete()

    scheduler = ConversationScheduler(process, concurrency=1, buffer_limit=8)
    await scheduler.submit(event(1, "blocked"))
    await scheduler.submit(event(2, "blocked"))
    await scheduler.submit(event(3, "other"))

    await scheduler.join()
    assert observed.index(("event-3", 1)) < observed.index(("event-1", 2))
    assert observed.index(("event-1", 2)) < observed.index(("event-2", 1))
    await scheduler.close(1)


@pytest.mark.asyncio
async def test_buffer_limit_applies_backpressure():
    release = asyncio.Event()

    async def process(_item):
        await release.wait()
        return ScheduleDecision.complete()

    scheduler = ConversationScheduler(process, concurrency=1, buffer_limit=2)
    await scheduler.submit(event(1, "one"))
    await scheduler.submit(event(2, "two"))
    blocked_submit = asyncio.create_task(scheduler.submit(event(3, "three")))

    await asyncio.sleep(0.02)
    assert not blocked_submit.done()
    assert scheduler.buffered_events == 2

    release.set()
    await asyncio.wait_for(blocked_submit, 1)
    await scheduler.join()
    await scheduler.close(1)


@pytest.mark.asyncio
async def test_close_rejects_new_events_and_cancels_after_grace():
    started = asyncio.Event()

    async def process(_item):
        started.set()
        await asyncio.Event().wait()

    scheduler = ConversationScheduler(process, concurrency=1, buffer_limit=2)
    await scheduler.submit(event(1, "one"))
    await started.wait()

    await scheduler.close(0.01)
    assert scheduler.buffered_events == 0
    with pytest.raises(RuntimeError, match="closed"):
        await scheduler.submit(event(2, "two"))


@pytest.mark.asyncio
async def test_processor_exception_is_exposed_without_leaking_capacity():
    async def process(_item):
        raise RuntimeError("processor failed")

    scheduler = ConversationScheduler(process, concurrency=1, buffer_limit=2)
    await scheduler.submit(event(1, "one"))

    with pytest.raises(RuntimeError, match="processor failed"):
        await scheduler.wait_failed()
    assert scheduler.buffered_events == 0
    await scheduler.close(1)
