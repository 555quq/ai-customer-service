"""Per-conversation FIFO scheduling with bounded global concurrency."""

import asyncio
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal

from .metrics import active_conversations, buffered_events, inflight, queue_wait


@dataclass(frozen=True)
class ScheduledEvent:
    stream_id: str
    event_id: str
    ordering_key: str
    received_at_ms: int
    fields: dict[Any, Any]


@dataclass(frozen=True)
class ScheduleDecision:
    action: Literal["complete", "retry"]
    retry_at_epoch: float | None = None

    @classmethod
    def complete(cls) -> "ScheduleDecision":
        return cls("complete")

    @classmethod
    def retry_at(cls, retry_at_epoch: float) -> "ScheduleDecision":
        return cls("retry", retry_at_epoch)


Processor = Callable[[ScheduledEvent], Awaitable[ScheduleDecision]]


class ConversationScheduler:
    """Run one FIFO per conversation while sharing a global concurrency cap."""

    def __init__(self, processor: Processor, concurrency: int, buffer_limit: int) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be positive")
        if buffer_limit < concurrency:
            raise ValueError("buffer_limit must be at least concurrency")
        self._processor = processor
        self._concurrency = asyncio.Semaphore(concurrency)
        self._buffer_slots = asyncio.Semaphore(buffer_limit)
        self._queues: dict[str, deque[ScheduledEvent]] = {}
        self._runners: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()
        self._idle = asyncio.Event()
        self._idle.set()
        self._failure: asyncio.Future[None] | None = None
        self._accepting = True
        self._buffered_events = 0
        self._inflight = 0
        self._started_stream_ids: set[str] = set()

    @property
    def active_conversations(self) -> int:
        return len(self._queues)

    @property
    def buffered_events(self) -> int:
        return self._buffered_events

    @property
    def inflight(self) -> int:
        return self._inflight

    @property
    def oldest_event_age_seconds(self) -> float:
        received = [item.received_at_ms for queue in self._queues.values() for item in queue]
        if not received:
            return 0.0
        return max(0.0, (time.time() * 1000 - min(received)) / 1000)

    async def submit(self, event: ScheduledEvent) -> None:
        if not self._accepting:
            raise RuntimeError("scheduler is closed")
        await self._buffer_slots.acquire()
        async with self._lock:
            if not self._accepting:
                self._buffer_slots.release()
                raise RuntimeError("scheduler is closed")
            queue = self._queues.setdefault(event.ordering_key, deque())
            queue.append(event)
            self._buffered_events += 1
            active_conversations.set(len(self._queues))
            buffered_events.set(self._buffered_events)
            self._idle.clear()
            if event.ordering_key not in self._runners:
                self._runners[event.ordering_key] = asyncio.create_task(
                    self._run_conversation(event.ordering_key),
                    name=f"webhook-conversation-{event.ordering_key[:24]}",
                )

    async def _run_conversation(self, ordering_key: str) -> None:
        try:
            while True:
                async with self._lock:
                    queue = self._queues.get(ordering_key)
                    if not queue:
                        self._remove_runner(ordering_key)
                        return
                    event = queue[0]

                while True:
                    async with self._concurrency:
                        self._inflight += 1
                        inflight.set(self._inflight)
                        try:
                            if event.stream_id not in self._started_stream_ids:
                                queue_wait.observe(
                                    max(0.0, (time.time() * 1000 - event.received_at_ms) / 1000)
                                )
                                self._started_stream_ids.add(event.stream_id)
                            decision = await self._processor(event)
                        finally:
                            self._inflight -= 1
                            inflight.set(self._inflight)
                    if decision.action == "complete":
                        break
                    if decision.retry_at_epoch is None:
                        raise RuntimeError("retry decision requires retry_at_epoch")
                    await asyncio.sleep(max(0.0, decision.retry_at_epoch - time.time()))

                async with self._lock:
                    queue = self._queues.get(ordering_key)
                    if queue and queue[0] is event:
                        queue.popleft()
                        self._started_stream_ids.discard(event.stream_id)
                        self._release_buffer_slot()
                    if not queue:
                        self._queues.pop(ordering_key, None)
                        active_conversations.set(len(self._queues))
                        self._remove_runner(ordering_key)
                        return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._accepting = False
            failure = self._failure_future()
            if not failure.done():
                failure.set_exception(exc)
        finally:
            await self._discard_conversation(ordering_key)

    def _failure_future(self) -> asyncio.Future[None]:
        if self._failure is None:
            self._failure = asyncio.get_running_loop().create_future()
        return self._failure

    async def wait_failed(self) -> None:
        await asyncio.shield(self._failure_future())

    def _remove_runner(self, ordering_key: str) -> None:
        current = asyncio.current_task()
        if self._runners.get(ordering_key) is current:
            self._runners.pop(ordering_key, None)

    def _release_buffer_slot(self) -> None:
        self._buffered_events -= 1
        buffered_events.set(self._buffered_events)
        self._buffer_slots.release()
        if self._buffered_events == 0:
            self._idle.set()

    async def _discard_conversation(self, ordering_key: str) -> None:
        async with self._lock:
            queue = self._queues.pop(ordering_key, None)
            if queue:
                for item in tuple(queue):
                    self._started_stream_ids.discard(item.stream_id)
                    self._release_buffer_slot()
            active_conversations.set(len(self._queues))
            self._remove_runner(ordering_key)

    async def join(self) -> None:
        await self._idle.wait()
        if self._failure is not None and self._failure.done():
            self._failure.result()

    async def close(self, grace_seconds: float) -> None:
        self._accepting = False
        try:
            await asyncio.wait_for(self.join(), timeout=grace_seconds)
        except (asyncio.TimeoutError, Exception) as exc:
            if not isinstance(exc, asyncio.TimeoutError):
                # The caller observes processor failures through wait_failed(); close
                # still owns cleanup of every remaining runner.
                pass
            tasks = list(self._runners.values())
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            if self._buffered_events == 0:
                self._idle.set()
