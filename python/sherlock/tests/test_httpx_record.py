import asyncio

import httpx
import pytest
from stub_server import StubServer

from sherlock import shim_httpx
from sherlock.cassette import Cassette
from sherlock.runtime import Runtime

BODY = {"model": "stub-1", "messages": [{"role": "user", "content": "hello there"}]}


@pytest.fixture
def stub():
    with StubServer() as s:
        yield s


@pytest.fixture
def rt(tmp_path):
    rt = Runtime(Cassette(tmp_path / ".sherlock" / "c.db"), "record")
    shim_httpx.patch(httpx, rt)
    yield rt
    shim_httpx.unpatch(httpx)


def test_json_call_is_recorded_with_full_bodies(stub, rt):
    r = httpx.post(f"{stub.url}/v1/chat/completions", json=BODY, headers={"Authorization": "Bearer sk-secret"})
    assert r.json()["choices"][0]["message"]["content"] == "echo: hello there"  # caller unaffected
    (call,) = rt.cassette.calls()
    assert call["kind"] == "http" and call["name"] == f"POST {stub.url}/v1/chat/completions"
    assert b"hello there" in call["request"]
    assert call["status"] == 200 and not call["is_sse"] and call["complete"] == 1
    assert call["duration_ms"] >= 0
    assert b"".join(rt.cassette.chunks(call["id"])) == r.content


def test_sse_response_is_recorded_as_ordered_chunks(stub, rt):
    seen = b""
    with httpx.stream("POST", f"{stub.url}/v1/chat/completions", json={**BODY, "stream": True}) as r:
        for part in r.iter_bytes():
            seen += part
    (call,) = rt.cassette.calls()
    chunks = rt.cassette.chunks(call["id"])
    assert call["is_sse"] == 1
    assert len(chunks) >= 3  # one per delta event, not one blob
    assert b"".join(chunks) == seen
    assert chunks[-1].endswith(b"data: [DONE]\n\n")
    order = [i for w in (b"echo:", b"hello", b"there") for i, c in enumerate(chunks) if w in c]
    assert order == sorted(order) and len(order) == 3  # chunk order preserved


def test_async_client_is_recorded(stub, rt):
    async def go():
        async with httpx.AsyncClient() as c:
            return await c.post(f"{stub.url}/v1/chat/completions", json=BODY)

    r = asyncio.run(go())
    (call,) = rt.cassette.calls()
    assert b"".join(rt.cassette.chunks(call["id"])) == r.content


def test_request_headers_and_secrets_are_not_stored(stub, rt):
    httpx.post(f"{stub.url}/v1/chat/completions", json=BODY, headers={"Authorization": "Bearer sk-secret"})
    assert b"sk-secret" not in rt.cassette.path.read_bytes()


def test_recorder_failure_never_breaks_the_call(stub, rt, monkeypatch):
    monkeypatch.setattr(rt.cassette, "begin", lambda *a, **k: 1 / 0)
    r = httpx.post(f"{stub.url}/v1/chat/completions", json=BODY)
    assert r.status_code == 200


def test_patch_is_idempotent(stub, rt):
    shim_httpx.patch(httpx, rt)
    httpx.post(f"{stub.url}/v1/chat/completions", json=BODY)
    assert len(rt.cassette.calls()) == 1
