"""`sherlock-rec run <cmd>`: launch a command with the recorder bootstrapped (spec 4.2)."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from sherlock.cassette import Cassette

PKG_DIR = Path(__file__).resolve().parent
BOOTSTRAP_DIR = PKG_DIR / "_bootstrap"
PKG_ROOT = PKG_DIR.parent
EXIT_ABSTAIN = 75  # EX_TEMPFAIL: "cannot say"  # makes `import sherlock` work in a child on another interpreter


def child_env(mode: str, cassette: Path, match: str, base: dict | None = None) -> dict:
    env = dict(os.environ if base is None else base)
    old = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join(
        [str(BOOTSTRAP_DIR), str(PKG_ROOT), *([old] if old else [])]
    )
    env["SHERLOCK_MODE"] = mode
    env["SHERLOCK_CASSETTE"] = str(cassette)
    env["SHERLOCK_MATCH"] = match
    return env


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sherlock-rec")
    sub = ap.add_subparsers(dest="verb", required=True)
    run = sub.add_parser("run", help="run a command under the recorder")
    run.add_argument("--replay", action="store_true", help="serve calls from the cassette; never go live")
    run.add_argument("--cassette", default=".sherlock/cassette.db")
    run.add_argument("--match", choices=["hash", "sequence"], default="hash")
    run.add_argument("cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args(argv)
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
    env = child_env(mode, cassette, args.match)
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
