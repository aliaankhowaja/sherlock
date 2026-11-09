"""Which ordering reaches the published culprit names sooner?

    cd python/sherlock
    uv run python eval/public_g1.py --cases cases.jsonl --backend fake
    uv run python eval/public_g1.py --cases cases.jsonl --backend laya --out ../../docs/eval/public_traces

Reads the records convert_public_traces.py writes. mathchat rows (tag two_role) are counted
in an appendix and left out of every mean. A lower trials_to_label means that order named
the labelled agents earlier. It does not mean those agents are a minimal fix.
"""

import argparse
import json
import math
import random
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "src"), str(HERE)]

from g1_eval import first_fix, metrics  # noqa: E402
from sherlock.checks import Checks  # noqa: E402
from sherlock.clues import history_clues, order_candidates  # noqa: E402
from sherlock.evaluation import g0_only  # noqa: E402
from sherlock.g1 import node_card, rank  # noqa: E402
from sherlock.search import Budget, _supersteps  # noqa: E402

METHODS = ("random", "path", "g0", "laya", "laya_masked")
INTRO = (
    "This compares orders against the published label. "
    "A lower trial count means the order named the labelled agents earlier. "
    "It does not mean those agents are a minimal fix, and it does not mean restoring them would make the task pass."
)


def path_of(history: list[dict]) -> list[str]:
    """Conversation order, one entry per node."""
    return list(dict.fromkeys(t["name"] for step in _supersteps(history) for t in step))


def _checks(record: dict) -> Checks:
    """An equals-check when the corpus published a reference. Who&When text has none."""
    assertions = []
    if record.get("reference") is not None:
        assertions = [{"type": "equals", "value": record["reference"]}]
    return Checks(assertions, "final_output", Path("."), Path("public-trace"))


def label_budget(n_nodes: int, gold_size: int) -> Budget:
    """The g1_eval auto budget, widened so a label of four names can be tried.

    The planted set passes only when every labelled name is restored. The default size cap is 3,
    which leaves a four-name label with no trial. The cap grows only for that label, and every
    method on the row uses the same budget.
    """
    size = max(3, gold_size)
    room = 1 + sum(math.comb(n_nodes, k) for k in range(1, min(size, n_nodes) + 1))
    trials = max(40, 3 * n_nodes + 20, room)
    return Budget(max_trials=trials, max_minutes=10, max_size=size)


def _orders(record: dict, seed: int, backend: str):
    history = record["history"]
    on_path = path_of(history)
    clues = history_clues(history, "final_output")
    checks = _checks(record)
    decks = {
        "laya": {n: node_card(n, history, None, checks, mask=False) for n in on_path},
        "laya_masked": {n: node_card(n, history, None, checks, mask=True) for n in on_path},
    }
    shuffled = list(on_path)
    random.Random(f"{seed}:{record['id']}").shuffle(shuffled)
    out = {"random": shuffled, "path": list(on_path), "g0": order_candidates(on_path, clues)}
    # `local` is left unset so LOCAL=true selects the in-process checkpoint, as in g1_eval.
    cfg = {"backend": backend, "allow_remote": True, "cache_dir": HERE / ".g1" / "public_cache"}
    problems = []
    for name in ("laya", "laya_masked"):
        deck = decks[name]
        g1 = rank(cfg, on_path, lambda n, deck=deck: tuple(deck[n]))
        if g1["status"] == "unavailable":
            problems.append(f"{record['id']} ({name}): {g1.get('reason') or 'unavailable'}")
        else:
            out[name] = order_candidates(on_path, clues, [s["node"] for s in g1["scores"]])
    return out, problems


def _score_row(record: dict, orders: dict) -> dict:
    gold_names = set(record["gold"][0])
    budget = label_budget(len(orders["path"]), len(gold_names))
    methods = {}
    for name, order in orders.items():
        trial, _reason = first_fix(order, record["gold"], budget)
        scored = metrics(order, gold_names)
        methods[name] = {
            "rank": scored["rank"],
            "reciprocal rank": scored["rr"],
            "recall@3": scored["recall3"],
            "ndcg@3": scored["ndcg3"],
            "trials_to_label": trial,
        }
    return {"id": record["id"], "source": record["source"], "framework": record["framework"],
            "gold_size": len(gold_names), "methods": methods}


def _mean(values):
    return round(statistics.mean(values), 3) if values else None


def summarize(rows: list[dict]) -> dict:
    out = {}
    for method in METHODS:
        cells = [row["methods"][method] for row in rows]
        trials = [cell["trials_to_label"] for cell in cells if cell["trials_to_label"] is not None]
        out[method] = {
            "rows": len(cells),
            "rank": _mean([cell["rank"] for cell in cells if cell["rank"] is not None]),
            "reciprocal rank": _mean([cell["reciprocal rank"] for cell in cells]),
            "recall@3": _mean([cell["recall@3"] for cell in cells]),
            "ndcg@3": _mean([cell["ndcg@3"] for cell in cells]),
            "trials_to_label": _mean(trials),
            "no_trial": len(cells) - len(trials),
        }
    return out


