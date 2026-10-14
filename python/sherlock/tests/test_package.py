import sherlock


def test_package_imports():
    assert sherlock.__version__


def test_console_script_does_not_clash_with_the_rust_binary():
    import tomllib
    from pathlib import Path

    scripts = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())["project"]["scripts"]
    assert "sherlock" not in scripts and scripts["sherlock-rec"] == "sherlock.cli:main"


def test_wheel_builds_with_entry_point_bootstrap_and_dependencies(tmp_path):  # NFR-21 (minimal); `uv build` in python/sherlock
    import shutil
    import subprocess
    import zipfile
    from pathlib import Path

    uv = shutil.which("uv")
    if not uv:
        import pytest

        pytest.skip("uv not on PATH")
    p = subprocess.run([uv, "build", "--wheel", "-o", str(tmp_path)], cwd=Path(__file__).parents[1],
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr
    (whl,) = tmp_path.glob("sherlock-*.whl")
    z = zipfile.ZipFile(whl)
    names = z.namelist()
    assert "sherlock/_bootstrap/sitecustomize.py" in names and "sherlock/shim_http.py" in names
    meta = z.read(next(n for n in names if n.endswith("METADATA"))).decode()
    assert "Name: sherlock" in meta and "Requires-Dist: pyyaml" in meta and "Requires-Dist: jsonschema" in meta
    assert "sherlock-rec = sherlock.cli:main" in z.read(next(n for n in names if n.endswith("entry_points.txt"))).decode()
