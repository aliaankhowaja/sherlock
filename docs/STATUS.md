# Sherlock — build status

> **This is the live progress tracker.** Read it before starting work; update it before you stop.
> Scope is set by [`sherlock-spec.md`](sherlock-spec.md), which governs. The status columns inside the spec are a 12 October snapshot — **live status lives here only.** Session rules (model, commits) are in [`../CLAUDE.md`](../CLAUDE.md).

**Last updated:** 2026-10-14 · **Current phase:** 6 — evaluation done; the planned phases are complete · **Branch:** `phase-6` (branched off `phase-5`; merge phases 0-6 in order)

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
| 4 | G0, G2, intake, known-good sources | ✅ done 2026-10-14 |
| 5 | Surface: run page, verified colouring, evidence panel | ✅ done 2026-10-14 |
| 6 | Evaluation: remaining teams, baselines, hidden set, CI invariants | ✅ done 2026-10-14 |

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

## Phase 4 — G0, G2, intake, known-good sources ✅

Code: `python/sherlock/src/sherlock/{clues,sources,intake,diagnose}.py` (+ `search.py`, `g3.py`, `cli.py`). Run: `cd python/sherlock && uv run pytest -q` (208 tests incl. 24 live, about 2.8 min); `cd harness && uv run pytest -q` (17).

- [x] **P4.1 G0 clues** (FR-G0.1-G0.5): node errors, empty values, malformed JSON, loop, extractive tokens (numbers, URLs, quoted strings absent from every upstream packet), tool-call errors/invalid args from the cassette. Clues are evidence (`strength: "clue"`), order the search, and widen it only when `widens` — `c0c4ddf`; `tests/test_clues.py`.
- [x] **P4.2 G2 path check** (FR-G2.1-G2.3): `--suspect NODE[->NODE]` must name a recorded arrow or is discarded with a reason; none left is the abstain `path_check_failed` — `c0c4ddf`, `47f86d7`.
- [x] **P4.3 Intake** (FR-I1-I4): `sherlock-rec intake` writes `.sherlock/intake/<thread>.json` (wrong / expected / check); `diagnose` reads it; a run marked wrong with no check returns clues and abstains `no_check` — `aa7d75c`; `tests/test_intake.py`. FR-I5 (one URL `/runs/:id`) is Phase 5.
- [x] **P4.4 Known-good from a prior success** (FR-K1, K3, K4, K5): `--good-run` / `--discover-good`; same-output nodes skipped, context difference becomes a per-node patch, picker ranks fewest-differing then newest, several successes are all searched and disagreement abstains — `47f86d7`; `tests/test_sources.py`, `tests/test_diagnose_sources.py`.
- [x] **P4.5 FR-D12 ordering** (candidates ordered by clue weight; speed only) — `c0c4ddf`. FR-D10 flakiness pre-check not built (see Decision log).
- [x] **P4.6 Live exit criterion** — `tests/test_g3_live.py::test_phase4_*` against a real `langgraph dev` in the socket trap (6 tests, ~50 s alone): starting from only a failed run and a prior success, no patch file, `diagnose` returns {retriever, extractor} for the two-cause run in 3 trials of 31 (90% fewer), {extractor} and {writer} for single faults in 1 trial each, all equal to `gold_minimal_sets`; the `differs_from_passing_run` clue is shown on `extractor`; a named failing run is rejected as a source (`does not pass the check`); `--suspect planner` abstains `path_check_failed` ("planner never ran"); no source abstains `no_known_good`; CLI: `intake` then `diagnose` without a check returns exit 75 `no_check` with the intake record, then with `-c` exit 0.

Not done in Phase 4: FR-K2 as an output paste (the `--known-good` file is a behaviour patch), FR-K3 interactive picker UI (CLI rule only), FR-G1, FR-D10, restoration other than the run `context` path, FR-I5/FR-U (Phase 5).

## Phase 5 — surface ✅

Code: `crates/app-core/src/diagnosis.rs`, `crates/api` (`/api/diagnoses`, `/api/info`), `crates/cli` (`sherlock diagnoses`), `ui/src/{Guide,RunPage,parts,terms,share,route,api}`. Run: `./scripts/test.sh`; look: `sherlock serve --sherlock-dir harness/fixtures/sherlock-demo`.

