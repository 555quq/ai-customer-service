import time

import pytest

import src.healthcheck as healthcheck


class FakeRedis:
    def __init__(self, heartbeat, lease_exists):
        self.heartbeat = heartbeat
        self.lease_exists = lease_exists
        self.closed = False

    async def get(self, _key):
        return self.heartbeat

    async def exists(self, _key):
        return int(self.lease_exists)

    async def aclose(self):
        self.closed = True


@pytest.mark.asyncio
async def test_healthcheck_requires_fresh_heartbeat_and_active_lease(monkeypatch):
    redis = FakeRedis(str(int(time.time())), True)
    monkeypatch.setattr(healthcheck.redis_async, "from_url", lambda *_args, **_kwargs: redis)

    assert await healthcheck.check() == 0
    assert redis.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "heartbeat,lease_exists",
    [(None, True), ("1", True), (None, False), (str(int(time.time())), False)],
)
async def test_healthcheck_fails_when_heartbeat_or_lease_is_missing(
    monkeypatch, heartbeat, lease_exists
):
    redis = FakeRedis(heartbeat, lease_exists)
    monkeypatch.setattr(healthcheck.redis_async, "from_url", lambda *_args, **_kwargs: redis)

    assert await healthcheck.check() == 1
