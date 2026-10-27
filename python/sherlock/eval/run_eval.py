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
sys.path[:0] = [str(HERE), str(HARNESS), str(HERE.parent / "tests"), str(HERE.parent / "src")]

from g1_stub import ShortlistStub  # noqa: E402
from sherlock_harness.catalog import BIG_TEAMS, HARMLESS, SEED, TEAMS, Case, build_cases  # noqa: E402
from sherlock_harness.stub import EchoStub  # noqa: E402
from test_g3_live import LAUNCHER, Server, http  # noqa: E402

from sherlock.checks import Checks  # noqa: E402
from sherlock.diagnose import _gather_sources, diagnose, write_artifact  # noqa: E402
import baselines as extra  # noqa: E402
from sherlock.evaluation import (BASELINES, METHODS, artifact_violations, from_artifact, score,  # noqa: E402
                                 summarize)
from sherlock.g1 import node_card  # noqa: E402
from sherlock.g3 import Client  # noqa: E402
from sherlock.search import Budget  # noqa: E402

SCHEMA = 2
G1_DIR = HERE / ".g1"  # node cards for eval/g1_eval.py (git-ignored: derived, rebuilt by every run)
ALL_METHODS = METHODS + extra.EXTRA
# FR-E9: the two-cause case live time-travel must fail, and a one-cause control it must be able to solve.
TWO_CAUSE = "vendor_brief:retriever.drop_latest+extractor.legacy_pattern"
CONTROL = "vendor_brief:router.wrong_source"
LIVE_TT = (TWO_CAUSE, CONTROL)
SLICES = {
    "all": lambda r: True,
    "visible": lambda r: r["split"] == "visible",
    "hidden": lambda r: r["split"] == "hidden",
    "hard": lambda r: r["hard"],
    "one_node": lambda r: r["size"] == 1,
    "two_node": lambda r: r["size"] >= 2,
    "last_step_ok": lambda r: "last_step_ok" in r["tags"],
}

# Gate probes on one failed run per large team: (a node on the path that is not the cause, a node that never ran).
PROBES = {"support_desk:customer_lookup.stale_cache": ("rerank", "escalate"),
          "loan_underwriting:policy_rules.dti_limit_low": ("dti_calc", "approve_terms"),
          "revenue_report:always_warn": ("forecast_next", "clean_pass")}


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


def _live_tt(client, tid, history, art, good_tid, team, checks, c):
    """Live time-travel (no cassette, one node restored per fork) scored like every method on the same case."""
    graph_id = (client.request("GET", f"/threads/{tid}").get("metadata") or {}).get("graph_id")
    src = _gather_sources(client, tid, graph_id, history, art["context"], checks, [good_tid], False,
                          team.node_map)[0]
    pred, seen = extra.live_time_travel(client, tid, history, src.known_good, checks, art["context"])
    return {"case": c.id, "gold": c.gold, "single_restore_verdicts": seen, "prediction": pred,
            "outcome": score(c.gold, pred)["outcome"]}


def _history(client, tid):
    return client.request("POST", f"/threads/{tid}/history", {"limit": 1000})


