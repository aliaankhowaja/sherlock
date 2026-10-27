> **Working note (tier 3). Not authoritative.** It may be stale or wrong. Facts come from the code and from docs/eval. Never cite this file in anything submitted to the university.

# Spike: the fork recipe against a live server

**Date:** 2026-10-13 · **Phase:** 0 (P0.2, P0.3, P0.5) · **Result:** 20/20 checks pass, two corrections to spec §4.3

**Versions:** langgraph-api 0.16.0, langgraph 1.2.15, langgraph-runtime-inmem 0.36.0
**Code:** `harness/spikes/fork_recipe.py` · **Raw results:** `harness/spikes/results/fork_recipe-2026-10-13.json`

## Question

Does spec §4.3 (fork over HTTP) and §4.4 (behaviour restoration via run `context`) work as written against a real Agent Server? And what does real checkpoint history look like, for the FR-R10 ingestion fix?

## Setup

Demo team #1 (`vendor_brief`): five deterministic nodes, router → retriever → extractor → writer → reviewer. The planted two-cause fault is chained:

- the retriever drops the document carrying ISO 27001;
- the extractor's legacy pattern reports an expired SOC 2 as current.

The check Z requires "ISO 27001" and "Data region: EU", and forbids "SOC 2" and "BLOCKED".

## The recipe that works

1. **Build an isolated fork thread.** `POST /threads` with:
   - `metadata: {"graph_id": "<graph>"}` — required;
   - `supersteps`: replay the original's per-node writes up to, but not including, the fork node. The first superstep is the input, with `as_node: "__start__"`.
2. **Find the fork point.** `POST /threads/{id}/history` → the newest snapshot, whose `next` is `[fork_node]`.
3. **Restore.**
   - **Behaviour:** skip to step 4, and pass the restored behaviour in the run's `context`.
   - **Output:** `POST /threads/{id}/state` with `{values: <known-good output>, checkpoint, as_node: <fork_node>}`, then resume from the returned checkpoint.
4. **Resume.** `POST /threads/{id}/runs/wait` with `input: null`, the checkpoint, and `context` only (never also `config.configurable`).

The original thread is never touched.

## Corrections to spec §4.3

| Spec says | Reality | Impact |
|---|---|---|
| `POST /threads` with `supersteps` synthesises the thread | Also needs `metadata.graph_id`. Without it: **HTTP 201**, an error `detail`, no `thread_id`, and an orphan thread | Clients must check the body for `thread_id`, not the status code |
| (not specified) | The first superstep must be `as_node: "__start__"`. `"__input__"` silently drops the input values | Silent corruption of the fork's state if done wrong |

## Confirmed as the spec says

- `as_node=X` on a state update resumes at X's successors.
- Sending `config.configurable` and `context` together → HTTP 400.
- `{"__overwrite__": [...]}` over HTTP replaces an append-reducer list; a plain list appends (open item 4 closed).
- Forks leave the original thread's history byte-identical (NFR-2).
- Behaviour restoration through `context` re-runs only the fork node and its downstream; repeated trials on deterministic nodes give identical results.

## Results on the chained two-cause case

| Trial | Restores | Result |
|---|---|---|
| Behaviour | {retriever} | fails — the extractor still adds SOC 2 |
| Behaviour | {extractor} | fails — ISO 27001 still missing |
| Behaviour | {retriever, extractor} | **passes** |
| Output (message) | retriever's message | fails |
| Output (message) | extractor's message | **passes** |

Message-level restoration (GCJR's unit) blames the extractor alone, because overwriting its message hides the retriever's fault. Behaviour-level restoration finds the pair the engineer actually has to fix. This is the GCJR gap from spec §3.3, reproduced on a real server.

## For FR-R10 (P0.1)

- Checkpoint metadata from this server version has no `writes` key. The keys seen are recorded in the results JSON.
- Diffing each checkpoint's `values` against its parent's, and attributing the change to the parent's `next`, recovers per-node writes in the correct order: `__start__, router, retriever, extractor, writer, reviewer`.
- **Better, and what the fix uses:** each snapshot's `tasks[]` already carries `result`, the exact output of the node that ran from that checkpoint. This needs no diffing and is safe for parallel nodes.
- Run `context` is copied into checkpoint metadata, so never pass secrets through it (FR-R8).
- The real history is saved as `harness/fixtures/vendor_brief_two_cause_history.json` for the Rust tests.

## Not covered by this spike

- LLM-backed nodes and cassette replay (Phase 1).
- Parallel super-steps, conditional edges, subgraphs, and message-list surgery with `tool_calls` (spec §4.3 sharp edges 3–5).
- Interceptor-level behaviour restoration (spec §4.4 primary mechanism).

## Re-run

```sh
cd harness
uv run langgraph dev --no-browser --no-reload --port 2024   # terminal 1
uv run python spikes/fork_recipe.py                         # terminal 2
```
