import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

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


def _alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


@pytest.mark.skipif(os.name != "nt", reason="CTRL_BREAK is the Windows stop signal")
def test_ctrl_break_on_run_also_stops_the_child(tmp_path):
    """Stopping `sherlock run` must not orphan the server it started (it sits in its own process group)."""
    pid_file = tmp_path / "child.pid"
    child = f"import os,time;open(r'{pid_file}','w').write(str(os.getpid()));time.sleep(60)"
    run = subprocess.Popen([sys.executable, "-m", "sherlock", "run", "--", sys.executable, "-c", child],
                           cwd=tmp_path, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    try:
        for _ in range(100):
            if pid_file.exists() and pid_file.read_text():
                break
            time.sleep(0.1)
        pid = int(pid_file.read_text())
        run.send_signal(signal.CTRL_BREAK_EVENT)
        run.wait(timeout=30)
        for _ in range(50):
            if not _alive(pid):
                break
            time.sleep(0.1)
        assert not _alive(pid), "the child outlived `sherlock run`"
    finally:
        pids = [str(run.pid)] + ([pid_file.read_text()] if pid_file.exists() and pid_file.read_text() else [])
        for pid in pids:  # never leave a sleeper behind, pass or fail
            subprocess.run(["taskkill", "/PID", pid, "/F", "/T"], capture_output=True)
