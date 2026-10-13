import sherlock


def test_package_imports():
    assert sherlock.__version__


def test_console_script_does_not_clash_with_the_rust_binary():
    import tomllib
    from pathlib import Path

    scripts = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())["project"]["scripts"]
    assert "sherlock" not in scripts and scripts["sherlock-rec"] == "sherlock.cli:main"