- [x] **P5.1 Artifact reader (app-core).** `parse_artifact` validates schema 1 (bad schema, bad status, "found" with no set, "abstain" with sets are all refused with a plain reason); `DiagnosisStore` lists newest first, reports broken files, guards ids — `1953ecb`; 6 tests, two on real artifacts.
- [x] **P5.2 Verified node status.** culprit = in a minimal set; cleared = tested candidate in a complete search and in no set; unverified = pruned, untestable, in an unverified set or search incomplete; abstained = every node when the diagnosis abstained. Pruned is never "cleared" — `1953ecb`.
- [x] **P5.3 API** — `GET /api/diagnoses`, `/api/diagnoses/{thread_id}` (400/404/422), `/api/info`; `serve --sherlock-dir` — `7879a0a`; 5 tests.
- [x] **P5.4 CLI** — `sherlock diagnoses list|show [--json] [--sherlock-dir]` (CLI path first, rule 1) — `1790ef2`; 4 tests.
- [x] **P5.5 UI** — home = four-step guide (pick failed run, pick known-good run, copy the exact `sherlock-rec diagnose` command, read the verdict) with empty/error states and a glossary; `/runs/:id` = verdict card, failed-check strip, per-node timeline coloured by verified status (glyph + words, not colour alone), evidence panel (known-good source, how much was tested, hints marked weaker, limits), trial log, read-only HTML and JSON download; old dashboard at `/explore` — `bee110a`. Lint and build green.
- [x] **P5.6 Seeded demo (FR-U9 groundwork).** `python/sherlock/tests/seed_demo.py` ran the real pipeline (record on `langgraph dev`, restart under replay in the socket trap, `diagnose`) and wrote `harness/fixtures/sherlock-demo/diagnoses/` (two-cause {retriever, extractor} in 3 trials of 31; single {writer}; abstain `no_known_good`). Screenshots (headless Chrome via `playwright-cli`) in `docs/screenshots/`.
- [x] **P5.7 Engine tweak.** Abstain artifacts now carry `pruning.nodes_on_path` so the run page can draw the path (nothing is claimed about it) — `1953ecb`; `tests/test_diagnose_sources.py`.

Not done in Phase 5: FR-U5 (node input beside output), FR-U6 (a green `ok` span hiding a wrong answer; the page is a check-first view), FR-U7 health checklist, FR-U9 first screen is still the guide (the seed is opt-in via `--sherlock-dir`, not embedded), FR-U10, FR-U14 graph view, FR-I5 mark-wrong button, FR-K3 UI picker beyond the radio list, a button that starts `diagnose` (see Decision log), UI unit tests (no tooling in `ui/`).

## Phase 6 — evaluation ✅

- [x] **P6.1 Four demo teams (FR-E1, E2).** `vendor_brief`, `order_desk` (parallel branches, unprefixed fault flags), `invoice_pipeline` (redundant repair path: two gold sets) and `support_bot` (LLM node calling a local echo stub, the honest-abstain team); single, chained and decoy faults — `03e1725`; `harness/tests/test_catalog.py` (48 harness tests).
- [x] **P6.2 Gold by restoration (FR-E3).** Generic `gold_minimal_sets(team, faults)` in `harness/sherlock_harness/catalog.py`; `test_decoy_fault_is_not_gold`, `test_redundant_repair_gives_two_minimal_sets`.
- [x] **P6.3 `cannot_attribute` gap.** `--node-map FILE` / `node_map=` maps a context item or key to its node, checked before the name-prefix rule; unclaimed items still abstain — `7e5776f`; `tests/test_sources.py`. `order_desk` (flags like `stale_inventory`) diagnoses exactly with it.
- [x] **P6.4 Baselines, scoring, hard slice, hidden set (FR-E4 partly, E5, E6).** `last_node`, `random_node`, `g0_only`, `paste_and_play`; exact / wrong / abstain + Jaccard; seeded hidden set (seed 20261014, 4 per team) disjoint from the 15 visible cases; hard-slice tags defined in `catalog.py` before any method ran — `9612ee3`, `03e1725`; `tests/test_evaluation.py`.
- [x] **P6.5 Runner and results (FR-E7).** `python/sherlock/eval/run_eval.py` records real `langgraph dev` runs, replays in a socket trap, diagnoses 31 cases and writes `docs/eval/results.{json,md}`; Sherlock 30 exact, 0 wrong, 1 abstain (`unrecorded_call`, the by-design LLM case); best baseline 10 exact; 68 trials vs 538 exhaustive (87.4% fewer) — `6f1473d`. Regenerated and diffed identical in 3 separate process runs.
- [x] **P6.6 CI invariants.** The gate's "evaluation" stage fails on any network attempt in replay, any original thread changed by forks, any abstain naming culprits or lacking a reason, or any difference from the committed table; `tests/test_eval_results.py` re-checks the committed file offline (incl. paste-and-play failing every two-cause case, FR-E8) — `1fb062b`.
- [x] **P6.7 `docs/eval/README.md`** with the §9.1 limitations first, method, results and what was not done.

