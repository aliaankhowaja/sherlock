import asyncio
import pickle

import pytest
from langchain_core.tools import tool
import langchain_core.tools.base as tools_base

from sherlock import shim_tools
from sherlock.cassette import Cassette
from sherlock.runtime import Runtime

CALLS = []


@tool
def word_count(text: str) -> int:
    """Count words."""
    CALLS.append(text)
    return len(text.split())


@tool
def boom(text: str) -> int:
    """Always fails."""
    raise RuntimeError("tool exploded")


@pytest.fixture
def rt(tmp_path):
    CALLS.clear()
    rt = Runtime(Cassette(tmp_path / ".sherlock" / "c.db"), "record")
    shim_tools.patch(tools_base, rt)
    yield rt
    shim_tools.unpatch(tools_base)


def test_local_tool_call_is_recorded_with_input_and_output(rt):
    assert word_count.invoke({"text": "a b c"}) == 3
    (call,) = rt.cassette.calls()
    assert call["kind"] == "tool" and call["name"] == "word_count" and call["status"] == 0
    assert b"a b c" in call["request"]
    first, readable = rt.cassette.chunks(call["id"])
    assert pickle.loads(first) == 3 and readable == b"3"


def test_async_tool_call_is_recorded(rt):
    assert asyncio.run(word_count.ainvoke({"text": "x y"})) == 2
    (call,) = rt.cassette.calls()
    assert call["name"] == "word_count"


def test_tool_exception_is_recorded_and_still_raised(rt):
    with pytest.raises(RuntimeError, match="tool exploded"):
        boom.invoke({"text": "x"})
    (call,) = rt.cassette.calls()
    assert call["name"] == "boom" and call["status"] == 1


def test_recorder_failure_never_breaks_the_tool(rt, monkeypatch):
    monkeypatch.setattr(rt.cassette, "begin", lambda *a, **k: 1 / 0)
    assert word_count.invoke({"text": "a b"}) == 2


def test_patch_is_idempotent(rt):
    shim_tools.patch(tools_base, rt)
    word_count.invoke({"text": "a"})
    assert len(rt.cassette.calls()) == 1
