# Sherlock — build status

> **This is the live progress tracker.** Read it before starting work; update it before you stop.
> Scope is set by [`sherlock-spec.md`](sherlock-spec.md), which governs. The status columns inside the spec are a 12 October snapshot — **live status lives here only.** Session rules (model, commits) are in [`../CLAUDE.md`](../CLAUDE.md).

**Last updated:** 2026-10-14 · **Current phase:** 2 — checks (Z) and the run-again test (G3), not started · **Branch:** `phase-1` (Phase 1 done; merge, then branch `phase-2`)

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
| 1 | Record and freeze: `sherlock run`, interceptors, cassette store, abort-on-miss | ✅ done 2026-10-14 |
| 2 | Checks (Z) and the run-again test (G3) | ⬜ next |
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

## Phase 1 — record and freeze ✅

Package: `python/sherlock/` (own uv project, 48 tests). Run: `cd python/sherlock && uv run pytest -q`.

- [x] **P1.1 Package skeleton** — `5dce0e8`.
- [x] **P1.2 `sherlock run <cmd>` launcher** (FR-R1) — `788f319`; `tests/test_launcher.py`.
- [x] **P1.3 `sitecustomize` bootstrap** (FR-R6): chains the user's `sitecustomize`, strips its own path, `sys.meta_path` hook, never kills the process — `3b5b70e`; `tests/test_bootstrap.py`.
- [x] **P1.4 httpx transport shim** (FR-R2, FR-R5): full bodies, SSE as ordered chunks, sync and async — `5079004`; `tests/test_httpx_record.py`, `tests/test_run_records.py`.
- [x] **P1.5 `BaseTool.run`/`arun` patch** (FR-R3) — `3b78c98`; `tests/test_tool_record.py`.
- [x] **P1.6 SQLite cassette** under `.sherlock/` (hash key, sequence fallback) — `c089a0b`; `tests/test_cassette.py`.
- [x] **P1.7 Replay + abstain** (FR-G3.5, NFR-3): a miss raises `CannotSay`, never a live call — `471c01d`; `tests/test_replay.py`, `tests/test_launcher.py`.
- [x] **P1.8 Test target + exit criterion** — `32fe394`; `tests/test_exit_criterion.py` (JSON and SSE): record, stop the stub, replay with a socket trap (zero connection attempts, identical output), changed question exits 75 with `cannot say: request changed since recording`. Demo team: `tests/llm_team.py`; stub: `tests/stub_server.py`.

## Next up — Phase 2: checks (Z) and the run-again test (spec §5.2 FR-C1–C6, FR-G3.1–G3.8)

Plan stub; revise against the spec before starting.

1. **Checks (FR-C1–C6):** define Z for a run (pass/fail predicate), starting with demo team #1 and the LLM demo team.
2. **Fork-and-resume driver (FR-G3.1–G3.4):** use the verified fork recipe (`spikes/2026-10-13-fork-recipe.md`) to restore one node's behaviour and re-run.
3. **Behaviour-keyed cassettes (FR-G3.5):** recordings made under a given behaviour; a mismatch abstains. Phase 1 gives the mechanism; the key does not yet include the restored behaviour.
4. **Side-effect allowlist and abort (FR-G3.6–G3.8):** LangGraph re-executes nodes after a fork; Phase 1 serves every tool from the cassette, with no allowlist yet.
5. **Exit criterion:** set from the spec when the phase starts.

## Requirement status

Only requirements that are not ⬜ are listed. IDs are from `sherlock-spec.md` §5.

| ID | Status | Notes |
|---|---|---|
| FR-R1 | ✅ | `sherlock run <cmd>`, no user edits (P1.2, P1.8) |
| FR-R2 | ✅ | Full request/response, status, headers, timing; model and params are in the body (P1.4) |
| FR-R3 | ✅ | Local tools via `BaseTool.run/arun` (P1.5) |
| FR-R4 | 🔨 | Per-node structure available from `tasks[]` |
| FR-R5 | ✅ | SSE kept as the ordered chunk sequence (P1.4, P1.8) |
| FR-R6 | ✅ | Chains the user's `sitecustomize` (P1.3) |
| FR-R7 | ✅ | Bodies and tool I/O recorded in clear by default |
| FR-R8 | 🔨 | Request headers are never stored; no body/PII deny-list yet |
| FR-R9 | ⬜ | Not started: no detection of missing checkpoint history |
| FR-R10 | ✅ | Fixed for LangGraph ≥ 0.5 (P0.1) |
| FR-R11 | 🔨 | LangSmith import, browse-only (`dd37b7d`) |
| FR-E1 | 🔨 | Team 1 of 4–6 (`vendor_brief`) |
| FR-E2 | 🔨 | Single and chained two-node faults on team 1 |
| FR-E3 | 🔨 | Gold by restoring subsets (`gold_minimal_sets`), in-process, deterministic teams only |
| FR-G3.1 | 🔨 | Fork-and-resume verified over HTTP; no product code yet |
| FR-G3.5 | 🔨 | Replay serves only from the cassette and abstains on a miss (P1.7); not yet keyed to a restored behaviour |
| NFR-3 | 🔨 | No live call in replay for httpx and `BaseTool`; `urllib`/`requests`/`aiohttp`/raw sockets are not covered |
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
- **2026-10-14 — Phase 1 verified:** `python/sherlock` 48 tests green on Python 3.12.9 (httpx, langchain-core and langgraph as resolved in `python/sherlock/uv.lock`); `harness` 16 tests still green. Exit criterion proven by `tests/test_exit_criterion.py`.
- **2026-10-14 — httpx:** `Client._send_single_request` wraps `response.stream` after the transport returns, so replacing `response.stream` inside `HTTPTransport.handle_request` is safe. The replacement must subclass `httpx.SyncByteStream`/`AsyncByteStream`, or `iter_raw` raises.
- **2026-10-14 — Windows:** `os.execl` does not replace the process (the parent returns at once), so the launcher uses `subprocess.call`.

