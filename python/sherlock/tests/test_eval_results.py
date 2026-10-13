"""CI invariants over the committed evaluation results (FR-E7, NFR-3, NFR-4; phase 6 exit criterion).

`docs/eval/results.json` is produced by `eval/run_eval.py` against real `langgraph dev` servers. The slow
gate regenerates it and diffs (scripts/test.sh); these tests are the fast offline half: they read the
committed file and fail if it records a broken invariant or a claim the data does not support.
"""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]
RESULTS = ROOT / "docs" / "eval" / "results.json"

pytest.importorskip("langgraph_cli")  # run_eval imports the live-test server helpers
spec = importlib.util.spec_from_file_location("run_eval", ROOT / "python" / "sherlock" / "eval" / "run_eval.py")
run_eval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_eval)

pytestmark = pytest.mark.skipif(not RESULTS.exists(), reason="docs/eval/results.json not generated yet")


@pytest.fixture(scope="module")
def res():
    return json.loads(RESULTS.read_text(encoding="utf-8"))


def test_at_least_four_teams_with_an_llm_node_team(res):
    assert len(res["teams"]) >= 4 and "support_bot" in res["teams"]
    assert {r["team"] for r in res["cases"]} == set(res["teams"])


def test_replay_made_zero_network_calls_and_originals_are_unchanged(res):
    assert res["invariants"]["replay_network_attempts"] == []
    assert res["invariants"]["original_thread_unchanged"] is True


def test_no_artifact_breaks_the_honesty_rules(res):
    assert res["invariants"]["artifact_violations"] == {}


def test_an_abstain_never_names_culprits(res):
    for r in res["cases"]:
        pred = r["methods"]["sherlock"]["prediction"]
        if pred["status"] == "abstain":
            assert "sets" not in pred and pred["reason"]
            assert r["methods"]["sherlock"]["outcome"] == "abstain"


def test_sherlock_is_exact_on_deterministic_teams_and_abstains_on_the_llm_prompt_cross_combination(res):
    for r in res["cases"]:
        outcome = r["methods"]["sherlock"]["outcome"]
        assert outcome == ("abstain" if r["expect_abstain"] else "exact"), r["id"]
    assert any(r["expect_abstain"] for r in res["cases"]), "the hard slice needs an abstain case"


def test_sherlock_never_makes_a_wrong_claim_and_beats_or_equals_every_baseline(res):
    for sl in ("all", "hidden", "hard"):
        mine = res["summary"][sl]["sherlock"]
        assert mine["wrong"] == 0
        for m in run_eval.BASELINES:
            other = res["summary"][sl][m]
            assert mine["exact"] >= other["exact"] and mine["wrong"] <= other["wrong"], (sl, m)


def test_paste_and_play_fails_every_two_cause_case(res):
    two = [r for r in res["cases"] if "two_cause" in r["tags"]]
    assert two and all(r["methods"]["paste_and_play"]["outcome"] != "exact" for r in two)


def test_pruning_beats_exhaustive_enumeration_by_the_nfr8_margin(res):
    assert res["trials"]["fewer_pct"] >= 40


def test_stored_failures_list_is_what_the_expectations_say(res):
    assert res["failures"] == run_eval.expectations(res) == []


def test_hidden_cases_are_seeded_disjoint_from_the_visible_ones(res):
    seen = {(r["team"], frozenset(r["faults"])) for r in res["cases"] if r["split"] == "visible"}
    hidden = [r for r in res["cases"] if r["split"] == "hidden"]
    assert hidden and all((r["team"], frozenset(r["faults"])) not in seen for r in hidden)
    assert res["seed"] == run_eval.SEED
