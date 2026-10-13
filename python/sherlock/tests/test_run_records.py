import os
import subprocess
import sys

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