def _gate_probes(client, c, tid, team, checks, cassette, good, decoy, ghost):
    """G1 nominates a wrong node first; G2 gets a shortlist with a node that never ran, then only such a node; no
    known-good run at all. Each has an expected outcome, so a regression in a gate shows up as a failed probe."""
    gold = c.gold
    names = sorted({n for g in gold for n in g})
    out = []

    def run(name, expect, ok, **kw):
        kw.setdefault("good_runs", [good])
        art = diagnose(client, tid, None, checks, cassette, Budget(), node_map=team.node_map, **kw)
        gs = art.get("gate_summary") or {}
        out.append({"case": c.id, "probe": name, "expect": expect, "status": art["status"],
                    "reason_code": art.get("reason_code"), "minimal_sets": art.get("minimal_sets", []),
                    "trials_used": (art.get("budget") or {}).get("trials_used", 0),
                    "g1_nominated": gs.get("g1_nominated", 0), "g2_cut": gs.get("g2_cut", 0), "ok": ok(art)})

    exact = lambda a: a["status"] == "found" and sorted(a["minimal_sets"]) == sorted(gold)
    with ShortlistStub([decoy] + names) as stub:
        run("g1_wrong_node_first", "exact answer; G1 only reorders", exact,
            g1={"url": stub.url, "model": "stub", "samples": 1})
    run("g2_cuts_ghost", "exact answer; the node that never ran is cut",
        lambda a: exact(a) and (a.get("gate_summary") or {}).get("g2_cut", 0) >= 1, suspects=names + [ghost])
    run("g2_all_cut", "abstain (the only suspect names no recorded arrow)",
        lambda a: a["status"] == "abstain" and not a.get("minimal_sets"), suspects=[ghost])
    run("no_known_good", "abstain no_known_good", lambda a: a.get("reason_code") == "no_known_good", good_runs=[])
    return out


def _run_group(cases, seed):
    """One lab for `cases`: record, restart under replay, diagnose each, score against the baselines."""
    work = Path(tempfile.mkdtemp(prefix="sherlock-eval-"))
    server, good, failed, cassette = _lab(work, cases)
    rows, artifacts, unchanged, probes, invariants_live, g1_changed = [], [], [], [], {}, []
    try:
        client = Client(server.url)
        for c in cases:
            team = TEAMS[c.team]
            checks = Checks(team.check, "final_output", work, work / "sherlock.yaml")
            tid = failed[c.id]
            if c.split == "probe":  # planted but harmless: the run passes, a diagnosis must say so
                art = diagnose(client, tid, None, checks, cassette, Budget(), good_runs=[good[c.team]],
                               node_map=team.node_map)
                probes.append({"case": c.id, "probe": "harmless", "expect": "already_passes", "status": art["status"],
                               "reason_code": art.get("reason_code"), "minimal_sets": [], "trials_used": 0,
                               "g1_nominated": 0, "g2_cut": 0, "ok": art.get("reason_code") == "already_passes"})
                continue
            before = _history(client, tid)
            art = diagnose(client, tid, None, checks, cassette, Budget(), good_runs=[good[c.team]],
                           node_map=team.node_map)
            write_artifact(art, work / ".sherlock")
            artifacts.append((c.id, art))
            after = _history(client, tid)
            unchanged.append((c.id, before == after))
            fake = diagnose(client, tid, None, checks, cassette, Budget(), good_runs=[good[c.team]],
                            node_map=team.node_map, g1={"backend": "fake"})
            if answer(fake) != answer(art):
                g1_changed.append(c.id)  # AC-G1-1: G1 may reorder trials, never change the answer
            good_hist = _history(client, good[c.team])
            rng = random.Random(f"{seed}:{c.id}")
            preds = {"sherlock": from_artifact(art)}
            for name, fn in BASELINES.items():
                preds[name] = fn(after, good_hist, checks, rng=rng)
            preds["llm_guess_stub"] = extra.llm_guess_stub(after, good_hist, checks)
            preds["g0_g2"] = extra.g0_g2(art)
            preds["plain_retry"], retry = extra.plain_retry(client, art, c.team, team.input, checks)
            if c.id in LIVE_TT:
                invariants_live[c.id] = _live_tt(client, tid, after, art, good[c.team], team, checks, c)
            cands = (art.get("pruning") or {}).get("candidates", [])  # in G0 order: G1 is off here
            g1_case = {"id": c.id, "team": c.team, "gold": c.gold, "status": art["status"], "candidates": cands,
                       "on_path": (art.get("pruning") or {}).get("nodes_on_path", []),
                       "clue_score": {n: sum(k["weight"] for k in art.get("clues", []) if k.get("node") == n) for n in cands},
                       "hint": [n for s in preds["llm_guess_stub"].get("sets", []) for n in s],
                       "cards": {n: node_card(n, after, good_hist, checks) for n in cands},
                       "masked": {n: node_card(n, after, good_hist, checks, mask=True) for n in cands}}
            red = art.get("trial_reduction") or {}
            gold_nodes = {n for g in c.gold for n in g}
            clue_nodes = sorted({k["node"] for k in art.get("clues", []) if k.get("node")})
            if c.id in PROBES:
                probes += _gate_probes(client, c, tid, team, checks, cassette, good[c.team], *PROBES[c.id])
            rows.append({**c.to_dict(), "_g1": g1_case,
                         "methods": {m: score(c.gold, preds[m]) | {"prediction": preds[m]} for m in ALL_METHODS},
                         "retry": retry,
                         "sherlock": {"status": art["status"], "reason_code": art.get("reason_code"),
                                      "trials_used": red.get("trials_used", 0),
                                      "exhaustive_trials": red.get("exhaustive_trials", 0),
                                      "pruned_ratio": (art.get("pruning") or {}).get("pruned_ratio"),
                                      "unverified_sets": art.get("unverified_sets", []),
                                      "on_path": len((art.get("pruning") or {}).get("nodes_on_path", [])),
                                      "candidates": len((art.get("pruning") or {}).get("candidates", [])),
                                      "clue_nodes": clue_nodes, "g0_hit": bool(gold_nodes & set(clue_nodes)),
                                      "gate": art.get("gate_summary"),
                                      "cannot_say_trials": (art.get("counts") or {}).get("cannot_say", 0)}})
    finally:
        server.stop()
    attempts = (work / "net_attempts.txt").read_text().splitlines() if (work / "net_attempts.txt").exists() else []
    shutil.rmtree(work, ignore_errors=True)
    return rows, artifacts, unchanged, attempts, probes, invariants_live, g1_changed


