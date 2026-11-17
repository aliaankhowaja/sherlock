"""The replay corpus (docs/notes/replay-corpus-plan.md): loader, gold and stop rules, and one live lab.

The live test records against the loopback stub, never a provider: the stub is the "model", its port is trapped
during replay, so a replay that tried to reach it would fail the case.
"""

import json
import sys
from pathlib import Path

import pytest
import stub_server
from stub_server import StubServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

import replay_corpus as rc  # noqa: E402
from sherlock.checks import evaluate  # noqa: E402
from sherlock_harness.teams import bench_solver as team  # noqa: E402

SOURCES = Path(__file__).parent / "fixtures" / "public_traces" / "sources.jsonl"
GSM8K = "GSM8K_gpt-4o-mini_agentverse_1_2433222f"


# --- step 1: loader, normalizer, fixture ----------------------------------------------------------------------

@pytest.mark.parametrize("raw, key", [
    ("Leon paid $400 + $20.\n#### 420", "420"),
    ("  B ", "b"),
    ("x #### 1 #### 42 ", "42"),
    ("Paris", "Paris"),
    (None, ""),
    ("635013559600, the unit is  .", "635013559600"),  # AEGIS SciBench
    ("\\$18.90", "18.90"),  # AEGIS MATH
    ("1,234,567", "1234567"),
])
def test_normalize_key(raw, key):
    assert rc.normalize_key(raw) == key


def test_fixture_rows_keep_two_questions_and_say_why_the_rest_go():
    got = {q["id"]: (q["source"], q["group"], q["key"], rc.ineligible(q)) for q in rc.questions([SOURCES])}
    assert got[GSM8K] == ("aegis", "GSM8K", "420", None)
    assert got["math_mathchat_0001"] == ("whowhen", "math", "351", None)
    assert got["smol+gaia_gpt-4o-mini_smoagents_24_78740a29"][3] == "excluded_benchmark"  # needs the web
    assert got["gpqa_debate_0001"][2:] == ("c", "excluded_benchmark")  # one letter, casefolded; multiple choice
    assert got["bigcodebench_macnet_0001"][3] == "excluded_benchmark"
    assert {q["id"] for q in rc.pool([SOURCES])} == {GSM8K, "math_mathchat_0001"}


def test_an_output_that_only_contains_the_key_fails_equals():
    check = [{"type": "equals", "value": "420"}]
    assert evaluate(check, "420").passed
    assert not evaluate(check, "The answer is 420").passed
    assert not evaluate(check, "Answer: 420").passed  # what format.prefix writes


def _row(rid, group, question, answer):
    return {"id": rid, "framework": "debate", "benchmark": group, "trajectory": [],
            "task": json.dumps({"query": question, "answer": answer})}


def test_pool_caps_each_group_drops_repeats_and_excluded_benchmarks(tmp_path):
    rows = [_row("a1", "math", "q one", "7"), _row("a2", "math", "q one", "7"),  # same text twice
            _row("a3", "math", "q two", "8"), _row("a4", "math", "q three", "9"),
            _row("b1", "HumanEval", "q four", "10"), _row("c1", "scibench", "q five", "11"),
            _row("d1", "tablebench", "q six", "12")]  # needs a data file: not self-contained
    path = tmp_path / "rows.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert sorted(q["id"] for q in rc.pool([path], cap=2)) == ["a1", "a3", "c1"]
    assert [q["id"] for q in rc.pool([path], cap=2)] == [q["id"] for q in rc.pool([path], cap=2)]  # fixed seed


# --- gold and the stop rules ----------------------------------------------------------------------------------

def _trials(verdicts):
    return [{"restored": sorted(s.split("+")), "verdict": v, "reason": "", "cassette_miss": v == "abstain"}
            for s, v in verdicts.items()]


def test_gold_is_the_minimal_passing_sets():
    trials = _trials({"bias": "fail", "extract": "fail", "format": "fail", "bias+extract": "fail",
                      "bias+format": "fail", "extract+format": "pass", "bias+extract+format": "pass"})
    assert rc.gold_of(trials) == [["extract", "format"]]


def test_a_passing_set_with_an_untestable_subset_is_not_gold():
    assert rc.gold_of(_trials({"preface": "abstain", "steer": "abstain", "preface+steer": "pass"})) == []


def _headline(gold_trials, product_sets, status="found"):
    forks = _trials(gold_trials)
    return {"preregistered": ["extract"], "forks": forks, "gold": rc.gold_of(forks),
            "product": {"status": status, "reason_code": "ok", "minimal_sets": product_sets}}


def test_headline_rules_pass_on_a_clean_case():
    rec = _headline({"bias": "fail", "extract": "pass", "bias+extract": "pass"}, [["extract"]])
    assert rc.headline_problems(rec) == []