Gate `./scripts/test.sh` green 2026-10-14: 48 harness, 228 recorder (24 live), evaluation stage (31 cases, reproducible), app-core 23, api 16, cli 21 tests, clippy, fmt.

## Redesigned UI backend (phase-6, 2026-10-14)

- [x] `--progress` `rerun` event: each re-run node's input and output per trial, restored nodes marked — `c6a28e9`; `tests/test_progress.py`.
- [x] `app_core::steps` + `GET /api/runs/{id}/steps`: a recorded run step by step (input, changed keys, who fed which key, output, error, timing, log lines, labelled hand-offs) — `f08f7c9`, `95cf2e2`; `crates/app-core/tests/steps.rs` on the real two-cause fixture.
- [x] Graph with per-node evidence, fault flags and known-good source: `GET /api/teams/{id}/graph`, `GET /api/diagnoses/{id}/graph` — `16884bd`, `a0638ea`, `95cf2e2`.
- [x] Run button: `POST /api/diagnose`, `GET /api/jobs[/{id}]`, token/Origin/Host guard, one job at a time, `serve --project/--sherlock-rec` with discovery — `d615ac0`, `48a8263`; `crates/api/src/run_tests.rs`.
- [x] Live check on the demo lab (`eval/live_demo.py`): steps for the undiagnosed `order_desk` failed run; POST without token 403, foreign Origin 403, unlisted id 400, second POST 409; with token the job ended `done` in about 2 s with 10 progress events (incl. `rerun`) and wrote `diagnoses/01a1391f-e082-….json` (`{parse}`, 1 trial).
- [ ] The UI itself (next session; contract in `agents.md` "Web API").
- Gap: the demo lab running during the check was launched before node kinds were declared, so its graph showed `kind: null`; a fresh `live_demo.py` serves the kinds (checked: `get_graph().to_json()` carries `metadata.kind`).

## Remaining / not built

- FR-E9 (live time-travel without call blocking must fail the two-cause case), the plain-LLM-guess and plain-retry baselines, G0+G2 as a separate row: not built (see `docs/eval/README.md`).
- No real-provider or real-failure evaluation; the LLM team uses a deterministic echo stub, so stochastic sampling is not measured. The "most real bugs are in deterministic nodes" claim is still unmeasured.
- Phase 5 leftovers: FR-U5 (node input beside output: API `/api/runs/{id}/steps` done, UI pending), FR-U6, FR-U7, FR-U9 first screen; Rust `sherlock diagnose` wrapper; `sherlock doctor` (FR-R12).
- Interceptors cover httpx and `BaseTool` only.

