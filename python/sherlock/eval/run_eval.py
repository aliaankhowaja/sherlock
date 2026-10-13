"""Phase 6 evaluation runner (spec 5.10, FR-E1..E7): every team x fault case, Sherlock and the baselines.

    cd python/sherlock
    uv run python eval/run_eval.py --out ../../docs/eval            # write results.json + results.md
    uv run python eval/run_eval.py --check ../../docs/eval/results.json   # regenerate and diff (the CI gate)

Real workflow, no provider: (1) `sherlock-rec run langgraph dev` records one known-good run per team and one failed
run per case against a local echo stub; (2) the stub goes away; (3) the server restarts under `sherlock-rec run
--replay` inside a socket trap that forbids every non-loopback connection; (4) `diagnose` runs on each failed run with
the team's good run as the known-good source. Baselines read the same recorded histories and the same check Z.
Exit 0 when every invariant and expectation holds, 1 when one fails, 2 on an infrastructure error.
"""

import argparse
import json
import random
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
HARNESS = ROOT / "harness"
sys.path[:0] = [str(HARNESS), str(HERE.parent / "tests"), str(HERE.parent / "src")]

from sherlock_harness.catalog import SEED, TEAMS, build_cases  # noqa: E402
from sherlock_harness.stub import EchoStub  # noqa: E402
from test_g3_live import LAUNCHER, Server, http  # noqa: E402

from sherlock.checks import Checks  # noqa: E402
from sherlock.diagnose import diagnose, write_artifact  # noqa: E402
from sherlock.evaluation import (BASELINES, METHODS, artifact_violations, from_artifact, score,  # noqa: E402
                                 summarize)
from sherlock.g3 import Client  # noqa: E402
from sherlock.search import Budget  # noqa: E402

SCHEMA = 1
SLICES = {
    "all": lambda r: True,
    "visible": lambda r: r["split"] == "visible",
    "hidden": lambda r: r["split"] == "hidden",
    "hard": lambda r: r["hard"],
    "one_node": lambda r: r["size"] == 1,
    "two_node": lambda r: r["size"] >= 2,
    "last_step_ok": lambda r: "last_step_ok" in r["tags"],
}


