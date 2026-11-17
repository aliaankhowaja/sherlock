"""Record the replay corpus: benchmark questions, one saved model reply each, gold from the product's own fork.

    cd python/sherlock
    export BENCH_URL=https://<openai-compatible host>/v1 BENCH_MODEL=<model> BENCH_API_KEY=<key>
    uv run python eval/replay_corpus.py pilot            # at most 90 attempts, stops at 30 kept, then the abstain case
    # a person reads every transcript in .replay_corpus/transcripts.md, then:
    uv run python eval/replay_corpus.py more --transcripts-read     # on to 200 kept or the end of the pool

Plan: docs/notes/replay-corpus-plan.md. Questions and answer keys come from the pinned AEGIS and Who&When Pro
snapshots (never from cases.jsonl). Per attempt, in its own lab with its own cassette:
  1. `sherlock-rec run langgraph dev` runs bench_solver once with no faults. `solve` is the only live call; its
     reply is the cassette. The question is kept only if this run passes `equals` against the normalized key.
  2. The server restarts under `--replay` inside a socket trap. The failed run (headline flags on extract and/or
     format, plus the bias decoy) is recorded there, so its `solve` reply is the saved one.
  3. Gold: every set of the nodes the passing run gives a patch to is forked once with `run_g3` (plan_fork +
     apply_restore). Gold is every inclusion-minimal passing set with no untestable proper subset.
  4. `diagnose` runs as a regression and must report the same sets. That match is not a finding.
The abstain case (steer and preface both change the `solve` request) records its failed run live.
Exit 0 when every rule holds, 1 when one fails, 2 on a setup or infrastructure error.
"""

import argparse
import json
import os
import random
import shutil
import sys
import time
from collections import Counter
from itertools import combinations
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
HARNESS = HERE.parents[2] / "harness"
sys.path[:0] = [str(HERE), str(HARNESS), str(HERE.parent / "tests"), str(HERE.parent / "src")]

import convert_public_traces as convert  # noqa: E402
from sherlock_harness.teams import bench_solver as team  # noqa: E402
from test_g3_live import LAUNCHER, Server  # noqa: E402

from sherlock.cassette import Cassette  # noqa: E402
from sherlock.checks import Checks, evaluate  # noqa: E402
from sherlock.diagnose import _context_of, diagnose  # noqa: E402
from sherlock.g3 import Client, run_g3  # noqa: E402
from sherlock.search import Budget  # noqa: E402
from sherlock.sources import assess, node_outputs  # noqa: E402

GRAPH = "bench_solver"
# Benchmarks one model call can answer from the question text alone (casefolded group names). The rest need files,
# tools or the web (GAIA, tablebench, dsqa, ...) or are code. Multiple-choice benchmarks are out too: their option
# letter is always in the question, so the key-in-question rule would drop every row anyway.
SELF_CONTAINED = ("gsm8k", "math", "scibench", "simpleqa_verified")
CAP, MAX_KEY, SEED = 50, 32, 20261117
PILOT_KEPT, PILOT_ATTEMPTS, MAX_KEPT = 30, 90, 200
SHAPES = [[f] for f in sorted(team.HEADLINE)] + [sorted(team.HEADLINE)]  # cycled by attempt number
DECOY_NODE = team.DECOY.split(".")[0]
REQUEST_NODES = sorted(f.split(".")[0] for f in team.REQUEST)
DEFAULT_OUT = HERE / ".replay_corpus"
# `langgraph dev` (in-memory) saves checkpoints every 10 s, and on Windows the stop kills it before its exit save, so
# the recorder stays up one full interval after the last write. Never read history on the recorder: in
# langgraph-runtime-inmem 0.36 that read unhooks the checkpoints from the 10 s save and the runs are lost.
FLUSH_S = 12


# --- questions (plan step 1) ----------------------------------------------------------------------------------

def normalize_key(raw) -> str:
    """The text after the last '####' when present, then the same `tidy` the team applies to the model's answer."""
    text = convert._text(raw)
    if "####" in text:
        text = text.rsplit("####", 1)[1]
    return team.tidy(text)


