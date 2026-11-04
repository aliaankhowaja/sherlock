"""G1 `laya` backend against a local System One stand-in: ordering, cache, fail-safe and privacy (AC-G1-4, 5, 11).

No real endpoint: `sherlock-rec g1-check --g1-allow-remote` is the live check.
"""

import json
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from g1_stub import LayaStub
from test_g1 import cassette, run  # noqa: F401 - `cassette` is a fixture

from sherlock import g1 as g1mod
from sherlock.g1 import QUESTIONS

KEY = "laya-planted-key-0123456789"


def answer(r):  # what G1 must never change; a set's members are listed in search order, so compare them as sets
    return [sorted(map(sorted, r[k])) for k in ("minimal_sets", "unverified_sets")] + [r["status"], r["reason_code"]]


def answers(body):
    """A well-formed System One reply: needs_restore is high for the extractor and low for every other node."""
    out = {}
    for qid, q in body["questions"].items():
        if q["type"] == "noul":
            out[qid] = {"type": "noul", "noul": (0.9 if "NODE: extractor" in body["state"] else 0.2)
                        if qid == "needs_restore" else 0.5}
        else:
            out[qid] = {"type": "choice", "probabilities": {o: 1 / len(q["criteria"]) for o in q["criteria"]}}
    return {"model": "stub-laya", "answers": out,
            "usage": {"input_tokens": 300, "state_tokens": 50, "state_tokens_dropped": 0, "truncated": False}}


def cfg(stub, tmp_path, **kw):
    return {"backend": "laya", "endpoint": stub.url, "cache_dir": tmp_path / "g1_cache", **kw}


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("LAYA_API_KEY", KEY)
    monkeypatch.delenv("LOCAL", raising=False)
    g1mod._LOCAL_AGENTS.clear()
    yield
    g1mod._LOCAL_AGENTS.clear()


class FakeLocalAgent:
    """The small part of `laya.Agent` G1 uses: `system_one(state, questions) -> raw result`."""

    def __init__(self):
        self.calls = []

    def system_one(self, state, questions):
        self.calls.append((state, questions))
        raw = answers({"state": state, "questions": questions})
        raw.pop("model", None)  # the local SDK need not name a checkpoint; G1 falls back to the requested model
        return raw


class FakeLaya:
    def __init__(self, agent):
        self.agent, self.loads = agent, []

    def load(self, model, **options):
        self.loads.append((model, options))
        return self.agent


def install_laya(monkeypatch, agent=None):
    agent = agent or FakeLocalAgent()
    module = FakeLaya(agent)
    monkeypatch.setitem(sys.modules, "laya", module)
    return agent, module


def local_cfg(tmp_path, **kw):
    return {"backend": "laya", "local": True, "endpoint": "https://api.laya.studio",
            "allow_remote": False, "cache_dir": tmp_path / "g1_cache", **kw}


def test_laya_orders_by_needs_restore_caches_and_never_leaks(cassette, tmp_path):  # noqa: F811
    base, events = run(cassette), []
    with LayaStub(lambda b: (200, answers(b), 0)) as stub:
        r = run(cassette, cfg(stub, tmp_path), progress=events.append)
        calls = len(stub.hits)
        again = run(cassette, cfg(stub, tmp_path))
        assert len(stub.hits) == calls  # the re-run is served from the cache, offline
    assert answer(r) == answer(base)
    g = r["g1"]
    assert g["status"] == "ok" and g["scores"][0]["node"] == "extractor" == r["pruning"]["candidates"][0]
    assert g["scores"][0]["answers"]["needs_restore"] == {"yes": 0.9, "no": 0.1} and g["model"] == "stub-laya"
    assert g["cache"] == {"hits": 0, "misses": calls} and again["g1"]["cache"] == {"hits": calls, "misses": 0}
    assert again["g1"]["scores"] == g["scores"]
    body = stub.hits[0]
    assert body["_auth"] == f"Bearer {KEY}" and body["_path"] == "/v1/systemone" and body["model"] == "typed-decisions"
    assert set(body["questions"]) == set(QUESTIONS)
    written = json.dumps([r, again, events]) + "".join(f.read_text() for f in (tmp_path / "g1_cache").iterdir())
    assert KEY not in written and body["state"] not in written  # AC-G1-11: no key, no card text