def _lab(work: Path, cases):
    """Record the good and failed runs, restart under replay. Returns (server, thread ids, cassette, stub port)."""
    shutil.copytree(HARNESS / "sherlock_harness", work / "sherlock_harness",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(HARNESS / "pyproject.toml", work / "pyproject.toml")
    (work / "launcher.py").write_text(LAUNCHER + "\n")
    graphs = {name: f"./sherlock_harness/teams/{name}.py:graph" for name in TEAMS}
    (work / "langgraph.json").write_text(json.dumps({"dependencies": ["."], "graphs": graphs}))
    cassette = work / ".sherlock" / "cassette.db"
    stub = EchoStub().start()
    recorder = Server(work, replay=False, cassette=cassette, stub_port=stub.port, log=work / "record.log")
    good, failed = {}, {}

    def record(graph, faults):
        tid = http(recorder.url, "POST", "/threads", {"metadata": {"assistant_id": graph}})["thread_id"]
        http(recorder.url, "POST", f"/threads/{tid}/runs/wait",
             {"assistant_id": graph, "input": TEAMS[graph].input, "context": {"faults": faults},
              "durability": "sync"})
        return tid

    try:
        for name in TEAMS:
            good[name] = record(name, [])
        for c in cases:
            failed[c.id] = record(c.team, c.faults)
    finally:
        recorder.stop()
        stub.stop()  # the provider is gone from here on
    server = Server(work, replay=True, cassette=cassette, stub_port=stub.port, log=work / "replay.log")
    return server, good, failed, cassette


def _history(client, tid):
    return client.request("POST", f"/threads/{tid}/history", {"limit": 1000})


def _run_group(cases, seed):
    """One lab for `cases`: record, restart under replay, diagnose each, score against the baselines."""
    work = Path(tempfile.mkdtemp(prefix="sherlock-eval-"))
    server, good, failed, cassette = _lab(work, cases)
    rows, artifacts, unchanged = [], [], []
    try:
        client = Client(server.url)
        for c in cases:
            team = TEAMS[c.team]
            checks = Checks(team.check, "final_output", work, work / "sherlock.yaml")
            tid = failed[c.id]
            before = _history(client, tid)
            art = diagnose(client, tid, None, checks, cassette, Budget(), good_runs=[good[c.team]],
                           node_map=team.node_map)
            write_artifact(art, work / ".sherlock")
            artifacts.append((c.id, art))
            after = _history(client, tid)
            unchanged.append((c.id, before == after))
            good_hist = _history(client, good[c.team])
            rng = random.Random(f"{seed}:{c.id}")
            preds = {"sherlock": from_artifact(art)}
            for name, fn in BASELINES.items():
                preds[name] = fn(after, good_hist, checks, rng=rng)
            red = art.get("trial_reduction") or {}
            rows.append({**c.to_dict(),
                         "methods": {m: score(c.gold, preds[m]) | {"prediction": preds[m]} for m in METHODS},
                         "sherlock": {"status": art["status"], "reason_code": art.get("reason_code"),
                                      "trials_used": red.get("trials_used", 0),
                                      "exhaustive_trials": red.get("exhaustive_trials", 0),
                                      "pruned_ratio": (art.get("pruning") or {}).get("pruned_ratio"),
                                      "unverified_sets": art.get("unverified_sets", []),
                                      "cannot_say_trials": (art.get("counts") or {}).get("cannot_say", 0)}})
    finally:
        server.stop()
    attempts = (work / "net_attempts.txt").read_text().splitlines() if (work / "net_attempts.txt").exists() else []
    shutil.rmtree(work, ignore_errors=True)
    return rows, artifacts, unchanged, attempts


def run_eval(seed: int = SEED) -> dict:
    cases = build_cases(seed)
    # Teams with no model call share one lab (their cassette is empty, so it cannot leak anything). Every LLM-team
    # case gets its own lab and cassette holding only its own good and failed tapes: a shared cassette would hold
    # other cases' requests and turn the never-recorded combinations (spec 9.1) into hits.
    groups = [[c for c in cases if not TEAMS[c.team].llm]] + [[c] for c in cases if TEAMS[c.team].llm]
    rows, artifacts, unchanged, net_attempts = [], [], [], []
    for group in groups:
        r, a, u, n = _run_group(group, seed)
        rows += r
        artifacts += a
        unchanged += u
        net_attempts += n
    order = {c.id: i for i, c in enumerate(cases)}
    rows.sort(key=lambda r: order[r["id"]])
    summary = {s: {m: summarize(rows, m, pick) for m in METHODS} for s, pick in SLICES.items()}
    used = sum(r["sherlock"]["trials_used"] for r in rows if r["sherlock"]["status"] == "found")
    exhaustive = sum(r["sherlock"]["exhaustive_trials"] for r in rows if r["sherlock"]["status"] == "found")
    results = {
        "schema": SCHEMA, "seed": seed, "teams": sorted(TEAMS), "cases": rows, "summary": summary,
        "by_team": {t: {m: summarize(rows, m, lambda r, t=t: r["team"] == t) for m in METHODS} for t in sorted(TEAMS)},
        "trials": {"used_on_found": used, "exhaustive_on_found": exhaustive,
                   "fewer_pct": round(100 * (1 - used / exhaustive), 1) if exhaustive else 0.0},
        "invariants": {
            "replay_network_attempts": net_attempts,
            "original_thread_unchanged": all(ok for _, ok in unchanged),
            "artifact_violations": {i: v for i, a in artifacts if (v := artifact_violations(a))},
        },
    }
    results["failures"] = expectations(results)
    return results


def expectations(res: dict) -> list[str]:
    """What must hold for the phase exit criterion; every miss is listed, none is hidden."""
    bad = []
    inv = res["invariants"]
    if inv["replay_network_attempts"]:
        bad.append(f"replay tried the network: {inv['replay_network_attempts'][:3]}")
    if not inv["original_thread_unchanged"]:
        bad.append("an original thread changed after the forks")
    if inv["artifact_violations"]:
        bad.append(f"artifacts break the honesty rules: {inv['artifact_violations']}")
    for r in res["cases"]:
        s = r["methods"]["sherlock"]
        if r["expect_abstain"]:
            if s["outcome"] != "abstain":
                bad.append(f"{r['id']}: expected an honest abstain, got {s['outcome']}")
        elif s["outcome"] != "exact":
            bad.append(f"{r['id']}: expected an exact answer, got {s['outcome']} ({s['reason'] or s['prediction']})")
    for sl in ("all", "hard"):
        mine = res["summary"][sl]["sherlock"]
        for m in BASELINES:
            other = res["summary"][sl][m]
            if mine["exact"] < other["exact"] or mine["wrong"] > other["wrong"]:
                bad.append(f"sherlock does not beat or equal {m} on the {sl} slice")
    if res["trials"]["exhaustive_on_found"] and res["trials"]["fewer_pct"] < 40:
        bad.append(f"fewer trials than exhaustive: {res['trials']['fewer_pct']}% < 40% (NFR-8)")
    return bad


# --- markdown ----------------------------------------------------------------------------------------------------

def _row(label, s):
    return f"| {label} | {s['n']} | {s['exact']} | {s['wrong']} | {s['abstain']} | {s['mean_jaccard']} |"


def render(res: dict) -> str:
    head = "| method | cases | exact | wrong claim | abstain | mean Jaccard (answered) |\n|---|---|---|---|---|---|\n"
    out = [f"# Evaluation results (seed {res['seed']})", "",
           "Generated by `python/sherlock/eval/run_eval.py`; do not edit. Read `README.md` first for what these numbers do not show.", ""]
    for sl, title in (("all", "All cases"), ("hidden", "Hidden set (never tuned on)"),
                      ("hard", "Hard slice (two-cause, OR-fix, decoy, abstain-by-design)"),
                      ("one_node", "Gold set of one node"), ("two_node", "Gold set of two nodes"),
                      ("last_step_ok", "The node that writes the output is not a culprit")):
        out += [f"## {title}", "", head + "\n".join(_row(m, res["summary"][sl][m]) for m in METHODS), ""]
    out += ["## Per team (Sherlock)", "",
            "| team | cases | exact | wrong claim | abstain | abstain reasons |\n|---|---|---|---|---|---|"]
    for t, ms in res["by_team"].items():
        s = ms["sherlock"]
        out.append(f"| {t} | {s['n']} | {s['exact']} | {s['wrong']} | {s['abstain']} | {s['abstain_reasons'] or '-'} |")
    tr = res["trials"]
    out += ["", "## Trials and pruning (Sherlock, cases with an answer)", "",
            f"{tr['used_on_found']} trials against {tr['exhaustive_on_found']} for exhaustive enumeration "
            f"= {tr['fewer_pct']}% fewer (NFR-8 asks for at least 40%).", "",
            "## Cases", "",
            "| case | split | tags | gold | Sherlock | trials / exhaustive | pruned |\n|---|---|---|---|---|---|---|"]
    for r in res["cases"]:
        s = r["methods"]["sherlock"]
        gold = " or ".join("{" + ", ".join(g) + "}" for g in r["gold"])
        verdict = s["outcome"] if s["outcome"] != "abstain" else f"abstain ({s['reason']})"
        out.append(f"| {r['id']} | {r['split']} | {', '.join(r['tags']) or '-'} | {gold} | {verdict} | "
                   f"{r['sherlock']['trials_used']} / {r['sherlock']['exhaustive_trials']} | {r['sherlock']['pruned_ratio']} |")
    inv = res["invariants"]
    out += ["", "## Invariants", "",
            f"- network attempts during replay: {len(inv['replay_network_attempts'])}",
            f"- original threads unchanged after forks: {inv['original_thread_unchanged']}",
            f"- artifacts that break the honesty rules: {len(inv['artifact_violations'])}",
            f"- expectation failures: {len(res['failures'])}", ""]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", help="write results.json and results.md here")
    ap.add_argument("--check", help="regenerate and compare with this results.json (exit 1 on any difference)")
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()
    try:
        res = run_eval(args.seed)
    except Exception as exc:  # infrastructure, not a result
        print(f"eval: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(res, indent=2, sort_keys=True) + "\n"
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "results.json").write_text(text, encoding="utf-8", newline="\n")
        (out / "results.md").write_text(render(res), encoding="utf-8", newline="\n")
    for f in res["failures"]:
        print(f"FAIL: {f}", file=sys.stderr)
    if args.check:
        want = Path(args.check).read_text(encoding="utf-8").replace("\r\n", "\n")
        if want != text:
            print(f"eval: results differ from {args.check} (not reproducible, or the code changed)", file=sys.stderr)
            return 1
        print("eval: results identical to", args.check)
    s = res["summary"]["all"]["sherlock"]
    print(f"eval: {s['n']} cases, sherlock exact {s['exact']}, wrong {s['wrong']}, abstain {s['abstain']}; "
          f"{len(res['failures'])} expectation failure(s)")
    return 1 if res["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
