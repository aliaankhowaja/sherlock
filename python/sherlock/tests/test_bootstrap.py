import os
import subprocess
import sys
import textwrap

import pytest

import sherlock.cli as cli
from sherlock import _hook


def run_child(code, tmp_path, *, user_sc=None, mode="record", extra_env=None):
    """Run `code` in a child python with the bootstrap installed, as `sherlock run` would."""
    env = cli.child_env(mode, tmp_path / "c.db", "hash")
    if user_sc is not None:
        d = tmp_path / "user"
        d.mkdir(exist_ok=True)
        (d / "sitecustomize.py").write_text(user_sc)
        env["PYTHONPATH"] += os.pathsep + str(d)
    env.update(extra_env or {})
    return subprocess.run([sys.executable, "-c", code], env=env, cwd=tmp_path, capture_output=True, text=True)


def test_chains_to_user_sitecustomize(tmp_path):
    p = run_child("import builtins;print(builtins.USER_SC_RAN)", tmp_path,
                  user_sc="import builtins; builtins.USER_SC_RAN = 'yes'")
    assert p.returncode == 0, p.stderr
    assert p.stdout.strip() == "yes"


def test_strips_its_own_path_from_pythonpath(tmp_path):
    p = run_child("import os;print(os.environ.get('PYTHONPATH',''))", tmp_path)
    assert str(cli.BOOTSTRAP_DIR) not in p.stdout.split(os.pathsep)
    assert str(cli.PKG_ROOT) in p.stdout  # only its own entry is removed


def test_bootstrap_failure_never_kills_the_process(tmp_path):
    p = run_child("print('alive')", tmp_path, mode="bogus-mode")
    assert p.returncode == 0
    assert p.stdout.strip() == "alive"
    assert "sherlock" in p.stderr.lower()


def test_user_sitecustomize_crash_does_not_kill_process(tmp_path):
    p = run_child("print('alive')", tmp_path, user_sc="raise RuntimeError('boom')")
    assert p.returncode == 0 and p.stdout.strip() == "alive"


def test_no_mode_is_a_noop(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(cli.BOOTSTRAP_DIR) + os.pathsep + str(cli.PKG_ROOT)}
    env.pop("SHERLOCK_MODE", None)
    p = subprocess.run([sys.executable, "-c", "print('ok')"], env=env, capture_output=True, text=True)
    assert p.stdout.strip() == "ok" and p.stderr == ""


def test_hook_patches_module_when_first_imported(tmp_path, monkeypatch):
    (tmp_path / "fake_lib_a.py").write_text("VALUE = 1\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    seen = []
    finder = _hook.install({"fake_lib_a": lambda m: seen.append(m.VALUE)})
    try:
        import fake_lib_a  # noqa: F401
        assert seen == [1]  # patched after the module body ran
    finally:
        sys.meta_path.remove(finder)
        sys.modules.pop("fake_lib_a", None)


def test_hook_patches_already_imported_module_immediately(monkeypatch):
    seen = []
    finder = _hook.install({"json": lambda m: seen.append(m.__name__)})
    try:
        assert seen == ["json"]
    finally:
        sys.meta_path.remove(finder)


def test_hook_patch_error_does_not_break_import(tmp_path, monkeypatch, capsys):
    (tmp_path / "fake_lib_b.py").write_text("VALUE = 2\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    def bad(m):
        raise RuntimeError("patch bug")
    finder = _hook.install({"fake_lib_b": bad})
    try:
        import fake_lib_b
        assert fake_lib_b.VALUE == 2
        assert "patch bug" in capsys.readouterr().err
    finally:
        sys.meta_path.remove(finder)
        sys.modules.pop("fake_lib_b", None)