FAILURES = {
    "unauthorized": lambda b: (401, {"error": "bad key"}, 0),
    "no_credits": lambda b: (402, {"error": {"code": "insufficient_credits"}}, 0),
    "wrong_model": lambda b: (400, {"error": "unknown model"}, 0),
    "server_error": lambda b: (500, {}, 0),
    "malformed": lambda b: (200, {"answers": {}}, 0),
    "not_a_probability": lambda b: (200, {**answers(b), "answers": {
        **answers(b)["answers"], "needs_restore": {"type": "noul", "noul": 1.7}}}, 0),
    "timeout": lambda b: (200, answers(b), 1.5),
}


@pytest.mark.parametrize("name", FAILURES)
def test_a_failing_endpoint_leaves_the_result_as_if_g1_were_off(name, cassette, tmp_path):  # noqa: F811 - AC-G1-5
    base = run(cassette)
    with LayaStub(FAILURES[name]) as stub:
        r = run(cassette, cfg(stub, tmp_path, timeout_ms=300))
    assert answer(r) == answer(base) and r["pruning"] == base["pruning"]
    assert [t["restored"] for t in r["trials"]] == [t["restored"] for t in base["trials"]]
    assert r["g1"]["status"] == "unavailable" and r["g1"]["scores"] == []


def test_a_dead_port_is_unavailable(cassette, tmp_path):  # noqa: F811
    r = run(cassette, {"backend": "laya", "endpoint": "http://127.0.0.1:9", "cache_dir": tmp_path})
    assert r["g1"]["status"] == "unavailable" and "URLError" in r["g1"]["reason"]


def test_a_truncated_card_gets_no_score_and_a_429_is_retried(cassette, tmp_path):  # noqa: F811
    def reply(body):
        if len(stub.hits) == 1:
            return 429, {}, 0
        out = answers(body)
        out["usage"]["truncated"] = "NODE: extractor" in body["state"]
        return 200, out, 0

    with LayaStub(reply) as stub:
        g = run(cassette, cfg(stub, tmp_path))["g1"]
    assert g["status"] == "partial" and g["truncated_cards"] == ["extractor"]
    assert g["scores"][-1] == {"node": "extractor", "score": None, "answers": g["scores"][-1]["answers"]}


def test_every_card_truncated_stays_partial_and_does_not_look_like_a_missing_key(cassette, tmp_path):  # noqa: F811
    base = run(cassette)

    def reply(body):
        out = answers(body)
        out["usage"]["truncated"] = True
        out["usage"]["state_tokens_dropped"] = 12
        return 200, out, 0

    with LayaStub(reply) as stub:
        r = run(cassette, cfg(stub, tmp_path))
    g = r["g1"]
    assert g["status"] == "partial" and "reason" not in g
    assert g["scores"] and all(s["score"] is None for s in g["scores"])
    assert set(g["truncated_cards"]) == {s["node"] for s in g["scores"]}
    assert answer(r) == answer(base)


def test_a_remote_endpoint_needs_the_opt_in_and_a_key_and_nothing_connects(cassette, tmp_path, monkeypatch):  # noqa: F811
    tried = []
    real = socket.socket.connect
    monkeypatch.setattr(socket.socket, "connect", lambda self, addr: tried.append(addr) or real(self, addr))
    remote = {"backend": "laya", "endpoint": "https://api.laya.studio", "cache_dir": tmp_path}
    no_opt_in = run(cassette, remote)["g1"]
    monkeypatch.delenv("LAYA_API_KEY")
    no_key = run(cassette, {**remote, "allow_remote": True})["g1"]
    run(cassette, {"backend": "fake"})
    assert no_opt_in["status"] == "unavailable" and "--g1-allow-remote" in no_opt_in["reason"]
    assert no_key["status"] == "unavailable" and "LAYA_API_KEY" in no_key["reason"]
    assert tried == []  # AC-G1-4


class BatchAgent(FakeLocalAgent):
    """Scores every uncached card in one predict_batch, which is what Metal wants."""

    def __init__(self):
        super().__init__()
        self.batches = []

    def predict_batch(self, states, questions):
        self.batches.append(list(states))
        out = []
        for state in states:
            raw = answers({"state": state, "questions": questions})
            raw.pop("model", None)
            out.append(raw)
        return out


def test_local_scoring_uses_one_batch_for_uncached_cards(cassette, tmp_path, monkeypatch):  # noqa: F811
    agent, module = install_laya(monkeypatch, BatchAgent())
    r = run(cassette, local_cfg(tmp_path))
    g = r["g1"]
    assert g["status"] == "ok" and g["scores"][0]["node"] == "extractor"
    assert agent.calls == [] and len(agent.batches) == 1 and len(agent.batches[0]) > 1
    assert module.loads == [("typed-decisions", {})]


