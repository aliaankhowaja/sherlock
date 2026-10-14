"""The diagnose driver against the fake Agent Server of test_g3_unit (no network, no langgraph)."""

import json

import pytest
from test_g3_unit import CHECKS, FAILING, GOOD, HISTORY, PASSING, FakeServer

from sherlock.cassette import Cassette
from sherlock.diagnose import diagnose, write_artifact
from sherlock.g3 import G3Error
from sherlock.search import Budget

KG = {**GOOD, "router": {"faults": {"$remove": ["router.bug"]}}, "writer": {"faults": {"$remove": ["writer.bug"]}}}


class DiagServer(FakeServer):
    """Recorded context = `faults`; a trial passes iff the faults left after restoring are all harmless."""

    def __init__(self, faults, **kw):
        super().__init__(**kw)
        self.faults = faults

    def request(self, method, path, body=None):
        if (method, path) == ("POST", "/threads"):
            self.ran = False
        if path.startswith("/threads/T/runs/"):
            return {"kwargs": {"context": {"faults": self.faults}}}
        out = super().request(method, path, body)
        if path == "/threads/F/runs/wait":
            left = body["context"]["faults"]
            self.result = FAILING if "extractor.legacy_pattern" in left or "retriever.drop_latest" in left else PASSING
            return self.result
        return out


@pytest.fixture
def cassette(tmp_path):
    path = tmp_path / "c.db"
    Cassette(path).mark_replay(1)
    return path


def go(server, cassette, kg=KG, **kw):
    return diagnose(server, "T", kg, CHECKS, cassette, kw.pop("budget", Budget()), **kw)


def test_two_cause_run_returns_the_pair_and_singletons_fail(cassette):
    server = DiagServer(["retriever.drop_latest", "extractor.legacy_pattern"])
    r = go(server, cassette)
    assert r["status"] == "found" and r["minimal_sets"] == [["retriever", "extractor"]]
    assert r["counts"] == {"fixes": 1, "partly_helps": 0, "does_not_help": 2, "cannot_say": 0, "total": 3}
    assert r["pruning"]["candidates"] == ["retriever", "extractor"]
    assert set(r["pruning"]["pruned"]) == {"router", "writer"} and r["pruning"]["untestable"] == ["reviewer"]
    assert r["trial_reduction"]["trials_used"] == 3 and r["trial_reduction"]["fewer_pct"] >= 40
    assert not server.wrote_to_original()


def test_single_fault_run_returns_the_singleton_in_one_trial(cassette):
    r = go(DiagServer(["extractor.legacy_pattern"]), cassette)
    assert r["minimal_sets"] == [["extractor"]] and r["counts"]["total"] == 1 and r["complete"] is False  # reviewer untestable
    assert r["pruning"]["untestable"] == ["reviewer"]


def test_missing_cassette_entry_abstains_with_the_reason(cassette):
    hook = lambda: Cassette(cassette).add_abstain("cannot say: request changed since recording: POST http://x")
    r = go(DiagServer(["extractor.legacy_pattern"], run_hook=hook), cassette)
    assert r["status"] == "abstain" and r["reason_code"] == "unrecorded_call"
    assert "request changed since recording" in r["reason"] and r["minimal_sets"] == []
    assert r["counts"]["cannot_say"] == 1


def test_original_that_passes_needs_no_diagnosis(cassette):
    h = [dict(s, values=dict(s["values"], final_output=PASSING["final_output"])) if i == 0 else s
         for i, s in enumerate(HISTORY)]
    r = go(DiagServer([], original=h), cassette)
    assert r["status"] == "abstain" and r["reason_code"] == "already_passes" and r["trials"] == []


def test_unusable_history_abstains(cassette):
    r = go(DiagServer([], original=HISTORY[:1]), cassette)
    assert r["status"] == "abstain" and r["reason_code"] == "no_history" and "durability" in r["reason"]


def test_refuses_without_a_replay_session(tmp_path):
    with pytest.raises(G3Error, match="replay"):
        go(DiagServer([]), tmp_path / "none.db")


def test_trial_budget_is_enforced_end_to_end(cassette):
    r = go(DiagServer(["retriever.drop_latest", "extractor.legacy_pattern"]), cassette, budget=Budget(max_trials=1))
    assert r["status"] == "abstain" and r["reason_code"] == "budget_exhausted" and r["counts"]["total"] == 1


def test_artifact_is_json_under_the_cassette_dir(cassette):
    r = go(DiagServer(["extractor.legacy_pattern"]), cassette)
    path = write_artifact(r, cassette.parent)
    assert path == cassette.parent / "diagnoses" / "T.json"
    saved = json.loads(path.read_text())
    assert saved["thread_id"] == "T" and saved["schema"] == 1 and saved["minimal_sets"] == [["extractor"]]
    assert saved["limitations"] and saved["check"]["pass"] is False and saved["created"]


def test_interrupt_in_history_abstains_interrupt_unsupported(cassette):  # FR-G3.10
    import copy

    history = copy.deepcopy(HISTORY)
    history[1]["tasks"].append({"name": "human", "result": None, "interrupts": [{"value": "approve?"}]})
    r = go(DiagServer(["retriever.drop_latest"], original=history), cassette)
    assert r["status"] == "abstain" and r["reason_code"] == "interrupt_unsupported" and r["trials"] == []
    assert any("interrupt" in x for x in r["limitations"])


def test_limitations_state_interrupt_resumes_out_of_scope(cassette):  # FR-G3.10
    r = go(DiagServer(["extractor.legacy_pattern"]), cassette)
    assert any("interrupt" in x and "v1" in x for x in r["limitations"])


def test_pasted_known_good_output_for_one_node_is_recorded_as_pasted(cassette):  # FR-K2
    server = DiagServer(["extractor.legacy_pattern"])
    r = go(server, cassette, pasted_nodes=["extractor"],
           kg={"extractor": {"faults": {"$remove": ["extractor.legacy_pattern"]}}})
    assert r["status"] == "found" and r["minimal_sets"] == [["extractor"]]
    assert r["known_good_source"] == {"kind": "pasted", "confirmed": True, "nodes": ["extractor"]}


def test_parse_pasted_reads_inline_json_and_files(tmp_path):  # FR-K2
    from sherlock.cli import parse_pasted

    f = tmp_path / "w.json"
    f.write_text('{"faults": {"$remove": ["w.bug"]}}')
    got = parse_pasted(['extractor={"faults": {"$remove": ["e.bug"]}}', f"writer=@{f}"])
    assert got == {"extractor": {"faults": {"$remove": ["e.bug"]}}, "writer": {"faults": {"$remove": ["w.bug"]}}}
    for bad in ["nonode", "n=[1]", "n="]:
        with pytest.raises(ValueError):
            parse_pasted([bad])
