import pytest

from src.queue import WebhookQueue


class FakeRedis:
    def __init__(self, result=None):
        self.result = result or [1, b"1-0"]
        self.eval_call = None

    async def eval(self, *args):
        self.eval_call = args
        return self.result


@pytest.mark.asyncio
async def test_enqueue_writes_ordering_key_and_millisecond_timestamp(adapter_settings):
    redis = FakeRedis()
    queue = WebhookQueue(redis, adapter_settings)

    result = await queue.enqueue(
        "e" * 64,
        "message_created",
        b'{"event":"message_created"}',
        ordering_key="42",
    )

    assert result.queued is True
    assert result.stream_id == "1-0"
    args = redis.eval_call
    assert args[0].count("ordering_key") == 1
    assert args[0].count("received_at_ms") == 1
    assert args[-1] == "42"
    assert len(args[-2]) >= 13


@pytest.mark.asyncio
async def test_duplicate_enqueue_returns_without_second_stream_id(adapter_settings):
    redis = FakeRedis([0, b""])
    queue = WebhookQueue(redis, adapter_settings)

    result = await queue.enqueue("e" * 64, "message_created", b"{}", ordering_key="42")

    assert result.queued is False
    assert result.stream_id is None
