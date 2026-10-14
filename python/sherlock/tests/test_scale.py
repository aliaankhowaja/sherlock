"""Scaling audit: the search on generated 30/40/60-node DAGs against a fake G3 oracle (FR-D1-D9, NFR-8).

The oracle is monotone: a restored set passes iff it contains one of the planted sets. Each test plants
minimal sets, runs pruning + ordering + search, and asserts the exact 1-minimal sets come back, complete,
inside a trial bound that is far under 2^n. No server, no network.
"""

import json
import time

import pytest

from sherlock.clues import Clue, order_candidates
from sherlock.g3 import Verdict
from sherlock.search import Budget, plan_candidates, search

SIZES = (30, 40, 60)


def make_history(n: int, width: int = 4) -> list[dict]:
    """A layered DAG with parallel branches: 1 start, layers of `width` parallel nodes, 1 writer (n nodes).
    Returns checkpoint history, newest first. The writer is the only node that writes `final_output`."""
    names = [f"n{i:02d}" for i in range(n - 1)] + ["writer"]
    layers = [names[:1]]
    middle = names[1:-1]
    layers += [middle[i:i + width] for i in range(0, len(middle), width)]
    layers.append(names[-1:])
    steps = [[{"name": nm, "result": {"final_output": "x"} if nm == "writer" else {f"{nm}_out": 1}} for nm in layer]
             for layer in layers]
    return [{"tasks": step} for step in reversed(steps)]


def world(n: int):
    history = make_history(n)
    nodes = [t["name"] for snap in reversed(history) for t in snap["tasks"]]
    kg = {nm: {"faults": {"$remove": [f"{nm}.bug"]}} for nm in nodes}
    ctx = {"faults": [f"{nm}.bug" for nm in nodes]}
    return history, kg, ctx, nodes


class Oracle:
    def __init__(self, planted):
        self.planted = [frozenset(p) for p in planted]
        self.calls = []

    def __call__(self, restore):
        s = frozenset(restore)
        self.calls.append(s)
        ok = any(p <= s for p in self.planted)
        return Verdict("pass" if ok else "fail", "ok" if ok else "still wrong", restored=list(restore),
                       check={"pass": ok, "results": [{"score": 1.0 if ok else 0.0}]})


def diagnose_synthetic(n, planted_fn, clue_nodes=(), max_size=3, max_trials=None):
    history, kg, ctx, nodes = world(n)
    plan = plan_candidates(history, kg, ctx, "final_output")
    planted = planted_fn(plan.candidates)
    clues = [Clue("extractive", c, "planted", weight=3) for c in clue_nodes]
    cands = order_candidates(plan.candidates, clues)
    oracle = Oracle(planted)
    budget = Budget(max_trials=max_trials or 4 * n + 40, max_minutes=5, max_size=max_size)
    t0 = time.perf_counter()
    res = search(cands, oracle, 0.0, budget)
    return res, oracle, plan, sorted(sorted(p) for p in planted), time.perf_counter() - t0


def check(res, oracle, plan, planted):
    assert res.status == "found" and res.complete, (res.reason_code, res.reason, res.notes)
    assert sorted(sorted(s) for s in res.minimal_sets) == planted
    assert len(oracle.calls) == len(set(oracle.calls)), "a set was tried twice"
    used = len(oracle.calls)
    assert used < 2 ** len(plan.on_path) // 10 ** 6  # nowhere near exhaustive
    return used


CASES = {
    "singleton": lambda c: [{c[len(c) // 2]}],
    "pair_far_apart": lambda c: [{c[0], c[-1]}],
    "and_across_branches": lambda c: [{c[3], c[len(c) // 2], c[-2]}],
    "or_redundant": lambda c: [{c[5]}, {c[-4]}],
    "mixed": lambda c: [{c[2], c[10]}, {c[2], c[-3]}],
}


@pytest.mark.parametrize("n", SIZES)
@pytest.mark.parametrize("case", CASES)
def test_planted_sets_are_found_exactly(n, case):
    res, oracle, plan, planted, _ = diagnose_synthetic(n, CASES[case])
    used = check(res, oracle, plan, planted)
    assert used <= 3 * n + 10, f"{case} n={n} used {used} trials"


@pytest.mark.parametrize("n", SIZES)
def test_g0_ordering_finds_a_planted_pair_in_a_handful_of_trials(n):
    """With clues on the culprits and a small budget, the answer arrives early (found, even if incomplete)."""
    history, kg, ctx, _ = world(n)
    cands = plan_candidates(history, kg, ctx, "final_output").candidates
    pair = {cands[-1], cands[-2]}
    res, oracle, *_ = diagnose_synthetic(n, lambda c: [pair], clue_nodes=pair, max_trials=12)
    assert sorted(res.minimal_sets[0]) == sorted(pair) and len(oracle.calls) <= 12


def test_artifact_stays_small_at_sixty_nodes():
    res, *_ = diagnose_synthetic(60, CASES["or_redundant"])
    assert len(json.dumps(res.to_dict())) < 120_000


def test_report_numbers(capsys):
    rows = []
    for n in SIZES:
        for case, fn in CASES.items():
            res, oracle, plan, planted, secs = diagnose_synthetic(n, fn)
            rows.append(f"n={n} {case}: candidates={len(plan.candidates)} trials={len(oracle.calls)} "
                        f"2^n={2 ** n} ({secs:.2f}s)")
    with capsys.disabled():
        print("\n" + "\n".join(rows))


def test_untestable_set_blocks_the_no_others_proof():
    """If a probe cannot be tested (cassette miss), Sherlock must not claim there is nothing else."""
    history, kg, ctx, _ = world(30)
    cands = plan_candidates(history, kg, ctx, "final_output").candidates
    a = cands[4]
    inner = Oracle([{a}])

    def oracle(restore):
        if a not in restore and len(restore) == len(cands) - 1:
            return Verdict("abstain", "request changed since recording", restored=list(restore), evidence={"cassette_miss": True})
        return inner(restore)

    res = search(cands, oracle, 0.0, Budget(max_trials=400, max_size=1))
    assert not res.screen["proved_no_others"] and not res.complete
    assert [sorted(s) for s in res.minimal_sets + res.unverified_sets] == [[a]]


def test_three_hundred_nodes_and_the_trial_ceiling():
    """Hundreds of agents: still a few dozen trials, and every planted case at 30-60 stays under 45."""
    res, oracle, plan, planted, _ = diagnose_synthetic(300, CASES["pair_far_apart"])
    assert check(res, oracle, plan, planted) <= 60
    for n in SIZES:
        for fn in CASES.values():
            res, oracle, plan, planted, _ = diagnose_synthetic(n, fn)
            assert len(oracle.calls) <= 45
