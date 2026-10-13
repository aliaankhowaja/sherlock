# Sherlock — build status

> **This is the live progress tracker.** Read it before starting work; update it before you stop.
> Scope is set by [`sherlock-spec.md`](sherlock-spec.md), which governs. The status columns inside the spec are a 12 October snapshot — **live status lives here only.** Session rules (model, commits) are in [`../CLAUDE.md`](../CLAUDE.md).

**Last updated:** 2026-10-14 · **Current phase:** 4 — G0, G2, intake, known-good sources, not started · **Branch:** `phase-3` (Phase 3 done, branched off `phase-2`; merge, then branch `phase-4`)

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
| 2 | Checks (Z) and the run-again test (G3) | ✅ done 2026-10-14 |
| 3 | Minimality search, verdicts, budget | ✅ done 2026-10-14 |
| 4 | G0, G2, intake, known-good sources | ⬜ next |
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

## Phase 2 — checks (Z) and the run-again test (G3) ✅

Code: `python/sherlock/src/sherlock/{checks,g3,redact}.py`, CLI `sherlock-rec check|g3`. Run: `cd python/sherlock && uv run pytest -q` (120 tests incl. 10 live, about 2 min).

- [x] **P2.0 Leftovers.** Console script renamed `sherlock-rec` — `bb90f8e`. FR-R8 deny-list redaction of stored requests — `c343ef8`; `tests/test_redact.py`. FR-R9 no-usable-history detection, in the G3 driver (`history_usable`; Rust ingestion untouched) — `f498a67`; `tests/test_g3_unit.py`.
- [x] **P2.1 Check file and assertions** (FR-C1–C6, C9) — `a5ef2e8`; `tests/test_checks.py` (34): `sherlock.yaml` auto-discovery and `-c`, `file://` against the config dir, `not-` on every type, `is-json` with schema, per-assertion `{pass, score, reason}`.
- [x] **P2.2 Per-trial replay, allowlist, replay marker** (FR-G3.5, G3.8) — `8589b3d`; `tests/test_trials.py`.
- [x] **P2.3 G3 driver** (FR-G3.1–G3.5, G3.7, G3.9): fork, restore via `context`, resume, verify, apply Z — `f498a67`; `tests/test_g3_unit.py` (fake server on the real fixture).
- [x] **P2.4 Live exit criterion** — `fa9570f`; `tests/test_g3_live.py`. Real `langgraph dev` recorded, restarted under `--replay` inside a socket trap (no non-loopback connection, stub provider stopped): single-fault run, restoring the faulty node returns **pass**; restoring router/retriever/writer/reviewer returns **fail**; the two-cause run needs {retriever, extractor}; a changed LLM request returns **abstain** (`request changed since recording`); CLI exit codes 0/1/75/2. The trap file stayed empty.
- [x] **P2.5 Abstain fix** — `b0f4b0d`: `CannotSay` is now an `Exception` (see Decision log).

Not done in Phase 2: FR-G3.10 limitation text; FR-C7/C8/C10/C11; interceptor-level restoration (§4.4 primary); a Rust `sherlock g3` wrapper (the engine is Python, see Decision log).

## Phase 3 — the search ✅

Code: `python/sherlock/src/sherlock/{search,diagnose}.py`, CLI `sherlock-rec diagnose`. Run: `cd python/sherlock && uv run pytest -q` (162 tests incl. 18 live, about 2.5 min); `cd harness && uv run pytest -q` (17).

- [x] **P3.1 Pruning** (FR-D1, D2): ancestry from the recorded supersteps plus no-op restores; nodes without known-good are `untestable`, never pruned — `1bcf3d4`; `tests/test_search.py`.
- [x] **P3.2 Search** (FR-D3-D5, D13): feasibility probe, then singletons, pairs, up to `--max-size`; supersets of a passing set skipped; every 1-minimal set returned; each set tried once — `1bcf3d4`.
- [x] **P3.3 Verdicts and abstain reasons** (FR-D6, D7, D11): four labels per trial, counts ("1 of 3"), trial log, reason codes `no_candidates | no_known_good | unrecorded_call | cannot_test | budget_exhausted | cutoff | not_fixable | already_passes | no_history` — `1bcf3d4`.
- [x] **P3.4 Budget** (FR-D8, D9): `--max-trials 40`, `--max-minutes 10`, `--max-size 3`; exhaustion is an abstain (or a find marked incomplete) — `1bcf3d4`.
- [x] **P3.5 `diagnose` and artifact**: `sherlock-rec diagnose --thread-id --known-good [-c] [--max-*]`, JSON at `.sherlock/diagnoses/<thread_id>.json` (schema 1, for the Phase 5 UI); exit 0 found, 75 cannot say, 2 error — `e5210e2`; `tests/test_diagnose_unit.py` (fake server).
- [x] **P3.6 Live exit criterion** — `1f7c0c6`; `tests/test_g3_live.py` against a real `langgraph dev` in a socket trap: single fault returns {extractor} in 1 trial, chained run returns {retriever, extractor} in 3 trials with both singletons failing, both equal to the harness `gold_minimal_sets`; writer fault matches gold; harmless fault is `already_passes`; a changed LLM request abstains (`unrecorded_call`: "request changed since recording"); `--max-trials 2` abstains `budget_exhausted`; the trap file stayed empty.

