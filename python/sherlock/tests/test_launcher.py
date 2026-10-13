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


def test_run_prepends_bootstrap_dir_and_sets_mode(tmp_path):
    code = "import json,os;print(json.dumps({k:os.environ.get(k) for k in ('PYTHONPATH','SHERLOCK_MODE','SHERLOCK_CASSETTE')}))"
    p = run_cli("run", "--", sys.executable, "-c", code, cwd=tmp_path, env_extra={"PYTHONPATH": "/keep/me"})
    assert p.returncode == 0, p.stderr
    seen = json.loads(p.stdout.strip().splitlines()[-1])
    parts = seen["PYTHONPATH"].split(os.pathsep)
    assert Path(parts[0]) == cli.BOOTSTRAP_DIR
    assert "/keep/me" in parts
    assert seen["SHERLOCK_MODE"] == "record"
    assert Path(seen["SHERLOCK_CASSETTE"]) == tmp_path / ".sherlock" / "cassette.db"


def test_run_passes_through_exit_code(tmp_path):
    p = run_cli("run", sys.executable, "-c", "raise SystemExit(7)", cwd=tmp_path)
    assert p.returncode == 7


def test_run_without_command_is_a_usage_error(tmp_path):
    assert run_cli("run", cwd=tmp_path).returncode == 2