def answer(art: dict) -> tuple:
    """What G1 must never change: the sets (as sets), the status and the reason code."""
    sets = lambda key: sorted(sorted(s) for s in art.get(key) or [])  # noqa: E731
    return sets("minimal_sets"), sets("unverified_sets"), art.get("status"), art.get("reason_code")


def run_eval(seed: int = SEED, only: set | None = None) -> dict:
    cases = [c for c in build_cases(seed) if not only or c.team in only]
    probe_cases = [Case(t, f, "probe") for t, f in HARMLESS if not only or t in only]
    # A case shares the common lab unless it changes the model request in two nodes: its restore-one-of-two trials
    # then ask for a request that was never recorded (spec 9.1), and a shared cassette holding another case's tape
    # would turn that into a hit. Those cases get their own lab and a cassette with only their own tapes. A case with
    # one request-changing fault cannot leak into another: each such tape is also what restoring that node asks for.
    def alone(c):
        team = TEAMS[c.team]
        return team.llm and len({team.faults[f].node for f in c.faults} & team.request_nodes) >= 2

    groups = [[c for c in cases + probe_cases if not alone(c)]] + [[c] for c in cases if alone(c)]
    rows, artifacts, unchanged, net_attempts, probes, live, g1_changed = [], [], [], [], [], {}, []
    for group in groups:
        r, a, u, n, p, lv, g = _run_group(group, seed)
        g1_changed += g
        live.update(lv)
        rows += r
        artifacts += a
        unchanged += u
        net_attempts += n
        probes += p
    order = {c.id: i for i, c in enumerate(cases)}
    rows.sort(key=lambda r: order[r["id"]])
    G1_DIR.mkdir(exist_ok=True)
    (G1_DIR / "cases.jsonl").write_text("".join(json.dumps(r.pop("_g1"), sort_keys=True) + "\n" for r in rows),
                                        encoding="utf-8", newline="\n")
    summary = {s: {m: summarize(rows, m, pick) for m in ALL_METHODS} for s, pick in SLICES.items()}
    used = sum(r["sherlock"]["trials_used"] for r in rows if r["sherlock"]["status"] == "found")
    exhaustive = sum(r["sherlock"]["exhaustive_trials"] for r in rows if r["sherlock"]["status"] == "found")
    results = {
        "schema": SCHEMA, "seed": seed, "teams": sorted(TEAMS), "cases": rows, "summary": summary,
        "by_team": {t: {m: summarize(rows, m, lambda r, t=t: r["team"] == t) for m in ALL_METHODS} for t in sorted(TEAMS)},
        "trials": {"used_on_found": used, "exhaustive_on_found": exhaustive,
                   "fewer_pct": round(100 * (1 - used / exhaustive), 1) if exhaustive else 0.0},
        "probes": probes, "scale": scale_table(rows),
        "invariants": {
            "replay_network_attempts": net_attempts,
            "original_thread_unchanged": all(ok for _, ok in unchanged),
            "artifact_violations": {i: v for i, a in artifacts if (v := artifact_violations(a))},
            "live_time_travel": live,
            "g1_fake_changed_answer": sorted(g1_changed),
        },
        "retry": {"runs_per_case": extra.RETRIES,
                  "cases_where_a_retry_passed": sum(r["retry"]["passed"] > 0 for r in rows),
                  "retries_that_passed": sum(r["retry"]["passed"] for r in rows)},
    }
    results["failures"] = expectations(results)
    return results