def test_local_inference_needs_no_endpoint_key_or_network(cassette, tmp_path, monkeypatch):  # noqa: F811 - AC-G1-4
    base = run(cassette)
    agent, module = install_laya(monkeypatch)
    monkeypatch.delenv("LAYA_API_KEY")
    tried = []
    real = socket.socket.connect
    monkeypatch.setattr(socket.socket, "connect", lambda self, addr: tried.append(addr) or real(self, addr))
    r = run(cassette, local_cfg(tmp_path))
    calls = len(agent.calls)
    again = run(cassette, local_cfg(tmp_path))
    assert answer(r) == answer(base)
    assert set(r["pruning"]["candidates"]) == set(base["pruning"]["candidates"])
    g = r["g1"]
    assert g["status"] == "ok" and g["mode"] == "local" and g["endpoint_host"] is None
    assert g["scores"][0]["node"] == "extractor" == r["pruning"]["candidates"][0]
    assert g["model"] == "typed-decisions"  # the local result does not name one
    assert module.loads == [("typed-decisions", {})]  # one resident agent, not one per card
    assert g["cache"] == {"hits": 0, "misses": calls} and again["g1"]["cache"] == {"hits": calls, "misses": 0}
    assert len(agent.calls) == calls and again["g1"]["scores"] == g["scores"]  # re-run is offline from the cache
    assert tried == []  # in-process inference opens no connection


def test_local_mode_can_be_selected_by_environ_and_overridden_by_config(cassette, tmp_path, monkeypatch):  # noqa: F811
    agent, _ = install_laya(monkeypatch)
    monkeypatch.setenv("LOCAL", "true")
    monkeypatch.delenv("LAYA_API_KEY")
    g = run(cassette, {"backend": "laya", "cache_dir": tmp_path / "g1_cache"})["g1"]
    assert g["mode"] == "local" and g["status"] == "ok" and agent.calls
    with LayaStub(lambda b: (200, answers(b), 0)) as stub:
        http = run(cassette, {**cfg(stub, tmp_path), "local": False})["g1"]
    assert http["mode"] == "http" and http["status"] == "ok"


def test_a_missing_or_unloadable_local_model_leaves_the_result_as_if_g1_were_off(cassette, tmp_path, monkeypatch):  # noqa: F811
    base = run(cassette)
    monkeypatch.setitem(sys.modules, "laya", None)  # `import laya` fails
    missing = run(cassette, local_cfg(tmp_path))
    assert answer(missing) == answer(base) and missing["g1"]["status"] == "unavailable"
    assert "pip install laya" in missing["g1"]["reason"]

    class Broken:
        def load(self, model, **options):
            raise OSError("checkpoint missing")

    monkeypatch.setitem(sys.modules, "laya", Broken())
    broken = run(cassette, local_cfg(tmp_path))
    assert answer(broken) == answer(base) and broken["g1"]["status"] == "unavailable"
    assert "could not be loaded" in broken["g1"]["reason"] and "typed-decisions" in broken["g1"]["reason"]


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_local_env_truthy_values(value, monkeypatch):
    monkeypatch.setenv("LOCAL", value)
    assert g1mod.local_mode({})


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off"])
def test_local_env_falsey_values(value, monkeypatch):
    monkeypatch.setenv("LOCAL", value)
    assert not g1mod.local_mode({})
    assert not g1mod.local_mode({"local": False})


def test_local_mode_uses_a_longer_default_total_timeout(monkeypatch):
    seen = []

    def fake(cfg, card, timeout_s):
        seen.append(cfg["total_timeout_ms"])
        return {"answers": {"needs_restore": {"yes": 0.5, "no": 0.5}}, "truncated": False, "model": "local"}, False

    monkeypatch.setattr(g1mod, "cached_answers", fake)
    g1mod.rank({"backend": "laya", "local": True}, ["a", "b"], lambda n: (n, False))
    assert seen == [g1mod.LOCAL_TOTAL_TIMEOUT_MS] * 2
    seen.clear()
    g1mod.rank({"backend": "laya", "local": True, "total_timeout_ms": 1234}, ["a", "b"], lambda n: (n, False))
    assert seen == [1234] * 2
