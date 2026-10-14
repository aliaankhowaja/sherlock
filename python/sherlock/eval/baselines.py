"""FR-E4 baselines that need more than the recorded history (spec 9.3: same tapes, same check Z, same cause definition).

`llm_guess_stub`  plain LLM guess: a node name, from a FIXED LOCAL HEURISTIC standing in for "ask an LLM which node is wrong".
`g0_g2`           G0 clues plus the G2 pruning/path check, no G3 trial.
`plain_retry`     re-run the failed run unchanged; it can never name a cause, so it is scored as no diagnosis.
`live_time_travel` FR-E9: fork at a checkpoint, restore ONE node, resume with no cassette (nothing blocks a live call).
"""
import json

from sherlock.evaluation import _path, _writer, abstain, answer
from sherlock.g3 import run_g3
from sherlock.sources import node_outputs

EXTRA = ("llm_guess_stub", "g0_g2", "plain_retry")
RETRIES = 3
# Words a reader (or a model) treats as "this looks wrong" in a node's output.
SUSPICIOUS = ("error", "fail", "stale", "missing", "unknown", "none", "n/a", "not found", "blocked", "timeout",
              "warn", "deprecated", "legacy", "empty")


def _anomaly(outputs) -> int:
    """How odd a node's recorded writes look: empty values plus alarming words. Looks at ONE node, never at the good run."""
    text = json.dumps(outputs, default=str).lower()
    empties = text.count('""') + text.count("null") + text.count("[]") + text.count("{}")
    return empties + sum(text.count(w) for w in SUSPICIOUS)


def llm_guess_stub(failed, good, checks, **_) -> dict:
    """STUB. A real "plain LLM guess" sends the failing trace to a model and parses a node name. We have no provider, so
    this is a deterministic stand-in: blame the node whose recorded output looks most anomalous (empty values, alarming
    words), the later node on a tie, the node that writes the output when nothing looks odd. It sees only the failed
    run, like a pasted trace. It shows what a skim of the trace gives; it does NOT bound what a real model would do."""
    path = _path(failed)
    if not path:
        return abstain("empty_path")
    out = node_outputs(failed)
    scores = {n: _anomaly(out.get(n)) for n in path}
    best = max(scores.values())
    if best == 0:
        node = _writer(failed, checks.output_key) or path[-1]
    else:
        node = [n for n in path if scores[n] == best][-1]
    return answer([node])


def g0_g2(art: dict) -> dict:
    """G0 clue weights (failed-run clues plus differs-from-passing-run) over the nodes that survive G2's pruning, top
    node wins (earliest on the candidate list on a tie). No trial. Abstains when no clue lands on a candidate."""
    cands = (art.get("pruning") or {}).get("candidates") or []
    weight = {n: 0 for n in cands}
    for c in art.get("clues") or []:
        if c.get("node") in weight:
            weight[c["node"]] += c.get("weight", 1)
    best = max(weight.values(), default=0)
    if best == 0:
        return abstain("no_clue")
    return answer([next(n for n in cands if weight[n] == best)])


def plain_retry(client, art: dict, graph_id: str, input_, checks) -> tuple[dict, dict]:
    """Run the failed run's own input and context again, RETRIES times, on new threads. Returns (prediction, stats)."""
    from sherlock.checks import evaluate
    passes = 0
    for _ in range(RETRIES):
        tid = client.request("POST", "/threads", {"metadata": {"assistant_id": graph_id}})["thread_id"]
        res = client.request("POST", f"/threads/{tid}/runs/wait", {
            "assistant_id": graph_id, "input": input_, "context": art.get("context"), "durability": "sync"})
        out = (res or {}).get(checks.output_key) if isinstance(res, dict) else None
        passes += bool(evaluate(checks.assertions, out if isinstance(out, str) else "", checks.base_dir).passed)
    return abstain("no_diagnosis"), {"runs": RETRIES, "passed": passes}


def live_time_travel(client, tid: str, history: list[dict], kg: dict, checks, context) -> tuple[dict, dict]:
    """Time-travel as an engineer does it by hand: for each node on the path in order, fork before it, put that ONE node
    back to its good behaviour, resume with `cassette_path=None` (no replay session required, no cassette miss turns
    into 'cannot say', so a call nobody recorded would run live), apply Z. Blame the first node whose single restore
    passes; abstain if none does."""
    seen = {}
    for node in _path(history):
        v = run_g3(client, tid, [node], kg, checks, None, context=context)
        seen[node] = v.verdict
        if v.verdict == "pass":
            return answer([node]), seen
    return abstain("no_single_node_fix"), seen
