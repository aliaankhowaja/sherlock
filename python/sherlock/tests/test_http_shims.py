"""NFR-3: `requests` and `urllib.request` are recorded, then replayed from the cassette without going live."""

import json
import urllib.error
import urllib.request

import pytest
import requests
import requests.adapters
from stub_server import StubServer

from sherlock import shim_http
from sherlock.cassette import Cassette
from sherlock.runtime import CannotSay, Runtime

BODY = {"model": "stub-1", "messages": [{"role": "user", "content": "hello there"}]}
CHANGED = {"model": "stub-1", "messages": [{"role": "user", "content": "other"}]}


@pytest.fixture
def stub():
    with StubServer() as s:
        yield s


@pytest.fixture
def install(tmp_path):
    path = tmp_path / ".sherlock" / "c.db"

    def go(mode):
        shim_http.unpatch_requests(requests.adapters)
        shim_http.unpatch_urllib(urllib.request)
        rt = Runtime(Cassette(path), mode)
        shim_http.patch_requests(requests.adapters, rt)
        shim_http.patch_urllib(urllib.request, rt)
        return rt

    yield go
    shim_http.unpatch_requests(requests.adapters)
    shim_http.unpatch_urllib(urllib.request)


def _urllib_post(url, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_requests_records_then_replays_without_going_live(stub, install):
    url = f"{stub.url}/v1/chat/completions"
    rt = install("record")
    live = requests.post(url, json=BODY).json()
    assert len(rt.cassette.calls()) == 1 and len(stub.hits) == 1
    install("replay")
    again = requests.post(url, json=BODY)
    assert again.status_code == 200 and again.json() == live and len(stub.hits) == 1  # no second live hit
    with pytest.raises(CannotSay):
        requests.post(url, json=CHANGED)
    assert len(stub.hits) == 1


def test_urllib_records_then_replays_without_going_live(stub, install):
    url = f"{stub.url}/v1/chat/completions"
    rt = install("record")
    live = _urllib_post(url, BODY)
    assert len(rt.cassette.calls()) == 1
    install("replay")
    assert _urllib_post(url, BODY) == live and len(stub.hits) == 1
    with pytest.raises(CannotSay):
        _urllib_post(url, CHANGED)
    assert len(stub.hits) == 1


def test_urllib_error_status_is_recorded_and_replayed_as_http_error(stub, install):
    url = f"{stub.url}/v1/chat/completions"
    install("record")
    with pytest.raises(urllib.error.HTTPError) as e1:
        urllib.request.urlopen(url)  # the stub has no GET: 501
    install("replay")
    with pytest.raises(urllib.error.HTTPError) as e2:
        urllib.request.urlopen(url)  # the stub has no GET: 501
    assert e1.value.code == e2.value.code


def test_bootstrap_patches_requests_and_urllib_in_a_child_process(stub, tmp_path):
    import subprocess
    import sys

    code = (f"import requests, urllib.request;"
            f"print(requests.post('{stub.url}/v1/chat/completions', json={BODY!r}).status_code);"
            f"print(urllib.request.urlopen(urllib.request.Request('{stub.url}/v1/chat/completions', "
            f"{json.dumps(BODY).encode()!r})).status)")
    run = lambda *a: subprocess.run([sys.executable, "-m", "sherlock", "run", *a, sys.executable, "-c", code],
                                    cwd=tmp_path, capture_output=True, text=True)
    rec = run()
    assert rec.returncode == 0 and rec.stdout.split() == ["200", "200"], rec.stderr
    assert len(stub.hits) == 2
    rep = run("--replay")
    assert rep.returncode == 0 and rep.stdout.split() == ["200", "200"], rep.stderr
    assert len(stub.hits) == 2  # replay never went live
