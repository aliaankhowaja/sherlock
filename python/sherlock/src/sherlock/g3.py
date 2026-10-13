"""G3, the run-again test (spec 4.3, 4.4, 5.4; FR-G3.1-G3.9).

Fork a recorded run at the earliest restored node, restore a known-good behaviour for the
candidate set S through the run `context`, resume so every later node produces a NEW answer,
and score the result with the check Z. Verdict: pass, fail, or abstain.

Safety by construction:
  * The original thread is only read (FR-G3.1). The fork is a fresh thread built from the
    recorded per-node writes that precede the fork point.
  * We never write a node's output after the fork point (FR-G3.3/G3.4): the resume starts at
    the fork checkpoint with `input: null`, so every later node must run again.
  * The server must be running under `sherlock-rec run --replay`, so model and tool calls
    come from the cassette or abstain (FR-G3.5/G3.6/G3.8). G3 refuses to run otherwise.
  * Before scoring, the prefix and the restore are verified (FR-G3.7). If they do not hold
    the answer is "replay went off track", never a verdict.

Only the context path (spec 4.4, secondary) is implemented; interceptor-level restoration is not.
"""

import copy
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from sherlock.cassette import Cassette
from sherlock.checks import CheckError, Checks, evaluate


class G3Error(Exception):
    """G3 cannot even start (bad setup). Distinct from an abstain, which is an analysis result."""


class ServerError(G3Error):
    def __init__(self, method, path, status, text):
        super().__init__(f"{method} {path} -> HTTP {status}: {text[:300]}")


@dataclass
class Verdict:
    verdict: str  # "pass" | "fail" | "abstain"
    reason: str
    restored: list[str] = field(default_factory=list)
    fork_node: str | None = None
    fork_thread: str | None = None
    check: dict | None = None
    evidence: dict = field(default_factory=dict)

    def to_dict(self):
        return {"verdict": self.verdict, "reason": self.reason, "restored": self.restored,
                "fork_node": self.fork_node, "fork_thread": self.fork_thread,
                "check": self.check, "evidence": self.evidence}


def abstain(reason, **kw) -> Verdict:
    return Verdict("abstain", reason, **kw)


def off_track(why, **kw) -> Verdict:
    return abstain(f"replay went off track: {why}", **kw)


