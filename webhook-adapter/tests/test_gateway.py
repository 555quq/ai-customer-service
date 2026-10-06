from dataclasses import dataclass

from fastapi.testclient import TestClient

from src.gateway import create_app


@dataclass
class FakeResult:
    queued: bool
    stream_id: str | None = "1-0"


class FakeRedis:
    async def ping(self):
        return True


class FakeQueue:
    def __init__(self, queued=True, fail=False):
        self.redis = FakeRedis()
        self.queued = queued
        self.fail = fail
        self.calls = []

    async def enqueue(self, event_id, event_type, raw_body, ordering_key):
        if self.fail:
            raise RuntimeError("secret backend failure")
        self.calls.append((event_id, event_type, raw_body, ordering_key))
        return FakeResult(self.queued)


def client(adapter_settings, queue=None):
    return TestClient(create_app(adapter_settings, queue or FakeQueue()))


def test_invalid_token_is_uniform_404(adapter_settings):
    response = client(adapter_settings).post(
        "/webhook/wrong",
        content=b"{}",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 404
    assert adapter_settings.ingress_token not in response.text


def test_gateway_validates_content_type_json_and_size(adapter_settings):
    valid_path = f"/webhook/{adapter_settings.ingress_token}"
    test_client = client(adapter_settings)
    assert test_client.post(valid_path, content=b"{}", headers={"Content-Type": "text/plain"}).status_code == 415
    assert test_client.post(valid_path, content=b"[1]", headers={"Content-Type": "application/json"}).status_code == 422
    oversized = b"x" * (adapter_settings.max_body_bytes + 1)
    assert test_client.post(valid_path, content=oversized, headers={"Content-Type": "application/json"}).status_code == 413


def test_gateway_enqueues_exact_raw_body_and_reports_duplicate(adapter_settings):
    body = b'{"event":"message_created","message":{"id":123},"conversation":{"id":42}}'
    queue = FakeQueue(queued=True)
    response = client(adapter_settings, queue).post(
        f"/webhook/{adapter_settings.ingress_token}",
        content=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert queue.calls[0][2] == body
    assert queue.calls[0][3] == "42"

    duplicate = FakeQueue(queued=False)
    response = client(adapter_settings, duplicate).post(
        f"/webhook/{adapter_settings.ingress_token}",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "duplicate"


def test_gateway_returns_redacted_503_when_queue_fails(adapter_settings):
    response = client(adapter_settings, FakeQueue(fail=True)).post(
        f"/webhook/{adapter_settings.ingress_token}",
        content=b"{}",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 503
    assert "secret backend failure" not in response.text
