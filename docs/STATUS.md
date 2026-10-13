# Sherlock — build status

> **This is the live progress tracker.** Read it before starting work; update it before you stop.
> Scope is set by [`sherlock-spec.md`](sherlock-spec.md), which governs. The status columns inside the spec are a 12 October snapshot — **live status lives here only.** Session rules (model, commits) are in [`../CLAUDE.md`](../CLAUDE.md).

**Last updated:** 2026-10-13 · **Current phase:** 1 — record and freeze (not started) · **Branch:** `phase-0` (merge, then branch `phase-1`)

## How to update this file

- Tick an item only when it is done **and verified**; link the evidence (test, spike result, commit).
- Anything checked against real software goes under **Verified facts**, dated, with how it was checked.
- Decisions go in the **Decision log** with the date and who decided.
- Add one line to the **Session log** per working session, newest first.
- Keep this file short. Details belong in `docs/spikes/` reports or commit messages.

## Phases (spec §8)

| Phase | Goal | Status |
|---|---|---|
| 0 | Unblock: fix ingestion, verify fork recipe and `__overwrite__`, demo team #1 | ✅ done 2026-10-13 |
| 1 | Record and freeze: `sherlock run`, interceptors, cassette store, abort-on-miss | ⬜ next |
| 2 | Checks (Z) and the run-again test (G3) | ⬜ |
| 3 | Minimality search, verdicts, budget | ⬜ |
| 4 | G0, G2, intake, known-good sources | ⬜ |
| 5 | Surface: run page, verified colouring, evidence panel | ⬜ |
| 6 | Evaluation: remaining teams, baselines, hidden set, CI invariants | ⬜ |

Legend: ✅ done · 🔨 in progress · ⬜ not started · ⛔ blocked

## Phase 0 — unblock ✅

- [x] **P0.1 Ingestion defect (FR-R10) fixed.** Per-node events now come from each checkpoint's `tasks[].result`; `metadata.writes` is only a fallback for old servers. Tests use the real fixture. `crates/app-core/src/ingestion.rs`.
- [x] **P0.2 Fork recipe verified** against a live `langgraph dev` — 20/20 checks, two corrections to spec §4.3. Report: [`spikes/2026-10-13-fork-recipe.md`](spikes/2026-10-13-fork-recipe.md).
- [x] **P0.3 `__overwrite__` over HTTP** works; closes spec open item 4.
- [x] **P0.4 Demo team #1 with fault injection** — `harness/`, 16 tests.
- [x] **P0.5 Real history fixture** — `harness/fixtures/vendor_brief_two_cause_history.json`.

## Next up — Phase 1: record and freeze (spec §4.2, FR-R1–R9, FR-G3.5)

The riskiest component; everything after it is ordinary engineering. Suggested order:

1. **Python package skeleton** at `python/sherlock/`, its own uv project for now. The maturin wheel comes later (spec §4.1).
2. **`sherlock run <cmd>` launcher** (FR-R1, FR-X1): prepend the bootstrap directory to `PYTHONPATH`, then exec the command.
3. **`sitecustomize` bootstrap** (FR-R6):
   - strip its own path;
   - chain to any existing user `sitecustomize`;
   - install a `sys.meta_path` hook;
   - wrap everything so an exception never kills the user's process (spec §9.3).
4. **httpx transport shim** (FR-R2, FR-R5): record full request and response bodies; record SSE as ordered chunks.
5. **`BaseTool.run`/`arun` patch** (FR-R3) for local tools.
6. **Cassette store** in SQLite under `.sherlock/`. Key on a hash of the request, falling back to sequence order (spec §9.3).
7. **Replay mode:** serve calls from the cassette; a miss aborts with an abstain reason, never a live call (FR-G3.5, NFR-3).
8. **Test target:** a demo team with one LLM node pointing at a **local stub OpenAI-compatible server**, so tests are deterministic and cost nothing. Use a real provider only for one smoke test (proposal — see Open items).

**Exit criterion:** record a run of the LLM demo team, replay it with zero network calls, and see a deliberately changed request abort with "cannot say".

## Requirement status

Only requirements that are not ⬜ are listed. IDs are from `sherlock-spec.md` §5.

| ID | Status | Notes |
|---|---|---|
| FR-R4 | 🔨 | Per-node structure available from `tasks[]` |
| FR-R10 | ✅ | Fixed for LangGraph ≥ 0.5 (P0.1) |
| FR-R11 | 🔨 | LangSmith import, browse-only (`dd37b7d`) |
| FR-E1 | 🔨 | Team 1 of 4–6 (`vendor_brief`) |
| FR-E2 | 🔨 | Single and chained two-node faults on team 1 |
| FR-E3 | 🔨 | Gold by restoring subsets (`gold_minimal_sets`), in-process, deterministic teams only |
| FR-G3.1 | 🔨 | Fork-and-resume verified over HTTP; no product code yet |
| FR-U13 | ✅ | Per-node timeline, errors first |
| FR-X5 | ✅ | `sherlock serve` |
| FR-X6 | ✅ | `sherlock ingest teams\|runs\|logs` |

