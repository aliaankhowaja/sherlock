"""Minimality search and pruning (FR-D1-D9, D11), against a fake G3 oracle. No server, no network."""

import json
from itertools import combinations
from pathlib import Path

import pytest

from sherlock.g3 import Verdict
from sherlock.search import Budget, label_of, plan_candidates, search

FIXTURE = Path(__file__).parents[3] / "harness" / "fixtures" / "vendor_brief_two_cause_history.json"
HISTORY = json.loads(FIXTURE.read_text())
KG = {n: {"faults": {"$remove": [f"{n}.bug"]}} for n in ["router", "retriever", "extractor", "writer", "reviewer"]}
CTX = {"faults": ["retriever.bug", "extractor.bug"]}


class Oracle:
    """Monotone fake G3: pass iff the restored set contains one of `fixes`; `abstain` sets cannot be tested."""

    def __init__(self, fixes, abstain=(), partial=()):
        self.fixes = [frozenset(f) for f in fixes]
        self.abstain = [frozenset(a) for a in abstain]
        self.partial = [frozenset(p) for p in partial]
        self.calls = []

    def __call__(self, restore):
        s = frozenset(restore)
        self.calls.append(s)
        if s in self.abstain:
            return Verdict("abstain", "request changed since recording", restored=list(restore),
                           evidence={"cassette_miss": True})
        if any(f <= s for f in self.fixes):
            return Verdict("pass", "ok", restored=list(restore), check={"pass": True, "results": [{"score": 1.0}]})
        score = 0.5 if any(p <= s for p in self.partial) else 0.0
        return Verdict("fail", "still wrong", restored=list(restore),
                       check={"pass": False, "results": [{"score": score}, {"score": 0.0}]})


def sets(result):
    return [sorted(s) for s in result.minimal_sets]


def run(oracle, cands=("a", "b", "c"), **budget):
    return search(list(cands), oracle, 0.0, Budget(**budget))


# --- search ---------------------------------------------------------------------------------------

def test_single_cause_returns_the_singleton_and_skips_its_supersets():
    o = Oracle([{"a"}])
    r = run(o)
    assert r.status == "found" and sets(r) == [["a"]] and r.complete
    assert frozenset({"a", "b"}) not in o.calls and frozenset({"a", "b", "c"}) in o.calls  # probe only
    assert len(o.calls) == len(set(o.calls)) == 5  # probe, a, b, c, {b,c}


def test_chained_pair_is_found_and_singletons_fail():
    r = run(Oracle([{"a", "b"}]))
    assert sets(r) == [["a", "b"]] and r.counts["does_not_help"] >= 2


def test_every_minimal_set_is_returned_or_and_and_together():
    r = run(Oracle([{"a"}, {"b", "c"}]))
    assert sets(r) == [["a"], ["b", "c"]]  # never collapsed to one locus (FR-D5)


def test_all_candidates_failing_abstains_after_one_trial():
    o = Oracle([])
    r = run(o)
    assert r.status == "abstain" and r.reason_code == "not_fixable" and len(o.calls) == 1
    assert "restoring" in r.reason and not r.minimal_sets


def test_single_candidate_has_no_separate_probe():
    o = Oracle([{"a"}])
    r = run(o, cands=("a",))
    assert sets(r) == [["a"]] and len(o.calls) == 1


def test_no_candidates_abstains_without_trials():
    o = Oracle([])
    r = run(o, cands=())
    assert r.status == "abstain" and r.reason_code == "no_candidates" and not o.calls


def test_trial_budget_exhaustion_is_an_abstain_not_a_crash():
    o = Oracle([{"a", "b", "c"}])
    r = run(o, cands=("a", "b", "c", "d"), max_trials=3)
    assert r.status == "abstain" and r.reason_code == "budget_exhausted" and len(o.calls) == 3
    assert "trial" in r.reason and r.budget["trials_used"] == 3


