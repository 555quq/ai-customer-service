import asyncio

import pytest

from src.lease import LeaseLost, RedisLease


class FakeRedis:
    def __init__(self, acquire=True, renew=True, release=True):
        self.acquire_result = acquire
        self.renew_result = renew
        self.release_result = release
        self.set_calls = []
        self.eval_calls = []

    async def set(self, *args, **kwargs):
        self.set_calls.append((args, kwargs))
        return self.acquire_result

    async def eval(self, script, *args):
        self.eval_calls.append((script, args))
        if "PEXPIRE" in script:
            return int(self.renew_result)
        return int(self.release_result)


@pytest.mark.asyncio
async def test_lease_acquire_uses_nx_and_millisecond_ttl():
    redis = FakeRedis()
    lease = RedisLease(redis, "lease-key", ttl_seconds=15, renew_seconds=5, token="owner")

    assert await lease.acquire() is True
    assert redis.set_calls == [(('lease-key', 'owner'), {'nx': True, 'px': 15000})]


@pytest.mark.asyncio
async def test_second_worker_cannot_acquire_existing_lease():
    lease = RedisLease(FakeRedis(acquire=None), "lease-key", 15, 5, token="other")
    assert await lease.acquire() is False


@pytest.mark.asyncio
async def test_renew_and_release_compare_owner_token():
    redis = FakeRedis()
    lease = RedisLease(redis, "lease-key", 15, 5, token="owner")

    assert await lease.renew() is True
    assert await lease.release() is True
    assert redis.eval_calls[0][1] == (1, "lease-key", "owner", 15000)
    assert redis.eval_calls[1][1] == (1, "lease-key", "owner")


@pytest.mark.asyncio
async def test_maintenance_raises_when_lease_is_lost():
    redis = FakeRedis(renew=False)
    lease = RedisLease(redis, "lease-key", 15, 0.01, token="owner")

    with pytest.raises(LeaseLost):
        await lease.maintain()


@pytest.mark.asyncio
async def test_maintenance_can_be_cancelled():
    lease = RedisLease(FakeRedis(), "lease-key", 15, 5, token="owner")
    task = asyncio.create_task(lease.maintain())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