def questions(paths):
    """Every row of the pinned files as {id, source, group, question, key}. Who&When `task` is parsed as JSON."""
    for path in paths:
        for row in convert.iter_jsonl(Path(path)):
            if isinstance(row.get("input"), dict) and "conversation_history" in row["input"]:
                rid = str(row.get("id") or "")
                yield {"id": rid, "source": "aegis", "group": rid.split("_", 1)[0],
                       "question": convert._text(row["input"].get("query")),
                       "key": normalize_key((row.get("ground_truth") or {}).get("correct_answer"))}
            elif "trajectory" in row:
                task = convert._parse(row.get("task"))
                task = task if isinstance(task, dict) else {}
                yield {"id": str(row.get("id") or ""), "source": "whowhen", "group": str(row.get("benchmark") or ""),
                       "question": convert._text(task.get("query")), "key": normalize_key(task.get("answer"))}


def ineligible(q: dict) -> str | None:
    """Why a question cannot be used, or None."""
    if q["group"].casefold() not in SELF_CONTAINED:
        return "excluded_benchmark"
    if not q["key"]:
        return "no_key"
    if len(q["key"]) > MAX_KEY:
        return "long_key"
    if not q["question"].strip():
        return "no_question"
    if q["key"].casefold() in q["question"].casefold():
        return "key_in_question"
    return None


def pool(paths, cap: int = CAP, seed: int = SEED) -> list[dict]:
    """Eligible questions, at most `cap` per Who&When benchmark or AEGIS id prefix (file order), each question text
    once, then shuffled with a fixed seed so the attempts mix benchmarks."""
    taken, seen, out = Counter(), set(), []
    for q in questions(paths):
        group = (q["source"], q["group"])
        if ineligible(q) or q["question"] in seen or taken[group] >= cap:
            continue
        seen.add(q["question"])
        taken[group] += 1
        out.append(q)
    random.Random(seed).shuffle(out)
    return out


# --- one case (plan steps 3 and 4) ----------------------------------------------------------------------------

def _new_lab(work: Path):
    if work.exists():
        shutil.rmtree(work)  # left by an attempt that stopped before its record was written
    work.mkdir(parents=True)
    shutil.copy(team.__file__, work / "bench_solver.py")
    shutil.copy(HARNESS / "pyproject.toml", work / "pyproject.toml")
    (work / "launcher.py").write_text(LAUNCHER + "\n")
    (work / "langgraph.json").write_text(json.dumps({"dependencies": ["."],
                                                     "graphs": {GRAPH: "./bench_solver.py:graph"}}))


def _run(client, question: str, faults: list[str], live: bool) -> tuple[str, dict]:
    """A new thread and its final values."""
    tid = client.request("POST", "/threads", {"metadata": {"assistant_id": GRAPH}})["thread_id"]
    result = client.request("POST", f"/threads/{tid}/runs/wait", {
        "assistant_id": GRAPH, "input": {"question": question}, "context": {"faults": faults}, "durability": "sync"})
    if live and isinstance(result, dict) and "__error__" in result:  # a provider error is not an unkept question
        raise RuntimeError(f"the live run failed: {result['__error__']}")
    return tid, result if isinstance(result, dict) else {}


def _history(client, tid):
    return client.request("POST", f"/threads/{tid}/history", {"limit": 1000})


def _values(history) -> dict:
    return (history[0].get("values") or {}) if history else {}


def _passes(checks: Checks, values: dict) -> bool:
    return evaluate(checks.assertions, values.get("final_output") or "", checks.base_dir).passed


def _requests(cassette: Path) -> list[str]:
    """The message text of every recorded model call."""
    out = []
    for call in Cassette(cassette).calls():
        try:
            body = json.loads(bytes(call["request"]))
        except ValueError:
            continue
        if isinstance(body, dict) and body.get("messages"):
            out.append("\n".join(str(m.get("content") or "") for m in body["messages"]))
    return out


def _sets(sets) -> list[list[str]]:
    return sorted(sorted(s) for s in sets or [])


def fork_sets(client, thread, known_good, checks, cassette, context) -> list[dict]:
    """Fork every non-empty set of the nodes that have a known-good patch, once each."""
    nodes = [n for n, patch in known_good.items() if patch]
    trials = []
    for k in range(1, len(nodes) + 1):
        for subset in combinations(nodes, k):
            v = run_g3(client, thread, list(subset), known_good, checks, cassette, context)
            trials.append({"restored": sorted(subset), "verdict": v.verdict, "reason": v.reason,
                           "cassette_miss": bool(v.evidence.get("cassette_miss"))})
    return trials


