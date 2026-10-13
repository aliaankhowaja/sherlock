"""Phase 0 spike: verify the spec's fork recipe against a live `langgraph dev`.

Checks the claims in spec §4.3 (fork over HTTP) and §4.4 (behaviour restoration through
runtime context) on demo team #1, and saves a real checkpoint history as a fixture for the
FR-R10 ingestion fix.

Run with the demo team served locally:
    uv run langgraph dev --no-browser --no-reload --port 2024
    uv run python spikes/fork_recipe.py

Exits non-zero if any expectation fails. Results go to spikes/results/.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sherlock_harness.teams.vendor_brief import check  # noqa: E402

BASE_URL = os.environ.get("SHERLOCK_LIVE_URL", "http://127.0.0.1:2024")
ASSISTANT = "vendor_brief"
TWO_CAUSE = ["retriever.drop_latest", "extractor.legacy_pattern"]
HERE = Path(__file__).resolve().parent

results: list[dict] = []


def record(name: str, expected, observed, note: str = "") -> bool:
    ok = expected == observed
    results.append({"check": name, "expected": expected, "observed": observed, "ok": ok, "note": note})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: expected {expected!r}, observed {observed!r}")
    return ok


def new_thread(client: httpx.Client, **body) -> str:
    body.setdefault("metadata", {"assistant_id": ASSISTANT})
    response = client.post("/threads", json=body)
    response.raise_for_status()
    payload = response.json()
    if "thread_id" not in payload:
        raise RuntimeError(f"thread creation failed: {payload}")
    return payload["thread_id"]


def run_wait(client: httpx.Client, thread_id: str, *, input=None, checkpoint=None, context=None) -> dict:
    body: dict = {"assistant_id": ASSISTANT, "input": input}
    if checkpoint is not None:
        body["checkpoint"] = checkpoint
    if context is not None:
        body["context"] = context
    response = client.post(f"/threads/{thread_id}/runs/wait", json=body)
    response.raise_for_status()
    return response.json()


def history(client: httpx.Client, thread_id: str) -> list[dict]:
    response = client.post(f"/threads/{thread_id}/history", json={"limit": 100})
    response.raise_for_status()
    return response.json()  # newest first


def node_writes(snapshots: list[dict]) -> list[tuple[str, dict]]:
    """Attribute each checkpoint's change to the node that ran, without metadata.writes.

    The replacement the spec proposes for FR-R10: diff a checkpoint's values against its
    parent's, and attribute the delta to the node named in the parent's `next`.
    """
    ordered = list(reversed(snapshots))  # oldest first
    by_id = {s["checkpoint"]["checkpoint_id"]: s for s in ordered}
    writes = []
    for snapshot in ordered:
        parent_ref = snapshot.get("parent_checkpoint") or {}
        parent = by_id.get(parent_ref.get("checkpoint_id"))
        if parent is None or not parent.get("next"):
            continue
        before, after = parent["values"], snapshot["values"]
        delta = {k: v for k, v in after.items() if before.get(k) != v}
        writes.append((",".join(parent["next"]), delta))
    return writes


def snapshot_before(snapshots: list[dict], node: str) -> dict:
    return next(s for s in snapshots if s.get("next") == [node])


def faults_without(nodes: set[str]) -> list[str]:
    return [f for f in TWO_CAUSE if f.split(".")[0] not in nodes]


def main() -> int:
    with httpx.Client(base_url=BASE_URL, timeout=60) as client:
        info = client.get("/info").json()
        print(f"server: langgraph-api {info.get('version')}, langgraph {info.get('langgraph_py_version')}")

        # 1. The failing run, and a clean reference run of the same input.
        original = new_thread(client)
        failed = run_wait(client, original, input={"vendor": "acme"}, context={"faults": TWO_CAUSE})
        record("two-cause run fails the check", False, check(failed["final_output"]).passed)
        clean = new_thread(client)
        passed = run_wait(client, clean, input={"vendor": "acme"}, context={"faults": []})
        record("clean run passes the check", True, check(passed["final_output"]).passed)

        # 2. Checkpoint metadata no longer carries `writes` (FR-R10 defect), and the
        #    diff-against-parent replacement recovers per-node writes.
        original_history = history(client, original)
        metadata_keys = sorted({k for s in original_history for k in (s.get("metadata") or {})})
        record("checkpoint metadata has no `writes` key", False, "writes" in metadata_keys,
               note=f"metadata keys seen: {metadata_keys}")
        recovered = [node for node, _ in node_writes(original_history)]
        record("diff-against-parent recovers node order", ["__start__", "router", "retriever", "extractor", "writer", "reviewer"], recovered)
        fixtures = HERE.parent / "fixtures"
        fixtures.mkdir(exist_ok=True)
        (fixtures / "vendor_brief_two_cause_history.json").write_text(json.dumps(original_history, indent=2))
        original_ids_before = [s["checkpoint"]["checkpoint_id"] for s in original_history]

        clean_writes = dict(node_writes(history(client, clean)))

        # 3. Isolated fork thread synthesised with `supersteps` (spec §4.3 step 1): replay the
        #    original's writes up to, not including, the fork node.
        prefix = node_writes(original_history)
        order = [node for node, _ in prefix]

        def supersteps_for(fork_node: str, input_node: str = "__start__") -> list[dict]:
            upto = order.index(fork_node)
            steps = [{"updates": [{"values": prefix[0][1], "as_node": input_node}]}]
            steps += [{"updates": [{"values": delta, "as_node": node}]} for node, delta in prefix[1:upto]]
            return steps

        def fork_thread(fork_node: str) -> str:
            # Finding: supersteps need `graph_id` in the thread metadata, or the server
            # creates the thread but cannot apply the updates (spec §4.3 omits this).
            return new_thread(client, supersteps=supersteps_for(fork_node),
                              metadata={"assistant_id": ASSISTANT, "graph_id": ASSISTANT})

        # Finding: without graph_id the server answers 201 Created with an error `detail`
        # and no thread_id, leaving an orphan thread. Clients must check the body.
        no_graph_id = client.post("/threads", json={"supersteps": supersteps_for("retriever")})
        record("supersteps without graph_id: 201 with error detail, no thread_id",
               [201, True, False],
               [no_graph_id.status_code, "detail" in no_graph_id.json(), "thread_id" in no_graph_id.json()],
               note=no_graph_id.text[:160])
        via_input = new_thread(client, supersteps=supersteps_for("retriever", input_node="__input__"),
                               metadata={"graph_id": ASSISTANT})
        record("first superstep as __input__ drops the input values", False,
               "vendor" in client.get(f"/threads/{via_input}/state").json()["values"],
               note="use as_node='__start__' for the input superstep")

        isolated = fork_thread("retriever")
        isolated_history = history(client, isolated)
        record("supersteps thread stops before retriever", ["retriever"], isolated_history[0].get("next"))
        record("supersteps thread keeps the input", "acme", isolated_history[0]["values"].get("vendor"))

        # 4. Behaviour restoration through runtime context (spec §4.4, secondary mechanism).
        def behaviour_trial(restore: set[str], fork_node: str) -> bool:
            thread = fork_thread(fork_node)
            fork_point = history(client, thread)[0]
            out = run_wait(client, thread, input=None, checkpoint=fork_point["checkpoint"],
                           context={"faults": faults_without(restore)})
            return check(out["final_output"]).passed

        record("behaviour: restore {retriever} alone", False, behaviour_trial({"retriever"}, "retriever"))
        record("behaviour: restore {extractor} alone", False, behaviour_trial({"extractor"}, "extractor"))
        record("behaviour: restore {retriever, extractor}", True, behaviour_trial({"retriever", "extractor"}, "retriever"))
        record("behaviour trial is repeatable", behaviour_trial({"retriever", "extractor"}, "retriever"),
               behaviour_trial({"retriever", "extractor"}, "retriever"))

        # 5. Output (message-level) restoration via POST /state with as_node (spec §4.3 step 3).
        def output_trial(node: str) -> tuple[bool, list[str] | None]:
            thread = fork_thread(node)
            fork_point = history(client, thread)[0]
            update = client.post(f"/threads/{thread}/state", json={
                "values": clean_writes[node], "checkpoint": fork_point["checkpoint"], "as_node": node})
            update.raise_for_status()
            new_checkpoint = update.json()["checkpoint"]
            after_update = client.get(f"/threads/{thread}/state").json()
            out = run_wait(client, thread, input=None, checkpoint=new_checkpoint,
                           context={"faults": faults_without({node})})
            return check(out["final_output"]).passed, after_update.get("next")

        passed_retriever, next_after = output_trial("retriever")
        record("as_node=retriever resumes at its successor", ["extractor"], next_after)
        record("output: restore retriever's message alone", False, passed_retriever)
        passed_extractor, _ = output_trial("extractor")
        record("output: restore extractor's message alone", True, passed_extractor,
               note="message-level replay blames the extractor alone; behaviour-level needs both")

        # 6. The original thread is never modified (NFR-2).
        original_ids_after = [s["checkpoint"]["checkpoint_id"] for s in history(client, original)]
        record("original thread history unchanged", original_ids_before, original_ids_after)

        # 7. `__overwrite__` bypasses an append reducer over HTTP (spec open item 4).
        probe = new_thread(client)
        run_wait(client, probe, input={"vendor": "acme"}, context={"faults": []})
        appended = client.post(f"/threads/{probe}/state", json={"values": {"notes": ["probe"]}, "as_node": "reviewer"})
        appended.raise_for_status()
        notes_after_append = client.get(f"/threads/{probe}/state").json()["values"]["notes"]
        record("plain list update appends", "probe", notes_after_append[-1],
               note=f"{len(notes_after_append)} notes after append")
        overwritten = client.post(f"/threads/{probe}/state",
                                  json={"values": {"notes": {"__overwrite__": ["replaced"]}}, "as_node": "reviewer"})
        record("__overwrite__ accepted over HTTP", 200, overwritten.status_code)
        notes_after_overwrite = client.get(f"/threads/{probe}/state").json()["values"]["notes"]
        record("__overwrite__ replaces the list", ["replaced"], notes_after_overwrite)

        # 8. Sending both config.configurable and context is rejected (spec Appendix A).
        both = client.post(f"/threads/{new_thread(client)}/runs/wait", json={
            "assistant_id": ASSISTANT, "input": {"vendor": "acme"},
            "config": {"configurable": {"x": 1}}, "context": {"faults": []}})
        record("config.configurable + context together is HTTP 400", 400, both.status_code)

    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    report = {"date": date.today().isoformat(), "server": info, "results": results}
    (out_dir / f"fork_recipe-{date.today().isoformat()}.json").write_text(json.dumps(report, indent=2))
    failures = [r for r in results if not r["ok"]]
    print(f"\n{len(results) - len(failures)}/{len(results)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