Not done in Phase 3: FR-D10 flakiness pre-check (S; trials replay the cassette, so they are deterministic), FR-D12 ordering (C), widening on an empty candidate set (open item 3). "Partly helps" is by Z score only.

## Next up — Phase 4: G0, G2, intake, known-good sources (spec 5.4, 5.6, 5.8)

Plan stub; revise against the spec before starting.

1. **G0 (FR-G0.1-G0.5):** programmatic flags from the tape: schema-invalid tool calls, empty retrieval, malformed JSON, extractive tokens in the final output absent from upstream, loop detector. Clues only; they may widen the candidate list (feeds `plan_candidates`, which today only prunes). Decide open item 3 (empty candidates after widening).
2. **G2 (FR-G2.1-G2.3):** a candidate must name a recorded arrow; no arrow, discard. Deterministic, only rejects.
3. **Intake (FR-I1-I5):** FAIL via mismatch or check; "Wrong" click with no node named; a marked-wrong run becomes diagnosable once a check or known-good is added. Needs a run-intake record under `.sherlock/`.
4. **Known-good sources (FR-K1-K6):** passing run of the same input compared node by node (FR-K1, test only differing nodes); pasted per-node output (K2); confirmed prior success (K3); two disagreeing successes abstain (K4). Today known-good is a hand-written per-node context patch (`--known-good`).
5. **Open for this phase:** `diagnose` still restores only through run `context`; K1/K2 restore outputs, which needs interceptor-level or `as_node` restoration (spec 4.4 primary) and must not break FR-G3.3/G3.4.

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
| FR-R8 | ✅ | Headers never stored; stored requests redacted against a documented deny-list (`redact.py`, P2.0). Responses and tool outputs are kept verbatim (replay needs them) |
| FR-R9 | 🔨 | G3 abstains on unusable history (P2.0); not yet in Rust ingestion or the UI |
| FR-R10 | ✅ | Fixed for LangGraph ≥ 0.5 (P0.1) |
| FR-R11 | 🔨 | LangSmith import, browse-only (`dd37b7d`) |
| FR-E1 | 🔨 | Team 1 of 4–6 (`vendor_brief`) |
| FR-E2 | 🔨 | Single and chained two-node faults on team 1 |
| FR-E3 | 🔨 | Gold by restoring subsets (`gold_minimal_sets`), in-process, deterministic teams only |
| FR-C1–C6 | ✅ | Check loader and assertions (P2.1). Also `icontains-all/any` (see Decision log) and FR-C9 |
| FR-G3.1 | ✅ | `g3.py` forks over HTTP; original thread verified unchanged (P2.3, P2.4) |
| FR-G3.2 | 🔨 | Known-good behaviour via a per-node context patch file; known-good sources are Phase 4 |
| FR-G3.3, G3.4 | ✅ | Resume with `input: null` from the fork checkpoint; we never write post-fork outputs (P2.3) |
| FR-G3.5 | ✅ | Calls served only from the cassette, miss abstains; the strict request hash already encodes the restored behaviour (P2.4: changed request abstains, unchanged request is served) |
| FR-G3.6 | ✅ | Strict hash match, no cross-recording fill; a cassette holds one failed run's calls |
| FR-G3.7 | ✅ | Prefix state and `next` compared, context and re-run of restored nodes verified, original unchanged; else "replay went off track" (P2.3) |
| FR-G3.8 | ✅ | Replay never executes a tool; `--allow-tool` aborts any unlisted one (P2.2) |
| FR-G3.9 | ✅ | Trials sent with `durability: "sync"` |
| NFR-3 | 🔨 | No live call in replay for httpx and `BaseTool`; `urllib`/`requests`/`aiohttp`/raw sockets are not covered |
| FR-D1, D2 | ✅ | Ancestry pruning from the recorded supersteps plus no-op restores; conservative; ratio reported (P3.1) |
| FR-D3, D4, D5 | ✅ | Singletons, pairs, up to 3; every 1-minimal set returned, none collapsed; chained pair found with singletons failing (P3.2, P3.6) |
| FR-D6, D7, D11 | ✅ | Four labels, first-class abstain with reason code and sentence, counts and trial log in the artifact (P3.3) |
| FR-D8, D9 | ✅ | `--max-trials/--max-minutes/--max-size`; cutoff documented in `search.py` and the Decision log (P3.4) |
| FR-D10, D12 | ⬜ | Flakiness pre-check and ordering not built (see Decision log) |
| FR-D13 | ✅ | Sets of 3 by default; configurable with `--max-size` |
| NFR-8 | ✅ | 31 exhaustive trials vs 1 (single) and 3 (two-cause) on team 1: 97% and 90% fewer; `trial_reduction` in the artifact |
| FR-E3 | ✅ | Live `diagnose` results equal `gold_minimal_sets` for single, two-cause and writer runs (P3.6) |
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