def test_budget_exhausted_after_a_find_keeps_the_find_but_is_not_complete():
    o = Oracle([{"a"}, {"b", "c"}])
    r = run(o, max_trials=4)  # probe, a, b, c; the pair {b,c} is never reached
    assert r.status == "found" and sets(r) == [["a"]] and not r.complete
    assert any("budget" in n for n in r.notes)


def test_time_budget_uses_the_injected_clock():
    ticks = iter(range(0, 1000, 70))  # each clock read is 70s later
    r = search(["a", "b", "c"], Oracle([{"a"}]), 0.0, Budget(max_minutes=1), clock=lambda: next(ticks))
    assert r.status == "abstain" and r.reason_code == "budget_exhausted" and "minute" in r.reason


def test_size_cutoff_abstains_when_only_a_bigger_set_would_fix_it():
    r = run(Oracle([{"a", "b", "c"}]), max_size=2)
    assert r.status == "abstain" and r.reason_code == "cutoff" and "2" in r.reason


def test_cutoff_keeps_what_it_found_but_marks_incomplete():
    r = run(Oracle([{"a"}]), cands=("a", "b", "c", "d"), max_size=1)
    assert sets(r) == [["a"]] and not r.complete and any("larger" in n for n in r.notes)


def test_an_untestable_subset_makes_a_passing_superset_unverified():
    r = run(Oracle([{"a", "b"}], abstain=[{"a"}]), cands=("a", "b"))
    assert r.status == "abstain" and r.reason_code == "unrecorded_call" and not r.minimal_sets
    assert [sorted(s) for s in r.unverified_sets] == [["a", "b"]]
    assert "request changed since recording" in r.reason


def test_cache_miss_everywhere_abstains_with_the_reason():
    r = run(Oracle([], abstain=[{"a"}, {"b"}, {"a", "b"}]), cands=("a", "b"))
    assert r.status == "abstain" and r.reason_code == "unrecorded_call"
    assert r.counts["cannot_say"] == 3


def test_untestable_nodes_without_known_good_block_a_negative_answer():
    r = search(["a"], Oracle([]), 0.0, Budget(), untestable=["z"])
    assert r.status == "abstain" and r.reason_code == "no_known_good" and "z" in r.reason


def test_untestable_nodes_do_not_hide_a_found_set_but_mark_it_incomplete():
    r = search(["a"], Oracle([{"a"}]), 0.0, Budget(), untestable=["z"])
    assert sets(r) == [["a"]] and not r.complete and any("z" in n for n in r.notes)


def test_each_set_is_tried_at_most_once_and_search_space_is_never_2_to_the_k():
    o = Oracle([{"a", "b", "c", "d", "e", "f"}])
    r = run(o, cands=tuple("abcdef"), max_size=2, max_trials=100)
    assert len(o.calls) == len(set(o.calls)) == 1 + 6 + 15  # probe + singletons + pairs, no triples


# --- verdict labels and counts (FR-D6, D11) ----------------------------------------------------------

def test_four_labels():
    v = Verdict("pass", "", check={"results": [{"score": 1}]})
    assert label_of(v, 0.0) == "fixes"
    assert label_of(Verdict("abstain", ""), 0.0) == "cannot_say"
    better = Verdict("fail", "", check={"results": [{"score": 1}, {"score": 0}]})
    assert label_of(better, 0.25) == "partly_helps" and label_of(better, 0.5) == "does_not_help"


def test_counts_and_trial_log_are_reported():
    o = Oracle([{"a", "b"}], partial=[{"a"}])
    r = run(o, cands=("a", "b"))
    assert r.counts == {"fixes": 1, "partly_helps": 1, "does_not_help": 1, "cannot_say": 0, "total": 3}
    t = {tuple(x["restored"]): x for x in r.trials}
    assert t[("a",)]["label"] == "partly_helps" and t[("a",)]["score"] == 0.25
    assert t[("a", "b")]["label"] == "fixes" and t[("a", "b")]["verdict"] == "pass"
    assert r.to_dict()["counts"]["total"] == 3 and json.dumps(r.to_dict())