def scale_table(rows) -> dict:
    """Per team: pipeline size, trials used against exhaustive, what each gate removed (cases with an answer)."""
    out = {}
    for t in sorted({r["team"] for r in rows}):
        mine = [r for r in rows if r["team"] == t]
        done = [r for r in mine if r["sherlock"]["trials_used"]]
        gs = [r["sherlock"]["gate"] or {} for r in mine]
        out[t] = {"nodes": len(TEAMS[t].nodes), "cases": len(mine),
                  "nodes_on_path_max": max(r["sherlock"]["on_path"] for r in mine),
                  "trials_max": max((r["sherlock"]["trials_used"] for r in mine), default=0),
                  "trials_mean": round(sum(r["sherlock"]["trials_used"] for r in done) / len(done), 1) if done else 0,
                  "exhaustive_max": max(r["sherlock"]["exhaustive_trials"] for r in mine),
                  "candidates_mean": round(sum(r["sherlock"]["candidates"] for r in mine) / len(mine), 1),
                  "pruned_by_ancestry": sum(g.get("pruned_by_ancestry", 0) for g in gs),
                  "pruned_other": sum(g.get("pruned_other", 0) for g in gs),
                  "g0_clue_hits": sum(r["sherlock"]["g0_hit"] for r in mine),
                  "g3_trials": sum(r["sherlock"]["trials_used"] for r in mine)}
    return out


