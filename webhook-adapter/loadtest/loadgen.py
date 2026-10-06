"""Deterministic P4-B capacity and ordering gate."""

import asyncio
import json
import math
import os
import re
import time
import uuid
from dataclasses import dataclass

import httpx
import redis.asyncio as redis_async


GATEWAY_URL = os.getenv(
    "LOADTEST_GATEWAY_URL",
    "http://webhook-gateway:8080/webhook/" + os.getenv("LOADTEST_INGRESS_TOKEN", ""),
)
WORKER_METRICS_URL = os.getenv("LOADTEST_WORKER_METRICS_URL", "http://webhook-worker:9101")
REDIS_URL = os.getenv("LOADTEST_REDIS_URL", "redis://redis:6379/0")
REDIS_PASSWORD = os.getenv("LOADTEST_REDIS_PASSWORD")
EXPECTED_CONCURRENCY = int(os.getenv("LOADTEST_EXPECTED_CONCURRENCY", "8"))


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    events: int
    elapsed_seconds: float
    queue_wait_p95_seconds: float


def parse_histogram_buckets(metrics_text: str) -> dict[float, float]:
    buckets: dict[float, float] = {}
    pattern = re.compile(
        r'^webhook_adapter_queue_wait_seconds_bucket\{le="([^"]+)"\}\s+([0-9.eE+-]+)$'
    )
    for line in metrics_text.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        boundary = math.inf if match.group(1) == "+Inf" else float(match.group(1))
        buckets[boundary] = float(match.group(2))
    return buckets


def histogram_quantile_from_metrics(
    before: dict[float, float],
    after: dict[float, float],
    quantile: float,
) -> float:
    total = after.get(math.inf, 0) - before.get(math.inf, 0)
    if total <= 0:
        raise AssertionError("queue wait histogram did not observe scenario events")
    target = total * quantile
    for boundary in sorted(after):
        delta = after[boundary] - before.get(boundary, 0)
        if delta >= target:
            return boundary
    return math.inf


