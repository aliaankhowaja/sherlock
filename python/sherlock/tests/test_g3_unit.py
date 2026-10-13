"""G3 planning and driver logic against a fake Agent Server built from the real Phase 0 history
fixture. No network, no langgraph. The live server is exercised in test_g3_live.py."""

import copy
import json
from pathlib import Path

import pytest

from sherlock.cassette import Cassette
from sherlock.checks import Checks
from sherlock.g3 import (G3Error, apply_restore, history_usable, load_known_good, plan_fork, prefix_mismatch,
                         run_g3)

FIXTURE = Path(__file__).parents[3] / "harness" / "fixtures" / "vendor_brief_two_cause_history.json"
HISTORY = json.loads(FIXTURE.read_text())  # newest first; two-cause failed run of demo team #1
FAULTS = ["retriever.drop_latest", "extractor.legacy_pattern"]
GOOD = {"retriever": {"faults": {"$remove": ["retriever.drop_latest"]}},
        "extractor": {"faults": {"$remove": ["extractor.legacy_pattern"]}}}
CHECKS = Checks([{"type": "contains", "value": "ISO 27001"}, {"type": "not-contains", "value": "SOC 2"}],
                "final_output", Path("."), Path("sherlock.yaml"))
PASSING = {"final_output": "Vendor brief: acme. Certifications: ISO 27001. Data region: EU."}
FAILING = {"final_output": "Vendor brief: acme. Certifications: SOC 2. Data region: EU."}


def test_history_is_a_failed_two_cause_run():
    assert "SOC 2" in HISTORY[0]["values"]["final_output"]


def test_plan_fork_picks_the_earliest_restored_node_and_the_writes_before_it():
    plan = plan_fork(HISTORY, ["extractor", "retriever"])
    assert plan.fork_node == "retriever" and plan.fork_snapshot["next"] == ["retriever"]
    assert [[u["as_node"] for u in s["updates"]] for s in plan.supersteps] == [["__start__"], ["router"]]
    assert plan.supersteps[0]["updates"][0]["values"] == {"vendor": "acme"}
    later = plan_fork(HISTORY, ["extractor"])
    assert later.fork_node == "extractor" and len(later.supersteps) == 3


def test_plan_fork_rejects_a_node_that_never_ran():
    with pytest.raises(KeyError, match="ghost"):
        plan_fork(HISTORY, ["retriever", "ghost"])


def test_apply_restore_removes_replaces_and_composes_without_mutating():
    original = {"faults": list(FAULTS), "other": 1}
    both = apply_restore(original, GOOD, ["retriever", "extractor"])
    assert both == {"faults": [], "other": 1} and original["faults"] == FAULTS
    assert apply_restore(original, GOOD, ["retriever"])["faults"] == ["extractor.legacy_pattern"]
    assert apply_restore(None, {"w": {"prompt": "good"}}, ["w"]) == {"prompt": "good"}


def test_history_usable_reports_missing_history():
    assert history_usable(HISTORY) is None
    assert "durability" in history_usable(HISTORY[:1])
    stripped = copy.deepcopy(HISTORY)
    for s in stripped:
        for t in s["tasks"]:
            t["result"] = None
    assert "no per-node results" in history_usable(stripped)


def test_prefix_mismatch_compares_state_and_next():
    snap = HISTORY[4]
    assert prefix_mismatch(snap, copy.deepcopy(snap)) is None
    bad = copy.deepcopy(snap)
    bad["values"]["vendor"] = "other"
    assert "state differs" in prefix_mismatch(snap, bad)
    bad = copy.deepcopy(snap)
    bad["next"] = ["writer"]
    assert "would run" in prefix_mismatch(snap, bad)


def test_load_known_good(tmp_path):
    p = tmp_path / "kg.json"
    p.write_text(json.dumps(GOOD))
    assert load_known_good(p) == GOOD
    p.write_text("[1, 2]")
    with pytest.raises(G3Error, match="mapping"):
        load_known_good(p)


