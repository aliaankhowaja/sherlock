"""Evaluation helpers (spec FR-E4, FR-E5, 9.3): cheap baselines, scoring and CI invariants. Pure, no server.

Every method answers the same question on the same tapes: "which set of nodes, restored to known-good
behaviour, fixes this run under check Z?" A prediction is {"status": "answer", "sets": [[node, ...], ...]}
or {"status": "abstain", "reason": code}. Scoring uses the same cause definition for all methods (the
1-minimal fixing sets derived as gold); nothing here compares against numbers from other papers.

Baselines (all read only the failed run's checkpoint history, the passing run's history and Z):
  last_node       blame the node that writes the output
  random_node     blame one node on the path, chosen by a seeded generator
  g0_only         sum the G0 clue weights per node (errors, empty values, malformed JSON, loops, extractive tokens,
                  differs-from-the-passing-run) and blame the earliest top-scoring node; abstain with no clue
  paste_and_play  restore a set by pasting the passing run's recorded output for those nodes and keeping every
                  other node's recorded output (nothing downstream re-runs); then apply Z
Not built: plain LLM guess, plain retry, live time-travel without call blocking (see docs/eval/README.md).
"""

from __future__ import annotations

import random
from itertools import combinations

from sherlock.checks import Checks, evaluate
from sherlock.clues import differs_clues, history_clues
from sherlock.search import _supersteps
from sherlock.sources import node_outputs

METHODS = ("sherlock", "last_node", "random_node", "g0_only", "paste_and_play")


def answer(*sets) -> dict:
    return {"status": "answer", "sets": sorted((sorted(s) for s in sets), key=lambda s: (len(s), s))}


def abstain(reason: str) -> dict:
    return {"status": "abstain", "reason": reason}


def _path(history: list[dict]) -> list[str]:
    return list(dict.fromkeys(t["name"] for step in _supersteps(history) for t in step))


def _writer(history: list[dict], output_key: str) -> str | None:
    writer = None
    for step in _supersteps(history):
        for t in step:
            if output_key in (t.get("result") or {}):
                writer = t["name"]
    return writer


def last_node(failed: list[dict], good: list[dict], checks: Checks, **_) -> dict:
    node = _writer(failed, checks.output_key) or (_path(failed) or [None])[-1]
    return answer([node]) if node else abstain("empty_path")


def random_node(failed: list[dict], good: list[dict], checks: Checks, rng: random.Random, **_) -> dict:
    path = _path(failed)
    return answer([rng.choice(path)]) if path else abstain("empty_path")


def g0_only(failed: list[dict], good: list[dict], checks: Checks, **_) -> dict:
    path = _path(failed)
    clues = history_clues(failed, checks.output_key)
    failed_out, good_out = node_outputs(failed), node_outputs(good)
    differing = [n for n in path if failed_out.get(n) != good_out.get(n)]
    clues += differs_clues(differing, [n for n in path if n not in differing], "good")
    score = {n: 0 for n in path}
    for c in clues:
        if c.node in score:
            score[c.node] += c.weight
    best = max(score.values(), default=0)
    if best == 0:
        return abstain("no_clue")
    return answer([next(n for n in path if score[n] == best)])


def _pasted_output(failed: list[dict], good: list[dict], restore: set[str], output_key: str):
    """The output of the failed run after pasting the passing run's recorded writes for `restore`."""
    out = None
    f_out, g_out = node_outputs(failed), node_outputs(good)
    for step in _supersteps(failed):
        for t in step:
            use = g_out.get(t["name"]) if t["name"] in restore else f_out.get(t["name"])
            result = (use or [None])[0] if use else None
            if isinstance(result, dict) and output_key in result:
                out = result[output_key]
    return out


def paste_and_play(failed: list[dict], good: list[dict], checks: Checks, max_size: int = 2, **_) -> dict:
    path = _path(failed)
    minimal: list[frozenset] = []
    for k in range(1, min(max_size, len(path)) + 1):
        for subset in combinations(path, k):
            key = frozenset(subset)
            if any(m <= key for m in minimal):
                continue
            out = _pasted_output(failed, good, set(key), checks.output_key)
            if evaluate(checks.assertions, out if isinstance(out, str) else "", checks.base_dir).passed:
                minimal.append(key)
    return answer(*minimal) if minimal else abstain("no_set_fixes_it")


BASELINES = {"last_node": last_node, "random_node": random_node, "g0_only": g0_only, "paste_and_play": paste_and_play}


def from_artifact(artifact: dict) -> dict:
    """Sherlock's prediction from its diagnosis artifact. `unverified_sets` are never claims."""
    if artifact["status"] == "found":
        return answer(*artifact["minimal_sets"])
    return abstain(artifact.get("reason_code") or "abstain")


# --- scoring ---------------------------------------------------------------------------------------------

def score(gold: list[list[str]], pred: dict) -> dict:
    """outcome: exact (the same collection of minimal sets), wrong (a claim that differs), abstain. Jaccard is
    over the union of nodes named, so a partial answer gets partial credit; it is None for an abstain."""
    if pred["status"] == "abstain":
        return {"outcome": "abstain", "jaccard": None, "reason": pred["reason"]}
    g = {frozenset(s) for s in gold}
    p = {frozenset(s) for s in pred["sets"]}
    gu, pu = set().union(*g) if g else set(), set().union(*p) if p else set()
    jac = len(gu & pu) / len(gu | pu) if gu | pu else 1.0
    return {"outcome": "exact" if g == p else "wrong", "jaccard": round(jac, 3), "reason": None}


def summarize(rows: list[dict], method: str, pick=lambda r: True) -> dict:
    """Counts for one method over the rows `pick` keeps. Abstains are reported beside accuracy, never inside it."""
    rs = [r["methods"][method] for r in rows if pick(r)]
    n = len(rs)
    exact = sum(r["outcome"] == "exact" for r in rs)
    wrong = sum(r["outcome"] == "wrong" for r in rs)
    abst = [r for r in rs if r["outcome"] == "abstain"]
    answered = [r for r in rs if r["outcome"] != "abstain"]
    reasons: dict[str, int] = {}
    for r in abst:
        reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
    return {"n": n, "exact": exact, "wrong": wrong, "abstain": len(abst), "abstain_reasons": reasons,
            "exact_of_answered": round(exact / len(answered), 3) if answered else None,
            "mean_jaccard": round(sum(r["jaccard"] for r in answered) / len(answered), 3) if answered else None}


# --- CI invariants over the diagnosis artifacts -----------------------------------------------------------------

def artifact_violations(artifact: dict) -> list[str]:
    """Reasons an artifact breaks the honesty rules (NFR-3, NFR-4, FR-D). Empty when it is sound."""
    bad = []
    if artifact["status"] == "abstain":
        if artifact.get("minimal_sets"):
            bad.append("abstain verdict still names culprit sets")
        if not artifact.get("reason_code") or not artifact.get("reason"):
            bad.append("abstain verdict without a reason")
    elif artifact["status"] == "found":
        if not artifact.get("minimal_sets"):
            bad.append("found verdict with no minimal set")
        if any(t["verdict"] == "pass" and t["cassette_miss"] for t in artifact.get("trials", [])):
            bad.append("a trial that missed the cassette was counted as a pass")
    else:
        bad.append(f"unknown status {artifact['status']!r}")
    return bad
