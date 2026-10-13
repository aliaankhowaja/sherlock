"""`sherlock run <cmd>`: launch a command with the recorder bootstrapped (spec 4.2)."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
BOOTSTRAP_DIR = PKG_DIR / "_bootstrap"
PKG_ROOT = PKG_DIR.parent  # makes `import sherlock` work in a child on another interpreter


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
    ap = argparse.ArgumentParser(prog="sherlock")
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
    env = child_env(mode, cassette, args.match)
    # subprocess, not os.execl: execl on Windows detaches the child from the parent.
    return subprocess.call(cmd, env=env)


if __name__ == "__main__":
    sys.exit(main())