class FakeServer:
    """Just enough Agent Server to drive run_g3: forks are prefixes of the fixture history."""

    def __init__(self, result=PASSING, *, tamper=False, original=HISTORY, run_hook=None):
        self.result, self.tamper, self.original, self.run_hook = result, tamper, original, run_hook
        self.calls, self.steps, self.ran, self.context = [], None, False, None

    def _fork_history(self):
        chrono = copy.deepcopy(list(reversed(self.original)))
        for s in chrono:
            s["checkpoint"]["checkpoint_id"] += "-fork"
        keep = len(self.steps) + 1 if not self.ran else len(chrono)
        history = list(reversed(chrono[:keep]))
        if self.tamper and not self.ran:
            history[0]["values"] = {**history[0]["values"], "vendor": "tampered"}
        return history

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == "/threads/T":
            return {"metadata": {"graph_id": "vendor_brief"}}
        if path == "/threads/T/history":
            return self.original
        if path.startswith("/threads/T/runs/"):
            return {"kwargs": {"context": {"faults": FAULTS}}}
        if (method, path) == ("POST", "/threads"):
            self.steps = body["supersteps"]
            return {"thread_id": "F"}
        if path == "/threads/F/history":
            return self._fork_history()
        if path == "/threads/F/runs/wait":
            self.ran, self.context = True, body["context"]
            if self.run_hook:
                self.run_hook()
            return self.result
        if path == "/threads/F/runs":
            return [{"kwargs": {"context": self.context}}]
        raise AssertionError(f"unexpected {method} {path}")

    def wrote_to_original(self):
        return [c for c in self.calls if c[0] != "GET" and not c[1].endswith("/history") and "/threads/T" in c[1]]


@pytest.fixture
def cassette(tmp_path):
    path = tmp_path / "c.db"
    Cassette(path).mark_replay(1)
    return path


def go(server, cassette, restore=("retriever", "extractor"), **kw):
    return run_g3(server, "T", list(restore), GOOD, CHECKS, cassette, **kw)


def test_pass_verdict_sends_the_restore_and_never_touches_the_original(cassette):
    server = FakeServer()
    verdict = go(server, cassette)
    assert verdict.verdict == "pass" and verdict.fork_node == "retriever" and verdict.fork_thread == "F"
    body = next(b for m, p, b in server.calls if p == "/threads/F/runs/wait")
    assert body["input"] is None and body["context"] == {"faults": []} and body["durability"] == "sync"
    assert body["checkpoint"]["checkpoint_id"].endswith("-fork")  # resumes at the fork, never the original
    assert server.wrote_to_original() == []
    assert {"retriever", "extractor", "writer", "reviewer"} <= set(verdict.evidence["nodes_rerun"])


def test_fail_verdict_names_what_is_still_wrong(cassette):
    verdict = go(FakeServer(result=FAILING), cassette, restore=("retriever",))
    assert verdict.verdict == "fail" and "SOC 2" in verdict.reason and verdict.check["pass"] is False


def test_refuses_without_a_replay_session(tmp_path):
    path = tmp_path / "c.db"
    Cassette(path)  # recorded, but no replay server ever served it
    with pytest.raises(G3Error, match="no replay session"):
        go(FakeServer(), path)


def test_original_that_already_passes_abstains(cassette):
    passing = copy.deepcopy(HISTORY)
    passing[0]["values"]["final_output"] = PASSING["final_output"]
    verdict = go(FakeServer(original=passing), cassette)
    assert verdict.verdict == "abstain" and "already passes" in verdict.reason


def test_unknown_restore_target_and_missing_known_good_abstain(cassette):
    assert "did not run" in run_g3(FakeServer(), "T", ["ghost"], {"ghost": {}}, CHECKS, cassette).reason
    assert "no known-good" in run_g3(FakeServer(), "T", ["writer"], GOOD, CHECKS, cassette).reason


def test_prefix_mismatch_is_off_track_not_a_verdict(cassette):
    verdict = go(FakeServer(tamper=True), cassette)
    assert verdict.verdict == "abstain" and verdict.reason.startswith("replay went off track")


def test_a_cassette_miss_during_the_trial_abstains(cassette):
    hook = lambda: Cassette(cassette).add_abstain("cannot say: request changed since recording: POST http://x")
    verdict = go(FakeServer(run_hook=hook), cassette)
    assert verdict.verdict == "abstain" and "request changed since recording" in verdict.reason
    assert verdict.check is None


def test_a_failed_trial_run_abstains(cassette):
    verdict = go(FakeServer(result={"__error__": {"error": "KeyError", "message": "'vendor'"}}), cassette)
    assert verdict.verdict == "abstain" and "KeyError" in verdict.reason


def test_unusable_history_abstains(cassette):
    verdict = go(FakeServer(original=HISTORY[:1]), cassette)
    assert verdict.verdict == "abstain" and "no usable checkpoint history" in verdict.reason