- **2026-10-14 — Phase 2 verified (live, langgraph-api 0.16.0):**
  - `runs/wait` returns HTTP 200 with `{"__error__": {error, message}}` when a node raises. Check the body.
  - A run's context is in `GET /threads/{id}/runs/{run_id}` under `kwargs.context`; a checkpoint's `metadata.run_id` links to it. Context keys are also flattened into checkpoint metadata.
  - A node raising a `BaseException` kills the dev server's only worker: the run stays "running" and `runs/wait` never returns. An ordinary `Exception` fails the run cleanly.
  - `langgraph dev` calls `pypi.org` at startup (a live call); `LANGGRAPH_NO_VERSION_CHECK=1` stops it. Found by the socket trap.
  - `langgraph dev` persists threads to `.langgraph_api/`; stopping it with Ctrl-Break (Windows) flushes them, so a recorded thread survives a restart under `--replay`.
  - The dev server makes no httpx or tool calls of its own: a replay server's cassette stayed at 0 calls and 0 abstains.
  - A fork thread built from `tasks[].result` writes has the same `values` and `next` as the original fork point (prefix check passes on a real server).

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

- **2026-10-14 — Phase 2 build (autonomous).**
  - **Engine stays in Python** (spec 4.1 puts it in Rust). Cassette, interceptors, harness and live-server fixtures are all Python; G3 is mostly HTTP and state plumbing, so a Rust engine would mean a Python-to-Rust bridge for no gain yet. `g3.py` and `checks.py` are plain modules that a PyO3 core can absorb later. The CLI is `sherlock-rec` for now; a Rust `sherlock g3` wrapper is open.
  - **`CannotSay` is an `Exception`** (supersedes the Phase 1 BaseException choice). A BaseException hangs `langgraph dev`; swallowing is still caught because the abstain is stored in the cassette first and read back by the launcher and G3.
  - **G3 does not start the server.** The user runs `sherlock-rec run --replay <server cmd>` against a recorded, persisted server. G3 refuses unless the cassette was marked by a replay process (`replay_sessions`), which guards against pointing it at a live-capable server (weak: the marker is not tied to a pid).
  - **Restoration uses the run `context` path only** (spec 4.4 secondary). Known-good file per node: `{context_key: value | {"$remove": [...]}}`, composed over the original run's context (read from the run record). Interceptor-level restoration is not built.
  - **Check file shape:** `assert:` or `defaultTest.assert:` (promptfoo); `tests:` is rejected; `output_key` (default `final_output`) names the state key to score. Spec says "eight assertions" but FR-C3 lists seven; added promptfoo's `icontains-all` and `icontains-any`.
  - **Per-trial consumption:** `Cassette.start_trial()` bumps a counter that replay processes read on each lookup, so one replay server serves many trials. This closes the Phase 1 gap "replay consumption state is per process".
  - **Redaction applies to the stored request only**; hash and responses are untouched, so replay is unchanged. Only email is covered as PII.
  - **Abstain semantics:** G3 returns `abstain` (exit 75) for a cassette miss, a failed trial run, unusable history, an original that already passes Z, a missing known-good, and "replay went off track". Exit 2 is reserved for setup errors.
  - Dev deps for tests: `langgraph-cli[inmem]`. Runtime deps added: `pyyaml`, `jsonschema`.

