"""Phase 1 exit criterion (STATUS.md): record the LLM demo team via `sherlock run`, replay it with
zero network calls, and see a deliberately changed request abort with "cannot say"."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from stub_server import StubServer

from sherlock.cassette import Cassette

TESTS = Path(__file__).parent
TEAM = str(TESTS / "llm_team.py")
NO_NET = str(TESTS / "no_net.py")
QUESTION = "what happened to the vendor brief"


def sherlock(*args, cwd, env=None):
    return subprocess.run([sys.executable, "-m", "sherlock", "run", *args], cwd=cwd,
                          capture_output=True, text=True, env={**os.environ, **(env or {})})


@pytest.mark.parametrize("stream", ["0", "1"], ids=["json", "sse"])
def test_record_replay_offline_and_changed_request_abstains(tmp_path, stream):
    env = {"STREAM": stream, "NO_NET_MARKER": str(tmp_path / "net_attempts.txt")}
    stub = StubServer().start()
    url, port = stub.url, stub.port
    try:
        # 1. record, with zero edits to the team
        rec = sherlock(sys.executable, TEAM, url, QUESTION, cwd=tmp_path, env=env)
        assert rec.returncode == 0, rec.stderr
        assert '"answer": "echo: what happened' in rec.stdout and '"words": 7' in rec.stdout
        assert len(stub.hits) == 1 and stub.hits[0]["stream"] == (stream == "1")
    finally:
        stub.stop()  # the provider is gone from here on
    calls = Cassette(tmp_path / ".sherlock" / "cassette.db").calls()
    assert [c["kind"] for c in calls] == ["http", "tool"]
    assert calls[0]["is_sse"] == (stream == "1")
    if stream == "1":
        assert len(Cassette(tmp_path / ".sherlock" / "cassette.db").chunks(calls[0]["id"])) >= 3

    # 2. replay offline: server stopped AND a socket trap on its port; output identical
    rep = sherlock("--replay", sys.executable, NO_NET, str(port), TEAM, url, QUESTION, cwd=tmp_path, env=env)
    assert rep.returncode == 0, rep.stderr
    assert rep.stdout == rec.stdout
    assert not (tmp_path / "net_attempts.txt").exists(), "replay tried to open a connection"

    # 3. a deliberately changed request abstains
    bad = sherlock("--replay", sys.executable, NO_NET, str(port), TEAM, url, "a different question",
                   cwd=tmp_path, env=env)
    assert bad.returncode == 75
    assert "cannot say: request changed since recording" in bad.stderr
    assert "answer" not in bad.stdout
    assert not (tmp_path / "net_attempts.txt").exists()
