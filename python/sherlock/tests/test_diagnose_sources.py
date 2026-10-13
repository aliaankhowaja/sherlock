"""diagnose with known-good runs, clues, the path check and intake, against the fake Agent Server."""

import json

import pytest
from test_diagnose_unit import KG, DiagServer
from test_g3_unit import CHECKS, FAILING, HISTORY, PASSING
from test_sources import GOOD_WRITES, good_history

from sherlock.cassette import Cassette
from sherlock.diagnose import diagnose
from sherlock.search import Budget

TWO = ["retriever.drop_latest", "extractor.legacy_pattern"]
CLEAN = {"faults": []}


class SrcServer(DiagServer):
    """DiagServer plus prior runs (id -> (history, recorded context)) and a pluggable trial rule."""

    def __init__(self, faults, goods, passes=None, **kw):
        super().__init__(faults, **kw)
        self.goods, self.passes = goods, passes

    def request(self, method, path, body=None):
        if (method, path) == ("POST", "/threads/search"):
            return [{"thread_id": "FORK", "metadata": {"sherlock_fork_of": "T"}}] + [{"thread_id": g} for g in self.goods]
        for gid, (history, ctx) in self.goods.items():
            if path == f"/threads/{gid}/history":
                return history
            if path.startswith(f"/threads/{gid}/runs/"):
                return {"kwargs": {"context": ctx}}
        out = super().request(method, path, body)
        if path == "/threads/F/runs/wait" and self.passes:
            self.result = PASSING if self.passes(body["context"]["faults"]) else FAILING
            return self.result
        return out


@pytest.fixture
def cassette(tmp_path):
    path = tmp_path / "c.db"
    Cassette(path).mark_replay(1)
    return path


def dx(server, cassette, **kw):
    return diagnose(server, "T", kw.pop("known_good", None), CHECKS, cassette, Budget(), **kw)


def test_a_prior_success_replaces_the_hand_written_patch(cassette):
    r = dx(SrcServer(TWO, {"G1": (good_history(), CLEAN)}), cassette, good_runs=["G1"])
    assert r["status"] == "found" and r["minimal_sets"] == [["retriever", "extractor"]]
    src = r["known_good_source"]
    assert src["thread_id"] == "G1" and src["confirmed"] and src["differing_nodes"][:2] == ["retriever", "extractor"]
    assert src["context_diff"] == {"retriever": {"faults": {"$remove": ["retriever.drop_latest"]}},
                                   "extractor": {"faults": {"$remove": ["extractor.legacy_pattern"]}}}
    p = r["pruning"]
    assert p["candidates"] == ["retriever", "extractor"] and p["untestable"] == []
    assert "same output" in p["pruned"]["router"] and "changes nothing" in p["pruned"]["writer"]
    assert p["pruned_ratio"] == 0.6 and r["trial_reduction"]["fewer_pct"] >= 90 and r["complete"] is True
    assert [t["n"] for t in r["trials"]] == [1, 2, 3] and all("elapsed_s" in t for t in r["trials"])
    assert ("differs_from_passing_run", "extractor") in {(c["kind"], c["node"]) for c in r["clues"]}
    assert r["sources_considered"][0]["eligible"]


def test_a_single_fault_needs_one_trial(cassette):
    r = dx(SrcServer(["extractor.legacy_pattern"], {"G1": (good_history(), CLEAN)}), cassette, good_runs=["G1"])
    assert r["minimal_sets"] == [["extractor"]] and r["counts"]["total"] == 1
    assert r["pruning"]["candidates"] == ["extractor"]


def test_a_file_known_good_still_works_and_overrides_a_derived_patch(cassette):
    r = dx(DiagServer(TWO), cassette, known_good=KG)
    assert r["known_good_source"] == {"kind": "file", "confirmed": True}
    assert r["minimal_sets"] == [["retriever", "extractor"]]
    override = {"extractor": {"faults": {"$remove": ["extractor.legacy_pattern", "extra.x"]}}}
    r = dx(SrcServer(TWO, {"G1": (good_history(), CLEAN)}), cassette, good_runs=["G1"], known_good=override)
    assert r["minimal_sets"] == [["retriever", "extractor"]]


def test_no_known_good_source_abstains_and_says_what_to_pass(cassette):
    r = dx(DiagServer(TWO), cassette)
    assert r["status"] == "abstain" and r["reason_code"] == "no_known_good" and r["trials"] == []
    assert "--good-run" in r["reason"] and r["known_good_source"] is None
    # the run page needs the path to draw nodes, even when nothing may be claimed about them
    assert r["pruning"]["nodes_on_path"] and r["pruning"]["candidates"] == []