## Verified facts

Dated; they have a shelf life. Re-check before relying on them in a report.

- **2026-10-13 — versions:** langgraph 1.2.15, langgraph-api 0.16.0, langgraph-runtime-inmem 0.36.0, langgraph-sdk 0.4.7, langgraph-cli 0.4.33 (`harness/uv.lock`). Rust 1.99 (`stable-x86_64-pc-windows-gnu`).
- **2026-10-13 — FR-R10:** checkpoint metadata has no `writes` key. Each history snapshot's `tasks[]` carries `name`, `error` and **`result`, the node's exact output**. This is better than the spec's diff-against-parent idea: exact, and safe for parallel nodes.
- **2026-10-13 — privacy (FR-R8):** a run's `context` is copied into checkpoint **metadata** (our `faults` list appeared there). Never pass secrets through `context`.
- **2026-10-13 — correction to spec §4.3 step 1:** `POST /threads` with `supersteps` needs `metadata.graph_id`. Without it the server answers **HTTP 201** with an error `detail`, no `thread_id`, and leaves an orphan thread. Check the body, not the status.
- **2026-10-13 — correction to spec §4.3 step 1:** the first superstep must use `as_node: "__start__"`; `"__input__"` silently drops the input values.
- **2026-10-13 — confirms spec:** `as_node=X` resumes at X's successors; `config.configurable` and `context` together → HTTP 400.
- **2026-10-13 — confirms spec §4.4:** resuming a supersteps fork with a run `context` restores a node's behaviour; upstream nodes are not re-run; trials on deterministic nodes are repeatable.
- **2026-10-13 — the GCJR gap, shown live:** on the chained retriever→extractor case, restoring the extractor's *message* alone passes; restoring *behaviour* needs {retriever, extractor}.
- **2026-10-13 — confirms NFR-2:** the original thread is unchanged after forks.
- **2026-10-13 — closes open item 4:** `{"__overwrite__": [...]}` over HTTP replaces an append-reducer list.
- **2026-10-13 — licences:** AgentAssay is AGPL-3.0-or-later; the CAR repo has no LICENSE file.
- **2026-10-13 — tooling:** Claude Code v2.1.288 supports the advisor (`--advisor opus`, `/advisor`, `advisorModel`). With Sonnet 5.5 as the main model it accepts Opus 5+ as advisor (code.claude.com/docs/en/advisor).

## Decision log

- **2026-10-12/13 — team meeting; spec by Ibraheem.** Final scope is `docs/sherlock-spec.md`. No live calls: cache or abstain. The 9 October brief is superseded on method.
- **2026-10-13 — Wajih.** Atomic commits; no AI co-author; the other two members as `Co-authored-by` (see `CLAUDE.md`). Build sessions use Sonnet with an Opus advisor; the token budget is tight.
- **2026-10-13.** Ingestion reads `tasks[].result` instead of diffing checkpoints (more exact than spec §5.1's proposal).
- **2026-10-13 — proposed.** Harness Python lives in `harness/` (uv, Python 3.12), separate from the future `pip install sherlock` package.
- **2026-10-13 — proposed.** Demo teams inject faults through LangGraph runtime `context`, which doubles as the spec §4.4 restoration path.

## Open items

Beyond spec §10:

- **Phase 1 test model:** use a local stub OpenAI-compatible server for deterministic, free tests, plus one real-provider smoke test. Which provider and key for that smoke test? *(Proposal; the team should confirm.)*
- The spec cites governing documents in `causal-debugger/` that are not in this repo. Add or link them.
- Competitors missing from spec §3: TraceSurgeon (`ahhbhishek/tracesurgeon`, MIT, LangGraph) and Agent-Casuality (PyPI `agent-casuality`). Review before mid-eval.
- Spec §1.2 and §9.1 say most real bugs live in deterministic nodes; this is unsourced. Measure the abstain rate on real failures early.
- The mid-evaluation date and the required demo.
- `ui/dist` must exist for the `api` crate to compile. Run `cd ui && npm run build`; an empty `ui/dist/` is enough for tests.

## Session log

- **2026-10-13** — Phase 0 complete on `phase-0`:
  - harness and demo team #1 (16 tests);
  - fork-recipe spike 20/20;
  - ingestion fixed to read `tasks[].result` (Rust tests, clippy and fmt green);
  - tracker, `CLAUDE.md` and the commit policy added;
  - Rust installed (GNU toolchain).
