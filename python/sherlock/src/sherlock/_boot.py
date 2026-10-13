"""Bootstrap entry, called from the sitecustomize shim. Reads the environment set by `sherlock run`."""

import os

from sherlock import _hook, shim_httpx, shim_tools
from sherlock.cassette import Cassette
from sherlock.runtime import Runtime

MODES = ("record", "replay")


def bootstrap():
    mode = os.environ.get("SHERLOCK_MODE")
    if not mode:
        return
    if mode not in MODES:
        raise ValueError(f"SHERLOCK_MODE={mode!r}, expected one of {MODES}")
    rt = Runtime(Cassette(os.environ["SHERLOCK_CASSETTE"]), mode, os.environ.get("SHERLOCK_MATCH", "hash"))
    _hook.install({
        "httpx": lambda m: shim_httpx.patch(m, rt),
        "langchain_core.tools.base": lambda m: shim_tools.patch(m, rt),
    })