For the team: (1) decide the mid-evaluation date and the required demo; (2) pick a provider and key for one real smoke test; (3) say whether a shared-cassette cross-case contamination check (see Decision log) should become a permanent test; (4) add the missing `causal-debugger/` governing documents and review TraceSurgeon / Agent-Casuality before mid-eval.

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
| FR-E1 | ✅ | Four teams in `harness/`, one an LLM-node team (P6.1) |
| FR-E2 | ✅ | Single, chained, decoy and OR (redundant-repair) faults across the four teams (P6.1) |
| FR-E3 | ✅ | Gold by restoring subsets (`catalog.gold_minimal_sets`), in-process oracle; also the live-vs-gold agreement in the results table (P6.2, P6.5) |
| FR-E4 | 🔨 | Four cheap baselines on the same tapes and Z: last node, random node, G0 only, paste-and-play. Not built: plain LLM guess, plain retry, G0+G2 row |
| FR-E5 | ✅ | Exact, Jaccard, abstain rate, split one-node / two-node (`results.md`) |
| FR-E6 | ✅ | Hard slice tags defined in `catalog.py` before any method ran |
| FR-E7 | ✅ | Same tapes, new processes: identical minimal sets (gate `--check`) |
| FR-E8 | ✅ | `paste_and_play` fails every two-cause case (`test_eval_results.py`) |
| FR-E9 | ⬜ | Live time-travel baseline not built |
| FR-C1–C6 | ✅ | Check loader and assertions (P2.1). Also `icontains-all/any` (see Decision log) and FR-C9 |
| FR-G3.1 | ✅ | `g3.py` forks over HTTP; original thread verified unchanged (P2.3, P2.4) |
| FR-G3.2 | ✅ | Known-good behaviour via a per-node context patch, written by hand or derived from a prior success (P4.4); output-level restore not built |
| FR-G3.3, G3.4 | ✅ | Resume with `input: null` from the fork checkpoint; we never write post-fork outputs (P2.3) |
| FR-G3.5 | ✅ | Calls served only from the cassette, miss abstains; the strict request hash already encodes the restored behaviour (P2.4: changed request abstains, unchanged request is served) |
| FR-G3.6 | ✅ | Strict hash match, no cross-recording fill; a cassette holds one failed run's calls |
| FR-G3.7 | ✅ | Prefix state and `next` compared, context and re-run of restored nodes verified, original unchanged; else "replay went off track" (P2.3) |
| FR-G3.8 | ✅ | Replay never executes a tool; `--allow-tool` aborts any unlisted one (P2.2) |
| FR-G3.9 | ✅ | Trials sent with `durability: "sync"` |
| NFR-3 | 🔨 | No live call in replay for httpx and `BaseTool`; `urllib`/`requests`/`aiohttp`/raw sockets are not covered. The eval gate runs replay in a socket trap and fails on any attempt |
| FR-D1, D2 | ✅ | Ancestry pruning from the recorded supersteps plus no-op restores; conservative; ratio reported (P3.1) |
| FR-D3, D4, D5 | ✅ | Singletons, pairs, up to 3; every 1-minimal set returned, none collapsed; chained pair found with singletons failing (P3.2, P3.6) |
| FR-D6, D7, D11 | ✅ | Four labels, first-class abstain with reason code and sentence, counts and trial log in the artifact (P3.3) |
| FR-D8, D9 | ✅ | `--max-trials/--max-minutes/--max-size`; cutoff documented in `search.py` and the Decision log (P3.4) |
| FR-D10 | ⬜ | Flakiness pre-check not built: trials replay the cassette, so they are deterministic (see Decision log) |
| FR-D12 | ✅ | Candidates ordered by clue weight (loop, error, extractive, differs-from-passing-run); speed only (P4.5) |
| FR-D13 | ✅ | Sets of 3 by default; configurable with `--max-size` |
| NFR-8 | ✅ | 31 exhaustive trials vs 1 (single) and 3 (two-cause) on team 1: 97% and 90% fewer; `trial_reduction` in the artifact. Across all four teams, 68 trials vs 538: 87.4% fewer (`docs/eval/results.md`) |
| FR-E3 | ✅ | Live `diagnose` results equal `gold_minimal_sets` for single, two-cause and writer runs (P3.6) |
| FR-U13 | ✅ | Per-node timeline, errors first |
| FR-U1 | 🔨 | `/runs/:id` is one page per diagnosed run (P5.5); the node list is a timeline, not a graph in the middle (FR-U14) |
| FR-U2 | 🔨 | Judgment strip shows the failed check and its assertions, plus the intake note; "expected vs actual" text is not shown |
| FR-U3 | ✅ | Nodes coloured by verified status (must change / not needed / not verified / cannot say), computed in `app-core` from the artifact, never by an LLM (P5.2) |
| FR-U4 | 🔨 | Evidence panel and trial log show every trial and result; hints are marked weaker; G1 is not built |
| FR-U8 | ✅ | Several minimal sets are all listed in the verdict and per node |
| FR-U11 | 🔨 | The HTML export has no script and no buttons; there is no hosted share view |
| FR-U12 | 🔨 | Diagnosis list with verdict per run; no question/actual-output columns |
| FR-S4 | ✅ | Read-only HTML export (self-contained, offline) and the raw JSON |
| NFR-4 | ✅ | Every abstain shows its sentence and code in the verdict card |
| NFR-6 | ✅ | Every reported cause sits beside the trial log that backs it |
| NFR-18 | ✅ | The export cannot run or fire anything; `serve` has no endpoint that starts a run or a tool |
| FR-G0.1-G0.5 | ✅ | `clues.py`; clues are evidence, order the search and widen it only for error/empty/malformed/extractive/schema-invalid (P4.1). FR-G0.1 sees tool calls from the cassette only (no node attribution) |
| FR-G2.1-G2.3 | ✅ | Path check on `--suspect`; deterministic, only rejects (P4.2) |
| FR-I1-I4 | ✅ | `intake` records wrong / expected / check; marked-wrong runs are diagnosable once a check or known-good is added (P4.3) |
| FR-I5 | 🔨 | `/runs/:id` exists (P5.5); the "Wrong" button that writes intake does not (CLI `sherlock-rec intake` only) |
| FR-K1, K5 | ✅ | Same-input prior success; per-node output comparison; context difference as behaviour (P4.4) |
| FR-K3 | 🔨 | Picker rule in the CLI (closest, then newest; `--discover-good` is unconfirmed); the UI has a plain radio list, not the ranked picker |
| FR-K4 | ✅ | Successes that disagree abstain `sources_disagree` (P4.4) |
| FR-K2 | 🔨 | Hand-written per-node behaviour patch (`--known-good`); pasting a node's output is not built |
| FR-K6 | ✅ | A final answer is a check: `intake --expected` becomes Z, never a known-good source |
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

