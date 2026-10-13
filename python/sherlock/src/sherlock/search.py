"""Minimality search and verdicts (spec 5.5; FR-D1-D9, D11).

Pure logic: no server, no I/O. `plan_candidates` prunes the nodes on the recorded path;
`search` drives a G3 oracle over subsets of the candidates and returns EVERY 1-minimal set
(S passes Z and no proper subset does), or an honest abstain.

Cutoff for the 2^k subset space (FR-D9, open item 2): sets of at most `Budget.max_size` nodes
(default 3), at most `max_trials` G3 trials (default 40) and `max_minutes` (default 10), whichever
comes first. Each set is tried at most once; supersets of a passing set are never tried.
"""

import time
from dataclasses import dataclass, field
from itertools import combinations

from sherlock.g3 import apply_restore

LABELS = ("fixes", "partly_helps", "does_not_help", "cannot_say")  # FR-D6
LIMITATION = "we recover ancestry, not read-dependencies; the dependency graph is conservative (spec 9.2)"


@dataclass
class Budget:
    max_trials: int = 40
    max_minutes: float = 10.0
    max_size: int = 3  # the subset cutoff (FR-D9)


# --- pruning (FR-D1, D2) -----------------------------------------------------------------------------

@dataclass
class Pruning:
    on_path: list[str]
    candidates: list[str]
    pruned: dict[str, str]  # node -> why it cannot be the cause
    untestable: list[str]  # nodes with no known-good behaviour: kept out of the search, never ruled out

    @property
    def exhaustive_trials(self) -> int:
        return 2 ** len(self.on_path) - 1

    @property
    def search_space(self) -> int:
        return 2 ** len(self.candidates) - 1

    def to_dict(self):
        return {"nodes_on_path": self.on_path, "candidates": self.candidates, "pruned": self.pruned,
                "untestable": self.untestable, "exhaustive_trials": self.exhaustive_trials,
                "search_space": self.search_space, "limitation": LIMITATION}


def _supersteps(history: list[dict]) -> list[list[dict]]:
    """Tasks that ran, per superstep in order (history is newest first). Internal `__` nodes skipped."""
    steps = []
    for snap in reversed(history):
        tasks = [t for t in snap.get("tasks") or [] if not t["name"].startswith("__")]
        if tasks:
            steps.append(tasks)
    return steps


def plan_candidates(history: list[dict], known_good: dict, context: dict | None, output_key: str) -> Pruning:
    """Conservative pruning from the recorded path.

    1. Ancestry: only nodes in a superstep up to the last writer of `output_key` can reach it, and in
       that superstep only the writers themselves (parallel nodes are independent). Nodes are
       over-included, never dropped, when ordering says "maybe" (FR-D2).
    2. No-op restores: a node whose known-good patch leaves the run context unchanged would replay the
       original, so it can neither be a cause nor part of a minimal set.
    Nodes with no known-good behaviour are `untestable`, not pruned.
    """
    steps = _supersteps(history)
    on_path = list(dict.fromkeys(t["name"] for step in steps for t in step))
    writer_step = max((i for i, step in enumerate(steps)
                       if any(output_key in (t.get("result") or {}) for t in step)), default=None)
    pruned, candidates, untestable = {}, [], []
    base = context or {}
    for i, step in enumerate(steps):
        for task in step:
            node = task["name"]
            if node in pruned or node in candidates or node in untestable:
                continue
            if writer_step is not None and i > writer_step:
                pruned[node] = f"runs after the last write of `{output_key}`, so it cannot reach the output"
            elif writer_step is not None and i == writer_step and output_key not in (task.get("result") or {}):
                pruned[node] = f"runs in parallel with the node that writes `{output_key}`; it cannot feed it"
            elif node not in known_good:
                untestable.append(node)
            elif apply_restore(context, known_good, [node]) == base:
                pruned[node] = "restoring it changes nothing (its known-good behaviour is already in the run)"
            else:
                candidates.append(node)
    return Pruning(on_path, candidates, pruned, untestable)


# --- verdict labels ------------------------------------------------------------------------------------

def score_of(check: dict | None) -> float | None:
    results = (check or {}).get("results") or []
    return sum(r["score"] for r in results) / len(results) if results else None


def label_of(verdict, original_score: float | None) -> str:
    """FR-D6: fixes it / partly helps / doesn't help / cannot say."""
    if verdict.verdict == "pass":
        return "fixes"
    if verdict.verdict == "abstain":
        return "cannot_say"
    score = score_of(verdict.check)
    return "partly_helps" if None not in (score, original_score) and score > original_score else "does_not_help"


# --- the search ----------------------------------------------------------------------------------------

class _Exhausted(Exception):
    pass