def g0_only_table(records: list[dict]) -> dict:
    """One named node against the label. One-name labels get a match rate. Larger labels get Jaccard too."""
    buckets = {"one name": [], "several names": []}
    for record in records:
        label = set(record["gold"][0])
        pred = g0_only(record["history"], record["history"], _checks(record))
        key = "one name" if len(label) == 1 else "several names"
        if pred["status"] != "answer":
            buckets[key].append({"in_label": False, "jaccard": None})
            continue
        named = set(pred["sets"][0])
        node = pred["sets"][0][0]
        union = named | label
        buckets[key].append({"in_label": node in label, "jaccard": len(named & label) / len(union)})
    out = {}
    for key, rows in buckets.items():
        answered = [row["jaccard"] for row in rows if row["jaccard"] is not None]
        out[key] = {
            "rows": len(rows),
            "name in label": _mean([1.0 if row["in_label"] else 0.0 for row in rows]) if rows else None,
            "Jaccard": _mean(answered) if key == "several names" else None,
        }
    return out


def two_role_appendix(records: list[dict]) -> dict:
    names = sorted({name for record in records for name in path_of(record["history"])})
    return {"rows": len(records), "node_names": names}


def evaluate(headline: list[dict], appendix: list[dict], backend: str, seed: int) -> dict:
    rows = []
    for record in headline:
        orders, failed = _orders(record, seed, backend)
        if failed:
            raise RuntimeError("Laya was unavailable:\n" + "\n".join(failed[:8]))
        rows.append(_score_row(record, orders))
    by_source = {}
    for row in rows:
        by_source.setdefault(row["source"], []).append(row)
    return {
        "intro": INTRO,
        "backend": backend,
        "seed": seed,
        "methods": summarize(rows),
        "by_source": {source: summarize(group) for source, group in sorted(by_source.items())},
        "g0_only": g0_only_table(headline),
        "two_role": two_role_appendix(appendix),
        "rows": rows,
    }


def _cell(value) -> str:
    return "-" if value is None else str(value)


def _table(head, body) -> str:
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    lines += ["| " + " | ".join(_cell(value) for value in row) + " |" for row in body]
    return "\n".join(lines)


def _method_table(summary: dict) -> str:
    cols = ["rank", "reciprocal rank", "recall@3", "ndcg@3", "trials_to_label"]
    body = [[method, summary[method]["rows"], *[_cell(summary[method][col]) for col in cols], summary[method]["no_trial"]]
            for method in METHODS]
    return _table(["method", "rows", *cols, "no trial"], body)


def render(report: dict) -> str:
    parts = [f"# Public-trace ordering ({report['backend']})", "", report["intro"], "",
             "mathchat rows tagged `two_role` are not in these means.", "",
             "## Methods", "", _method_table(report["methods"]), ""]
    for source, summary in report["by_source"].items():
        parts += [f"## {source}", "", _method_table(summary), ""]
    g0 = report["g0_only"]
    parts += ["## g0_only", "",
              "g0_only names one node. One-name labels are a match rate. Several names report whether that "
              "node sits in the label, and the Jaccard of the two sets.", "",
              _table(["labels", "rows", "name in label", "Jaccard"],
                     [[key, g0[key]["rows"], g0[key]["name in label"], g0[key]["Jaccard"]] for key in ("one name", "several names")]),
              "", "## Appendix: two_role", ""]
    appendix = report["two_role"]
    names = ", ".join(appendix["node_names"]) or "(none)"
    noun = "row" if appendix["rows"] == 1 else "rows"
    parts.append(f"{appendix['rows']} {noun}. Node names: {names}.")
    parts.append("These rows have no rank, no reciprocal rank, no recall@3, no ndcg@3, and no trials_to_label.")
    parts.append("")
    return "\n".join(parts)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cases", type=Path, required=True)
    ap.add_argument("--out", type=Path, help="write public_g1.md and public_g1.json here")
    ap.add_argument("--backend", choices=("laya", "fake"), default="laya")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    records = [json.loads(line) for line in args.cases.read_text(encoding="utf-8").splitlines() if line.strip()]
    headline = [row for row in records if "two_role" not in row.get("tags", [])]
    appendix = [row for row in records if "two_role" in row.get("tags", [])]
    try:
        report = evaluate(headline, appendix, args.backend, args.seed)
    except RuntimeError as exc:
        sys.exit(f"public_g1: {exc}")
    text = render(report)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "public_g1.md").write_text(text, encoding="utf-8", newline="\n")
        (args.out / "public_g1.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                                                 encoding="utf-8", newline="\n")
    print(text, end="")


if __name__ == "__main__":
    main()