- **2026-10-14 — Phase 4 verified (live, langgraph-api 0.16.0):**
  - `POST /threads/search` with `metadata: {graph_id}` returns every thread of the graph, including Sherlock's own trial forks (they carry `metadata.sherlock_fork_of`); discovery must filter them or a passing fork becomes a "source".
  - A prior run's recorded `context` (`GET /threads/{id}/runs/{run_id}` -> `kwargs.context`) is enough to derive a per-node patch on team 1: the failed and passing runs differ only in the `faults` list, whose items are named `<node>.<fault>`.
  - Extractive check, open item 6: 0 false positives over all 64 fault subsets of team 1 (`tests/test_clues.py`). This says little about LLM teams, which paraphrase and compute numbers; measure there in Phase 6.
  - Live diagnose from a prior success equals `gold_minimal_sets` for the single (extractor), writer and two-cause (retriever + extractor) runs; the two-cause run takes 3 trials of 31.

- **2026-10-14 — Phase 6 verified (live, `langgraph dev` under `sherlock-rec run --replay`, no provider):**
  - On four teams and 31 cases (15 visible, 16 seeded hidden), `diagnose` from the failed run plus one passing run equals the in-process gold on 30; the 31st (`support_bot:prep.truncate+ask.terse_instruction`) abstains `unrecorded_call`. Zero wrong claims. Baselines: g0_only 10 exact, last_node 5, paste_and_play 5, random_node 4 (`docs/eval/results.md`).
  - Redundant repair path (`invoice_pipeline`): either `extract` or `normalize` alone fixes the run, and `diagnose` returns both minimal sets.
  - A cassette shared by several LLM-team cases turned the never-recorded combination (spec 9.1) into a hit: the first run of the eval showed no abstain at all. Giving each LLM-team case its own lab and cassette fixed it. A real engineer's cassette holds whatever was recorded, so on a busy cassette Sherlock may resolve more than the single-case run does; that is honest (the call was recorded) but changes the abstain rate.
  - Whole table regenerated in 3 separate process runs (new ports, thread ids, temp dirs): byte-identical `results.json`. One eval takes about 5 minutes.
  - Building an httpx client costs about 0.75 s on this Windows machine (SSL context), which dominates LLM-team runs.
- **2026-10-14 — end-to-end web check ([`verification.md`](verification.md)):** `eval/live_demo.py` ran the real pipeline on four teams (five diagnoses: two-cause, single, redundant fix, LLM-team abstain `unrecorded_call`), `sherlock serve` pointed at the live replay server, and headless Chromium walked guide, run pages, HTML/JSON downloads, `/explore`, server-down and empty states. Fixed: Sherlock's own trial threads listed as runs, seeded diagnoses missing from the guide's run list (the known gap), failed runs offered as known-good, abstain page repeating the raw reason on every node, spec codes in user text, green "idle" in `/explore`. One browser, one viewport, synthetic data.

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

