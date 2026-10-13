"""Phase 2 additions to the recorder: per-trial consumption (FR-G3.5), the read-safe tool
allowlist (FR-G3.8) and the replay-session marker G3 relies on."""

import httpx
import langchain_core.tools.base as tools_base
import pytest
from stub_server import StubServer

from sherlock import _boot, shim_httpx, shim_tools
from sherlock.cassette import Cassette
from sherlock.runtime import CannotSay, Runtime
from test_replay import BODY, RAN, URL_PATH, boom, shout


@pytest.fixture
def stub():
    with StubServer() as s:
        yield s


@pytest.fixture
def patched():
    state = {}

    def install(path, mode, **kw):
        shim_httpx.unpatch(httpx)
        shim_tools.unpatch(tools_base)
        rt = Runtime(Cassette(path), mode, **kw)
        shim_httpx.patch(httpx, rt)
        shim_tools.patch(tools_base, rt)
        state["rt"] = rt
        return rt

    yield install
    shim_httpx.unpatch(httpx)
    shim_tools.unpatch(tools_base)


def test_a_new_trial_makes_recordings_available_again(stub, patched, tmp_path):
    path = tmp_path / "c.db"
    patched(path, "record")
    httpx.post(stub.url + URL_PATH, json=BODY)
    patched(path, "replay")
    httpx.post(stub.url + URL_PATH, json=BODY)
    with pytest.raises(CannotSay):  # one recording, already consumed in this trial
        httpx.post(stub.url + URL_PATH, json=BODY)
    first = Cassette(path).start_trial()
    assert httpx.post(stub.url + URL_PATH, json=BODY).status_code == 200  # fresh trial, served again
    assert Cassette(path).start_trial() == first + 1
    with pytest.raises(CannotSay):  # still never invents a second answer within one trial
        httpx.post(stub.url + URL_PATH, json=BODY)
        httpx.post(stub.url + URL_PATH, json=BODY)


def test_allowlist_lets_read_safe_tools_through_and_aborts_the_rest(patched, tmp_path):
    path = tmp_path / "c.db"
    patched(path, "record")
    shout.invoke({"text": "a"})
    with pytest.raises(ValueError):
        boom.invoke({"text": "a"})
    RAN.clear()
    patched(path, "replay", allow_tools=["shout"])
    assert shout.invoke({"text": "a"}) == "A"
    with pytest.raises(CannotSay, match="boom.*read-safe allowlist"):
        boom.invoke({"text": "a"})
    assert RAN == []  # nothing fired
    assert any("read-safe allowlist" in r for r in Cassette(path).abstains())


def test_no_allowlist_keeps_phase_one_behaviour(patched, tmp_path):
    path = tmp_path / "c.db"
    patched(path, "record")
    shout.invoke({"text": "a"})
    patched(path, "replay")
    assert shout.invoke({"text": "a"}) == "A"


def test_bootstrap_marks_the_cassette_as_served_by_a_replay_process(tmp_path, monkeypatch):
    path = tmp_path / "c.db"
    Cassette(path)  # exists
    assert Cassette(path).replay_sessions() == 0
    monkeypatch.setenv("SHERLOCK_MODE", "replay")
    monkeypatch.setenv("SHERLOCK_CASSETTE", str(path))
    monkeypatch.setenv("SHERLOCK_ALLOW_TOOLS", "a, b")
    monkeypatch.setattr(_boot._hook, "install", lambda patches: None)
    _boot.bootstrap()
    assert Cassette(path).replay_sessions() == 1


def test_launcher_passes_the_allowlist_to_the_child(tmp_path):
    from sherlock.cli import child_env

    assert child_env("replay", tmp_path / "c.db", "hash", base={}, allow_tools=["a", "b"])["SHERLOCK_ALLOW_TOOLS"] == "a,b"
    assert "SHERLOCK_ALLOW_TOOLS" not in child_env("replay", tmp_path / "c.db", "hash", base={})


def test_replay_children_skip_the_langgraph_version_check_which_is_a_live_call(tmp_path):
    from sherlock.cli import child_env

    assert child_env("replay", tmp_path / "c.db", "hash", base={})["LANGGRAPH_NO_VERSION_CHECK"] == "1"
    assert "LANGGRAPH_NO_VERSION_CHECK" not in child_env("record", tmp_path / "c.db", "hash", base={})
