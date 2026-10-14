"""Bootstrap entry, called from the sitecustomize shim. Reads the environment set by `sherlock-rec run`."""

import os
import sys

from sherlock import _hook, shim_http, shim_httpx, shim_tools
from sherlock.cassette import Cassette
from sherlock.runtime import Runtime

MODES = ("record", "replay")


def bootstrap():
    mode = os.environ.get("SHERLOCK_MODE")
    if not mode:
        return
    if mode not in MODES:
        raise ValueError(f"SHERLOCK_MODE={mode!r}, expected one of {MODES}")
    allow = os.environ.get("SHERLOCK_ALLOW_TOOLS")
    rt = Runtime(Cassette(os.environ["SHERLOCK_CASSETTE"]), mode, os.environ.get("SHERLOCK_MATCH", "hash"),
                 None if allow is None else [t.strip() for t in allow.split(",") if t.strip()])
    if rt.replaying:
        rt.cassette.mark_replay(os.getpid())

    def guarded(patch):
        def apply(module):
            try:
                patch(module, rt)
            except Exception as exc:
                if rt.replaying:  # an unpatched transport would go live (NFR-3)
                    print(f"sherlock: cannot say: replay patch failed ({exc!r})", file=sys.stderr)
                    os._exit(75)
                raise
        return apply

    _hook.install({
        "httpx": guarded(shim_httpx.patch),
        "langchain_core.tools.base": guarded(shim_tools.patch),
        "requests.adapters": guarded(shim_http.patch_requests),
        "urllib.request": guarded(shim_http.patch_urllib),
    })