def gold_of(trials: list[dict]) -> list[list[str]]:
    """Every passing set with no passing proper subset. A proper subset that could not be tested keeps it out."""
    verdict = {frozenset(t["restored"]): t["verdict"] for t in trials}
    gold = []
    for s, v in verdict.items():
        below = [verdict[x] for x in verdict if x < s]
        if v == "pass" and "pass" not in below and "abstain" not in below:
            gold.append(sorted(s))
    return _sets(gold)


def preregistered(faults: list[str]) -> list[str]:
    """The answer-flipping nodes, fixed before the model call. The decoy is stored beside them, never in them."""
    return sorted({f.split(".")[0] for f in faults if f in team.HEADLINE})


def headline_problems(rec: dict) -> list[str]:
    want, gold = rec["preregistered"], rec["gold"]
    verdict = {frozenset(t["restored"]): t["verdict"] for t in rec["forks"]}
    bad = [f"the fork of {t['restored']} could not be tested: {t['reason']}"
           for t in rec["forks"] if t["verdict"] == "abstain"]
    if gold != [want]:
        bad.append(f"gold {gold} is not the pre-registered set {want}")
    for k in range(1, len(want)):
        for sub in combinations(want, k):
            if verdict.get(frozenset(sub)) != "fail":
                bad.append(f"the proper subset {list(sub)} does not fail")
    if any(DECOY_NODE in g for g in gold):
        bad.append(f"the decoy {DECOY_NODE} is in a gold set")
    product = rec["product"]
    if product["status"] != "found":
        bad.append(f"the product search abstained: {product['reason_code']}")
    elif _sets(product["minimal_sets"]) != gold:
        bad.append(f"the product search reported {product['minimal_sets']}, the forks {gold}")
    return bad


def abstain_problems(product: dict) -> list[str]:
    trials = {frozenset(t["restored"]): t for t in product["trials"]}
    pair = trials.get(frozenset(REQUEST_NODES))
    bad = []
    if product["minimal_sets"]:
        bad.append(f"minimal_sets is {product['minimal_sets']}, not empty")
    if _sets(product["unverified_sets"]) != [REQUEST_NODES]:
        bad.append(f"unverified_sets is {product['unverified_sets']}, not exactly {REQUEST_NODES}")
    if product["reason_code"] != "unrecorded_call":
        bad.append(f"the reason code is {product['reason_code']}, not unrecorded_call")
    if not pair or pair["verdict"] != "pass":
        bad.append("the pair trial did not pass")
    for node in REQUEST_NODES:
        single = trials.get(frozenset([node]))
        if not single or not single["cassette_miss"]:
            bad.append(f"restoring only {node} was not a cassette miss")
    return bad


