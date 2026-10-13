"""FR-R8: secrets and PII never reach the cassette's stored request, yet replay still matches."""

import json

from sherlock.cassette import Cassette, request_key
from sherlock.redact import REDACTED, redact_body


def _load(b):
    return json.loads(b)


def test_deny_listed_keys_are_masked_at_any_depth():
    body = json.dumps({"model": "m", "max_tokens": 5, "api_key": "abc", "auth": {"Authorization": "Bearer xyz12345678"},
                       "items": [{"password": "hunter2", "n": 1}]}).encode()
    out = _load(redact_body(body))
    assert out["api_key"] == REDACTED and out["auth"]["Authorization"] == REDACTED
    assert out["items"][0] == {"password": REDACTED, "n": 1}
    assert out["model"] == "m" and out["max_tokens"] == 5  # max_tokens is not a secret


def test_secret_shaped_values_and_emails_are_masked_inside_text():
    body = json.dumps({"messages": [{"role": "user", "content":
        "use key sk-abcdefghijklmnopqrstuvwx and mail jane.doe@example.com, header Bearer abcdefghij1234"}]}).encode()
    text = _load(redact_body(body))["messages"][0]["content"]
    assert "sk-abcdefghijklmnopqrstuvwx" not in text and "jane.doe@example.com" not in text
    assert "abcdefghij1234" not in text and text.startswith("use key ")


def test_non_json_bodies_are_scanned_as_text():
    assert b"sk-abcdefghijklmnopqrstuvwx" not in redact_body(b"token=sk-abcdefghijklmnopqrstuvwx&a=1")


def test_clean_bodies_are_untouched():
    body = b'{"a":1,"q":"hello world"}'
    assert redact_body(body) == body


def test_cassette_stores_redacted_request_but_keys_on_the_original(tmp_path):
    cas = Cassette(tmp_path / "c.db")
    body = json.dumps({"api_key": "s3cret-value", "q": "hi"}).encode()
    call_id = cas.begin("http", "POST http://x/v1", body)
    row = cas.calls()[0]
    assert b"s3cret-value" not in bytes(row["request"])
    assert row["key"] == request_key("http", "POST http://x/v1", body) and row["id"] == call_id