def test_trial_restored_nodes_follow_candidate_order():
    o = Oracle([{"a", "c"}])
    r = run(o, cands=("c", "b", "a"))
    assert sets(r) == [["a", "c"]]
    assert all(x["restored"] == sorted(x["restored"], key=["c", "b", "a"].index) for x in r.trials)


# --- pruning (FR-D1, D2, NFR-8) ----------------------------------------------------------------------

def test_prune_keeps_only_nodes_whose_restore_changes_something():
    p = plan_candidates(HISTORY, KG, CTX, "final_output")
    assert p.on_path == ["router", "retriever", "extractor", "writer", "reviewer"]
    assert p.candidates == ["retriever", "extractor"] and p.untestable == []
    assert "changes nothing" in p.pruned["router"] and set(p.pruned) == {"router", "writer", "reviewer"}
    assert p.exhaustive_trials == 31 and p.search_space == 3


def test_prune_flags_nodes_without_known_good_as_untestable_not_pruned():
    p = plan_candidates(HISTORY, {"extractor": KG["extractor"]}, CTX, "final_output")
    assert p.candidates == ["extractor"] and p.untestable == ["router", "retriever", "writer", "reviewer"]


def snap(i, nodes, results=None):
    results = results or {}
    return {"checkpoint": {"checkpoint_id": str(i)}, "next": list(nodes), "values": {},
            "tasks": [{"name": n, "result": results.get(n, {"x": 1})} for n in nodes]}


def test_ancestry_pruning_drops_nodes_that_cannot_reach_the_output():
    # newest first. start -> a -> (b, c in parallel) -> d writes out -> e (after the writer)
    h = [snap(5, []), snap(4, ["e"]), snap(3, ["d"], {"d": {"out": "x"}}), snap(2, ["b", "c"]),
         snap(1, ["a"]), snap(0, ["__start__"])]
    kg = {n: {"k": n} for n in "abcde"}
    p = plan_candidates(h, kg, {}, "out")
    assert p.on_path == ["a", "b", "c", "d", "e"]
    assert p.candidates == ["a", "b", "c", "d"] and "after" in p.pruned["e"]


def test_parallel_siblings_of_the_last_writer_cannot_affect_it():
    h = [snap(3, []), snap(2, ["w", "side"], {"w": {"out": "x"}}), snap(1, ["a"]), snap(0, ["__start__"])]
    p = plan_candidates(h, {n: {"k": n} for n in ["a", "w", "side"]}, {}, "out")
    assert p.candidates == ["a", "w"] and "parallel" in p.pruned["side"]


def test_unknown_output_writer_prunes_nothing_by_ancestry():
    h = [snap(2, []), snap(1, ["a", "b"]), snap(0, ["__start__"])]
    p = plan_candidates(h, {n: {"k": n} for n in "ab"}, {}, "out")
    assert p.candidates == ["a", "b"]


def test_pruning_meets_nfr8_on_team_one():
    p = plan_candidates(HISTORY, KG, CTX, "final_output")
    r = search(p.candidates, Oracle([{"retriever", "extractor"}]), 0.0, Budget())
    assert len(r.trials) == 3 and 1 - len(r.trials) / p.exhaustive_trials >= 0.4


def test_search_space_is_all_nonempty_subsets_of_candidates():
    assert sum(1 for k in range(1, 3) for _ in combinations("ab", k)) == 3


def test_same_output_nodes_are_pruned_unless_a_widening_clue_brings_them_back():
    plain = plan_candidates(HISTORY, KG, CTX, "final_output", same_output={"retriever", "writer"})
    assert "retriever" not in plain.candidates and "same output" in plain.pruned["retriever"] and plain.widened == []
    wide = plan_candidates(HISTORY, KG, CTX, "final_output", same_output={"retriever"}, widen={"retriever"})
    assert "retriever" in wide.candidates and wide.widened == ["retriever"]
    # a widened node whose restore changes nothing is still not a candidate
    still = plan_candidates(HISTORY, KG, {"faults": []}, "final_output", same_output={"retriever"}, widen={"retriever"})
    assert "retriever" not in still.candidates
