"""Sherlock bootstrap, imported by Python's `site` at interpreter startup.

Stdlib only until the final step. Everything is wrapped: an exception here
must never kill the user's process (spec 9.3).
"""

import os
import sys


def _chain_user_sitecustomize(own_dir):
    import importlib.machinery
    import importlib.util

    others = [p for p in sys.path if os.path.abspath(p or ".") != own_dir]
    spec = importlib.machinery.PathFinder.find_spec("sitecustomize", others)
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)


def _strip_own_path(own_dir):
    parts = os.environ.get("PYTHONPATH", "").split(os.pathsep)
    kept = [p for p in parts if p and os.path.abspath(p) != own_dir]
    if kept:
        os.environ["PYTHONPATH"] = os.pathsep.join(kept)
    else:
        os.environ.pop("PYTHONPATH", None)


def _main():
    own_dir = os.path.dirname(os.path.abspath(__file__))
    try:
        _chain_user_sitecustomize(own_dir)
    except Exception as exc:
        print(f"sherlock: user sitecustomize failed: {exc!r}", file=sys.stderr)
    try:
        _strip_own_path(own_dir)
        from sherlock import _boot

        _boot.bootstrap()
    except Exception as exc:
        print(f"sherlock: bootstrap failed, running unrecorded: {exc!r}", file=sys.stderr)


_main()