def test_an_unusable_prior_run_is_named_with_the_reason(cassette):
    r = dx(SrcServer(TWO, {"G1": (good_history(vendor="globex"), CLEAN)}), cassette, good_runs=["G1"])
    assert r["reason_code"] == "no_known_good" and "G1 it ran on a different input" in r["reason"]
    assert r["sources_considered"][0]["eligible"] is False


def test_discover_good_finds_runs_but_marks_them_unconfirmed(cassette):
    r = dx(SrcServer(TWO, {"G1": (good_history(), CLEAN)}), cassette, discover_good=True)
    assert r["status"] == "found" and r["known_good_source"]["confirmed"] is False


def test_two_agreeing_successes_pick_the_closest_and_list_the_other(cassette):
    near = good_history("2026-10-13T00:00:00+00:00")
    far = good_history("2026-10-14T00:00:00+00:00", writes={**GOOD_WRITES, "router": {"source": "other", "notes": []}})
    r = dx(SrcServer(TWO, {"G1": (far, CLEAN), "G2": (near, CLEAN)}), cassette, good_runs=["G1", "G2"])
    assert r["status"] == "found" and r["known_good_source"]["thread_id"] == "G2"
    assert r["other_sources"] == [{"thread_id": "G1", "status": "found", "minimal_sets": [["retriever", "extractor"]],
                                   "reason_code": "ok"}]


def test_two_successes_that_disagree_abstain(cassette):
    def passes(left):
        return "retriever.v2" in left or "extractor.legacy_pattern" not in left

    goods = {"G1": (good_history(), CLEAN),
             "G2": (good_history("2026-10-13T00:00:00+00:00"), {"faults": ["extractor.legacy_pattern", "retriever.v2"]})}
    r = dx(SrcServer(TWO, goods, passes), cassette, good_runs=["G1", "G2"])
    assert r["status"] == "abstain" and r["reason_code"] == "sources_disagree" and r["minimal_sets"] == []
    assert "{extractor}" in r["reason"] and "{retriever}" in r["reason"]


def test_unattributable_difference_abstains_instead_of_guessing(cassette):
    r = dx(SrcServer(TWO, {"G1": (good_history(), {"faults": [], "mystery": 1})}), cassette, good_runs=["G1"])
    assert r["status"] == "abstain" and r["reason_code"] == "cannot_attribute" and "mystery" in r["reason"]


def test_a_success_with_the_same_configuration_has_nothing_to_restore(cassette):
    r = dx(SrcServer(TWO, {"G1": (good_history(), {"faults": TWO})}), cassette, good_runs=["G1"])
    assert r["status"] == "abstain" and r["reason_code"] == "no_candidates"
    assert "not something Sherlock can restore" in r["reason"]


def test_a_suspect_that_names_no_recorded_arrow_abstains_with_the_reason(cassette):
    r = dx(SrcServer(TWO, {"G1": (good_history(), CLEAN)}), cassette, good_runs=["G1"], suspects=["ghost"])
    assert r["status"] == "abstain" and r["reason_code"] == "path_check_failed" and r["trials"] == []
    assert "ghost never ran" in r["reason"] and r["path_check"]["rejected"]["ghost"]


def test_the_path_check_shortlists_the_search(cassette):
    srv = SrcServer(["extractor.legacy_pattern"], {"G1": (good_history(), CLEAN)})
    r = dx(srv, cassette, good_runs=["G1"], suspects=["extractor", "ghost"])
    assert r["minimal_sets"] == [["extractor"]] and r["path_check"]["kept"] == ["extractor"]
    assert r["path_check"]["arrows"]["extractor"] == ["extractor", "writer"] and r["complete"] is False
    assert any("limited to the suspects" in n for n in r["notes"])


def test_marked_wrong_with_no_check_shows_clues_and_abstains(cassette):
    h = [dict(s, tasks=[dict(t, result={"documents": [], "notes": []}) if t["name"] == "retriever" else t
                        for t in s["tasks"]]) for s in HISTORY]
    rec = {"kind": "wrong", "thread_id": "T"}
    r = diagnose(DiagServer([], original=h), "T", None, None, cassette, intake=rec)
    assert r["status"] == "abstain" and r["reason_code"] == "no_check" and r["intake"] == rec
    assert ("empty_output", "retriever") in {(c["kind"], c["node"]) for c in r["clues"]} and r["trials"] == []
    assert "not a verdict" in r["reason"]


def test_artifact_keeps_every_phase_three_field(cassette):
    r = dx(SrcServer(TWO, {"G1": (good_history(), CLEAN)}), cassette, good_runs=["G1"])
    for key in ("status", "minimal_sets", "unverified_sets", "trials", "counts", "pruning", "trial_reduction", "budget",
                "check", "context", "limitations", "complete", "notes", "reason", "reason_code", "created"):
        assert key in r
    assert json.loads(json.dumps(r)) == r and r["schema"] == 1
