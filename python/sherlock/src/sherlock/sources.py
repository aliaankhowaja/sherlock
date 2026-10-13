"""Known-good sources (spec 5.6; FR-K1, K3, K4, K5): a prior successful run replaces the hand-written patch.

A source is a recorded run of the same input that passes the check Z. From it we derive:
  * the nodes whose recorded output differs from the failed run (FR-K1: only those are tested; a node
    that wrote the same thing is pruned);
  * a per-node behaviour patch: the difference between the two runs' recorded run `context`, with each
    difference attributed to a node by name (FR-K5, the context path of spec 4.4). A difference that
    cannot be attributed to a node is reported, never guessed.

Pure logic over histories and contexts; the HTTP fetching is in `diagnose.py`.
Picker rule (FR-K3, open item 5): eligible sources are ranked by fewest differing nodes (the closest
success), then newest. Disagreement between eligible sources is an abstain (FR-K4).
"""

from dataclasses import dataclass, field

from sherlock.checks import Checks, evaluate
from sherlock.search import _supersteps

SEPARATORS = (".", ":", "/", "_", "-")


def run_input(history: list[dict]):
    """The input the run started with: the `__start__` task's write."""
    for snap in reversed(history):
        for t in snap.get("tasks") or []:
            if t["name"] == "__start__":
                return t.get("result")
    return None


def node_outputs(history: list[dict]) -> dict[str, list]:
    """Every write each node made, in order (a node that loops appears more than once)."""
    out: dict[str, list] = {}
    for step in _supersteps(history):
        for t in step:
            out.setdefault(t["name"], []).append(t.get("result"))
    return out


def _owner(item, nodes: list[str]) -> str | None:
    """The node a context item belongs to: its name, or a name followed by a separator (longest wins)."""
    if not isinstance(item, str):
        return None
    hits = [n for n in nodes if item == n or any(item.startswith(n + s) for s in SEPARATORS)]
    return max(hits, key=len) if hits else None


def derive_known_good(failed: dict | None, good: dict | None, nodes: list[str]) -> tuple[dict, list[str]]:
    """Per-node context patches turning the failed run's behaviour into the good run's.

    Returns (known_good, unattributed). Every node in `nodes` gets an entry; an empty patch means its
    recorded behaviour already equals the good run's. List-valued keys are compared item by item
    (`$remove` / `$add`); other keys are replaced by the good value. Items or keys that no node name
    claims, or that the good run lacks, are returned in `unattributed`.
    """
    failed, good = failed or {}, good or {}
    known = {n: {} for n in nodes}
    unattributed: list[str] = []
    for key in sorted(set(failed) | set(good)):
        f, g = failed.get(key), good.get(key)
        if f == g:
            continue
        if isinstance(f, list | type(None)) and isinstance(g, list | type(None)):
            f, g = f or [], g or []
            for kind, items in (("$remove", [x for x in f if x not in g]), ("$add", [x for x in g if x not in f])):
                for item in items:
                    node = _owner(item, nodes)
                    if node is None:
                        unattributed.append(f"{key}: {item!r}")
                    else:
                        known[node].setdefault(key, {}).setdefault(kind, []).append(item)
        else:
            node = _owner(key, nodes)
            if node is None or key not in good:
                unattributed.append(key)
            else:
                known[node][key] = g
    return known, unattributed


@dataclass
class Source:
    """A candidate known-good source and what comparing it with the failed run showed."""
    thread_id: str
    confirmed: bool  # named by the engineer (True) or found by --discover-good (False)
    eligible: bool = False
    why: str = ""  # why it is not eligible, or a one-line summary when it is
    created_at: str = ""
    differing: list[str] = field(default_factory=list)
    same_output: list[str] = field(default_factory=list)
    known_good: dict = field(default_factory=dict)
    unattributed: list[str] = field(default_factory=list)
    context: dict | None = None

    def to_dict(self):
        return {"kind": "run", "thread_id": self.thread_id, "confirmed": self.confirmed, "eligible": self.eligible,
                "why": self.why, "created_at": self.created_at, "differing_nodes": self.differing,
                "same_output_nodes": self.same_output, "unattributed": self.unattributed,
                "context_diff": {n: p for n, p in self.known_good.items() if p}}


def assess(thread_id: str, confirmed: bool, failed_history: list[dict], failed_context: dict | None,
           good_history: list[dict], good_context: dict | None, checks: Checks) -> Source:
    """Decide whether `thread_id` is a usable known-good source for the failed run, and derive from it."""
    src = Source(thread_id, confirmed, created_at=str((good_history[0].get("created_at") if good_history else "") or ""))
    if not good_history or not any(t.get("result") is not None for s in good_history for t in s.get("tasks") or []):
        src.why = "it has no usable checkpoint history"
        return src
    if run_input(good_history) != run_input(failed_history):
        src.why = "it ran on a different input (a known-good source must be the same input, FR-K1)"
        return src
    out = (good_history[0].get("values") or {}).get(checks.output_key)
    report = evaluate(checks.assertions, out if out is not None else "", checks.base_dir)
    if not report.passed:
        src.why = "it does not pass the check, so it is not a success"
        return src
    nodes = [n for n in node_outputs(failed_history)]
    failed_out, good_out = node_outputs(failed_history), node_outputs(good_history)
    src.differing = [n for n in nodes if failed_out[n] != good_out.get(n)]
    src.same_output = [n for n in nodes if n not in src.differing]
    src.known_good, src.unattributed = derive_known_good(failed_context, good_context, nodes)
    src.context = good_context
    src.eligible = True
    src.why = f"passes the check on the same input; {len(src.differing)} node(s) wrote something different"
    return src


def rank(sources: list[Source]) -> list[Source]:
    """The picker rule: eligible sources only; fewest differing nodes first, then newest."""
    ok = [s for s in sources if s.eligible]
    ok.sort(key=lambda s: s.created_at, reverse=True)
    ok.sort(key=lambda s: len(s.differing))
    return ok
