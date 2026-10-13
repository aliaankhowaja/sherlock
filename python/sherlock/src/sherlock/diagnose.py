"""`sherlock-rec diagnose`: find every 1-minimal set of nodes whose restoration fixes a failed run.

Composes pruning and search (search.py) over the G3 trial primitive (g3.py). Writes a JSON
artifact for the UI to `.sherlock/diagnoses/<thread_id>.json`. No live calls, ever: every trial
is served from the cassette or abstains (NFR-3).
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from sherlock.cassette import Cassette
from sherlock.checks import Checks, evaluate
from sherlock.g3 import G3Error, history_usable, run_g3
from sherlock.search import LIMITATION, Budget, Pruning, plan_candidates, score_of, search

SCHEMA = 1
LIMITATIONS = [
    LIMITATION,
    "restoration goes through the run context only (spec 4.4, secondary path); a node whose behaviour "
    "is not configurable through context cannot be restored",
    "trials are served only from the recorded cassette; a set that needs a call that was never recorded "
    "is reported as 'cannot say', never guessed",
]


def _early(thread_id, code, reason, check=None, **extra) -> dict:
    """An abstain decided before any trial."""
    empty = Pruning([], [], {}, [])
    return {"schema": SCHEMA, "thread_id": thread_id, "status": "abstain", "reason_code": code, "reason": reason,
            "minimal_sets": [], "unverified_sets": [], "complete": False, "notes": [],
            "counts": {"fixes": 0, "partly_helps": 0, "does_not_help": 0, "cannot_say": 0, "total": 0},
            "budget": {}, "trials": [], "check": check, "pruning": empty.to_dict(),
            "trial_reduction": None, "limitations": LIMITATIONS, **extra}


def diagnose(client, thread_id: str, known_good: dict, checks: Checks, cassette_path: Path | str,
             budget: Budget | None = None, context: dict | None = None, clock=time.monotonic) -> dict:
    """Run the whole diagnosis and return the result artifact (a JSON-able dict)."""
    budget = budget or Budget()
    cassette_path = Path(cassette_path)
    if Cassette(cassette_path).replay_sessions() == 0:
        raise G3Error("no replay session on this cassette: start the server with "
                      "`sherlock-rec run --replay <server command>` first; diagnose never runs against a "
                      "server that could make live calls")
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    thread = client.request("GET", f"/threads/{thread_id}")
    history = client.request("POST", f"/threads/{thread_id}/history", {"limit": 1000})
    problem = history_usable(history)
    if problem:
        return _early(thread_id, "no_history", problem, created=created)
    report = evaluate(checks.assertions, (history[0]["values"] or {}).get(checks.output_key) or "", checks.base_dir)
    original = report.to_dict()
    if report.passed:
        return _early(thread_id, "already_passes", "the original run already passes the check; "
                      "there is nothing to diagnose", check=original, created=created)
    if context is None:
        run_id = (history[0].get("metadata") or {}).get("run_id")
        run = client.request("GET", f"/threads/{thread_id}/runs/{run_id}") if run_id else None
        context = ((run or {}).get("kwargs") or {}).get("context") or {}

    pruning = plan_candidates(history, known_good, context, checks.output_key)
    result = search(
        pruning.candidates,
        lambda restore: run_g3(client, thread_id, restore, known_good, checks, cassette_path, context),
        score_of(original), budget, clock, pruning.untestable).to_dict()
    used = result["budget"]["trials_used"]
    exhaustive = pruning.exhaustive_trials
    return {"schema": SCHEMA, "created": created, "thread_id": thread_id,
            "graph_id": (thread.get("metadata") or {}).get("graph_id"), "check": original,
            "context": context, **result, "pruning": pruning.to_dict(),
            "trial_reduction": {"exhaustive_trials": exhaustive, "trials_used": used,
                                "fewer_pct": round(100 * (1 - used / exhaustive), 1) if exhaustive else 0.0},
            "limitations": LIMITATIONS}


def write_artifact(result: dict, sherlock_dir: Path | str) -> Path:
    path = Path(sherlock_dir) / "diagnoses" / f"{result['thread_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return path
