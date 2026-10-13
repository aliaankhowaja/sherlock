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
