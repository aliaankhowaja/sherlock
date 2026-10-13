"""Per-process recorder state shared by the interceptors."""

import sys
import threading

from sherlock.cassette import Cassette, request_key


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
        self._lock = threading.Lock()

    @property
    def replaying(self) -> bool:
        return self.mode == "replay"

    def abstain(self, reason: str):
        msg = f"cannot say: {reason}"
        try:
            self.cassette.add_abstain(msg)
        except Exception as exc:
            warn("storing the abstain reason", exc)
        print(f"sherlock: {msg}", file=sys.stderr)
        raise CannotSay(msg)

    def lookup(self, kind: str, name: str, body: bytes) -> dict:
        """Replay: the recorded call for this request, or abstain. Never returns None, never goes live."""
        key = request_key(kind, name, body)
        with self._lock:
            row = self.cassette.find(kind, key, self.consumed)
            if row is None and self.match == "sequence":
                row = self.cassette.next_by_name(kind, name, self.consumed)
            if row is not None:
                self.consumed.add(row["id"])
                return row
        if self.cassette.next_by_name(kind, name, set()) is not None:
            self.abstain(f"request changed since recording: {name} (hash {key[:12]}); "
                         "replay never makes a live call")
        self.abstain(f"never recorded: {name} (hash {key[:12]}); replay never makes a live call")


def warn(what, exc):
    print(f"sherlock: {what} failed: {exc!r}; the call itself is unaffected", file=sys.stderr)
