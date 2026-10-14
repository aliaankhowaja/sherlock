"""`sherlock-rec diagnose`: find every 1-minimal set of nodes whose restoration fixes a failed run.

Composes G0 clues and the G2 path check (clues.py), known-good sources (sources.py), pruning and
search (search.py) over the G3 trial primitive (g3.py). Writes a JSON artifact for the UI to
`.sherlock/diagnoses/<thread_id>.json`. No live calls, ever: every trial is served from the cassette
or abstains (NFR-3).
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from sherlock.cassette import Cassette
from sherlock.checks import Checks, evaluate
from sherlock.clues import differs_clues, history_clues, order_candidates, path_check, tool_call_clues
from sherlock.g3 import G3Error, history_usable, run_g3
from sherlock.search import LIMITATION, Budget, Pruning, SearchResult, _supersteps, plan_candidates, score_of, search
from sherlock.sources import Source, assess, rank

# Schema 1 stays; Phase 4 only adds fields: clues, path_check, known_good_source, sources_considered,
# other_sources, intake, trials[].n/elapsed_s, pruning.pruned_ratio/widened.
SCHEMA = 1
MAX_SOURCES = 3  # prior successes searched and compared (FR-K4); each gets the full trial budget
DISCOVER_CAP = 10
LIMITATIONS = [
    LIMITATION,
    "restoration goes through the run context only (spec 4.4, secondary path); a node whose behaviour "
    "is not configurable through context cannot be restored",
    "trials are served only from the recorded cassette; a set that needs a call that was never recorded "
    "is reported as 'cannot say', never guessed",
    "clues (G0) are weaker than a G3 trial: they order the search and may widen it, they never decide",
]
NEW_FIELDS = {"clues": [], "path_check": None, "known_good_source": None, "sources_considered": [],
              "other_sources": [], "intake": None}


def _early(thread_id, code, reason, check=None, **extra) -> dict:
    """An abstain decided before any trial."""
    empty = Pruning(list(extra.pop("on_path", [])), [], {}, [])  # the path is shown, nothing is claimed about it
    return {"schema": SCHEMA, "thread_id": thread_id, "status": "abstain", "reason_code": code, "reason": reason,
            "minimal_sets": [], "unverified_sets": [], "complete": False, "notes": [],
            "counts": {"fixes": 0, "partly_helps": 0, "does_not_help": 0, "cannot_say": 0, "total": 0},
            "budget": {}, "trials": [], "check": check, "pruning": empty.to_dict(),
            "trial_reduction": None, "limitations": LIMITATIONS, **{**NEW_FIELDS, **extra}}


def _context_of(client, thread_id, history):
    run_id = (history[0].get("metadata") or {}).get("run_id")
    run = client.request("GET", f"/threads/{thread_id}/runs/{run_id}") if run_id else None
    return ((run or {}).get("kwargs") or {}).get("context") or {}


def _tool_clues(cassette_path):
    cassette = Cassette(cassette_path)
    return tool_call_clues(cassette.calls(), cassette.chunks)


def _gather_sources(client, thread_id, graph_id, history, context, checks, good_runs, discover,
                    owners=None) -> list[Source]:
    """Assess every named prior run (confirmed by the engineer) and, if asked, same-graph runs found on the server."""
    wanted = [(g, True) for g in dict.fromkeys(good_runs) if g != thread_id]
    if discover:
        found = client.request("POST", "/threads/search", {"metadata": {"graph_id": graph_id}, "limit": 50}) or []
        known = {g for g, _ in wanted} | {thread_id}
        # Sherlock's own trial forks are never sources (they carry `sherlock_fork_of`).
        own = [t for t in found if t["thread_id"] not in known and "sherlock_fork_of" not in (t.get("metadata") or {})]
        wanted += [(t["thread_id"], False) for t in own][:DISCOVER_CAP]
    sources = []
    for gid, confirmed in wanted:
        try:
            good_history = client.request("POST", f"/threads/{gid}/history", {"limit": 1000})
        except G3Error as exc:
            sources.append(Source(gid, confirmed, why=f"cannot be read: {exc}"))
            continue
        sources.append(assess(gid, confirmed, history, context, good_history,
                              _context_of(client, gid, good_history) if good_history else None, checks, owners))
    return sources


def _no_source_reason(sources):
    if not sources:
        return ("no known-good source: pass --good-run THREAD (a prior successful run of the same input), "
                "--known-good FILE, or --discover-good")
    return "no usable known-good run: " + "; ".join(f"{s.thread_id} {s.why}" for s in sources)


def _unit(client, thread_id, history, context, checks, cassette_path, budget, clock, original, clues, kg,
          source, path, suspects, emit=lambda _event: None):
    """One search with one known-good source. Returns (result dict, pruning, clues shown)."""
    unit_clues = clues + (differs_clues(source.differing, source.same_output, source.thread_id) if source else [])
    widen = {c.node for c in unit_clues if c.widens and c.node}
    pruning = plan_candidates(history, kg, context, checks.output_key,
                              set(source.same_output) if source else set(), widen)
    notes = []
    if suspects:
        allowed = set(path.kept) | (widen & set(pruning.candidates))
        for n in pruning.candidates:
            if n not in allowed:
                pruning.pruned[n] = "not on the shortlist and no widening clue (FR-G0.5)"
        pruning.candidates = [n for n in pruning.candidates if n in allowed]
        notes.append("the search was limited to the suspects and the nodes a G0 clue widened it with")
    candidates = order_candidates(pruning.candidates, unit_clues)
    pruning.candidates = candidates
    emit({"event": "plan", "source": source.thread_id if source else None, "candidates": candidates,
          "pruned": dict(pruning.pruned), "exhaustive_trials": pruning.exhaustive_trials,
          "max_trials": budget.max_trials, "max_size": budget.max_size})
    if source and source.unattributed:
        result = SearchResult(
            "abstain", "cannot_attribute",
            f"the passing run {source.thread_id} differs in {', '.join(source.unattributed)}, which no node name "
            "claims, so Sherlock cannot tell which node's behaviour to restore (name context items after their "
            "node, e.g. `writer.template`, or pass --node-map or --known-good)", notes=notes).to_dict()
    else:
        result = search(candidates,
                        lambda restore: run_g3(client, thread_id, restore, kg, checks, cassette_path, context,
                                               progress=emit),
                        score_of(original), budget, clock, pruning.untestable, progress=emit).to_dict()
        if suspects:
            result["complete"] = False
        if source and result["reason_code"] == "no_candidates":
            result["reason"] += (f"; the passing run {source.thread_id} used the same node configuration or wrote "
                                 "the same outputs, so the difference is not something Sherlock can restore")
        result["notes"] = notes + result["notes"]
    return result, pruning, unit_clues


def diagnose(client, thread_id: str, known_good: dict | None, checks: Checks | None, cassette_path: Path | str,
             budget: Budget | None = None, context: dict | None = None, clock=time.monotonic, *,
             good_runs=(), discover_good: bool = False, suspects=(), intake: dict | None = None,
             node_map: dict[str, str] | None = None, progress=None) -> dict:
    """Run the whole diagnosis and return the result artifact (a JSON-able dict).

    Known-good comes from `known_good` (a hand-written per-node context patch), from prior successful runs
    (`good_runs`, or found with `discover_good`), or both (the file overrides the derived patch per node).
    `node_map` says which node a run-context item or key configures when its name does not (a global
    prompt, an unprefixed flag); without an entry such a difference still abstains `cannot_attribute`.
    `suspects` is an optional shortlist that the G2 path check must accept. `checks` None means the run was
    marked wrong with no check yet: the result is the G0 clues and an abstain.

    `progress(event)` (optional) hears each step as it happens: `start`, `check`, `sources`, `plan`, then per trial
    `trial_start`, `fork`, `resume`, `trial`, and always a final `done` (the event list is in agents.md).
    """
    emit = progress or (lambda _event: None)
    result = _diagnose(client, thread_id, known_good, checks, cassette_path, budget, context, clock, good_runs,
                       discover_good, suspects, intake, node_map, emit)
    emit({"event": "done", "status": result["status"], "reason_code": result.get("reason_code"),
          "reason": result.get("reason"), "minimal_sets": result.get("minimal_sets", []),
          "trials_used": (result.get("budget") or {}).get("trials_used", 0)})
    return result


def _diagnose(client, thread_id, known_good, checks, cassette_path, budget, context, clock, good_runs,
              discover_good, suspects, intake, node_map, emit) -> dict:
    budget = budget or Budget()
    cassette_path = Path(cassette_path)
    known_good = known_good or {}
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if checks is not None and Cassette(cassette_path).replay_sessions() == 0:
        raise G3Error("no replay session on this cassette: start the server with "
                      "`sherlock-rec run --replay <server command>` first; diagnose never runs against a "
                      "server that could make live calls")
    thread = client.request("GET", f"/threads/{thread_id}")
    history = client.request("POST", f"/threads/{thread_id}/history", {"limit": 1000})
    problem = history_usable(history)
    if problem:
        return _early(thread_id, "no_history", problem, created=created, intake=intake)
    clues = history_clues(history, checks.output_key if checks else "final_output") + _tool_clues(cassette_path)
    on_path = list(dict.fromkeys(t["name"] for step in _supersteps(history) for t in step))
    shown = [c.to_dict() for c in clues]
    emit({"event": "start", "thread_id": thread_id, "graph_id": (thread.get("metadata") or {}).get("graph_id"),
          "nodes_on_path": on_path, "clues": len(shown)})
    if checks is None:
        return _early(thread_id, "no_check",
                      "the run is marked wrong, but there is no check Z to say what right looks like; the clues are "
                      "not a verdict. Add a check (-c sherlock.yaml, or `intake --expected`) and a known-good run "
                      "to get one", created=created, intake=intake, clues=shown, on_path=on_path)
    report = evaluate(checks.assertions, (history[0]["values"] or {}).get(checks.output_key) or "", checks.base_dir)
    original = report.to_dict()
    emit({"event": "check", "pass": report.passed,
          "failed": [r["reason"] for r in original.get("results", []) if not r.get("pass")]})
    if report.passed:
        return _early(thread_id, "already_passes", "the original run already passes the check; "
                      "there is nothing to diagnose", check=original, created=created, intake=intake, clues=shown, on_path=on_path)
    if context is None:
        context = _context_of(client, thread_id, history)
    graph_id = (thread.get("metadata") or {}).get("graph_id")

    sources = (_gather_sources(client, thread_id, graph_id, history, context, checks, good_runs, discover_good, node_map)
               if (good_runs or discover_good) else [])
    early = dict(created=created, intake=intake, clues=shown, on_path=on_path, sources_considered=[s.to_dict() for s in sources])
    if sources:
        emit({"event": "sources", "sources": [{"thread_id": s.thread_id, "eligible": s.eligible, "why": s.why,
                                               "differing_nodes": s.differing} for s in sources]})
    path = path_check(history, checks.output_key, list(suspects)) if suspects else None
    if path:
        early["path_check"] = path.to_dict()
    ranked = rank(sources)[:MAX_SOURCES]
    if not ranked and not known_good:
        return _early(thread_id, "no_known_good", _no_source_reason(sources), check=original, **early)
    if path is not None and not path.kept and not any(c.widens and c.node for c in clues):
        reasons = "; ".join(f"{k}: {v}" for k, v in path.rejected.items())
        return _early(thread_id, "path_check_failed",
                      f"no suspect names a recorded arrow ({reasons}), so there is nothing to test",
                      check=original, **early)

    units = [(s, {**s.known_good, **known_good}) for s in ranked] or [(None, known_good)]
    outcomes = [(source, *_unit(client, thread_id, history, context, checks, cassette_path, budget, clock, original,
                                clues, kg, source, path, list(suspects), emit)) for source, kg in units]

    found = [o for o in outcomes if o[1]["status"] == "found"]
    source, result, pruning, unit_clues = (found or outcomes)[0]
    result = dict(result)
    distinct = {frozenset(frozenset(s) for s in o[1]["minimal_sets"]) for o in found}
    if len(distinct) > 1:  # FR-K4: successes that disagree about what restoring flips never become gold
        said = "; ".join(f"{o[0].thread_id}: " + " and ".join("{" + ", ".join(s) + "}" for s in o[1]["minimal_sets"])
                         for o in found)
        result.update(status="abstain", reason_code="sources_disagree", minimal_sets=[], complete=False,
                      reason=f"the prior successful runs disagree about which nodes fix the run ({said}); "
                             "Sherlock does not take either as gold")
    used = result["budget"].get("trials_used", 0)
    exhaustive = pruning.exhaustive_trials
    return {"schema": SCHEMA, "created": created, "thread_id": thread_id, "graph_id": graph_id, "check": original,
            "context": context, **result, "pruning": pruning.to_dict(),
            "trial_reduction": {"exhaustive_trials": exhaustive, "trials_used": used,
                                "fewer_pct": round(100 * (1 - used / exhaustive), 1) if exhaustive else 0.0},
            "clues": [c.to_dict() for c in unit_clues], "path_check": path.to_dict() if path else None,
            "known_good_source": source.to_dict() if source else {"kind": "file", "confirmed": True},
            "sources_considered": early["sources_considered"],
            "other_sources": [{"thread_id": o[0].thread_id, "status": o[1]["status"],
                               "minimal_sets": o[1]["minimal_sets"], "reason_code": o[1]["reason_code"]}
                              for o in outcomes if o[0] is not source and o[0]],
            "intake": intake, "limitations": LIMITATIONS}


def write_artifact(result: dict, sherlock_dir: Path | str) -> Path:
    path = Path(sherlock_dir) / "diagnoses" / f"{result['thread_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return path
