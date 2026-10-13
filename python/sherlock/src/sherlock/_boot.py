"""Bootstrap entry, called from the sitecustomize shim. Reads the environment set by `sherlock run`."""

import os

from sherlock import _hook

MODES = ("record", "replay")


def bootstrap():
    mode = os.environ.get("SHERLOCK_MODE")
    if not mode:
        return
    if mode not in MODES:
        raise ValueError(f"SHERLOCK_MODE={mode!r}, expected one of {MODES}")
    _hook.install({})
