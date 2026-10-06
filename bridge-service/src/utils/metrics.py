"""Low-cardinality Prometheus metrics for the Bridge service."""
from __future__ import annotations

import re
import time
from typing import Callable

from fastapi import Request, Response
from prometheus_client import Counter, Gauge, Histogram


METRIC_PREFIX = "ai_customer_service"

requests_total = Counter(
    f"{METRIC_PREFIX}_http_requests_total",
    "Bridge HTTP requests.",
    ["method", "route", "status"],
)
request_duration_seconds = Histogram(
    f"{METRIC_PREFIX}_http_request_duration_seconds",
    "Bridge HTTP request duration in seconds.",
    ["method", "route"],
)
message_counter = Counter(
    f"{METRIC_PREFIX}_messages_total",
    "Customer messages accepted by source and result.",
    ["source", "result"],
)
webhook_counter = Counter(
    f"{METRIC_PREFIX}_webhooks_total",
    "Chatwoot webhook events by stable event and result.",
    ["event", "result"],
)
webhook_idempotency_total = Counter(
    f"{METRIC_PREFIX}_webhook_idempotency_total",
    "Webhook idempotency outcomes.",
    ["result"],
)
ai_requests_total = Counter(
    f"{METRIC_PREFIX}_ai_requests_total",
    "AI requests by provider and result.",
    ["provider", "result"],
)
ai_response_time = Histogram(
    f"{METRIC_PREFIX}_ai_request_duration_seconds",
    "AI request duration in seconds.",
    ["provider"],
)
low_confidence_total = Counter(
    f"{METRIC_PREFIX}_low_confidence_total",
    "AI responses below the configured confidence threshold.",
    ["provider"],
)
handoff_counter = Counter(
    f"{METRIC_PREFIX}_handoffs_total",
    "Human handoff attempts by normalized reason and result.",
    ["reason", "result"],
)
chatwoot_requests_total = Counter(
    f"{METRIC_PREFIX}_chatwoot_requests_total",
    "Chatwoot API calls by operation and result.",
    ["operation", "result"],
)
chatwoot_api_time = Histogram(
    f"{METRIC_PREFIX}_chatwoot_request_duration_seconds",
    "Chatwoot API request duration in seconds.",
    ["operation"],
)
qdrant_operations_total = Counter(
    f"{METRIC_PREFIX}_qdrant_operations_total",
    "Qdrant operations by operation and result.",
    ["operation", "result"],
)
qdrant_operation_duration_seconds = Histogram(
    f"{METRIC_PREFIX}_qdrant_operation_duration_seconds",
    "Qdrant operation duration in seconds.",
    ["operation"],
)
knowledge_jobs_total = Counter(
    f"{METRIC_PREFIX}_knowledge_jobs_total",
    "Knowledge ingestion job terminal outcomes.",
    ["status"],
)
knowledge_job_duration_seconds = Histogram(
    f"{METRIC_PREFIX}_knowledge_job_duration_seconds",
    "Knowledge ingestion job duration in seconds.",
    ["status"],
)
knowledge_jobs_in_progress = Gauge(
    f"{METRIC_PREFIX}_knowledge_jobs_in_progress",
    "Knowledge ingestion jobs currently executing in this Bridge process.",
)


def normalize_handoff_reason(reason: str) -> str:
    """Map free-form handoff details to a bounded label set."""
    value = (reason or "").lower()
    if "置信度" in value or "confidence" in value:
        return "low_confidence"
    if "连续" in value or "未解决" in value or "unresolved" in value:
        return "unresolved"
    if "ai 回复" in value or "ai response" in value:
        return "ai_suggestion"
    if any(keyword in value for keyword in ("人工", "客服", "投诉", "退款", "human")):
        return "keyword"
    return "other"


def normalize_webhook_event(event: str | None) -> str:
    """Keep webhook labels bounded even when integrations send custom events."""
    value = (event or "unknown").strip().lower()
    return value if value in {"message_created", "conversation_updated"} else "other"


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if template:
        return str(template)
    path = request.url.path
    path = re.sub(r"/[0-9a-fA-F-]{8,}", "/{id}", path)
    return re.sub(r"/\d+", "/{id}", path)


async def metrics_middleware(request: Request, call_next: Callable) -> Response:
    """Record request count and latency using route templates, not raw IDs."""
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        route = _route_template(request)
        request_duration_seconds.labels(method=request.method, route=route).observe(
            time.perf_counter() - started
        )
        requests_total.labels(
            method=request.method,
            route=route,
            status=str(status_code),
        ).inc()