- **2026-10-14 — Phase 3 build (autonomous).**
  - **Subset cutoff (spec open item 2, FR-D9):** sets of at most 3 nodes (`--max-size`), at most 40 trials, at most 10 minutes, whichever first. Never enumerate 2^k: each set is tried once, supersets of a passing set are skipped. Sets of three (FR-D13, could) come free with the size cap.
  - **Feasibility probe:** with 2+ candidates the first trial restores all of them. If that fails, nothing inside the candidates can pass, so the search abstains (`not_fixable`) after one trial. If it passes but no set within the cutoff does, the abstain is `cutoff`. Assumes restoring more never hurts (holds on team 1). It only shortcuts the negative case; positive results always come from a direct trial.
  - **Pruning:** (1) ancestry: a node can reach `output_key` only if it ran in a superstep up to the last write of that key, and in that superstep only the writer itself (parallel nodes cannot feed it); with no writer found, nothing is pruned by ancestry. Read-dependencies are unknown, so earlier nodes are always kept. (2) no-op restore: if the node's known-good patch leaves the run context unchanged, a trial would replay the original, so the node cannot be a cause or part of a minimal set. Exact for the context path; uses the known-good file and recorded context, not the planted fault names.
  - **Nodes with no known-good** are `untestable`, not pruned. They stay out of the search; a found set is still valid but the result is `complete: false` with a note, and a negative result is the abstain `no_known_good`.
  - **Trial abstains:** a set whose trial abstains is "cannot say". A passing superset of such a set goes to `unverified_sets`, not `minimal_sets`, because minimality cannot be certified. With no certified set the result is an abstain (`unrecorded_call` when a cassette miss was seen, else `cannot_test`).
  - **Result status:** `found` (every certified 1-minimal set; `complete` says whether every set up to the candidates was decided) or `abstain`. A budget stop after a find keeps the find with `complete: false`.
  - **"Partly helps"** = Z failed but the mean assertion score rose above the original run's. No repeat trials: the cassette makes every trial deterministic, so FR-D10 (should) is left out. No widening on an empty candidate set (open item 3): it is an abstain until G0 exists in Phase 4.
  - **Artifact:** `.sherlock/diagnoses/<thread_id>.json` next to the cassette (`--out` overrides), schema 1. `search.py` is pure (fake-oracle tested); `diagnose.py` wires G3 to it. G3 now tags cassette-miss abstains (`evidence.cassette_miss`).

## Open items

Beyond spec §10:

- **Phase 1 smoke test:** all Phase 1 tests use the local stub; no real-provider smoke test was run (no keys). Which provider and key? *(Proposal; the team should confirm.)* Real SDK streaming (openai/anthropic over httpx) is unverified.
- **Phase 3 gaps:** known-good is still a hand-written context patch, so only context-configurable behaviour can be restored; `diagnose` was only exercised on team 1 and a small LLM graph. `complete` is conservative (any untestable node or cassette miss makes it false).
- **Phase 1 gaps:** only httpx and `BaseTool` are intercepted (`requests`/`urllib`/`aiohttp` are not); `sherlock doctor` (FR-R12) not started.
- The spec cites governing documents in `causal-debugger/` that are not in this repo. Add or link them.
- Competitors missing from spec §3: TraceSurgeon (`ahhbhishek/tracesurgeon`, MIT, LangGraph) and Agent-Casuality (PyPI `agent-casuality`). Review before mid-eval.
- Spec §1.2 and §9.1 say most real bugs live in deterministic nodes; this is unsourced. Measure the abstain rate on real failures early.
- The mid-evaluation date and the required demo.
- `ui/dist` must exist for the `api` crate to compile. Run `cd ui && npm run build`; an empty `ui/dist/` is enough for tests.

## Session log

- **2026-10-14** — Phase 3 complete on `phase-3` (3 code commits): pruning, minimality search, verdict labels, budget, `sherlock-rec diagnose` and the JSON artifact. 162 recorder tests (18 live) and 17 harness tests green; on team 1 `diagnose` equals gold for the single and two-cause runs (1 and 3 trials of 31) and abstains on the cache-miss case. Rust untouched.
- **2026-10-14** — Phase 2 complete on `phase-2` (7 atomic commits): checks, G3 driver, redaction, per-trial replay and allowlist, `sherlock-rec` rename; 120 recorder tests (10 live against `langgraph dev`) and 17 harness tests green. First real verdicts: pass, fail and abstain. Rust untouched.
- **2026-10-14** — Phase 1 complete on `phase-1` (8 atomic commits): `python/sherlock` recorder, replay and abstain; 48 tests; harness suite still green.

- **2026-10-13** — Phase 0 complete on `phase-0`:
  - harness and demo team #1 (16 tests);
  - fork-recipe spike 20/20;
  - ingestion fixed to read `tasks[].result` (Rust tests, clippy and fmt green);
  - tracker, `CLAUDE.md` and the commit policy added;
  - Rust installed (GNU toolchain).
