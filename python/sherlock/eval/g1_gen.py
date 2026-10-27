"""Synthetic G1 cases where the candidate list is the set of agents whose configuration changed between runs.

    cd python/sherlock
    uv run python eval/g1_gen.py                      # eval/.g1/gen_v1/{dev,test}.jsonl, seeded and byte-reproducible
    uv run python eval/g1_eval.py --cases eval/.g1/gen_v1/test.jsonl --backend fake

A deploy touched several agents; one or two changes broke the run (a fact dropped or corrupted), the rest are harmless
(rewording, reordering). Downstream outputs differ only because their input differed. The candidates are exactly the
changed agents, so a scorer has to tell a real fault from wording noise; planted cases cannot show that. Each fact travels
along its own chain of agents (one per layer), so a drop or a corrupt at any link of the chain breaks the check. Every case is
self-checked against the Z check (good passes, failed fails, restoring the culprits fixes it, no culprit is skippable).
Output: one JSON object per line in the format g1_eval.py reads, plus `dataset` and `split`.
"""

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "src")]

import baselines as extra  # noqa: E402
from sherlock.checks import Checks, evaluate  # noqa: E402
from sherlock.clues import differs_clues, history_clues, order_candidates  # noqa: E402
from sherlock.g1 import node_card  # noqa: E402
from sherlock.sources import node_outputs  # noqa: E402

DATASET = "g1_gen_v1"
REQUEST = "Prepare the vendor brief for the review board."
ROLES = ("planner researcher retriever summarizer extractor validator critic formatter translator ranker router writer "
         "reviewer classifier scraper indexer fact_checker editor curator analyst auditor tagger deduplicator normalizer "
         "enricher scheduler negotiator estimator forecaster moderator annotator verifier dispatcher aggregator tracker "
         "profiler mapper explainer drafter proofreader sorter linker inspector").split()
FACT_POOL = {  # key -> (label, values); no value is a substring of another value
    "certification": ("certification", ["ISO 27001", "SOC 2 Type II", "PCI DSS", "HIPAA"]),
    "region": ("data region", ["EU-Frankfurt", "US-Virginia", "APAC-Singapore", "UK-London"]),
    "price": ("price", ["120 USD", "95 USD", "210 USD", "80 EUR"]),
    "deadline": ("deadline", ["2026-03-01", "2026-06-15", "2025-12-31", "2026-09-30"]),
    "owner": ("owner", ["Dana", "Marcus", "Priya", "Chen"]),
    "sla": ("availability", ["99.9 percent uptime", "99.5 percent uptime", "99.99 percent uptime"]),
    "tier": ("support level", ["tier gold", "tier silver", "tier bronze"]),
}
CLAUSE = ("{label}: {value}", "the {label} is {value}", "confirmed {label} = {value}", "{label} reported as {value}")
FILLER = ("no blockers", "status ok", "nothing further", "queued for the next step")


def build_team(rng):
    n = rng.randint(8, 40)
    names = rng.sample(ROLES + [f"{r}_2" for r in ROLES], n)
    rest, layers = names[:-1], []
    while rest:
        w = min(rng.randint(1, 4), len(rest))
        layers.append(rest[:w])
        rest = rest[w:]
    final = names[-1]
    facts = []
    for key in rng.sample(sorted(FACT_POOL), rng.randint(3, 5)):
        label, values = FACT_POOL[key]
        value = rng.choice(values)
        facts.append({"key": key, "label": label, "value": value,
                      "wrong": rng.choice([v for v in values if v != value])})
    for f in facts:  # the chain: one node from each of L distinct layers (so each link can read the one before), then final
        picks = sorted(rng.sample(range(len(layers)), rng.randint(1, min(4, len(layers)))))
        f["chain"] = [rng.choice(layers[i]) for i in picks] + [final]
    return {"n": n, "layers": layers, "final": final, "facts": facts, "template": {x: rng.randrange(len(CLAUSE)) for x in names}}


def run(team, changes):
    """(history newest first, final_output). Pure: the same team and changes give the same tape."""
    state, pairs, snaps = {"request": REQUEST}, {}, [{"values": {}, "next": ["__start__"], "metadata": {"step": -1},
                                                         "tasks": [{"name": "__start__", "result": {"request": REQUEST}}]}]
    for step, layer in enumerate(team["layers"] + [[team["final"]]]):
        before, tasks = dict(state), []
        for node in layer:
            ch, t = changes.get(node, ("",)), team["template"][node]
            if ch[0] == "paraphrase":
                t = (t + 1) % len(CLAUSE)
            seen = {}
            for i, f in enumerate(team["facts"]):
                if node not in f["chain"] or (ch[0] == "drop" and ch[1] == i):
                    continue
                pos = f["chain"].index(node)
                value = f["value"] if pos == 0 else pairs[f["chain"][pos - 1]].get(i)
                if value is not None:
                    seen[i] = f["wrong"] if ch[0] == "corrupt" and ch[1] == i else value
            pairs[node] = seen
            clauses = [CLAUSE[t].format(label=team["facts"][i]["label"], value=v) for i, v in sorted(seen.items())]
            clauses.append(FILLER[t])
            text = "; ".join(clauses[::-1] if ch[0] == "reorder" else clauses)
            key = "final_output" if node == team["final"] else f"{node}_out"
            tasks.append({"name": node, "result": {key: text}})
        snaps.append({"values": before, "next": list(layer), "metadata": {"step": step}, "tasks": tasks})
        for t in tasks:
            state.update(t["result"])
    snaps.append({"values": dict(state), "next": [], "metadata": {"step": len(snaps) - 1}, "tasks": []})
    return snaps[::-1], state["final_output"]