def test_headline_rules_catch_each_failure():
    decoy_gold = _headline({"bias": "pass", "extract": "pass", "bias+extract": "pass"}, [["bias"], ["extract"]])
    assert any("decoy" in p for p in rc.headline_problems(decoy_gold))
    mismatch = _headline({"bias": "fail", "extract": "pass", "bias+extract": "pass"}, [["bias", "extract"]])
    assert any("product search reported" in p for p in rc.headline_problems(mismatch))
    abstained = _headline({"bias": "fail", "extract": "pass", "bias+extract": "pass"}, [], status="abstain")
    assert any("abstained" in p for p in rc.headline_problems(abstained))
    pair = {**_headline({"extract": "pass", "format": "pass", "extract+format": "pass"}, [["extract"], ["format"]]),
            "preregistered": ["extract", "format"]}
    assert any("proper subset" in p for p in rc.headline_problems(pair))


def _abstain_product(**over):
    base = {"status": "abstain", "reason_code": "unrecorded_call", "minimal_sets": [],
            "unverified_sets": [["steer", "preface"]],
            "trials": [{"restored": ["preface", "steer"], "verdict": "pass", "cassette_miss": False},
                       {"restored": ["preface"], "verdict": "abstain", "cassette_miss": True},
                       {"restored": ["steer"], "verdict": "abstain", "cassette_miss": True}]}
    return {**base, **over}


def test_abstain_rules():
    assert rc.abstain_problems(_abstain_product()) == []
    total_miss = _abstain_product(unverified_sets=[])  # same reason code, not this result
    assert rc.abstain_problems(total_miss)


def test_record_stops_at_the_kept_target_cap_or_a_failure_and_resumes(tmp_path, monkeypatch):
    outcomes = iter(["unkept", "kept", "dropped", "kept", "failed", "kept"])
    seen = []

    def fake(work, q, faults, *, url, abstain=False):
        seen.append(faults)
        return {**q, "faults": faults, "lab": work.name, "outcome": next(outcomes), "why": []}

    monkeypatch.setattr(rc, "run_case", fake)
    rows = [{"id": f"q{i}", "source": "s", "group": "g", "question": f"q{i}", "key": "1"} for i in range(9)]
    assert [r["outcome"] for r in rc.record(tmp_path, rows, "http://x", 2, 90)] == ["unkept", "kept", "dropped", "kept"]
    assert seen == [s + [team.DECOY] for s in rc.SHAPES + rc.SHAPES[:1]]  # shape fixed by the attempt number
    done = rc.record(tmp_path, rows, "http://x", 5, 90)  # resumes from attempts.jsonl, stops at the failure
    assert [r["id"] for r in done] == [f"q{i}" for i in range(5)] and done[-1]["outcome"] == "failed"
    assert len(rc.record(tmp_path, rows, "http://x", 9, 5)) == 5  # attempt cap


# --- steps 3 and 4: one live lab per case ---------------------------------------------------------------------

def test_driver_records_a_headline_case_and_the_abstain_case(tmp_path, monkeypatch):
    pytest.importorskip("langgraph_cli")

    def reply(messages):
        text = messages[-1]["content"]
        return "#### four hundred twenty" if team.WORDS in text else "234 + 166 = 400, fee 20.\n#### 420"

    monkeypatch.setattr(stub_server, "reply_text", reply)
    q = next(q for q in rc.pool([SOURCES]) if q["id"] == GSM8K)
    stub = StubServer().start()
    try:
        monkeypatch.setenv("BENCH_URL", stub.url + "/v1")
        monkeypatch.setenv("BENCH_MODEL", "stub-1")
        head = rc.run_case(tmp_path / "head", q, sorted(team.HEADLINE) + [team.DECOY], url=stub.url)
        live_calls = len(stub.hits)
        abstain = rc.run_case(tmp_path / "abstain", q, sorted(team.REQUEST), url=stub.url, abstain=True)
    finally:
        stub.stop()

    assert head["outcome"] == "kept", head["why"]
    assert live_calls == 1  # one live clean call; the failed run and every fork came from the cassette
    assert head["clean"]["final_output"] == "420" and head["failed"]["final_output"] == "Answer: 42"
    assert head["gold"] == [["extract", "format"]] == rc._sets(head["product"]["minimal_sets"])
    assert len(head["forks"]) == 7  # every non-empty set of {bias, extract, format}
    assert abstain["outcome"] == "kept", abstain["why"]
    assert abstain["product"]["reason_code"] == "unrecorded_call"
    for lab in ("head", "abstain"):
        assert not (tmp_path / lab / "net_attempts.txt").exists()