- **2026-10-14 — Phase 4 build (autonomous).**
  - **Known-good = a prior successful run's recorded behaviour.** Eligible when it has the same input (the `__start__` write), passes Z, and has usable history. Per node: output equal to the failed run's -> not tested (FR-K1, pruned, widened back only by a clue that `widens`); behaviour = the difference between the two runs' recorded run `context`. Output-level restore (K2 paste) is not built: it would restore a message, not behaviour, and the GCJR gap (Phase 0) says that gives the wrong set on chained faults.
  - **Attribution rule:** a context item (list element) or key belongs to the node whose name it equals or starts with, followed by `.`, `:`, `/`, `_` or `-` (longest name wins). Unclaimed or good-run-missing differences abstain `cannot_attribute` rather than guess. This is a naming convention, not magic; `--known-good FILE` overrides per node.
  - **Nodes whose recorded behaviour equals the good run's** get an empty patch, so the existing no-op rule prunes them; they are not `untestable`.
  - **Picker rule (open item 5, CLI form):** eligible sources only; fewest differing nodes, then newest; up to 3 are each searched with the full budget, `known_good_source` is the first that found a set. Two found sets that differ abstain `sources_disagree` (FR-K4); a source that merely abstains does not veto. `--good-run` is the engineer's confirmation; `--discover-good` runs are marked `confirmed: false` (FR-K3: never a silent oracle). Trials are per source, so a multi-source diagnosis can use up to 3x the trial budget.
  - **Open item 3 (empty candidates after widening):** abstain. Candidates come from pruning, not G1; widening only returns pruned nodes that carry a `widens` clue, and an empty set stays `no_candidates` (or `path_check_failed` when suspects were given). G0 alone never produces a verdict.
  - **G2 without G1:** the nominator is the engineer (`--suspect`), since G1 (hosted model) is out of scope here. With suspects, the search is limited to kept suspects plus clue-widened nodes and `complete` is false. Without suspects G2 is not run; the pruning already requires a tape position.
  - **Clue scope:** FR-G0.1 sees only the cassette, which records no node, so tool-call clues name no node and never widen a specific node. "Out-of-role" (FR-D12) needs role text and is not built. Loop = a node that wrote the identical result twice.
  - **FR-D10 skipped:** trials replay a strict cassette, so a re-run cannot differ; a flakiness check would always say "stable". Revisit if replay ever tolerates nondeterminism.
  - **Intake lives next to the cassette** (`.sherlock/intake/`), read by `diagnose`; `-c` beats the intake record, which beats an auto-discovered `sherlock.yaml`. `--known-good` became optional; with no source at all `diagnose` abstains `no_known_good` (exit 75) instead of erroring.
  - **Artifact:** schema stays 1; fields were only added.

- **2026-10-14 — Phase 5 build (autonomous).**
  - **No "run diagnosis" button.** The UI shows the exact `sherlock-rec diagnose` command with a copy button. A button would make `serve` spawn a process from an HTTP request: any web page could post to `localhost` and start commands (no auth on `serve`), and a diagnosis needs a replay server the user starts anyway. Revisit with a token and a job queue if the demo needs it.
  - **Colour rules live in `app-core`, not the UI.** Culprit only for a node in a G3-verified minimal set; cleared only for a tested candidate in a complete search; everything pruned or untested is "not verified" (skipped is not cleared); an abstain colours every node "cannot say". The reader refuses artifacts that contradict themselves (abstain with sets, found with none).
  - **Artifact only, no live join.** The run page renders from the artifact alone (it works with LangGraph down and the export is self-contained). Node inputs and outputs from `/api/logs` are not shown (FR-U5 later).
  - **Routing:** real paths (`/`, `/explore`, `/runs/:id`) with `history.pushState`; the existing SPA fallback serves them. No router dependency.
  - **Share:** the export is the rendered report's HTML plus the page CSS, with every `data-noshare` element removed and no script. JSON is the raw artifact.
  - **Demo seed:** checked in as `harness/fixtures/sherlock-demo/` (a `--sherlock-dir`), generated by the real pipeline, not hand-written. Its thread ids do not exist on a fresh server; since the 2026-10-14 verification pass the guide still lists them (tagged diagnosed) for the matching team.
  - **`short(id)`** now shows `first8…last4`: UUIDv7 ids share their first 8 characters.