class LoadGate:
    def __init__(self) -> None:
        self.redis = redis_async.from_url(
            REDIS_URL,
            password=REDIS_PASSWORD,
            decode_responses=True,
        )
        self.client = httpx.AsyncClient(timeout=10)
        self.message_id = int(time.time() * 1_000_000)

    async def close(self) -> None:
        await self.client.aclose()
        await self.redis.aclose()

    async def metrics(self) -> dict[float, float]:
        response = await self.client.get(WORKER_METRICS_URL)
        response.raise_for_status()
        return parse_histogram_buckets(response.text)

    async def send(
        self,
        run_id: str,
        conversation_id: str,
        sequence: int,
        *,
        fail_once: bool = False,
    ) -> str:
        self.message_id += 1
        payload = {
            "event": "message_created",
            "id": self.message_id,
            "message": {"id": self.message_id},
            "conversation": {"id": conversation_id},
            "loadtest": {
                "run_id": run_id,
                "sequence": sequence,
                "fail_once": fail_once,
            },
        }
        response = await self.client.post(GATEWAY_URL, json=payload)
        if response.status_code != 202 or response.json().get("status") != "queued":
            raise AssertionError(f"Gateway rejected load event: HTTP {response.status_code}")
        return str(response.json()["event_id"])

    async def successes(self, run_id: str) -> list[dict]:
        values = await self.redis.lrange(f"loadtest:success:{run_id}", 0, -1)
        return [json.loads(value) for value in values]

    async def wait_successes(self, run_id: str, expected: int, timeout: float) -> list[dict]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            values = await self.successes(run_id)
            if len(values) >= expected:
                return values
            await asyncio.sleep(0.05)
        raise AssertionError(f"{run_id} completed {len(await self.successes(run_id))}/{expected} events")

    async def scenario_result(
        self,
        name: str,
        run_id: str,
        expected: int,
        started: float,
        before: dict[float, float],
        timeout: float,
    ) -> tuple[ScenarioResult, list[dict]]:
        records = await self.wait_successes(run_id, expected, timeout)
        elapsed = time.monotonic() - started
        after = await self.metrics()
        p95 = histogram_quantile_from_metrics(before, after, 0.95)
        if await self.redis.get(f"loadtest:duplicates:{run_id}"):
            raise AssertionError(f"{name} produced duplicate successful deliveries")
        if len({record["event_id"] for record in records}) != expected:
            raise AssertionError(f"{name} lost or duplicated an event")
        peak = int(await self.redis.get(f"loadtest:peak:{run_id}") or 0)
        print(
            json.dumps(
                {
                    "scenario": name,
                    "elapsed_seconds": round(elapsed, 3),
                    "bridge_peak_concurrency": peak,
                    "queue_wait_p95_seconds": p95,
                },
                separators=(",", ":"),
            ),
            flush=True,
        )
        return ScenarioResult(name, expected, elapsed, p95), records

    async def sustained(self) -> ScenarioResult:
        run_id = "sustained-" + uuid.uuid4().hex
        before = await self.metrics()
        started = time.monotonic()
        for sequence in range(60):
            await self.send(run_id, f"sustained-{sequence}", sequence)
            target = started + sequence + 1
            await asyncio.sleep(max(0, target - time.monotonic()))
        result, _ = await self.scenario_result(
            "sustained", run_id, 60, started, before, timeout=10
        )
        if result.queue_wait_p95_seconds > 3:
            raise AssertionError(f"sustained queue wait P95 was {result.queue_wait_p95_seconds}s")
        return result

    async def burst(self) -> ScenarioResult:
        run_id = "burst-" + uuid.uuid4().hex
        before = await self.metrics()
        started = time.monotonic()
        await asyncio.gather(
            *(self.send(run_id, f"burst-{sequence}", sequence) for sequence in range(50))
        )
        result, _ = await self.scenario_result("burst", run_id, 50, started, before, timeout=8)
        if result.elapsed_seconds > 5:
            raise AssertionError(f"burst drained in {result.elapsed_seconds:.3f}s, expected <= 5s")
        return result

    async def ordered(self) -> ScenarioResult:
        run_id = "ordered-" + uuid.uuid4().hex
        before = await self.metrics()
        started = time.monotonic()
        for sequence in range(20):
            await self.send(run_id, "ordered-conversation", sequence)
        result, records = await self.scenario_result(
            "ordered", run_id, 20, started, before, timeout=15
        )
        if [record["sequence"] for record in records] != list(range(20)):
            raise AssertionError("same-conversation delivery order was not FIFO")
        return result

    async def retry_isolation(self) -> ScenarioResult:
        run_id = "retry-" + uuid.uuid4().hex
        before = await self.metrics()
        started = time.monotonic()
        await self.send(run_id, "blocked-conversation", 0, fail_once=True)
        await asyncio.gather(
            self.send(run_id, "blocked-conversation", 1),
            self.send(run_id, "other-conversation", 2),
        )
        result, records = await self.scenario_result(
            "retry-isolation", run_id, 3, started, before, timeout=12
        )
        blocked = [record for record in records if record["conversation_id"] == "blocked-conversation"]
        other = next(record for record in records if record["conversation_id"] == "other-conversation")
        if [record["sequence"] for record in blocked] != [0, 1]:
            raise AssertionError("retry allowed a later same-conversation event to overtake")
        if other["completed_at_ms"] >= blocked[0]["completed_at_ms"]:
            raise AssertionError("retrying conversation blocked an unrelated conversation")
        return result

    async def concurrency_probe(self) -> ScenarioResult:
        run_id = "concurrency-probe-" + uuid.uuid4().hex
        before = await self.metrics()
        started = time.monotonic()
        event_count = max(4, EXPECTED_CONCURRENCY * 2)
        await asyncio.gather(
            *(self.send(run_id, f"probe-{sequence}", sequence) for sequence in range(event_count))
        )
        result, _ = await self.scenario_result(
            "concurrency-probe", run_id, event_count, started, before, timeout=20
        )
        peak = int(await self.redis.get(f"loadtest:peak:{run_id}") or 0)
        if peak != EXPECTED_CONCURRENCY:
            raise AssertionError(
                f"worker peak concurrency was {peak}, expected {EXPECTED_CONCURRENCY}"
            )
        return result

    async def assert_queue_clean(self) -> None:
        if await self.redis.xlen("ai:webhook-adapter:events") != 0:
            raise AssertionError("primary Redis Stream is not empty")
        pending = await self.redis.xpending("ai:webhook-adapter:events", "webhook-workers")
        pending_count = pending.get("pending", 0) if isinstance(pending, dict) else pending[0]
        if pending_count != 0:
            raise AssertionError("Redis Consumer Group still has pending events")
        if await self.redis.xlen("ai:webhook-adapter:dead-letter") != 0:
            raise AssertionError("load test produced dead-letter events")

    async def run(self) -> list[ScenarioResult]:
        scenarios = {
            "sustained": self.sustained,
            "burst": self.burst,
            "ordered": self.ordered,
            "retry-isolation": self.retry_isolation,
            "concurrency-probe": self.concurrency_probe,
        }
        selected = [
            value.strip()
            for value in os.getenv(
                "LOADTEST_SCENARIOS", "sustained,burst,ordered,retry-isolation"
            ).split(",")
            if value.strip()
        ]
        unknown = set(selected) - set(scenarios)
        if unknown:
            raise ValueError(f"Unknown load-test scenarios: {', '.join(sorted(unknown))}")
        results = [await scenarios[name]() for name in selected]
        await self.assert_queue_clean()
        return results


async def async_main() -> int:
    gate = LoadGate()
    try:
        results = await gate.run()
        print(
            json.dumps(
                {
                    "status": "passed",
                    "scenarios": [result.__dict__ for result in results],
                },
                separators=(",", ":"),
            )
        )
        return 0
    finally:
        await gate.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
