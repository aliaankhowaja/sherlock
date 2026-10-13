import asyncio
import socket

import httpx
import langchain_core.tools.base as tools_base
import pytest
from langchain_core.tools import tool
from stub_server import StubServer

from sherlock import shim_httpx, shim_tools
from sherlock.cassette import Cassette
from sherlock.runtime import CannotSay, Runtime

URL_PATH = "/v1/chat/completions"
BODY = {"model": "stub-1", "messages": [{"role": "user", "content": "hello there"}]}
CHANGED = {"model": "stub-1", "messages": [{"role": "user", "content": "something else"}]}
RAN = []


@tool
def shout(text: str) -> str:
    """Upper-case."""
    RAN.append(text)
    return text.upper()


@tool
def boom(text: str) -> str:
    """Fails."""
    RAN.append(text)
    raise ValueError("bad input")


@pytest.fixture
def stub():
    with StubServer() as s:
        yield s


@pytest.fixture
def session(tmp_path):
    """record() / replay(match) install the shims over one shared cassette file."""
    path = tmp_path / ".sherlock" / "c.db"
    state = {}

    def install(mode, match="hash"):
        uninstall()
        rt = Runtime(Cassette(path), mode, match)
        shim_httpx.patch(httpx, rt)
        shim_tools.patch(tools_base, rt)
        state["rt"] = rt
        return rt

    def uninstall():
        shim_httpx.unpatch(httpx)
        shim_tools.unpatch(tools_base)

    yield install
    uninstall()


@pytest.fixture
def block_sockets(monkeypatch):
    """Call to forbid any outbound connection from here on."""
    def block():
        def deny(self, *a, **k):
            raise AssertionError(f"network attempted during replay: {a}")

        monkeypatch.setattr(socket.socket, "connect", deny)
        monkeypatch.setattr(socket.socket, "connect_ex", deny)

    return block


def test_json_replay_makes_no_network_call_and_matches_recording(stub, session, block_sockets):
    session("record")
    live = httpx.post(stub.url + URL_PATH, json=BODY)
    hits_after_record = len(stub.hits)
    stub.stop()  # server gone, and sockets blocked: any live call would fail loudly
    block_sockets()
    session("replay")
    r = httpx.post(stub.url + URL_PATH, json=BODY)
    assert (r.status_code, r.content) == (live.status_code, live.content)
    assert r.headers["content-type"] == "application/json"
    assert len(stub.hits) == hits_after_record


def test_sse_replay_delivers_the_same_ordered_chunks(stub, session):
    session("record")
    with httpx.stream("POST", stub.url + URL_PATH, json={**BODY, "stream": True}) as r:
        live = list(r.iter_raw())
    stub_hits = len(stub.hits)
    session("replay")
    with httpx.stream("POST", stub.url + URL_PATH, json={**BODY, "stream": True}) as r:
        replayed = list(r.iter_raw())
    assert replayed == live and len(live) >= 3
    assert len(stub.hits) == stub_hits


def test_async_replay(stub, session):
    async def call():
        async with httpx.AsyncClient() as c:
            return await c.post(stub.url + URL_PATH, json=BODY)

    session("record")
    live = asyncio.run(call())
    session("replay")
    again = asyncio.run(call())
    assert again.content == live.content and len(stub.hits) == 1


def test_changed_request_abstains_and_never_goes_live(stub, session):
    session("record")
    httpx.post(stub.url + URL_PATH, json=BODY)
    rt = session("replay")
    with pytest.raises(CannotSay, match="cannot say"):
        httpx.post(stub.url + URL_PATH, json=CHANGED)
    assert len(stub.hits) == 1  # nothing was sent
    (reason,) = rt.cassette.abstains()
    assert reason.startswith("cannot say") and "changed" in reason


def test_never_recorded_request_abstains(stub, session):
    session("record")
    session("replay")
    with pytest.raises(CannotSay, match="never recorded"):
        httpx.post(stub.url + URL_PATH, json=BODY)
    assert stub.hits == []


def test_abstain_is_not_swallowed_by_except_exception(stub, session):
    session("record")
    session("replay")
    swallowed = False
    try:
        try:
            httpx.post(stub.url + URL_PATH, json=BODY)
        except Exception:
            swallowed = True
    except CannotSay:
        pass
    assert not swallowed


def test_sequence_fallback_serves_changed_request_in_recorded_order(stub, session):
    session("record")
    first = httpx.post(stub.url + URL_PATH, json=BODY)
    session("replay", match="sequence")
    r = httpx.post(stub.url + URL_PATH, json=CHANGED)
    assert r.content == first.content
    with pytest.raises(CannotSay):  # only one recorded call to hand out
        httpx.post(stub.url + URL_PATH, json=CHANGED)


def test_tool_replay_does_not_run_the_tool(session):
    RAN.clear()
    session("record")
    assert shout.invoke({"text": "abc"}) == "ABC"
    assert RAN == ["abc"]
    RAN.clear()
    session("replay")
    assert shout.invoke({"text": "abc"}) == "ABC"
    assert RAN == []


def test_tool_replay_reraises_recorded_error(session):
    session("record")
    with pytest.raises(ValueError):
        boom.invoke({"text": "x"})
    RAN.clear()
    session("replay")
    with pytest.raises(ValueError, match="bad input"):
        boom.invoke({"text": "x"})
    assert RAN == []


def test_tool_changed_input_abstains(session):
    session("record")
    shout.invoke({"text": "abc"})
    RAN.clear()
    session("replay")
    with pytest.raises(CannotSay, match="cannot say"):
        shout.invoke({"text": "different"})
    assert RAN == []
