"""`sherlock-rec run <cmd>`: launch a command with the recorder bootstrapped (spec 4.2)."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from sherlock.cassette import Cassette

PKG_DIR = Path(__file__).resolve().parent
BOOTSTRAP_DIR = PKG_DIR / "_bootstrap"
PKG_ROOT = PKG_DIR.parent
EXIT_ABSTAIN = 75  # EX_TEMPFAIL: "cannot say"  # makes `import sherlock` work in a child on another interpreter


def child_env(mode: str, cassette: Path, match: str, base: dict | None = None, allow_tools=None,
              max_cassette_mb: float | None = None) -> dict:
    env = dict(os.environ if base is None else base)
    old = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join(
        [str(BOOTSTRAP_DIR), str(PKG_ROOT), *([old] if old else [])]
    )
    env["SHERLOCK_MODE"] = mode
    env["SHERLOCK_CASSETTE"] = str(cassette)
    env["SHERLOCK_MATCH"] = match
    if mode == "replay":
        # `langgraph dev` asks pypi.org for the latest version at startup, which is a live call.
        env.setdefault("LANGGRAPH_NO_VERSION_CHECK", "1")
    if max_cassette_mb is not None:
        env["SHERLOCK_MAX_CASSETTE_MB"] = str(max_cassette_mb)
    if allow_tools is not None:
        env["SHERLOCK_ALLOW_TOOLS"] = ",".join(allow_tools)
    return env


# FR-X7: 0 pass, 100 the check failed (answered wrong), 1 infrastructure error (graph/server/IO crashed),
# 75 cannot say, 2 usage (argparse).
EXIT_FAIL = 100
EXIT_ERROR = 1


def _check(args) -> int:
    from sherlock.checks import CheckError, evaluate, load_checks

    try:
        checks = load_checks(args.config)
        if args.output_file:
            output = Path(args.output_file).read_text(encoding="utf-8")
        else:
            output = args.output if args.output is not None else sys.stdin.read()
        report = evaluate(checks.assertions, output, checks.base_dir)
    except (CheckError, OSError) as exc:
        print(f"sherlock-rec: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(json.dumps(report.to_dict(), indent=2))
    return 0 if report.passed else EXIT_FAIL


def _g3(args) -> int:
    from sherlock.checks import CheckError, load_checks
    from sherlock.g3 import Client, G3Error, load_known_good, run_g3

    try:
        checks = load_checks(args.config)
        client = Client(args.url, args.api_key)
        context = json.loads(args.context) if args.context else None
        verdict = run_g3(client, args.thread_id, [n for n in args.restore.split(",") if n.strip()],
                         load_known_good(args.known_good), checks, args.cassette, context)
    except (G3Error, CheckError, ValueError) as exc:
        print(f"sherlock-rec: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(json.dumps(verdict.to_dict(), indent=2))
    if verdict.verdict == "abstain":
        print(f"sherlock-rec: cannot say: {verdict.reason}", file=sys.stderr)
        return EXIT_ABSTAIN
    return 0 if verdict.verdict == "pass" else EXIT_FAIL


def jsonl_progress(stream):
    """A progress listener that writes one JSON object per line and flushes, so a watcher sees each step live."""
    def emit(event: dict) -> None:
        stream.write(json.dumps(event) + "\n")
        stream.flush()
    return emit


def parse_pasted(items) -> dict:
    """FR-K2: `NODE=@file.json` or `NODE='{"key": value}'` -> {node: known-good behaviour patch}."""
    import yaml

    out = {}
    for item in items or []:
        node, sep, raw = item.partition("=")
        if not sep or not node.strip() or not raw.strip():
            raise ValueError(f"--known-good-output expects NODE=@file.json or NODE=<json>, got {item!r}")
        text = Path(raw[1:]).read_text(encoding="utf-8") if raw.startswith("@") else raw
        try:
            value = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"--known-good-output {node}: not valid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"--known-good-output {node}: expected a mapping of context keys to values")
        out[node.strip()] = value
    return out


def _laya_cfg(args, cache_dir: Path | None) -> dict:
    """G1 Laya settings from the flags. The key stays in the environment: LAYA_API_KEY, or a .env file here."""
    env_file = Path(".env")
    if "LAYA_API_KEY" not in os.environ and env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() == "LAYA_API_KEY":
                os.environ["LAYA_API_KEY"] = value.strip().strip("'\"")
    given = {"endpoint": args.g1_endpoint or os.environ.get("LAYA_API_BASE"), "path": args.g1_path,
             "model": args.g1_model, "timeout_ms": args.g1_timeout_ms, "total_timeout_ms": args.g1_total_timeout_ms}
    return {"backend": "laya", "allow_remote": args.g1_allow_remote, "cache_dir": None if args.g1_no_cache else cache_dir,
            **{k: v for k, v in given.items() if v is not None}}


def _g1_check(args) -> int:
    """Smoke test of a G1 Laya endpoint: the sample card twice, the reported model, usage and every probability."""
    import time
    from urllib.parse import urlsplit

    from sherlock.g1 import DEFAULTS, SAMPLE_CARD, ask, blocked, parse

    cfg = {**DEFAULTS, **_laya_cfg(args, None)}
    print(f"sherlock-rec: this sends card text to {urlsplit(cfg['endpoint']).hostname}", file=sys.stderr)
    problem = blocked(cfg)
    if problem:
        print(f"sherlock-rec: {problem}", file=sys.stderr)
        return EXIT_ERROR
    runs = []
    try:
        for _ in range(2):
            start = time.monotonic()
            raw = ask(cfg, SAMPLE_CARD, cfg["timeout_ms"] / 1000)
            runs.append((raw, *parse(raw), round(1000 * (time.monotonic() - start))))
    except (OSError, ValueError) as exc:
        print(f"sherlock-rec: {cfg['endpoint']}{cfg['path']}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_ERROR
    (raw, answers, truncated, first_ms), (_, again, _, warm_ms) = runs
    print(json.dumps({"url": cfg["endpoint"] + cfg["path"], "model_requested": cfg.get("model"),
                      "model_reported": raw.get("model"), "routed_to": (raw.get("routing") or {}).get("model"),
                      "usage": raw.get("usage"), "truncated": truncated, "answers": answers,
                      "same_answers_twice": answers == again, "ms_first": first_ms, "ms_warm": warm_ms}, indent=2))
    return 0


def _diagnose(args) -> int:
    from sherlock.checks import CheckError
    from sherlock.diagnose import diagnose, write_artifact
    from sherlock.g3 import Client, G3Error, load_known_good, load_node_map
    from sherlock.intake import checks_for, read_intake
    from sherlock.search import Budget

    try:
        sherlock_dir = Path(args.out or Path(args.cassette).parent)
        record = read_intake(sherlock_dir, args.thread_id)
        checks = checks_for(record, args.config)
        context = json.loads(args.context) if args.context else None
        known_good = load_known_good(args.known_good) if args.known_good else None
        pasted = parse_pasted(args.known_good_output)
        known_good = {**(known_good or {}), **pasted} if pasted else known_good
        node_map = load_node_map(args.node_map) if args.node_map else None
        backend = args.g1 or ("hosted" if args.g1_url else "off")
        if (backend == "hosted") != bool(args.g1_url) or (backend == "hosted" and not args.g1_model):
            raise ValueError("--g1 hosted needs both --g1-url and --g1-model, and --g1-url is only for it")
        g1 = ({"url": args.g1_url, "model": args.g1_model, "samples": max(args.g1_samples, 1), "key": args.g1_key}
              if backend == "hosted" else _laya_cfg(args, sherlock_dir / "g1_cache") if backend == "laya"
              else {"backend": "fake"} if backend == "fake" else None)
        result = diagnose(Client(args.url, args.api_key), args.thread_id, known_good, checks, args.cassette,
                          Budget(args.max_trials or 40, args.max_minutes, args.max_size, auto=args.max_trials is None), context,
                          good_runs=args.good_run or [], discover_good=args.discover_good,
                          suspects=args.suspect or [], intake=record, node_map=node_map,
                          progress=jsonl_progress(sys.stderr) if args.progress else None, g1=g1,
                          pasted_nodes=list(pasted))
        path = write_artifact(result, sherlock_dir)
    except (G3Error, CheckError, ValueError, OSError) as exc:
        print(f"sherlock-rec: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(json.dumps(result, indent=2))
    c = result["counts"]
    print(f"sherlock-rec: {result['reason']} ({c['fixes']} fix, {c['partly_helps']} partly, "
          f"{c['does_not_help']} no help, {c['cannot_say']} cannot say of {c['total']} trials; "
          f"{len(result['clues'])} clue(s)) -> {path}", file=sys.stderr)
    return 0 if result["status"] == "found" else EXIT_ABSTAIN


def _outcomes(args) -> int:
    from sherlock.checks import CheckError, load_checks
    from sherlock.g3 import Client, G3Error
    from sherlock.outcomes import outcomes

    try:
        checks = load_checks(args.config)
        threads = Client(args.url, args.api_key).request(
            "POST", "/threads/search", {"metadata": {"graph_id": args.graph_id}, "limit": args.limit})
    except (G3Error, CheckError, ValueError, OSError) as exc:
        print(f"sherlock-rec: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(json.dumps(outcomes(threads or [], checks), indent=2))
    return 0


def _intake(args) -> int:
    from sherlock.checks import CheckError
    from sherlock.intake import write_intake

    try:
        expected = Path(args.expected_file).read_text(encoding="utf-8") if args.expected_file else args.expected
        record = write_intake(args.dir, args.thread_id, expected=expected, check_file=args.check, note=args.note)
    except (CheckError, OSError) as exc:
        print(f"sherlock-rec: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(json.dumps(record, indent=2))
    return 0


def _laya_args(p) -> None:
    p.add_argument("--g1-model", help="model name: for --g1-url, or the Laya checkpoint (default typed-decisions)")
    p.add_argument("--g1-endpoint", help="Laya base URL (default: env LAYA_API_BASE, else https://api.laya.studio)")
    p.add_argument("--g1-path", help="Laya path (default /v1/systemone)")
    p.add_argument("--g1-allow-remote", action="store_true",
                   help="allow a non-local Laya endpoint: the redacted node cards then leave this machine")
    p.add_argument("--g1-timeout-ms", type=int, help="per Laya call (default 10000)")
    p.add_argument("--g1-total-timeout-ms", type=int, help="all of G1 in one diagnosis (default 60000)")
    p.add_argument("--g1-no-cache", action="store_true",
                   help="always call the endpoint; the result is then not reproducible (g1.cache = disabled)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sherlock-rec", epilog="exit codes: 0 pass, 100 check failure, 1 infrastructure error, 75 cannot say, 2 usage")
    sub = ap.add_subparsers(dest="verb", required=True)
    chk = sub.add_parser("check", help="score an output against sherlock.yaml (exit 0 pass, 100 check failed, 1 error)")
    chk.add_argument("-c", "--config", help="check file (default: sherlock.yaml found upward from cwd)")
    chk.add_argument("--output", help="the output text (default: stdin)")
    chk.add_argument("--output-file")
    g3 = sub.add_parser("g3", help="run-again test: restore nodes in a forked run, resume from the cassette, "
                                   "apply the check (exit 0 pass, 100 check failed, 75 abstain, 1 error)")
    g3.add_argument("--thread-id", required=True, help="the recorded failed run")
    g3.add_argument("--restore", required=True, help="comma-separated nodes to restore (the candidate set)")
    g3.add_argument("--known-good", required=True, help="JSON/YAML: node -> context patch giving its good behaviour")
    g3.add_argument("-c", "--config", help="check file (default: sherlock.yaml found upward from cwd)")
    g3.add_argument("--url", default="http://127.0.0.1:2024", help="a server started with `sherlock-rec run --replay`")
    g3.add_argument("--api-key")
    g3.add_argument("--cassette", default=".sherlock/cassette.db")
    g3.add_argument("--context", help="JSON run context to start from (default: the original run's)")
    dg = sub.add_parser("diagnose", help="find every minimal set of nodes whose restoration fixes a failed run "
                                         "(exit 0 found, 75 cannot say, 1 error); writes .sherlock/diagnoses/<thread>.json. "
                                         "Interrupt (human-in-the-loop) resumes are out of scope for v1")
    dg.add_argument("--thread-id", required=True, help="the recorded failed run")
    dg.add_argument("--known-good", help="JSON/YAML: node -> context patch giving its good behaviour "
                                         "(overrides what --good-run derives, per node)")
    dg.add_argument("--known-good-output", action="append", metavar="NODE=@FILE|JSON",
                    help="a known-good behaviour pasted by hand for one node, as a JSON mapping of run-context keys "
                         "(repeatable; wins over --known-good and --good-run for that node; recorded as 'pasted')")
    dg.add_argument("--node-map", help="JSON/YAML: context item or key -> node, for behaviour not named after its node "
                                       "(e.g. a global prompt); without it such a difference abstains cannot_attribute")
    dg.add_argument("--good-run", action="append", metavar="THREAD",
                    help="a prior successful run of the same input on this server; its recorded behaviour is the "
                         "known-good source (repeatable; several are ranked, and disagreement abstains)")
    dg.add_argument("--discover-good", action="store_true",
                    help="also look for passing same-input runs of the same graph on the server (unconfirmed)")
    dg.add_argument("--suspect", action="append", metavar="NODE[->NODE]",
                    help="shortlist a node; the path check discards it unless it names a recorded arrow (repeatable)")
    dg.add_argument("-c", "--config", help="check file (default: sherlock.yaml found upward from cwd)")
    dg.add_argument("--url", default="http://127.0.0.1:2024", help="a server started with `sherlock-rec run --replay`")
    dg.add_argument("--api-key")
    dg.add_argument("--cassette", default=".sherlock/cassette.db")
    dg.add_argument("--context", help="JSON run context to start from (default: the original run's)")
    dg.add_argument("--max-trials", type=int, default=None,
                    help="hard cap on G3 trials (default: 40, or 3 per candidate + 20 when larger)")
    dg.add_argument("--g1", choices=["off", "hosted", "laya", "fake"],
                    help="optional G1 trial ordering (default off; hosted when --g1-url is given). `laya` scores each "
                         "candidate with the Laya API (key: env LAYA_API_KEY); `fake` scores by a hash of the node "
                         "name, for tests. G1 only reorders trials, never changes the answer")
    dg.add_argument("--g1-url", help="optional G1 shortlist: base URL of an OpenAI-compatible endpoint "
                                     "(e.g. https://api.openai.com/v1). The model sees redacted node summaries, has no tools, "
                                     "and can only reorder trials")
    _laya_args(dg)
    dg.add_argument("--g1-samples", type=int, default=1, help="G1 samples; more only widen the list (default 1)")
    dg.add_argument("--g1-key", help="API key for G1 (default: env SHERLOCK_G1_API_KEY, then OPENAI_API_KEY)")
    dg.add_argument("--max-minutes", type=float, default=10.0, help="hard cap on wall-clock time (default 10)")
    dg.add_argument("--max-size", type=int, default=3, help="largest set of nodes to try (default 3)")
    dg.add_argument("--out", help="artifact directory (default: the cassette's directory)")
    dg.add_argument("--progress", action="store_true",
                    help="also write each step to stderr as it happens, one JSON object per line ({\"event\": ...})")
    oc = sub.add_parser("outcomes", help="list a team's runs with pass/fail against the check (JSON); "
                                         "Sherlock's own trial forks are left out")
    oc.add_argument("--graph-id", required=True, help="the team's graph id")
    oc.add_argument("-c", "--config", help="check file (default: sherlock.yaml found upward from cwd)")
    oc.add_argument("--url", default="http://127.0.0.1:2024", help="the LangGraph server holding the runs")
    oc.add_argument("--api-key")
    oc.add_argument("--limit", type=int, default=100)
    it = sub.add_parser("intake", help="mark a run wrong (no node named), or give the output it should have had, "
                                       "or a check file; `diagnose` picks the record up")
    it.add_argument("--thread-id", required=True, help="the failed run")
    it.add_argument("--expected", help="the output the run should have produced (fails if it differs)")
    it.add_argument("--expected-file")
    it.add_argument("--check", help="a check file Z (sherlock.yaml)")
    it.add_argument("--note")
    it.add_argument("--dir", default=".sherlock", help="Sherlock directory (default .sherlock)")
    gc = sub.add_parser("g1-check", help="smoke-test a G1 Laya endpoint with the sample card (sends it twice)")
    _laya_args(gc)
    run = sub.add_parser("run", help="run a command under the recorder")
    run.add_argument("--replay", action="store_true", help="serve calls from the cassette; never go live")
    run.add_argument("--cassette", default=".sherlock/cassette.db")
    run.add_argument("--match", choices=["hash", "sequence"], default="hash")
    run.add_argument("--allow-tool", action="append", metavar="NAME",
                     help="replay: serve only these read-safe tools; any other tool aborts (repeatable)")
    run.add_argument("--max-cassette-mb", type=float, default=None, metavar="MB",
                     help="record: stop recording (with a warning; the app keeps running) once the cassette "
                          "reaches this size (default 500, or env SHERLOCK_MAX_CASSETTE_MB)")
    run.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args(argv)
    if args.verb == "check":
        return _check(args)
    if args.verb == "g3":
        return _g3(args)
    if args.verb == "diagnose":
        return _diagnose(args)
    if args.verb == "outcomes":
        return _outcomes(args)
    if args.verb == "intake":
        return _intake(args)
    if args.verb == "g1-check":
        return _g1_check(args)
    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    if not cmd:
        ap.error("run: missing command")
    cassette = Path(args.cassette).resolve()
    mode = "replay" if args.replay else "record"
    if mode == "record":
        for suffix in ("", "-wal", "-shm"):  # a fresh recording replaces the old one
            Path(f"{cassette}{suffix}").unlink(missing_ok=True)
    elif not cassette.exists():
        print(f"sherlock: cannot say: no recording at {cassette}", file=sys.stderr)
        return EXIT_ABSTAIN
    env = child_env(mode, cassette, args.match, allow_tools=args.allow_tool, max_cassette_mb=args.max_cassette_mb)
    # subprocess, not os.execl: execl on Windows detaches the child from the parent.
    code = subprocess.call(cmd, env=env)
    if mode == "replay":
        # The child may have swallowed the abort; the cassette remembers it.
        reasons = Cassette(cassette).abstains()
        if reasons:
            print(f"sherlock: {reasons[0]}", file=sys.stderr)
            return EXIT_ABSTAIN
    return code


if __name__ == "__main__":
    sys.exit(main())