def run_case(work: Path, q: dict, faults: list[str], *, url: str, abstain: bool = False) -> dict:
    """One case in its own lab and cassette. Outcome: kept, unkept (the keep rule), dropped (a drop rule) or failed."""
    _new_lab(work)
    cassette = work / ".sherlock" / "cassette.db"
    checks = Checks([{"type": "equals", "value": q["key"]}], "final_output", work, work / "sherlock.yaml")
    parts = urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)  # the replay trap also refuses this port
    rec = {**q, "faults": faults, "lab": work.name}

    def done(outcome, why):
        return {**rec, "outcome": outcome, "why": why}

    server = Server(work, replay=False, cassette=cassette, stub_port=port, log=work / "record.log")
    try:
        client = Client(server.url, timeout=900)
        clean, values = _run(client, q["question"], [], live=True)
        rec["clean"] = {"thread": clean, "reply": values.get("reply"), "final_output": values.get("final_output")}
        if not _passes(checks, values):
            return done("unkept", ["the clean run does not pass equals"])
        failed = _run(client, q["question"], faults, live=True)[0] if abstain else None
        time.sleep(FLUSH_S)
    finally:
        server.stop()
    # The reply is not scanned (a right answer contains the key), nor the raw body (the model name may hold digits).
    if any(q["key"].casefold() in text.casefold() for text in _requests(cassette)):
        return done("dropped", ["the key is in the solve request"])

    server = Server(work, replay=True, cassette=cassette, stub_port=port, log=work / "replay.log")
    try:
        client = Client(server.url, timeout=900)
        if not abstain:  # served from the clean tape, so the model text cannot change between the two runs
            failed = _run(client, q["question"], faults, live=False)[0]
        good, bad = _history(client, clean), _history(client, failed)
        if not good or not bad or _values(good).get("final_output") != rec["clean"]["final_output"]:
            raise RuntimeError(f"the replay server lost a recorded run of {work.name} (dev persistence)")
        rec["failed"] = {"thread": failed, "final_output": _values(bad).get("final_output")}
        if not abstain:
            if node_outputs(bad).get("solve") != node_outputs(good).get("solve"):
                return done("dropped", ["the failed run's solve write differs from the clean run's"])
            if _passes(checks, _values(bad)):
                return done("unkept", ["the failed run passes equals"])
            context = _context_of(client, failed, bad)
            source = assess(clean, True, bad, context, good, _context_of(client, clean, good), checks)
            rec["forks"] = fork_sets(client, failed, source.known_good, checks, cassette, context)
            rec["gold"] = gold_of(rec["forks"])
            rec["preregistered"] = preregistered(faults)
        art = diagnose(client, failed, None, checks, cassette, Budget(max_size=3), good_runs=[clean])
        rec["product"] = {k: art.get(k) for k in ("status", "reason_code", "reason", "minimal_sets", "unverified_sets")}
        rec["product"]["trials"] = [{k: t[k] for k in ("restored", "verdict", "cassette_miss")}
                                    for t in art.get("trials") or []]
    finally:
        server.stop()
    why = abstain_problems(rec["product"]) if abstain else headline_problems(rec)
    trap = work / "net_attempts.txt"
    if trap.exists():
        why.append(f"replay opened a non-loopback socket: {trap.read_text().split()[:3]}")
    return done("failed" if why else "kept", why)


# --- the corpus (plan step 5) ---------------------------------------------------------------------------------

def load(out: Path) -> list[dict]:
    log = out / "attempts.jsonl"
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()] \
        if log.exists() else []


