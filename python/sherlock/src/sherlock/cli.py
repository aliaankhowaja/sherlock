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


def child_env(mode: str, cassette: Path, match: str, base: dict | None = None, allow_tools=None) -> dict:
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
    if allow_tools is not None:
        env["SHERLOCK_ALLOW_TOOLS"] = ",".join(allow_tools)
    return env


EXIT_FAIL = 1
EXIT_ERROR = 2


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
        node_map = load_node_map(args.node_map) if args.node_map else None
        result = diagnose(Client(args.url, args.api_key), args.thread_id, known_good, checks, args.cassette,
                          Budget(args.max_trials, args.max_minutes, args.max_size), context,
                          good_runs=args.good_run or [], discover_good=args.discover_good,
                          suspects=args.suspect or [], intake=record, node_map=node_map,
                          progress=jsonl_progress(sys.stderr) if args.progress else None)
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sherlock-rec")
    sub = ap.add_subparsers(dest="verb", required=True)
    chk = sub.add_parser("check", help="score an output against sherlock.yaml (exit 0 pass, 1 fail, 2 error)")
    chk.add_argument("-c", "--config", help="check file (default: sherlock.yaml found upward from cwd)")
    chk.add_argument("--output", help="the output text (default: stdin)")
    chk.add_argument("--output-file")
    g3 = sub.add_parser("g3", help="run-again test: restore nodes in a forked run, resume from the cassette, "
                                   "apply the check (exit 0 pass, 1 fail, 75 abstain, 2 error)")
    g3.add_argument("--thread-id", required=True, help="the recorded failed run")
    g3.add_argument("--restore", required=True, help="comma-separated nodes to restore (the candidate set)")
    g3.add_argument("--known-good", required=True, help="JSON/YAML: node -> context patch giving its good behaviour")
    g3.add_argument("-c", "--config", help="check file (default: sherlock.yaml found upward from cwd)")
    g3.add_argument("--url", default="http://127.0.0.1:2024", help="a server started with `sherlock-rec run --replay`")
    g3.add_argument("--api-key")
    g3.add_argument("--cassette", default=".sherlock/cassette.db")
    g3.add_argument("--context", help="JSON run context to start from (default: the original run's)")
    dg = sub.add_parser("diagnose", help="find every minimal set of nodes whose restoration fixes a failed run "
                                         "(exit 0 found, 75 cannot say, 2 error); writes .sherlock/diagnoses/<thread>.json")
    dg.add_argument("--thread-id", required=True, help="the recorded failed run")
    dg.add_argument("--known-good", help="JSON/YAML: node -> context patch giving its good behaviour "
                                         "(overrides what --good-run derives, per node)")
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
    dg.add_argument("--max-trials", type=int, default=40, help="hard cap on G3 trials (default 40)")
    dg.add_argument("--max-minutes", type=float, default=10.0, help="hard cap on wall-clock time (default 10)")
    dg.add_argument("--max-size", type=int, default=3, help="largest set of nodes to try (default 3)")
    dg.add_argument("--out", help="artifact directory (default: the cassette's directory)")
    dg.add_argument("--progress", action="store_true",
                    help="also write each step to stderr as it happens, one JSON object per line ({\"event\": ...})")
    it = sub.add_parser("intake", help="mark a run wrong (no node named), or give the output it should have had, "
                                       "or a check file; `diagnose` picks the record up")
    it.add_argument("--thread-id", required=True, help="the failed run")
    it.add_argument("--expected", help="the output the run should have produced (fails if it differs)")
    it.add_argument("--expected-file")
    it.add_argument("--check", help="a check file Z (sherlock.yaml)")
    it.add_argument("--note")
    it.add_argument("--dir", default=".sherlock", help="Sherlock directory (default .sherlock)")
    run = sub.add_parser("run", help="run a command under the recorder")
    run.add_argument("--replay", action="store_true", help="serve calls from the cassette; never go live")
    run.add_argument("--cassette", default=".sherlock/cassette.db")
    run.add_argument("--match", choices=["hash", "sequence"], default="hash")
    run.add_argument("--allow-tool", action="append", metavar="NAME",
                     help="replay: serve only these read-safe tools; any other tool aborts (repeatable)")
    run.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args(argv)
    if args.verb == "check":
        return _check(args)
    if args.verb == "g3":
        return _g3(args)
    if args.verb == "diagnose":
        return _diagnose(args)
    if args.verb == "intake":
        return _intake(args)
    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    if not cmd:
        ap.error("run: missing command")
    cassette = Path(args.cassette).resolve()
    mode = "replay" if args.replay else "record"
    if mode == "record":
        cassette.unlink(missing_ok=True)  # a fresh recording replaces the old one
    elif not cassette.exists():
        print(f"sherlock: cannot say: no recording at {cassette}", file=sys.stderr)
        return EXIT_ABSTAIN
    env = child_env(mode, cassette, args.match, allow_tools=args.allow_tool)
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
