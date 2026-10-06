"""Deterministic signed Bridge substitute used only by the isolated load test."""

import asyncio
import hashlib
import hmac
import json
import os
import re
import time

import redis.asyncio as redis_async
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from src.security import canonical_v2


WEBHOOK_SECRET = os.getenv("LOADTEST_WEBHOOK_SECRET", "")
REDIS_URL = os.getenv("LOADTEST_REDIS_URL", "redis://redis:6379/0")
REDIS_PASSWORD = os.getenv("LOADTEST_REDIS_PASSWORD")
DELAY_SECONDS = int(os.getenv("LOADTEST_BRIDGE_DELAY_MS", "500")) / 1000

redis = redis_async.from_url(REDIS_URL, password=REDIS_PASSWORD, decode_responses=True)
app = FastAPI(title="Webhook Adapter Load Test Bridge", docs_url=None, redoc_url=None)

START_ATTEMPT_LUA = r"""
local attempts = redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], 3600)
local active = redis.call('INCR', KEYS[2])
redis.call('EXPIRE', KEYS[2], 3600)
local peak = tonumber(redis.call('GET', KEYS[3]) or '0')
if active > peak then
  redis.call('SET', KEYS[3], active, 'EX', 3600)
end
return attempts
"""

RECORD_SUCCESS_LUA = r"""
redis.call('DECR', KEYS[1])
local fresh = redis.call('SET', KEYS[2], '1', 'EX', 3600, 'NX')
if not fresh then
  redis.call('INCR', KEYS[3])
  redis.call('EXPIRE', KEYS[3], 3600)
  return 1
end
redis.call('RPUSH', KEYS[4], ARGV[1])
redis.call('EXPIRE', KEYS[4], 3600)
return 0
"""


def signature_valid(
    secret: str,
    signature: str | None,
    timestamp: str | None,
    event_id: str | None,
    raw_body: bytes,
    *,
    now: float | None = None,
) -> bool:
    if not secret or not signature or not timestamp or not event_id:
        return False
    if re.fullmatch(r"[0-9a-f]{64}", event_id) is None:
        return False
    try:
        timestamp_value = int(timestamp)
    except ValueError:
        return False
    if abs((time.time() if now is None else now) - timestamp_value) > 300:
        return False
    candidate = signature[7:] if signature.startswith("sha256=") else signature
    if re.fullmatch(r"[0-9a-fA-F]{64}", candidate) is None:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        canonical_v2(timestamp, event_id, raw_body),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(candidate.lower(), expected)


@app.get("/health")
async def health() -> dict[str, str]:
    try:
        await redis.ping()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="redis unavailable") from exc
    return {"status": "ok"}


@app.post("/webhook/chatwoot")
async def webhook(request: Request) -> JSONResponse:
    raw_body = await request.body()
    if request.headers.get("X-Chatwoot-Signature-Version") != "v2" or not signature_valid(
        WEBHOOK_SECRET,
        request.headers.get("X-Chatwoot-Signature"),
        request.headers.get("X-Chatwoot-Timestamp"),
        request.headers.get("X-Chatwoot-Event-Id"),
        raw_body,
    ):
        raise HTTPException(status_code=401, detail="invalid signature")
    try:
        payload = json.loads(raw_body)
        metadata = payload["loadtest"]
        run_id = str(metadata["run_id"])
        sequence = int(metadata["sequence"])
        conversation_id = str(payload["conversation"]["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="invalid load-test payload") from exc

    event_id = request.headers["X-Chatwoot-Event-Id"]
    attempt_key = f"loadtest:attempts:{run_id}:{event_id}"
    active_key = f"loadtest:active:{run_id}"
    attempts = int(
        await redis.eval(
            START_ATTEMPT_LUA,
            3,
            attempt_key,
            active_key,
            f"loadtest:peak:{run_id}",
        )
    )
    received_at_ms = int(time.time() * 1000)
    try:
        await asyncio.sleep(DELAY_SECONDS)
    finally:
        await redis.decr(f"loadtest:active:{run_id}")

    if bool(metadata.get("fail_once")) and attempts == 1:
        await redis.decr(active_key)
        return JSONResponse(status_code=503, content={"status": "retry"})

    record = json.dumps(
        {
            "event_id": event_id,
            "conversation_id": conversation_id,
            "sequence": sequence,
            "attempts": attempts,
            "received_at_ms": received_at_ms,
            "completed_at_ms": int(time.time() * 1000),
        },
        separators=(",", ":"),
    )
    duplicate = bool(
        await redis.eval(
            RECORD_SUCCESS_LUA,
            4,
            active_key,
            f"loadtest:completed:{run_id}:{event_id}",
            f"loadtest:duplicates:{run_id}",
            f"loadtest:success:{run_id}",
            record,
        )
    )
    return JSONResponse(
        status_code=200,
        content={"status": "duplicate" if duplicate else "success"},
    )