- **2026-10-14 — Phase 6 build (autonomous).**
  - **Node map instead of a smarter attribution.** `--node-map FILE` (`{context item or key: node}`) is the whole fix for the `cannot_attribute` gap. The alternatives (guess from which node's output differs, or split a global key) would claim causes the data does not support. The harness derives the map from each team's fault catalogue; it is used only to restore, never to build gold.
  - **Cases and slices.** 15 visible cases picked by hand; hidden = seeded sample (seed 20261014, 4 per team) of 1- and 2-fault combinations not in the visible list that still fail Z. Hard slice = `two_cause`, `or_fix`, `silent_decoy`, `abstain_by_design`; `last_step_ok` separate. `expect_abstain` is a rule (LLM team, faults on two nodes that both change the model request), not a per-case judgment.
  - **Scoring.** exact / wrong claim / abstain, never merged; Jaccard over the union of named nodes, answered cases only. A baseline predicts a collection of node sets like Sherlock does, so the cause definition is shared (spec 9.3).
  - **Baselines kept cheap.** last node, seeded random node, G0 clues only, paste-and-play. Plain LLM guess needs a model and key; plain retry adds no information; FR-E9 would need a live-fallback implementation. Listed as not built.
  - **Runner is a script, not a `sherlock-rec` verb.** It needs the harness and the live-test server helpers, which are not part of the installed package; the pure parts (baselines, scoring, checks) live in `src/sherlock/evaluation.py`.
  - **One lab for all deterministic teams, one lab per LLM-team case** (see Verified facts on cassette contamination).
  - **Gate cost.** The evaluation stage adds about 5 minutes to `./scripts/test.sh` and is the reproducibility check; `tests/test_eval_results.py` is the fast offline half.

- **2026-10-14 — run button security (redesigned UI backend).** A browser-started diagnosis is allowed, but only under all of these, enforced in `api/src/run.rs` and `app_core::runner`:
  - `serve` binds loopback; `--project` (or a discovered project) on a non-loopback `--host` refuses to start. LangSmith source: button off.
  - With the button on, every request needs a loopback `Host` (127.0.0.1 / localhost / [::1], serve's port) so a DNS-rebound page cannot read `GET /api/info`.
  - `POST` needs the per-process random `X-Sherlock-Token` from `GET /api/info` (a cross-origin page cannot read it), an `Origin` of this server when one is sent, and no `Sec-Fetch-Site: cross-site`.
  - Only the fixed argv `sherlock-rec diagnose --progress --thread-id F --good-run G --url --cassette -c --out [--node-map]` is spawned, without a shell; ids must be well formed and listed by the LangGraph server for that team, not Sherlock trial forks, failed != good.
  - One job at a time (409 otherwise), killed after 15 minutes; progress is polled (`GET /api/jobs/{id}`), not streamed, to keep the server simple.
  - Token is generated from the standard library's OS-seeded hasher keys (no new dependency); good enough for a localhost CSRF token, not a secret store.

## Open items

Beyond spec §10:

- **Phase 6 gaps:** the evaluation is synthetic (our teams, our planted faults, an echo stub for the LLM team) and small (31 cases), so 30 of 31 exact says the pipeline matches the in-process oracle, not that real failures are diagnosed. The hidden set is hidden from tuning only. Not built: FR-E9, plain-LLM-guess and plain-retry baselines. Gate time grew by about 5 minutes. See `docs/eval/README.md`.
- **Phase 5 gaps:** no UI test tooling (verified by lint, build, headless screenshots and API/CLI tests); screenshots were refreshed 2026-10-14; `_early` abstains carry no `graph_id`, so the list shows `-` for them.
- **Phase 4 gaps:** attribution by name prefix suits teams that name behaviour per node (team 1 does); teams with global prompts or a single `system_prompt` key abstain `cannot_attribute` unless the engineer supplies `--node-map` (Phase 6); there is no automatic way to split a shared key between nodes. Now live-tested on four teams. Multi-source diagnosis multiplies trials. A Rust `sherlock diagnose` wrapper does not exist.
- **Phase 1 smoke test:** all Phase 1 tests use the local stub; no real-provider smoke test was run (no keys). Which provider and key? *(Proposal; the team should confirm.)* Real SDK streaming (openai/anthropic over httpx) is unverified.
- **Phase 3 gaps:** known-good is still a hand-written context patch, so only context-configurable behaviour can be restored; `diagnose` was only exercised on team 1 and a small LLM graph. `complete` is conservative (any untestable node or cassette miss makes it false).
- **Phase 1 gaps:** only httpx and `BaseTool` are intercepted (`requests`/`urllib`/`aiohttp` are not); `sherlock doctor` (FR-R12) not started.
- The spec cites governing documents in `causal-debugger/` that are not in this repo. Add or link them.
- Competitors missing from spec §3: TraceSurgeon (`ahhbhishek/tracesurgeon`, MIT, LangGraph) and Agent-Casuality (PyPI `agent-casuality`). Review before mid-eval.
- Spec §1.2 and §9.1 say most real bugs live in deterministic nodes; this is unsourced. Measure the abstain rate on real failures early.
- The mid-evaluation date and the required demo.
- `ui/dist` must exist for the `api` crate to compile. Run `cd ui && npm run build`; an empty `ui/dist/` is enough for tests.

## Session log

- **2026-10-14** — Final verification pass on `phase-6` (3 commits): drove the real product through the web app, fixed the newcomer-facing issues above, added `eval/live_demo.py`, refreshed `docs/screenshots/`, wrote `docs/verification.md`. Gate `./scripts/test.sh` green (48 harness, 228 recorder, evaluation reproducible, app-core 23, api 16, cli 21, clippy, fmt); gaps are listed in `verification.md`.

- **2026-10-14** — Phase 6 complete on `phase-6` (5 code/doc commits): demo teams 2-4, `--node-map`, baselines and scoring, `eval/run_eval.py`, committed results table and README, gate stage. 31 cases: Sherlock 30 exact, 0 wrong, 1 honest abstain; best baseline 10 exact; reproducible across 3 runs. `./scripts/test.sh` green: 48 harness, 228 recorder (24 live), eval stage, app-core 23, api 16, cli 21 tests, clippy and fmt.

- **2026-10-14** — Phase 5 complete on `phase-5` (5 commits): artifact reader with verified node status, `/api/diagnoses`, `sherlock diagnoses`, guided run flow, run page with trial log and read-only export, seeded demo from the real pipeline, screenshots. Rust: app-core 23, api 16, cli 21 tests; `seed_demo.py` ran live against `langgraph dev`; `./scripts/test.sh` green: 17 harness, 208 recorder (24 live), app-core 23, api 16, cli 21 tests, clippy and fmt.

- **2026-10-14** — Phase 4 complete on `phase-4` (3 code commits + docs): G0 clues, G2 path check, ordering, intake, known-good from a prior success with picker and disagreement abstain; 208 recorder tests (24 live) and 17 harness tests green; on team 1 `diagnose --good-run` equals gold for single, writer and two-cause runs (1, 1, 3 trials of 31) with no hand-written patch. Rust untouched.
- **2026-10-14** — Phase 3 complete on `phase-3` (3 code commits): pruning, minimality search, verdict labels, budget, `sherlock-rec diagnose` and the JSON artifact. 162 recorder tests (18 live) and 17 harness tests green; on team 1 `diagnose` equals gold for the single and two-cause runs (1 and 3 trials of 31) and abstains on the cache-miss case. Rust untouched.
- **2026-10-14** — Phase 2 complete on `phase-2` (7 atomic commits): checks, G3 driver, redaction, per-trial replay and allowlist, `sherlock-rec` rename; 120 recorder tests (10 live against `langgraph dev`) and 17 harness tests green. First real verdicts: pass, fail and abstain. Rust untouched.
- **2026-10-14** — Phase 1 complete on `phase-1` (8 atomic commits): `python/sherlock` recorder, replay and abstain; 48 tests; harness suite still green.

- **2026-10-13** — Phase 0 complete on `phase-0`:
  - harness and demo team #1 (16 tests);
  - fork-recipe spike 20/20;
  - ingestion fixed to read `tasks[].result` (Rust tests, clippy and fmt green);
  - tracker, `CLAUDE.md` and the commit policy added;
  - Rust installed (GNU toolchain).