## Decision log

- **2026-10-12/13 — team meeting; spec by Ibraheem.** Final scope is `docs/sherlock-spec.md`. No live calls: cache or abstain. The 9 October brief is superseded on method.
- **2026-10-13 — Wajih.** Atomic commits; no AI co-author; the other two members as `Co-authored-by` (see `CLAUDE.md`). Build sessions use Sonnet with an Opus advisor; the token budget is tight.
- **2026-10-13.** Ingestion reads `tasks[].result` instead of diffing checkpoints (more exact than spec §5.1's proposal).
- **2026-10-13 — proposed.** Harness Python lives in `harness/` (uv, Python 3.12), separate from the future `pip install sherlock` package.
- **2026-10-13 — proposed.** Demo teams inject faults through LangGraph runtime `context`, which doubles as the spec §4.4 restoration path.
- **2026-10-14 — Phase 1 build (autonomous).**
  - Launcher uses `subprocess.call`, not `execl` (spec 4.2 says exec). The console script is named `sherlock` per the brief and will clash with the Rust binary until the wheel and CLI are merged.
  - Cassette matching is strict by default: only a request-hash match is served, and a changed request abstains. The sequence-order fallback (spec 9.3) is opt-in via `--match sequence` and serves the next unconsumed call with the same method and URL, because a default fallback would serve changed requests and break FR-G3.5.
  - `CannotSay` derives from `BaseException` so retry loops and `except Exception` cannot swallow it. The launcher also reads the stored abstain reason after exit and returns 75, so a swallowed abort still aborts.
  - In replay, a bootstrap or patch failure exits 75 rather than "never kill the process", since running unpatched could go live (NFR-3). In record mode, failures only warn.
  - Cassette: one SQLite file `.sherlock/cassette.db`, replaced on each record run. Request headers are never stored. Tool outputs are stored pickled (for replay) plus readable text.
  - Replay serves every tool from the cassette; the side-effect allowlist is Phase 2 (FR-G3.8).
  - The test target lives in `python/sherlock/tests/` (not `harness/`); the LLM node uses httpx directly against the stub, with no provider SDK.

## Open items

Beyond spec §10:

- **Phase 1 smoke test:** all Phase 1 tests use the local stub; no real-provider smoke test was run (no keys). Which provider and key? *(Proposal; the team should confirm.)* Real SDK streaming (openai/anthropic over httpx) is unverified.
- **Phase 1 gaps:** FR-R9 not done; body PII deny-list (FR-R8) not done; only httpx and `BaseTool` are intercepted (`requests`/`urllib`/`aiohttp` are not); replay consumption state is per process; `sherlock doctor` (FR-R12) not started.
- The spec cites governing documents in `causal-debugger/` that are not in this repo. Add or link them.
- Competitors missing from spec §3: TraceSurgeon (`ahhbhishek/tracesurgeon`, MIT, LangGraph) and Agent-Casuality (PyPI `agent-casuality`). Review before mid-eval.
- Spec §1.2 and §9.1 say most real bugs live in deterministic nodes; this is unsourced. Measure the abstain rate on real failures early.
- The mid-evaluation date and the required demo.
- `ui/dist` must exist for the `api` crate to compile. Run `cd ui && npm run build`; an empty `ui/dist/` is enough for tests.

## Session log

- **2026-10-14** — Phase 1 complete on `phase-1` (8 atomic commits): `python/sherlock` recorder, replay and abstain; 48 tests; harness suite still green.

- **2026-10-13** — Phase 0 complete on `phase-0`:
  - harness and demo team #1 (16 tests);
  - fork-recipe spike 20/20;
  - ingestion fixed to read `tasks[].result` (Rust tests, clippy and fmt green);
  - tracker, `CLAUDE.md` and the commit policy added;
  - Rust installed (GNU toolchain).
