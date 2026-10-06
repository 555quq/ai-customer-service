"""Low-cardinality adapter metrics."""

from prometheus_client import Counter, Gauge, Histogram


ingress_total = Counter(
    "webhook_adapter_ingress_total",
    "Webhook adapter ingress outcomes.",
    ("result",),
)
ingress_duration = Histogram(
    "webhook_adapter_ingress_duration_seconds",
    "Webhook adapter ingress latency.",
)
delivery_total = Counter(
    "webhook_adapter_delivery_total",
    "Webhook delivery outcomes.",
    ("result",),
)
retry_total = Counter(
    "webhook_adapter_retry_total",
    "Webhook retry outcomes.",
    ("reason",),
)
dead_letter_total = Counter(
    "webhook_adapter_dead_letter_total",
    "Webhook dead-letter outcomes.",
    ("reason",),
)
worker_heartbeat = Gauge(
    "webhook_adapter_worker_heartbeat_unixtime",
    "Last successful worker heartbeat as Unix time.",
)
queue_depth = Gauge(
    "webhook_adapter_queue_depth",
    "Entries currently retained in the primary webhook stream.",
)
inflight = Gauge(
    "webhook_adapter_inflight",
    "Webhook events currently occupying a delivery concurrency slot.",
)
active_conversations = Gauge(
    "webhook_adapter_active_conversations",
    "Conversation FIFO queues currently active in the worker.",
)
buffered_events = Gauge(
    "webhook_adapter_buffered_events",
    "Events currently buffered by the in-process scheduler.",
)
oldest_event_age = Gauge(
    "webhook_adapter_oldest_event_age_seconds",
    "Age in seconds of the oldest event buffered by the worker.",
)
queue_wait = Histogram(
    "webhook_adapter_queue_wait_seconds",
    "Time from durable enqueue to first acquisition of a processing slot.",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 10, 30, 60, 300),
)
delivery_duration = Histogram(
    "webhook_adapter_delivery_duration_seconds",
    "Duration of each signed Bridge delivery attempt.",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120, 330),
)
lease_events_total = Counter(
    "webhook_adapter_lease_events_total",
    "Worker singleton lease lifecycle events.",
    ("result",),
)
