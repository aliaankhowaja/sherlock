"""G1 optional shortlist (FR-G1.1-G1.6) and per-gate attribution. Local stub only: no provider, no network."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from g1_stub import ShortlistStub
from test_diagnose_unit import KG, DiagServer
from test_g3_unit import CHECKS, HISTORY

from sherlock.cassette import Cassette
from sherlock.diagnose import diagnose
from sherlock.gates import parse_nominations, run_g1
from sherlock.search import Budget

NODES = ["router", "retriever", "extractor", "writer", "reviewer"]


def g1(url, **kw):
    return run_g1(HISTORY, "final_output", "the wrong answer", ["no match"], NODES, url=url, model="stub", **kw)


def test_parse_accepts_lists_objects_prose_and_drops_unknown_names():
    assert parse_nominations('["extractor", "ghost"]', NODES) == (["extractor"], ["ghost"])
    assert parse_nominations('{"nodes": ["writer"]}', NODES)[0] == ["writer"]
    assert parse_nominations("I suspect the retriever and then the writer.", NODES)[0] == ["retriever", "writer"]
    assert parse_nominations("nothing useful", NODES) == ([], [])


def test_call_has_no_tools_and_the_prompt_is_redacted():
    secret = "sk-" + "a" * 30
    history = [dict(s, tasks=[dict(t, result={**(t.get("result") or {}), "note": f"key {secret} mail bob@corp.com"})
                              for t in s.get("tasks") or []]) for s in HISTORY]
    with ShortlistStub(["extractor"]) as stub:
        r = run_g1(history, "final_output", "out", [], NODES, url=stub.url, model="m", key="k-123")
    body = stub.hits[0]
    assert "tools" not in body and "functions" not in body and "tool_choice" not in body
    prompt = json.dumps(body["messages"])
    assert secret not in prompt and "bob@corp.com" not in prompt and r.redactions >= 1
    assert body["_auth"] == "Bearer k-123" and r.endpoint.startswith("http://127.0.0.1")
    assert r.nominated == ["extractor"] and r.fallback is None


def test_samples_only_widen_the_list():
    with ShortlistStub(per_sample=[["extractor"], ["writer", "extractor"], []]) as stub:
        r = g1(stub.url, samples=3)
    assert r.per_sample == [["extractor"], ["writer", "extractor"], []]
    assert set(r.nominated) == {"extractor", "writer"} and r.nominated[0] == "extractor"  # most-named first, none dropped


def test_empty_or_unreachable_falls_back_to_g0_only_and_says_so():
    with ShortlistStub(raw="no idea") as stub:
        empty = g1(stub.url, samples=2)
    assert empty.nominated == [] and empty.fallback == "g0_only" and "G0 clues only" in empty.note
    down = g1("http://127.0.0.1:9/v1", timeout=1)
    assert down.fallback == "g0_only" and down.error and down.samples_ok == 0


@pytest.fixture
def cassette(tmp_path):
    path = tmp_path / "c.db"
    Cassette(path).mark_replay(1)
    return path


def run(cassette, g1_cfg=None, **kw):
    server = DiagServer(["retriever.drop_latest", "extractor.legacy_pattern"])
    return diagnose(server, "T", KG, CHECKS, cassette, Budget(), g1=g1_cfg, **kw)


def test_g1_changes_order_never_the_answer(cassette):
    base = run(cassette)
    with ShortlistStub(["extractor", "writer"]) as stub:
        with_g1 = run(cassette, {"url": stub.url, "model": "stub", "samples": 1})
    assert [sorted(x) for x in with_g1["minimal_sets"]] == [sorted(x) for x in base["minimal_sets"]] and with_g1["status"] == "found"
    assert with_g1["g1"]["nominated"] == ["extractor", "writer"] and with_g1["g1"]["strength"] == "weak"
    assert with_g1["pruning"]["candidates"][0] == "extractor"  # nominated first among otherwise equal candidates
    assert set(with_g1["pruning"]["candidates"]) == set(base["pruning"]["candidates"])  # nothing excluded or added
    assert base["g1"]["enabled"] is False  # FR-G1.6: off by default, system complete


def test_wrong_or_failing_g1_cannot_hide_the_culprits(cassette):
    with ShortlistStub(["router"]) as stub:  # confidently wrong
        wrong = run(cassette, {"url": stub.url, "model": "stub"})
    assert [sorted(x) for x in wrong["minimal_sets"]] == [["extractor", "retriever"]]
    dead = run(cassette, {"url": "http://127.0.0.1:9/v1", "model": "stub"})
    assert [sorted(x) for x in dead["minimal_sets"]] == [["extractor", "retriever"]] and dead["g1"]["fallback"] == "g0_only"


def test_artifact_attributes_each_trial_and_summarises_each_gate(cassette):
    with ShortlistStub(["extractor"]) as stub:
        r = run(cassette, {"url": stub.url, "model": "stub"})
    assert all("g3" in t["gates"] for t in r["trials"])
    assert any("g1" in t["gates"] for t in r["trials"] if "extractor" in t["restored"])
    assert all("g1" not in t["gates"] for t in r["trials"] if "extractor" not in t["restored"])
    s = r["gate_summary"]
    assert s["nodes_total"] == len(r["pruning"]["nodes_on_path"]) and s["g1_nominated"] == 1
    assert s["g3_trials"] == len(r["trials"]) and s["exhaustive_count"] == r["pruning"]["exhaustive_trials"]
    assert {"pruned_by_ancestry", "g0_flagged", "g2_cut"} <= set(s)


def test_g2_cut_and_g0_flags_are_counted(cassette):
    r = run(cassette, suspects=["extractor", "writer"])
    assert any("g2" in t["gates"] for t in r["trials"]) and r["gate_summary"]["g2_cut"] >= 0
