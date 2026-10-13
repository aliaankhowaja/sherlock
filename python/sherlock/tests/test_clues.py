"""G0 clues, the G2 path check and candidate ordering: pure functions over the recorded tape."""

import copy
import sys
from itertools import combinations
from pathlib import Path

import pytest
from test_g3_unit import HISTORY

from sherlock.clues import Clue, extractive_tokens, history_clues, order_candidates, path_check, tool_call_clues

HARNESS = Path(__file__).parents[3] / "harness"


def with_result(node, **result):
    h = copy.deepcopy(HISTORY)
    for snap in h:
        for t in snap["tasks"]:
            if t["name"] == node:
                t["result"] = {**t["result"], **result}
    return h


# --- G0.3 extractive ------------------------------------------------------------------------------------

def test_extractive_flags_numbers_urls_and_quoted_strings_absent_upstream():
    up = ["Acme serves 1,200 teams. See https://acme.example/trust", 'It said "fully compliant" once']
    out = ('Acme serves 1,200 teams, 99.9% uptime, https://acme.example/trust and https://evil.example '
           '"Gold Tier" "fully compliant"')
    assert set(extractive_tokens(up, out)) == {"gold tier", "99.9%", "https://evil.example"}


def test_extractive_ignores_paraphrase_and_matching_numbers():
    up = ["Acme held SOC 2 Type II, expired 2023", "audit 27001 passed"]
    assert extractive_tokens(up, "Acme no longer holds the SOC 2 certificate since 2023; ISO 27001 applies") == []


def test_extractive_clue_attaches_to_the_node_that_wrote_the_output_and_widens():
    h = with_result("reviewer", final_output="Vendor brief: acme. Certifications: SOC 2. Uptime 99.99%.")
    clue = next(c for c in history_clues(h, "final_output") if c.kind == "extractive")
    assert clue.node == "reviewer" and clue.widens and clue.evidence["tokens"] == ["99.99%"]
    assert "no upstream packet" in clue.detail and clue.to_dict()["strength"] == "clue"


def test_a_plain_failed_run_has_no_extractive_clue():
    assert [c for c in history_clues(HISTORY, "final_output") if c.kind == "extractive"] == []


# --- the other G0 clues ---------------------------------------------------------------------------------

def test_node_error_empty_output_and_malformed_json():
    h = copy.deepcopy(HISTORY)
    for snap in h:
        for t in snap["tasks"]:
            if t["name"] == "retriever":
                t["result"] = {"documents": [], "notes": ["x"]}
            if t["name"] == "writer":
                t["error"] = "ValueError: boom"
            if t["name"] == "router":
                t["result"] = {"source": '{"a": 1,', "notes": []}
    got = {(c.kind, c.node): c for c in history_clues(h, "final_output")}
    assert ("empty_output", "retriever") in got and got[("empty_output", "retriever")].widens
    assert ("node_error", "writer") in got and ("malformed_json", "router") in got
    assert ("empty_output", "router") not in got  # `notes` is bookkeeping, never a packet


def test_loop_detector_needs_a_repeat_with_no_progress():
    h = copy.deepcopy(HISTORY)
    h.insert(0, copy.deepcopy(next(s for s in h if s["next"] == ["extractor"])))  # extractor ran again, same write
    loop = [c for c in history_clues(h, "final_output") if c.kind == "loop"]
    assert [c.node for c in loop] == ["extractor"] and not loop[0].widens
    assert [c for c in history_clues(HISTORY, "final_output") if c.kind == "loop"] == []


