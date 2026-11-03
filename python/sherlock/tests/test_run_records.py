import os
import signal
import subprocess
import sys
import time

import pytest

from stub_server import StubServer

from sherlock.cassette import Cassette

CODE = """
import httpx, sys
r = httpx.post(sys.argv[1] + "/v1/chat/completions", json={"model": "m", "messages": [{"role": "user", "content": "hi"}]})
print(r.json()["choices"][0]["message"]["content"])
"""


def test_sherlock_run_records_httpx_calls_with_zero_user_code_changes(tmp_path):
    with StubServer() as stub:
        p = subprocess.run([sys.executable, "-m", "sherlock", "run", sys.executable, "-c", CODE, stub.url],
                           cwd=tmp_path, capture_output=True, text=True, env=os.environ.copy())
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip() == "echo: hi"
    (call,) = Cassette(tmp_path / ".sherlock" / "cassette.db").calls()
    assert call["status"] == 200 and b'"hi"' in call["request"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal forwarding")
def test_run_forwards_sigint_so_the_child_can_flush(tmp_path):
    ready, done = tmp_path / "ready", tmp_path / "done"
    code = """
import signal, sys, time
from pathlib import Path
ready, done = Path(sys.argv[1]), Path(sys.argv[2])
signal.signal(signal.SIGINT, lambda *_: (done.write_text("clean"), sys.exit(0)))
ready.write_text("ready")
time.sleep(60)
"""
    proc = subprocess.Popen([sys.executable, "-m", "sherlock", "run", sys.executable, "-c", code,
                             str(ready), str(done)], cwd=tmp_path, env=os.environ.copy())
    try:
        for _ in range(200):
            if ready.exists():
                break
            time.sleep(0.05)
        assert ready.exists()
        proc.send_signal(signal.SIGINT)
        assert proc.wait(timeout=10) == 0
        assert done.read_text() == "clean"
    finally:
        if proc.poll() is None:
            proc.kill()
