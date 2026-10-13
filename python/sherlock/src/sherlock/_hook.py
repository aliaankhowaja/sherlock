"""sys.meta_path hook: run a patch function right after a module is first imported.

Order-independent, unlike eager patching: the user may import httpx before or
after the bootstrap runs (spec 4.2 step 4).
"""

import importlib.util
import sys
from importlib.abc import MetaPathFinder


def _warn(name, exc):
    print(f"sherlock: patching {name} failed: {exc!r}; continuing unpatched", file=sys.stderr)


def _apply(name, patch, module):
    try:
        patch(module)
    except Exception as exc:  # a patch bug must never break the user's import
        _warn(name, exc)


class _Loader:
    def __init__(self, loader, name, patch):
        self._loader, self._name, self._patch = loader, name, patch

    def create_module(self, spec):
        return self._loader.create_module(spec)

    def exec_module(self, module):
        self._loader.exec_module(module)
        _apply(self._name, self._patch, module)

    def __getattr__(self, attr):
        return getattr(self._loader, attr)


class PatchFinder(MetaPathFinder):
    def __init__(self, patches):
        self._patches = dict(patches)
        self._busy = set()

    def find_spec(self, name, path=None, target=None):
        if name not in self._patches or name in self._busy:
            return None
        self._busy.add(name)
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, ValueError):
            return None
        finally:
            self._busy.discard(name)
        if spec is None or spec.loader is None:
            return None
        spec.loader = _Loader(spec.loader, name, self._patches[name])
        return spec


def install(patches):
    """Install the hook; patch modules that are already imported right away."""
    finder = PatchFinder(patches)
    sys.meta_path.insert(0, finder)
    for name, patch in patches.items():
        if name in sys.modules:
            _apply(name, patch, sys.modules[name])
    return finder