@dataclass
class SearchResult:
    status: str  # "found" | "abstain"
    reason_code: str
    reason: str
    minimal_sets: list[list[str]] = field(default_factory=list)
    unverified_sets: list[list[str]] = field(default_factory=list)  # pass, but a proper subset could not be tested
    complete: bool = False
    notes: list[str] = field(default_factory=list)
    trials: list[dict] = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    budget: dict = field(default_factory=dict)

    def to_dict(self):
        return {"status": self.status, "reason_code": self.reason_code, "reason": self.reason,
                "minimal_sets": self.minimal_sets, "unverified_sets": self.unverified_sets,
                "complete": self.complete, "notes": self.notes, "counts": self.counts,
                "budget": self.budget, "trials": self.trials}


def search(candidates: list[str], oracle, original_score: float | None, budget: Budget,
           clock=time.monotonic, untestable=()) -> SearchResult:
    """Find every 1-minimal set among `candidates`. `oracle(restore_list) -> g3.Verdict`."""
    order = list(candidates)
    t0 = clock()
    cache: dict[frozenset, tuple[dict, object]] = {}
    exhausted: list[str] = []

    def trial(subset) -> dict:
        key = frozenset(subset)
        if key not in cache:
            if len(cache) >= budget.max_trials:
                raise _Exhausted(f"the trial budget of {budget.max_trials} was used up")
            if clock() - t0 > budget.max_minutes * 60:
                raise _Exhausted(f"the time budget of {budget.max_minutes:g} minute(s) was used up")
            restored = sorted(key, key=order.index)
            v = oracle(restored)
            cache[key] = ({"restored": restored, "verdict": v.verdict, "label": label_of(v, original_score),
                           "score": score_of(v.check), "reason": v.reason, "fork_node": v.fork_node,
                           "fork_thread": v.fork_thread, "check": v.check,
                           "cassette_miss": bool(v.evidence.get("cassette_miss"))}, v)
        return cache[key][0]

    minimal: list[frozenset] = []
    unverified: list[frozenset] = []
    m = len(order)
    full_failed = False
    try:
        if m > 1:  # feasibility probe: if restoring everything fails, no subset can pass
            full_failed = trial(order)["verdict"] == "fail"
        if not full_failed:
            for k in range(1, min(budget.max_size, m) + 1):
                for subset in combinations(order, k):
                    key = frozenset(subset)
                    if any(found <= key for found in minimal + unverified):
                        continue
                    if trial(subset)["verdict"] == "pass":
                        below = [s for s, (rec, _) in cache.items() if s < key and rec["verdict"] == "abstain"]
                        (unverified if below else minimal).append(key)
    except _Exhausted as exc:
        exhausted.append(str(exc))

    def as_lists(sets):
        return [sorted(s, key=order.index) for s in sets]

    records = [rec for rec, _ in cache.values()]
    counts = {name: sum(r["label"] == name for r in records) for name in LABELS} | {"total": len(records)}
    notes = []
    if exhausted:
        notes.append(f"search stopped early: {exhausted[0]}; sets may be missing")
    if m > budget.max_size and not exhausted:
        notes.append(f"sets larger than {budget.max_size} nodes were not tried (raise --max-size)")
    if untestable:
        notes.append(f"no known-good behaviour for {', '.join(untestable)}, so they could not be ruled out")
    misses = [r for r in records if r["verdict"] == "abstain"]
    if misses:
        notes.append(f"{len(misses)} set(s) could not be tested: {misses[0]['reason']}")
    # complete: every set up to the size of the candidates was decided, nothing was untestable or unknown
    complete = not exhausted and not misses and not untestable and (full_failed or m <= budget.max_size)
    spent = {"max_trials": budget.max_trials, "max_minutes": budget.max_minutes, "max_size": budget.max_size,
             "trials_used": len(records), "elapsed_s": round(clock() - t0, 3)}
    base = dict(minimal_sets=as_lists(minimal), unverified_sets=as_lists(unverified), notes=notes,
                trials=records, counts=counts, budget=spent)

    if minimal:
        names = " and ".join("{" + ", ".join(s) + "}" for s in base["minimal_sets"])
        return SearchResult("found", "ok", f"minimal set(s) of nodes whose restoration fixes the run: {names}",
                            complete=complete, **base)
    if exhausted:
        code, why = "budget_exhausted", f"{exhausted[0]} before any minimal set was confirmed"
    elif misses:
        code = "unrecorded_call" if any(r["cassette_miss"] for r in misses) else "cannot_test"
        why = f"{len(misses)} candidate set(s) could not be tested honestly: {misses[0]['reason']}"
        if unverified:
            why += f"; {{{', '.join(base['unverified_sets'][0])}}} passes but is not confirmed minimal"
    elif untestable:
        code, why = "no_known_good", (f"no known-good behaviour for {', '.join(untestable)}, "
                                      "so they could not be ruled out as the cause")
    elif m == 0:
        code, why = "no_candidates", "no node on the recorded path can be restored to a different behaviour"
    elif not full_failed and m > budget.max_size:
        code, why = "cutoff", (f"restoring all {m} candidates fixes the run but no set of at most "
                               f"{budget.max_size} nodes does (raise --max-size)")
    else:
        code, why = "not_fixable", f"restoring the candidates ({', '.join(order)}) does not fix the run"
    return SearchResult("abstain", code, why, complete=False, **base)
