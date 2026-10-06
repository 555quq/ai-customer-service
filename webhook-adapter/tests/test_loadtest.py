import hashlib
import hmac

from loadtest.loadgen import histogram_quantile_from_metrics
from loadtest.mock_bridge import signature_valid


def test_mock_bridge_verifies_exact_hmac_v2_request():
    body = b'{"event":"message_created"}'
    timestamp = "1789488000"
    event_id = "a" * 64
    canonical = timestamp.encode() + b"\n" + event_id.encode() + b"\n" + body
    signature = "sha256=" + hmac.new(b"secret", canonical, hashlib.sha256).hexdigest()

    assert signature_valid("secret", signature, timestamp, event_id, body, now=1789488000)
    assert not signature_valid("secret", signature, timestamp, event_id, body + b" ", now=1789488000)


def test_histogram_quantile_uses_scenario_bucket_deltas():
    before = {
        1.0: 10,
        2.0: 10,
        3.0: 10,
        float("inf"): 10,
    }
    after = {
        1.0: 28,
        2.0: 29,
        3.0: 30,
        float("inf"): 30,
    }

    assert histogram_quantile_from_metrics(before, after, 0.95) == 2.0