class Client:
    """Minimal JSON client for the LangGraph Agent Server (stdlib only)."""

    def __init__(self, base_url, api_key=None, timeout=120):
        self.base, self.api_key, self.timeout = base_url.rstrip("/"), api_key, timeout

    def request(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raise ServerError(method, path, exc.code, exc.read().decode("utf-8", "replace")) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise G3Error(f"cannot reach the LangGraph server at {self.base}: {exc}") from exc
        return json.loads(raw) if raw else None


# --- planning (pure) -------------------------------------------------------------------------

def history_usable(history: list[dict]) -> str | None:
    """FR-R9: why this history cannot be forked, or None if it can."""
    if len(history) < 2:
        return ("no usable checkpoint history: fewer than two checkpoints "
                "(was the run started with durability='exit'?)")
    if not any(t.get("result") is not None for s in history for t in s.get("tasks") or []):
        return "no usable checkpoint history: checkpoints carry no per-node results"
    return None


def writes_of(snapshot: dict) -> list[dict]:
    """The updates that the tasks of this checkpoint produced, as superstep updates."""
    return [{"values": t["result"], "as_node": t["name"]}
            for t in snapshot.get("tasks") or [] if t.get("result") is not None]


@dataclass
class ForkPlan:
    fork_snapshot: dict  # original checkpoint whose `next` holds the earliest restored node
    fork_node: str
    supersteps: list[dict]


def plan_fork(history: list[dict], restore: list[str]) -> ForkPlan:
    """Pick the earliest restored node on the recorded path and the writes that precede it.

    `history` is newest first, as the server returns it. Raises KeyError(node) if a node to
    restore never ran in the original.
    """
    chrono = list(reversed(history))
    ran = {n for s in chrono for n in s.get("next") or []}
    for node in restore:
        if node not in ran:
            raise KeyError(node)
    index = next(i for i, s in enumerate(chrono) if set(s.get("next") or []) & set(restore))
    steps = [{"updates": u} for u in (writes_of(s) for s in chrono[:index]) if u]
    node = next(n for n in chrono[index]["next"] if n in restore)
    return ForkPlan(chrono[index], node, steps)


def apply_restore(context: dict | None, known_good: dict, restore: list[str]) -> dict:
    """The run context that gives each restored node its known-good behaviour.

    `known_good[node]` maps context keys to a replacement value, or to {"$remove": [..]} to
    drop items from a list-valued key. Patches compose over the original run's context.
    """
    ctx = copy.deepcopy(context or {})
    for node in restore:
        for key, patch in known_good[node].items():
            if isinstance(patch, dict) and set(patch) == {"$remove"}:
                drop = patch["$remove"]
                ctx[key] = [x for x in ctx.get(key, []) if x not in drop]
            else:
                ctx[key] = copy.deepcopy(patch)
    return ctx


def load_known_good(path: Path | str) -> dict:
    """Known-good behaviours per node: {node: {context_key: value | {"$remove": [..]}}}. JSON or YAML."""
    import yaml

    try:
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise G3Error(f"cannot read known-good file {path}: {exc}") from exc
    if not isinstance(doc, dict) or not all(isinstance(v, dict) for v in doc.values()):
        raise G3Error(f"{path}: expected a mapping of node name to a mapping of context keys")
    return doc


def prefix_mismatch(original: dict, forked: dict) -> str | None:
    """FR-G3.7: the fork point must be the same state, heading to the same nodes."""
    if forked.get("values") != original.get("values"):
        return f"fork state differs from the original at {original.get('next')}"
    if sorted(forked.get("next") or []) != sorted(original.get("next") or []):
        return f"fork would run {forked.get('next')} but the original ran {original.get('next')}"
    return None


# --- the driver --------------------------------------------------------------------------------

def _ids(history):
    return [s["checkpoint"]["checkpoint_id"] for s in history]


def _output(values, key):
    return values.get(key) if isinstance(values, dict) else None


def run_g3(client, thread_id: str, restore: list[str], known_good: dict, checks: Checks,
           cassette_path: Path | str | None, context: dict | None = None) -> Verdict:
    """One trial: restore the set `restore`, resume from the cassette, apply Z."""
    restore = list(dict.fromkeys(restore))
    if not restore:
        raise G3Error("nothing to restore: pass at least one node")
    cassette = None
    if cassette_path is not None:
        cassette = Cassette(cassette_path)
        if cassette.replay_sessions() == 0:
            raise G3Error("no replay session on this cassette: start the server with "
                          "`sherlock-rec run --replay <server command>` first; G3 never runs against a server "
                          "that could make live calls")

    thread = client.request("GET", f"/threads/{thread_id}")
    graph_id = (thread.get("metadata") or {}).get("graph_id")
    if not graph_id:
        raise G3Error(f"thread {thread_id} has no metadata.graph_id")
    history = client.request("POST", f"/threads/{thread_id}/history", {"limit": 1000})
    problem = history_usable(history)
    if problem:
        return abstain(problem, restored=restore)
    before_ids = _ids(history)

    original = evaluate(checks.assertions, _output(history[0]["values"], checks.output_key) or "", checks.base_dir)
    if original.passed:
        return abstain("the original run already passes the check; there is nothing to diagnose", restored=restore)

    missing = [n for n in restore if n not in known_good]
    if missing:
        return abstain(f"no known-good behaviour for {', '.join(missing)}", restored=restore)
    try:
        plan = plan_fork(history, restore)
    except KeyError as exc:
        return abstain(f"node {exc.args[0]} did not run in the recorded path", restored=restore)

    if context is None:
        run_id = (plan.fork_snapshot.get("metadata") or {}).get("run_id")
        run = client.request("GET", f"/threads/{thread_id}/runs/{run_id}") if run_id else None
        context = ((run or {}).get("kwargs") or {}).get("context")
    trial_context = apply_restore(context, known_good, restore)
    base = dict(restored=restore, fork_node=plan.fork_node)

    # FR-G3.1: an isolated fork thread; spec 4.3 as corrected by the Phase 0 spike.
    created = client.request("POST", "/threads", {
        "metadata": {"graph_id": graph_id, "sherlock_fork_of": thread_id}, "supersteps": plan.supersteps})
    fork_id = (created or {}).get("thread_id")
    if not fork_id:  # the server answers 201 with an error `detail` and no thread_id
        return off_track(f"the server could not build the fork thread: {created}", **base)
    base["fork_thread"] = fork_id
    fork_point = client.request("POST", f"/threads/{fork_id}/history", {"limit": 1000})[0]
    mismatch = prefix_mismatch(plan.fork_snapshot, fork_point)
    if mismatch:
        return off_track(mismatch, **base)

    # FR-G3.3-G3.5/G3.9: resume from the fork checkpoint; later nodes run again, served from the cassette.
    if cassette is not None:
        cassette.start_trial()
        seen = len(cassette.abstains())
    result = client.request("POST", f"/threads/{fork_id}/runs/wait", {
        "assistant_id": graph_id, "input": None, "checkpoint": fork_point["checkpoint"],
        "context": trial_context, "durability": "sync"})
    if cassette is not None:
        fresh = cassette.abstains()[seen:]
        if fresh:
            return abstain(fresh[0], **base)
    if isinstance(result, dict) and "__error__" in result:
        error = result["__error__"]
        return abstain(f"the trial run failed: {error.get('error')}: {error.get('message')}", **base)

    # FR-G3.7: verify the restore was applied and nothing else moved, before any verdict.
    evidence = _verify_applied(client, fork_id, fork_point, restore, trial_context)
    if evidence["problem"]:
        return off_track(evidence["problem"], **base, evidence=evidence)
    if _ids(client.request("POST", f"/threads/{thread_id}/history", {"limit": 1000})) != before_ids:
        return off_track("the original thread changed during the trial", **base, evidence=evidence)

    output = _output(result, checks.output_key)
    if output is None:
        return abstain(f"the resumed run has no `{checks.output_key}` to check", **base, evidence=evidence)
    try:
        report = evaluate(checks.assertions, output, checks.base_dir)
    except CheckError as exc:
        raise G3Error(str(exc)) from exc
    names = ", ".join(restore)
    if report.passed:
        return Verdict("pass", f"restoring {names} makes the check pass", check=report.to_dict(),
                       evidence=evidence, **base)
    why = "; ".join(r.reason for r in report.results if not r.pass_)
    return Verdict("fail", f"restoring {names} does not fix the check: {why}", check=report.to_dict(),
                   evidence=evidence, **base)


def _verify_applied(client, fork_id, fork_point, restore, trial_context) -> dict:
    """Evidence that the trial ran what we asked: the server saw the context, restored nodes re-ran."""
    history = client.request("POST", f"/threads/{fork_id}/history", {"limit": 1000})
    chrono = list(reversed(history))
    start = _ids(chrono).index(fork_point["checkpoint"]["checkpoint_id"])
    after = chrono[start:]
    reran = sorted({t["name"] for s in after for t in s.get("tasks") or [] if t.get("result") is not None})
    runs = client.request("GET", f"/threads/{fork_id}/runs")
    seen = ((runs[0] if runs else {}).get("kwargs") or {}).get("context")
    problem = None
    if seen != trial_context:
        problem = f"the server ran with context {seen}, not the restored {trial_context}"
    elif [n for n in restore if n not in reran]:
        problem = f"restored node(s) {[n for n in restore if n not in reran]} did not run again"
    elif chrono[-1].get("next"):
        problem = f"the resumed run stopped early at {chrono[-1]['next']}"
    return {"context": seen, "nodes_rerun": reran, "problem": problem}