def make_changes(team, rng):
    """(changes by node, culprit nodes, changed nodes in run order). Culprits sit on the chains of different facts."""
    order = [x for layer in team["layers"] for x in layer]
    culprits = {}
    for i in rng.sample(range(len(team["facts"])), rng.randint(1, 2)):
        free = [x for x in team["facts"][i]["chain"][:-1] if x not in culprits]
        if free or not culprits:
            node = rng.choice(free)
            culprits[node] = ("drop", i) if rng.random() < 0.5 else ("corrupt", i)
    harmless = rng.sample([x for x in order if x not in culprits], rng.randint(max(3, len(culprits)), min(10, len(order))) - len(culprits))
    changes = {**culprits, **{x: (rng.choice(["paraphrase", "reorder"]),) for x in harmless}}
    return changes, [x for x in order if x in culprits], [x for x in order if x in changes]


def make_case(seed, i, split):
    rng = random.Random(f"{seed}:{i}")
    team = build_team(rng)
    changes, culprits, changed = make_changes(team, rng)
    assertions = [{"type": "contains", "value": f["value"]} for f in team["facts"]] + [
        {"type": "not-contains", "value": team["facts"][c[1]]["wrong"]} for c in changes.values() if c[0] == "corrupt"]
    checks = Checks(assertions, "final_output", Path("."), Path("sherlock.yaml"))
    good_hist, good_out = run(team, {})
    failed_hist, failed_out = run(team, changes)
    ok = lambda active: evaluate(assertions, run(team, active)[1]).passed  # noqa: E731
    without = lambda drop: {x: c for x, c in changes.items() if x not in drop}  # noqa: E731
    assert evaluate(assertions, good_out).passed and not evaluate(assertions, failed_out).passed, i
    assert ok(without(culprits)), f"case {i}: restoring the culprits does not fix the run"
    if len(culprits) > 1:
        assert not any(ok(without([c])) for c in culprits), f"case {i}: a culprit can be skipped"
    out, good = node_outputs(failed_hist), node_outputs(good_hist)
    differing = [x for x in out if out[x] != good.get(x)]
    clues = history_clues(failed_hist, "final_output") + differs_clues(differing, [x for x in out if x not in differing], "good")
    cands = order_candidates([x for x in changed if x in differing], clues)  # Sherlock prunes same-output nodes
    cards = lambda mask: {x: list(node_card(x, failed_hist, good_hist, checks, mask=mask)) for x in cands}  # noqa: E731
    return {"id": f"g1gen:{seed}:{i:04d}", "team": f"gen_n{team['n']}", "gold": [culprits], "status": "found",
            "candidates": cands, "on_path": list(out), "dataset": DATASET, "split": split,
            "clue_score": {x: sum(c.weight for c in clues if c.node == x) for x in cands},
            "hint": [x for s in extra.llm_guess_stub(failed_hist, good_hist, checks).get("sets", []) for x in s],
            "cards": cards(False), "masked": cards(True)}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--cases", type=int, default=200, help="first half dev, second half test")
    ap.add_argument("--out", type=Path, default=HERE / ".g1" / "gen_v1")
    a = ap.parse_args()
    cases = [make_case(a.seed, i, "dev" if i < a.cases // 2 else "test") for i in range(a.cases)]
    a.out.mkdir(parents=True, exist_ok=True)
    for split in ("dev", "test"):
        rows = [c for c in cases if c["split"] == split]
        data = "".join(json.dumps(c, sort_keys=True) + "\n" for c in rows).encode("utf-8")
        (a.out / f"{split}.jsonl").write_bytes(data)
        print(f"{a.out / (split + '.jsonl')}: {len(rows)} lines, sha256 {hashlib.sha256(data).hexdigest()}")
    n = len(cases) or 1
    print(f"mean candidates {sum(len(c['candidates']) for c in cases) / n:.2f}, "
          f"mean gold nodes {sum(len(c['gold'][0]) for c in cases) / n:.2f}")


if __name__ == "__main__":
    main()
