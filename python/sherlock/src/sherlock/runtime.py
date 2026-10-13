"""Per-process recorder state shared by the interceptors."""

import sys
import threading

from sherlock.cassette import Cassette, request_key


class CannotSay(Exception):
    """Replay needed something the cassette does not have: abstain, never go live.

    An Exception, not a BaseException: inside `langgraph dev` a BaseException kills the worker
    and the run hangs forever (seen live, Phase 2), whereas an Exception fails the node and the
    run. Swallowing is still caught: every abstain is stored in the cassette first, and both
    the launcher (exit 75) and G3 read it back, so user code that swallows it cannot turn an
    abort into an invented answer.
    """


class Runtime:
    def __init__(self, cassette: Cassette, mode: str, match: str = "hash", allow_tools=None):
        self.cassette = cassette
        self.mode = mode
        self.match = match
        # None: every recorded tool may be served. A list: only these read-safe tools; any other
        # tool aborts the trial (FR-G3.8). Replay never executes a tool either way.
        self.allow_tools = None if allow_tools is None else set(allow_tools)
        self.consumed: set[int] = set()
        self.trial = None
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
            trial = self.cassette.trial_id()
            if trial != self.trial:  # G3 started a new trial: recordings are available again
                self.trial, self.consumed = trial, set()
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