def test_tool_call_clues_flag_bad_arguments_and_raised_errors_without_naming_a_node():
    calls = [{"id": 1, "kind": "tool", "name": "search", "request": b'{"q": "x"}', "status": 0},
             {"id": 2, "kind": "tool", "name": "search", "request": b"not json", "status": 0},
             {"id": 3, "kind": "tool", "name": "fetch", "request": b"{}", "status": 1},
             {"id": 4, "kind": "tool", "name": "calc", "request": b"{}", "status": 1},
             {"id": 5, "kind": "http", "name": "POST", "request": b"", "status": 200}]
    chunks = {3: [b"", b"ValidationError('1 validation error for X')"], 4: [b"", b"TimeoutError()"]}
    got = tool_call_clues(calls, lambda i: chunks[i])
    assert [(c.kind, c.evidence["tool"]) for c in got] == [
        ("schema_invalid_tool_call", "search"), ("schema_invalid_tool_call", "fetch"), ("tool_error", "calc")]
    assert all(c.node is None and c.widens for c in got)


# --- G2 path check ------------------------------------------------------------------------------------

def test_path_check_keeps_a_node_with_a_recorded_arrow():
    pc = path_check(HISTORY, "final_output", ["retriever", "extractor->writer", "reviewer"])
    assert pc.kept == ["retriever", "extractor", "reviewer"] and pc.rejected == {}
    assert pc.arrows == {"retriever": ["retriever", "extractor"], "extractor": ["extractor", "writer"],
                         "reviewer": ["reviewer", "final_output"]}


def test_path_check_rejects_invented_stories_with_a_reason():
    pc = path_check(HISTORY, "final_output", ["ghost", "writer->ghost", "writer->extractor", "extractor"])
    assert pc.kept == ["extractor"]
    assert "never ran" in pc.rejected["ghost"] and "never ran" in pc.rejected["writer->ghost"]
    assert "did not run before" in pc.rejected["writer->extractor"]


def test_path_check_rejects_a_node_with_no_output_and_one_after_the_answer():
    h = copy.deepcopy(HISTORY)
    for snap in h:
        for t in snap["tasks"]:
            if t["name"] == "router":
                t["result"] = {"notes": ["only bookkeeping"]}
    assert "no output" in path_check(h, "final_output", ["router"]).rejected["router"]
    early = with_result("writer", final_output="done")  # the output is written before the reviewer runs
    for snap in early:
        for t in snap["tasks"]:
            if t["name"] == "reviewer":
                t["result"] = {"verdict": "ok"}
    assert "after `final_output` was written" in path_check(early, "final_output", ["reviewer"]).rejected["reviewer"]


def test_path_check_is_deterministic():
    a = path_check(HISTORY, "final_output", ["ghost", "extractor"]).to_dict()
    assert a == path_check(HISTORY, "final_output", ["ghost", "extractor"]).to_dict()


# --- ordering (FR-D12) ------------------------------------------------------------------------------------

def test_ordering_puts_strong_clues_first_and_keeps_ties_in_tape_order():
    clues = [Clue("differs_from_passing_run", "extractor", "", 2), Clue("extractive", "writer", "", 3, True),
             Clue("tool_error", None, "", 3)]
    assert order_candidates(["router", "retriever", "extractor", "writer"], clues) == [
        "writer", "extractor", "router", "retriever"]
    assert order_candidates(["a", "b"], []) == ["a", "b"]


# --- open item 6: false-positive rate of the extractive check on demo team #1 ---------------------------------

def test_extractive_false_positive_rate_on_team_one_is_zero_over_all_fault_subsets():
    pytest.importorskip("langgraph")
    sys.path.insert(0, str(HARNESS))
    from sherlock_harness.faults import FAULTS
    from sherlock_harness.teams.vendor_brief import Context, graph

    total = hits = 0
    for k in range(len(FAULTS) + 1):
        for subset in combinations(sorted(FAULTS), k):
            steps = [{"tasks": [{"name": n, "result": r}]} for u in
                     graph.stream({"vendor": "acme"}, context=Context(faults=list(subset)), stream_mode="updates")
                     for n, r in u.items()]
            history = list(reversed([{"tasks": [{"name": "__start__", "result": {"vendor": "acme"}}]}] + steps))
            total += 1
            hits += any(c.kind == "extractive" for c in history_clues(history, "final_output"))
    assert total == 64 and hits == 0
