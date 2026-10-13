import json
import os
import subprocess
import sys
from pathlib import Path

import sherlock.cli as cli


def run_cli(*args, cwd, env_extra=None):
    env = {**os.environ, **(env_extra or {})}
    return subprocess.run(
        [sys.executable, "-m", "sherlock", *args],
        cwd=cwd, env=env, capture_output=True, text=True,
    )


def test_child_env_prepends_bootstrap_dir_and_keeps_existing_path(tmp_path):
    env = cli.child_env("record", tmp_path / "c.db", "hash", base={"PYTHONPATH": "/keep/me"})
    parts = env["PYTHONPATH"].split(os.pathsep)
    assert Path(parts[0]) == cli.BOOTSTRAP_DIR and "/keep/me" in parts
    assert (cli.BOOTSTRAP_DIR / "sitecustomize.py").exists()
    assert env["SHERLOCK_MODE"] == "record" and env["SHERLOCK_MATCH"] == "hash"


def test_run_sets_mode_and_default_cassette_in_child(tmp_path):
    code = "import json,os;print(json.dumps({k:os.environ.get(k) for k in ('SHERLOCK_MODE','SHERLOCK_CASSETTE')}))"
    p = run_cli("run", "--", sys.executable, "-c", code, cwd=tmp_path)
    assert p.returncode == 0, p.stderr
    seen = json.loads(p.stdout.strip().splitlines()[-1])
    assert seen["SHERLOCK_MODE"] == "record"
    assert Path(seen["SHERLOCK_CASSETTE"]) == tmp_path / ".sherlock" / "cassette.db"


def test_run_passes_through_exit_code(tmp_path):
    p = run_cli("run", sys.executable, "-c", "raise SystemExit(7)", cwd=tmp_path)
    assert p.returncode == 7


def test_run_without_command_is_a_usage_error(tmp_path):
    assert run_cli("run", cwd=tmp_path).returncode == 2


SWALLOW = """
import httpx
try:
    httpx.get("http://127.0.0.1:9/never-recorded")
except BaseException as e:      # user code that swallows everything
    print("swallowed", type(e).__name__)
"""


def test_replay_without_a_cassette_says_cannot_say(tmp_path):
    p = run_cli("run", "--replay", sys.executable, "-c", "print('ran')", cwd=tmp_path)
    assert p.returncode == cli.EXIT_ABSTAIN
    assert "cannot say" in p.stderr and "ran" not in p.stdout


def test_replay_abstain_is_reported_even_if_user_code_swallows_it(tmp_path):
    assert run_cli("run", sys.executable, "-c", "pass", cwd=tmp_path).returncode == 0  # empty cassette
    p = run_cli("run", "--replay", sys.executable, "-c", SWALLOW, cwd=tmp_path)
    assert "swallowed CannotSay" in p.stdout
    assert p.returncode == cli.EXIT_ABSTAIN
    assert "cannot say: never recorded" in p.stderr