def expectations(res: dict) -> list[str]:
    """What must hold for the phase exit criterion; every miss is listed, none is hidden."""
    bad = []
    inv = res["invariants"]
    if inv["replay_network_attempts"]:
        bad.append(f"replay tried the network: {inv['replay_network_attempts'][:3]}")
    if not inv["original_thread_unchanged"]:
        bad.append("an original thread changed after the forks")
    if inv["g1_fake_changed_answer"]:
        bad.append(f"G1 (fake) changed the answer: {inv['g1_fake_changed_answer']}")
    if inv["artifact_violations"]:
        bad.append(f"artifacts break the honesty rules: {inv['artifact_violations']}")
    for r in res["cases"]:
        s = r["methods"]["sherlock"]
        if r["expect_abstain"]:
            if s["outcome"] != "abstain":
                bad.append(f"{r['id']}: expected an honest abstain, got {s['outcome']}")
        elif s["outcome"] != "exact":
            bad.append(f"{r['id']}: expected an exact answer, got {s['outcome']} ({s['reason'] or s['prediction']})")
    for p in res["probes"]:
        if not p["ok"]:
            bad.append(f"gate probe {p['probe']} on {p['case']}: expected {p['expect']}, got {p['status']} "
                       f"{p['reason_code'] or p['minimal_sets']}")
    for sl in ("all", "hard"):
        mine = res["summary"][sl]["sherlock"]
        for m in (*BASELINES, *extra.EXTRA):
            other = res["summary"][sl][m]
            if mine["exact"] < other["exact"] or mine["wrong"] > other["wrong"]:
                bad.append(f"sherlock does not beat or equal {m} on the {sl} slice")
    live = inv.get("live_time_travel", {})
    if not live:
        bad.append("FR-E9: live time-travel was not run")
    if TWO_CAUSE in live and live[TWO_CAUSE]["outcome"] == "exact":
        bad.append("FR-E9: live time-travel (no call blocking) solved the two-cause case; the invariant is broken")
    if CONTROL in live and live[CONTROL]["outcome"] != "exact":
        bad.append("FR-E9 control: live time-travel could not solve a one-cause case, so the baseline is a straw man")
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
        out += [f"## {title}", "", head + "\n".join(_row(m, res["summary"][sl][m]) for m in ALL_METHODS), ""]
    out += ["## Per team (Sherlock)", "",
            "| team | cases | exact | wrong claim | abstain | abstain reasons |\n|---|---|---|---|---|---|"]
    for t, ms in res["by_team"].items():
        s = ms["sherlock"]
        out.append(f"| {t} | {s['n']} | {s['exact']} | {s['wrong']} | {s['abstain']} | {s['abstain_reasons'] or '-'} |")
    out += ["", "## Scale: trials used against exhaustive enumeration, per team", "",
            "| team | nodes | cases | max nodes on a path | exhaustive (max) | max trials | mean trials (answered) | mean candidates | "
            "pruned by ancestry | pruned other (same output / no-op restore) | G0 clue named a gold node | G3 trials |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for team, s in res["scale"].items():
        out.append(f"| {team} | {s['nodes']} | {s['cases']} | {s['nodes_on_path_max']} | "
                   f"2^{s['nodes_on_path_max']} - 1 = {s['exhaustive_max']:,} | {s['trials_max']} | {s['trials_mean']} | "
                   f"{s['candidates_mean']} | {s['pruned_by_ancestry']} | {s['pruned_other']} | "
                   f"{s['g0_clue_hits']} / {s['cases']} | {s['g3_trials']} |")
    out += ["", "## Gate probes (one failed run per large team, plus the harmless runs)", "",
            "| case | probe | expected | got | trials | G1 nominated | G2 cut | ok |\n|---|---|---|---|---|---|---|---|"]
    for p in res["probes"]:
        got = p["reason_code"] or "{" + "}, {".join(", ".join(s) for s in p["minimal_sets"]) + "}"
        out.append(f"| {p['case']} | {p['probe']} | {p['expect']} | {p['status']}: {got} | {p['trials_used']} | "
                   f"{p['g1_nominated']} | {p['g2_cut']} | {'yes' if p['ok'] else 'NO'} |")
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
            f"- FR-E9 live time-travel (fork, restore one node, no cassette): "
            + "; ".join(f"{k}: {v['outcome']} ({v['prediction'].get('reason') or v['prediction']['sets']})"
                        for k, v in inv["live_time_travel"].items()),
            f"- plain retry (x{res['retry']['runs_per_case']} per case) passed on {res['retry']['cases_where_a_retry_passed']} case(s)",
            f"- expectation failures: {len(res['failures'])}", ""]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", help="write results.json and results.md here")
    ap.add_argument("--check", help="regenerate and compare with this results.json (exit 1 on any difference)")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--only", help="comma-separated teams (a quick partial run; never use with --check)")
    args = ap.parse_args()
    try:
        res = run_eval(args.seed, set(args.only.split(",")) if args.only else None)
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
