"""Baselines, scoring and artifact invariants (FR-E4, FR-E5). Pure: histories come from the team 1 fixture."""

import random

from test_g3_unit import CHECKS, HISTORY
from test_sources import good_history

from sherlock.evaluation import (BASELINES, abstain, answer, artifact_violations, from_artifact, g0_only, last_node,
                                 paste_and_play, score, summarize)

GOLD = [["extractor", "retriever"]]  # the two-cause fixture: both must be restored


def test_last_node_blames_the_node_that_writes_the_output():
    assert last_node(HISTORY, good_history(), CHECKS) == answer(["reviewer"])


def test_random_node_is_seeded_and_on_the_path():
    a = BASELINES["random_node"](HISTORY, good_history(), CHECKS, rng=random.Random("s:1"))
    b = BASELINES["random_node"](HISTORY, good_history(), CHECKS, rng=random.Random("s:1"))
    assert a == b and a["sets"][0][0] in {"router", "retriever", "extractor", "writer", "reviewer"}


def test_g0_only_blames_the_earliest_node_that_differs_and_abstains_without_clues():
    pred = g0_only(HISTORY, good_history(), CHECKS)
    assert pred["status"] == "answer" and pred["sets"] == [["retriever"]]  # first divergence, one node: wrong for two-cause
    assert g0_only(HISTORY, HISTORY, CHECKS)["status"] == "abstain"


def test_paste_and_play_fails_the_two_cause_case():
    """FR-E8: pasting recorded downstream outputs cannot see that two upstream nodes both matter."""
    pred = paste_and_play(HISTORY, good_history(), CHECKS)
    assert pred == answer(["reviewer"])  # only the node that writes the output can flip the pasted output
    assert score(GOLD, pred)["outcome"] == "wrong"


def test_score_exact_wrong_abstain_and_jaccard():
    assert score(GOLD, answer(["retriever", "extractor"])) == {"outcome": "exact", "jaccard": 1.0, "reason": None}
    wrong = score(GOLD, answer(["retriever"]))
    assert wrong["outcome"] == "wrong" and wrong["jaccard"] == 0.5
    assert score(GOLD, abstain("unrecorded_call")) == {"outcome": "abstain", "jaccard": None, "reason": "unrecorded_call"}
    two = [["a"], ["b"]]
    assert score(two, answer(["a"], ["b"]))["outcome"] == "exact" and score(two, answer(["a"]))["outcome"] == "wrong"


def test_summary_keeps_abstains_out_of_accuracy():
    rows = [{"methods": {"m": s}} for s in (score(GOLD, answer(*GOLD)), score(GOLD, answer(["x"])),
                                            score(GOLD, abstain("r")), score(GOLD, abstain("r")))]
    s = summarize(rows, "m")
    assert (s["n"], s["exact"], s["wrong"], s["abstain"]) == (4, 1, 1, 2)
    assert s["abstain_reasons"] == {"r": 2} and s["exact_of_answered"] == 0.5


def test_from_artifact_never_claims_unverified_sets():
    art = {"status": "abstain", "reason_code": "unrecorded_call", "minimal_sets": [], "unverified_sets": [["a", "b"]]}
    assert from_artifact(art) == abstain("unrecorded_call")
    assert from_artifact({"status": "found", "minimal_sets": [["b", "a"]]}) == answer(["a", "b"])


def test_artifact_violations():
    ok = {"status": "abstain", "reason_code": "x", "reason": "y", "minimal_sets": []}
    assert artifact_violations(ok) == []
    assert artifact_violations({**ok, "minimal_sets": [["a"]]}) == ["abstain verdict still names culprit sets"]
    assert artifact_violations({**ok, "reason": ""}) == ["abstain verdict without a reason"]
    assert artifact_violations({"status": "found", "minimal_sets": []}) == ["found verdict with no minimal set"]
    miss = {"status": "found", "minimal_sets": [["a"]], "trials": [{"verdict": "pass", "cassette_miss": True}]}
    assert artifact_violations(miss) == ["a trial that missed the cassette was counted as a pass"]
