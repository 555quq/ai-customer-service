from __future__ import annotations

import pytest

from src.services.handoff_store import (
    HandoffSessionNotRestorable,
    HandoffStore,
    HandoffStoreUnavailable,
    HandoffVisitorMismatch,
)


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.pending: list[tuple[str, int, str]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def setex(self, key: str, ttl: int, value: str):
        self.pending.append((key, ttl, value))
        return self

    async def execute(self):
        if self.redis.fail_execute:
            raise ConnectionError("redis write failed")
        if self.redis.incomplete_execute:
            return [True, False]
        for key, ttl, value in self.pending:
            self.redis.values[key] = value
            self.redis.ttls[key] = ttl
        return [True] * len(self.pending)


class FakeRedis:
    def __init__(self):
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.fail_read = False
        self.fail_execute = False
        self.incomplete_execute = False

    def pipeline(self, transaction: bool = True):
        assert transaction is True
        return FakePipeline(self)

    async def mget(self, keys: list[str]):
        if self.fail_read:
            raise ConnectionError("redis read failed")
        return [self.values.get(key) for key in keys]

    async def get(self, key: str):
        if self.fail_read:
            raise ConnectionError("redis read failed")
        return self.values.get(key)


@pytest.mark.asyncio
async def test_handoff_store_atomically_saves_and_restores_bound_visitor():
    redis = FakeRedis()
    store = HandoffStore(redis, fingerprint_secret="server-only-secret", ttl_seconds=120)

    await store.save("conversation-1", "visitor-1", "42")
    restored = await store.resolve("conversation-1", "visitor-1")

    assert restored is not None
    assert restored.chatwoot_conversation_id == "42"
    assert redis.ttls == {
        "handoff:conversation-1": 120,
        "handoff_visitor:conversation-1": 120,
    }
    assert redis.values["handoff_visitor:conversation-1"] != "visitor-1"


@pytest.mark.asyncio
async def test_handoff_store_rejects_wrong_visitor():
    redis = FakeRedis()
    store = HandoffStore(redis, fingerprint_secret="server-only-secret")
    await store.save("conversation-1", "visitor-1", "42")

    with pytest.raises(HandoffVisitorMismatch):
        await store.resolve("conversation-1", "visitor-2")


@pytest.mark.asyncio
async def test_handoff_store_rejects_legacy_mapping_without_visitor_binding():
    redis = FakeRedis()
    redis.values["handoff:conversation-1"] = "42"
    store = HandoffStore(redis, fingerprint_secret="server-only-secret")

    with pytest.raises(HandoffSessionNotRestorable):
        await store.resolve("conversation-1", "visitor-1")


@pytest.mark.asyncio
async def test_handoff_store_fails_closed_when_redis_is_unavailable():
    redis = FakeRedis()
    redis.fail_read = True
    store = HandoffStore(redis, fingerprint_secret="server-only-secret")

    with pytest.raises(HandoffStoreUnavailable):
        await store.resolve("conversation-1", "visitor-1")

    redis.fail_read = False
    redis.fail_execute = True
    with pytest.raises(HandoffStoreUnavailable):
        await store.save("conversation-1", "visitor-1", "42")
    assert redis.values == {}

    redis.fail_execute = False
    redis.incomplete_execute = True
    with pytest.raises(HandoffStoreUnavailable):
        await store.save("conversation-1", "visitor-1", "42")
    assert redis.values == {}


@pytest.mark.asyncio
async def test_handoff_store_preserves_existing_scalar_route_mapping():
    redis = FakeRedis()
    store = HandoffStore(redis, fingerprint_secret="server-only-secret")
    await store.save("conversation-1", "visitor-1", "42")

    assert await store.get_chatwoot_conversation_id("conversation-1") == "42"