def record(out: Path, rows: list[dict], url: str, want_kept: int, max_attempts: int) -> list[dict]:
    """Attempt questions in pool order until `want_kept` are kept, `max_attempts` were made, a case failed or the
    pool ran out. Resumes from attempts.jsonl. The fault shape is fixed by the attempt number, before the call."""
    done = load(out)
    tried = {r["id"] for r in done}
    for q in rows:
        if (sum(r["outcome"] == "kept" for r in done) >= want_kept or len(done) >= max_attempts
                or any(r["outcome"] == "failed" for r in done)):
            break
        if q["id"] in tried:
            continue
        n = len(done)
        rec = {"n": n, **run_case(out / "labs" / f"{n:03d}", q, SHAPES[n % len(SHAPES)] + [team.DECOY], url=url)}
        with (out / "attempts.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        done.append(rec)
        print(f"[{n}] {q['source']}/{q['group']} {q['id']}: {rec['outcome']} {'; '.join(rec['why'])}", flush=True)
    return done


def abstain_case(out: Path, done: list[dict], url: str) -> dict | None:
    """The one abstain case, on the first kept question with a numeric key (an answer in words then fails equals)."""
    path = out / "abstain.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    q = next((r for r in done if r["outcome"] == "kept" and r["key"].isdigit()), None)
    if q is None:
        return None
    q = {k: q[k] for k in ("id", "source", "group", "question", "key")}
    rec = run_case(out / "labs" / "abstain", q, sorted(team.REQUEST), url=url, abstain=True)
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return rec


def pilot_problems(done: list[dict], abstain: dict | None) -> list[str]:
    kept = sum(r["outcome"] == "kept" for r in done)
    bad = [f"{r['id']}: {'; '.join(r['why'])}" for r in done if r["outcome"] == "failed"]
    if kept < PILOT_KEPT:
        bad.append(f"{kept} kept in {len(done)} attempts; the pilot needs {PILOT_KEPT} within {PILOT_ATTEMPTS}")
    if abstain is None:
        bad.append("the abstain case was not recorded (a headline case failed, or no kept question has a numeric key)")
    elif abstain["outcome"] != "kept":
        bad.append(f"abstain case ({abstain['outcome']}): {'; '.join(abstain['why'])}")
    return bad


def write_report(out: Path, done: list[dict], abstain: dict | None, problems: list[str], stage: str):
    counts = Counter(r["outcome"] for r in done)
    lines = [f"# Replay corpus ({stage})", "", "Generated by `python/sherlock/eval/replay_corpus.py`. "
             "Plan: `docs/notes/replay-corpus-plan.md`.", "",
             f"Attempts {len(done)}: kept {counts['kept']}, unkept {counts['unkept']}, dropped {counts['dropped']}, "
             f"failed {counts['failed']}.", "", "## Rules", ""]
    lines += [f"- {p}" for p in problems] or ["- every rule held (the transcript read is a person's job)"]
    if abstain:
        p = abstain.get("product") or {}
        lines += ["", "## Abstain case", "", f"{abstain['id']}: {abstain['outcome']}; product {p.get('status')} "
                  f"{p.get('reason_code')}, unverified {p.get('unverified_sets')}"]
    lines += ["", "## Attempts", "", "| n | source/group | id | key | faults | outcome | gold | why |",
              "|---|---|---|---|---|---|---|---|"]
    for r in done:
        lines.append(f"| {r['n']} | {r['source']}/{r['group']} | {r['id']} | `{r['key']}` | {', '.join(r['faults'])} | "
                     f"{r['outcome']} | {r.get('gold', '-')} | {'; '.join(r['why']) or '-'} |")
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    talk = ["# Clean transcripts of the kept cases", "",
            "Read every one: a reply that answers a different question, or states another answer, yet extracts the "
            "key fails the pilot.", ""]
    for r in done:
        if r["outcome"] == "kept":
            talk += [f"## {r['n']}. {r['id']} ({r['source']}/{r['group']})", "",
                     f"key `{r['key']}`, clean final_output `{r['clean']['final_output']}`", "", "Question:", "",
                     "```text", r["question"], "```", "", "Reply:", "", "```text", r["clean"]["reply"] or "", "```", ""]
    (out / "transcripts.md").write_text("\n".join(talk), encoding="utf-8")


def main() -> int:
    defaults = convert.default_paths()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stage", choices=("pilot", "more"))
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--transcripts-read", action="store_true",
                    help="`more` only: a person read every pilot transcript and none answers something else")
    for name in ("aegis_test", "aegis_val", "whowhen"):
        ap.add_argument("--" + name.replace("_", "-"), type=Path, default=defaults[name])
    args = ap.parse_args()
    url = os.environ.get("BENCH_URL")
    if not url or not os.environ.get("BENCH_MODEL"):
        print("replay_corpus: set BENCH_URL (OpenAI-compatible base, e.g. https://host/v1) and BENCH_MODEL; "
              "BENCH_API_KEY when the endpoint needs one", file=sys.stderr)
        return 2
    paths = [args.aegis_test, args.aegis_val, args.whowhen]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        print("replay_corpus: pinned JSONL not found:\n" + "\n".join(missing), file=sys.stderr)
        return 2
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    rows = pool(paths)
    try:
        if args.stage == "pilot":
            done = record(out, rows, url, PILOT_KEPT, PILOT_ATTEMPTS)
            abstain = abstain_case(out, done, url) if not any(r["outcome"] == "failed" for r in done) else None
            problems = pilot_problems(done, abstain)
            (out / "pilot.json").write_text(json.dumps({"ok": not problems, "problems": problems}, indent=2),
                                            encoding="utf-8")
        else:
            pilot = json.loads((out / "pilot.json").read_text(encoding="utf-8")) if (out / "pilot.json").exists() else {}
            if not pilot.get("ok") or not args.transcripts_read:
                print("replay_corpus: `more` needs a passing pilot (pilot.json) and --transcripts-read", file=sys.stderr)
                return 2
            done = record(out, rows, url, MAX_KEPT, len(rows))
            abstain = abstain_case(out, done, url)
            problems = [f"{r['id']}: {'; '.join(r['why'])}" for r in done if r["outcome"] == "failed"]
    except Exception as exc:  # infrastructure, not a result
        print(f"replay_corpus: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    write_report(out, done, abstain, problems, args.stage)
    print(f"replay_corpus: {sum(r['outcome'] == 'kept' for r in done)} kept in {len(done)} attempts "
          f"(pool {len(rows)}); {len(problems)} problem(s); see {out / 'summary.md'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
