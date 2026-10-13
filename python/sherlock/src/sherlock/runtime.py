"""Per-process recorder state shared by the interceptors."""

import sys

from sherlock.cassette import Cassette


class CannotSay(BaseException):
    """Replay needed something the cassette does not have: abstain, never go live.

    BaseException on purpose: SDK retry loops and user code catch Exception, and
    swallowing an abstain would let the run carry on with an invented answer.
    """


class Runtime:
    def __init__(self, cassette: Cassette, mode: str, match: str = "hash"):
        self.cassette = cassette
        self.mode = mode
        self.match = match
        self.consumed: set[int] = set()

    @property
    def replaying(self) -> bool:
        return self.mode == "replay"


def warn(what, exc):
    print(f"sherlock: {what} failed: {exc!r}; the call itself is unaffected", file=sys.stderr)
