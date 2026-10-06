"""Private Chatwoot webhook ingress."""

import logging
from time import perf_counter

import redis.asyncio as redis_async
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .config import AdapterSettings, settings
from .metrics import ingress_duration, ingress_total
from .queue import WebhookQueue
from .security import event_id_for, ordering_key_for, parse_json_object, token_matches


logger = logging.getLogger("webhook_adapter.gateway")


def create_app(config: AdapterSettings = settings, queue: WebhookQueue | None = None) -> FastAPI:
    app = FastAPI(title="Webhook Adapter Gateway", docs_url=None, redoc_url=None)
    redis_client = None
    if queue is None:
        redis_client = redis_async.from_url(
            config.redis_url,
            password=config.redis_password,
            decode_responses=False,
        )
        queue = WebhookQueue(redis_client, config)
    app.state.queue = queue
    app.state.redis = redis_client or queue.redis

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> dict[str, str]:
        try:
            await app.state.redis.ping()
        except Exception as exc:
            raise HTTPException(status_code=503, detail={"code": "REDIS_UNAVAILABLE"}) from exc
        return {"status": "ready"}

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/webhook/{candidate}", status_code=202)
    async def webhook(candidate: str, request: Request) -> JSONResponse:
        started = perf_counter()
        result_label = "error"
        try:
            if not token_matches(candidate, config.ingress_token):
                result_label = "rejected"
                raise HTTPException(status_code=404, detail={"code": "NOT_FOUND"})
            content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                result_label = "rejected"
                raise HTTPException(status_code=415, detail={"code": "JSON_REQUIRED"})
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > config.max_body_bytes:
                        result_label = "rejected"
                        raise HTTPException(status_code=413, detail={"code": "PAYLOAD_TOO_LARGE"})
                except ValueError:
                    result_label = "rejected"
                    raise HTTPException(status_code=400, detail={"code": "INVALID_CONTENT_LENGTH"})
            raw_body = await request.body()
            if len(raw_body) > config.max_body_bytes:
                result_label = "rejected"
                raise HTTPException(status_code=413, detail={"code": "PAYLOAD_TOO_LARGE"})
            try:
                payload = parse_json_object(raw_body)
            except (ValueError, UnicodeDecodeError) as exc:
                result_label = "rejected"
                raise HTTPException(status_code=422, detail={"code": "INVALID_JSON"}) from exc
            event_id = event_id_for(payload, raw_body)
            event_type = str(payload.get("event") or "unknown")
            ordering_key = ordering_key_for(payload, event_id)
            try:
                queued = await app.state.queue.enqueue(
                    event_id,
                    event_type,
                    raw_body,
                    ordering_key,
                )
            except Exception as exc:
                logger.error("Webhook queue unavailable for event %.12s", event_id)
                result_label = "unavailable"
                raise HTTPException(status_code=503, detail={"code": "QUEUE_UNAVAILABLE"}) from exc
            result_label = "queued" if queued.queued else "duplicate"
            return JSONResponse(
                status_code=202,
                content={"status": result_label, "event_id": event_id},
            )
        finally:
            ingress_total.labels(result=result_label).inc()
            ingress_duration.observe(perf_counter() - started)

    return app


app = create_app()


def main() -> None:
    settings.validate_gateway()
    uvicorn.run(
        "src.gateway:app",
        host="0.0.0.0",
        port=settings.gateway_port,
        access_log=False,
    )


if __name__ == "__main__":
    main()
