> **Working note (tier 3). Not authoritative.** It may be stale or wrong. Facts come from the code and from docs/eval. Never cite this file in anything submitted to the university.

# Sherlock — build status

> **This is the live progress tracker.** Read it before starting work; update it before you stop.
> Scope is set by [`spec.md`](spec.md), which governs. The status columns inside the spec are a 12 October snapshot — **live status lives here only.** Session rules (model, commits) are in [`../../AGENTS.md`](../../AGENTS.md).

**Last updated:** 2026-10-14 · **Current phase:** 6 — evaluation done; the planned phases are complete · **Branch:** `phase-6` (branched off `phase-5`; merge phases 0-6 in order)

## How to update this file

- Tick an item only when it is done **and verified**; link the evidence (test, spike result, commit).
- Anything checked against real software goes under **Verified facts**, dated, with how it was checked.
- Decisions go in the Decision log in `docs/history/status-log.md` with the date and who decided.
- Add one line to the Session log in `docs/history/status-log.md` per working session, newest first.
- Keep this file short. Details belong in `docs/notes/` reports or commit messages.

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
- [x] **P0.2 Fork recipe verified** against a live `langgraph dev` — 20/20 checks, two corrections to spec §4.3. Report: [`fork-recipe.md`](fork-recipe.md).
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
- [x] The UI itself (`9485691`, `0eaa2c8`, `06ed793`, `9e0d784`): stepper Pick runs -> Pipeline & replay -> Diagnose -> Verdict with a "Next" line; `PipelineStage` plays a recorded run (each node's input, output, and the keys handed to the next node, with a travelling pulse on the edge) and a diagnosis job's events on the same graph; run button with polling and a step checklist; verdict headline, graph by verified status, trial log, node evidence, export. Verified in headless Chrome on the live demo lab, see `docs/notes/verification.md` "Redesigned UI".
- Gap: the demo lab running during the check was launched before node kinds were declared, so its graph showed `kind: null`; a fresh `live_demo.py` serves the kinds (checked: `get_graph().to_json()` carries `metadata.kind`).

## Remaining / not built

- FR-E9 (live time-travel without call blocking must fail the two-cause case), the plain-LLM-guess and plain-retry baselines, G0+G2 as a separate row: not built (see `docs/eval/README.md`).
- No real-provider or real-failure evaluation; the LLM team uses a deterministic echo stub, so stochastic sampling is not measured. The "most real bugs are in deterministic nodes" claim is still unmeasured.
- Phase 5 leftovers: FR-U6, FR-U7, FR-U9 first screen; Rust `sherlock diagnose` wrapper; `sherlock doctor` (FR-R12).
- Interceptors cover httpx and `BaseTool` only.

For the team: (1) decide the mid-evaluation date and the required demo; (2) pick a provider and key for one real smoke test; (3) say whether a shared-cassette cross-case contamination check (see Decision log) should become a permanent test; (4) add the missing `causal-debugger/` governing documents and review TraceSurgeon / Agent-Casuality before mid-eval.

## Requirement status

Only requirements that are not ⬜ are listed. IDs are from `spec.md` §5.

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
| FR-D12 | ✅ | Candidates ordered by clue weight (loop, error, extractive, differs-from-passing-run), then G1 nominations; speed only (P4.5, P6b) |
| FR-D9 (large) | ✅ | Above 6 candidates minimal sets are found by duality (shrink + "avoid one node of each found set" probes), 6-41 trials on 30/60-node DAGs, size cutoff no longer binds when the probes prove completeness (`tests/test_scale.py`) |
| Per-gate attribution | ✅ | `trials[].gates` and `gate_summary {nodes_total, pruned_by_ancestry, g0_flagged, g1_nominated, g2_cut, g3_trials, exhaustive_count}` in the artifact (`tests/test_g1.py`) |
| FR-D13 | ✅ | Sets of 3 by default; configurable with `--max-size` |
| NFR-8 | ✅ | 31 exhaustive trials vs 1 (single) and 3 (two-cause) on team 1: 97% and 90% fewer; `trial_reduction` in the artifact. Across all four teams, 68 trials vs 538: 87.4% fewer (`docs/eval/results.md`) |
| FR-E3 | ✅ | Live `diagnose` results equal `gold_minimal_sets` for single, two-cause and writer runs (P3.6) |
| FR-U13 | ✅ | Per-node timeline, errors first |
| FR-U1 | ✅ | `/runs/:id` opens the verdict step for that run, with the pipeline graph in the middle and replay one click away |
| FR-U5 | ✅ | Replay and node card show each node's input beside its output; differing keys against the known-good run are flagged (`Replay.tsx`, `NodeCard.tsx`) |
| FR-U14 | ✅ | Hand-rolled SVG graph (server layer/row, parallel branches, back edges, edge labels with the keys carried), coloured by verified status on the verdict (`Graph.tsx`) |
| FR-U2 | 🔨 | Judgment strip shows the failed check and its assertions, plus the intake note; "expected vs actual" text is not shown |
| FR-U3 | ✅ | Nodes coloured by verified status (must change / not needed / not verified / cannot say), computed in `app-core` from the artifact, never by an LLM (P5.2) |
| FR-U4 | 🔨 | Evidence panel and trial log show every trial and result; hints are marked weaker; G1 nominations are in the artifact (`g1`, `trials[].gates`) but the UI does not show them yet |
| FR-U8 | ✅ | Several minimal sets are all listed in the verdict and per node |
| FR-U11 | 🔨 | The HTML export has no script and no buttons; there is no hosted share view |
| FR-U12 | 🔨 | Diagnosis list with verdict per run; no question/actual-output columns |
| FR-S4 | ✅ | Read-only HTML export (self-contained, offline) and the raw JSON |
| NFR-4 | ✅ | Every abstain shows its sentence and code in the verdict card |
| NFR-6 | ✅ | Every reported cause sits beside the trial log that backs it |
| NFR-18 | ✅ | The export cannot run or fire anything; `serve` has no endpoint that starts a run or a tool |
| FR-G0.1-G0.5 | ✅ | `clues.py`; clues are evidence, order the search and widen it only for error/empty/malformed/extractive/schema-invalid (P4.1). FR-G0.1 sees tool calls from the cassette only (no node attribution) |
| FR-G1.1-G1.6 | ✅ | `gates.py`, `diagnose --g1-url/--g1-model/--g1-samples`: swappable OpenAI-compatible endpoint, zero tools, redacted node summaries, samples union, reorder-only, `g1.fallback: g0_only` when empty/down, off = unchanged (`tests/test_g1.py`, 8 tests, local stub `tests/g1_stub.py`). Real-provider call not exercised |
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

- **2026-10-14 — Scale audit (synthetic oracle, `tests/test_scale.py`, no server):** layered DAGs with 4 parallel branches per layer, monotone oracle, planted sets. Trials used (exhaustive in brackets): singleton 6/8/7 for 30/40/60 nodes; pair far apart 19/22/23; AND of 3 across branches 27/29/32; OR (two redundant singletons) 23/20/27; mixed (a AND (b OR c)) 37/40/41 [2^30, 2^40, 2^60]. 100 nodes: 25 trials, 300 nodes: 31 (pair). Every run returned exactly the planted 1-minimal sets with `complete` true; runtime under 0.1 s; the 60-node artifact is 16.6 KB. Before the change the OR case at 30 nodes needed 160+ trials and did not finish inside 4n+40 (singletons, then C(n,2) pairs, then C(n,3) triples in lexicographic order).
- **2026-10-14 — Ancestry pruning is by superstep, not by edges:** in a layered DAG every earlier-layer node stays a candidate even on a branch that does not feed the writer, because a LangGraph node reads shared state and graph edges alone would under-include (the "ancestry, not read-dependencies" limitation). On big pipelines the known-good source is what shrinks the list: `same_output` nodes (FR-K1) and no-op restores are pruned. `pruned_by_ancestry` in `gate_summary` counts only the superstep rule.
- **2026-10-14 — G1 behaviour (local stub only):** a nominated node moves to the front among equal-clue candidates; a confidently wrong shortlist (`router`) and a dead endpoint both return the same minimal sets as G1 off; the request body has no `tools`, `functions` or `tool_choice`, and an `sk-` key and an e-mail in node writes do not appear in the prompt.

- **2026-10-14 - Large teams and the eval at scale (`eval/run_eval.py`, 7 teams, 86 cases):** `support_desk` 33 nodes / 35 faults, `loan_underwriting` 32 / 39, `revenue_report` 33 / 35 (built with `harness/sherlock_harness/teams/_kit.py`; 3-way and 4-way fan-outs, a conditional route each, tool and one echo-stub LLM node each). 36 visible + 18 hidden cases on them (single, two-cause, AND across parallel branches, redundant repair with two gold sets, silent decoy, a node that raises, a route change, abstain-by-design). Result: **84 of 86 cases exact, 0 wrong, 2 abstain** (both `abstain_by_design`: two request-changing faults, `unrecorded_call`); hidden 34 of 34 exact; hard slice 49 exact + 2 abstain of 51; best baseline `g0_only` 38 of 86 exact. On the 55 large-team cases Sherlock used at most 7 trials (27 cases 1 trial, 27 cases 3, one 7) against up to 2^32 - 1 = 4,294,967,295 exhaustive subsets; over all cases 174 trials against 158,913,790,468 (NFR-8 asks 40% fewer). Mean candidates after pruning 1.4-1.6 per case; the pruning is `pruned_other` (same output as the passing run, or a no-op restore): 491 / 503 / 578 node removals on the three large teams, `pruned_by_ancestry` 0 (every node on these paths feeds the output). G0 `differs_from_passing_run` named a gold node in every case, so that count says little; the genuine error clue (node_error) fired on the `order_lookup.timeout` run. Gate probes (15, all as expected): G1 stub nominating a wrong node first still returns the exact gold; G2 with a node that never ran in the shortlist cuts it and keeps the answer; G2 with only such a node abstains; no known-good run abstains `no_known_good`; harmless planted faults give `already_passes`. Oracle gold for all 86 cases agreed with the pipeline.
- **2026-10-14 - A LangGraph list-edge join is invisible in the server history:** `add_edge([a, b], n)` runs correctly in-process, but in `/threads/{id}/history` the join steps list no tasks, so `n` never appears as a node (Sherlock then abstained `cannot_attribute` on 13 of 18 first-run `support_desk` cases, because faults owned by joined nodes had no node on the tape). `defer=True` is not a substitute (the node ran before its other predecessors finished). The kit wires a join from the last-finishing predecessors with plain edges, which the history shows. Real teams that use list-edge joins would hit this; not handled in the engine.

## Open items

- **For the UI agent (Phase 6b, additive artifact fields, Rust validator untouched):** `g1` (`enabled`, `nominated`, `fallback`, `strength: "weak"`, ...), `gate_summary`, `trials[].gates` (subset of `g0 g1 g2 g3`), `screen {mode, proved_no_others}`. Show G1 nominations visually weaker than G2/G3 (FR-U4). `pruning.exhaustive_trials` is an exact integer that exceeds 2^53 at 54+ nodes: display `2^n` using `pruning.nodes_on_path.length`. A `plan` progress event is unchanged; a new `g1 {nominated, fallback, samples_ok}` progress event fires before it when G1 is on.

Beyond spec §10:

- **Big demo (2026-10-14, still running):** `eval/live_demo.py` lab at `SERVER http://127.0.0.1:58469`, dir `/tmp/sherlock-big` (Windows `C:\Users\hp\AppData\Local\Temp\sherlock-big`; diagnoses in `diagnoses/`, project in `lab/`). 7 teams recorded, 11 failed runs diagnosed (10 found, all equal to gold; `support_bot` abstained `unrecorded_call` as designed), 3 left undiagnosed for the run button: `support_desk:refund_calc.cap_off+rerank.ascending`, `loan_underwriting:limit_check.stale_exposure`, `revenue_report:wrong_prior+no_dampening`. View it: `sherlock serve --langgraph-url http://127.0.0.1:58469 --sherlock-dir /tmp/sherlock-big --sherlock-rec <path>`.
- **Large-team eval gaps:** the eval pair-samples hidden cases (at most two faults per run); the 30+ node teams have one wide fan-out stage and single-node gold, so the search never exceeds 7 trials; ancestry pruning contributes nothing on them because every node feeds the output; the history join limitation above is worked around in the kit, not fixed. A run with all candidates cut by a shortlist but a widening clue abstains `no_candidates` rather than `path_check_failed` (loan probe).
- **Phase 6 gaps:** the evaluation is synthetic (our teams, our planted faults, an echo stub for the LLM team) and still small (86 cases over 7 teams, three with 32-33 nodes), so 84 of 86 exact says the pipeline matches the in-process oracle, not that real failures are diagnosed. The hidden set is hidden from tuning only. Not built: FR-E9, plain-LLM-guess and plain-retry baselines. Gate time grew by about 5 minutes. See `docs/eval/README.md`.
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


## G1 Laya API v0 (branch `g1-laya`, local)

Build plan: [`g1-laya-spec.md`](g1-laya-spec.md). Default off behind `--g1`. Updated 2026-10-28.

### Build steps (spec section 12)

| Step | State | Evidence |
| --- | --- | --- |
| 1 Backend interface, `off`/`fake`, call site | ✅ | `g1.py` `rank`; hook in `diagnose._unit` after pruning; `tests/test_g1.py`, `tests/test_scale.py` |
| 2 Node cards, golden files | ✅ | `g1.node_card`; `tests/golden/g1_cards/` (vendor brief, all 5 nodes read by eye) |
| 3 Laya client, cache, `g1-check`, fake server tests | ✅ | `tests/test_g1_laya.py`; `sherlock-rec g1-check --g1-allow-remote` returned 200 from api.laya.studio, same answers twice, 0.9 s warm |
| 4 Zero-shot evaluation on the 86 cases | ⏳ gate done, Laya numbers blocked | `eval/g1_eval.py`. Gate fires: min(G0, rule) is already optimal on 96.4% of the 84 answered cases. Laya rows not valid yet: account out of credits (HTTP 402) |
| 5 Harder generated cases | ⏳ data done, Laya numbers blocked | `eval/g1_gen.py` (seed 7, 100 dev + 100 test, test sha256 739f3ee40245...); G0 is optimal on only 22% of the test half. No question tuning yet (still `g1_questions_v1`) |
| 6 Integration | ✅ code; final run and ship decision open | `g1` result object, `g1` progress line, Rust reader test (schema stays 1), UI weak hint hidden on abstain |

### Acceptance criteria

- [x] AC-G1-1: same answer with G1 on and off: 86 cases (`results.json` invariant `g1_fake_changed_answer` = []), 30 to 300 nodes (`test_scale.py`).
- [ ] AC-G1-2: tight budgets: needs the Laya runs.
- [ ] AC-G1-3: three byte-identical runs: not run yet.
- [x] AC-G1-4: socket trap in `test_g1_laya.py` (remote without opt-in, no key, fake: zero connections).
- [x] AC-G1-5: dead port, 401, 402, 400, 500, timeout, malformed, out-of-range answers all give the G1-off result with `status = unavailable`.
- [x] AC-G1-6: golden cards; cards capped at 2,400 characters (800 tokens at 3 characters each); the API measured about 3 characters per token.
- [x] AC-G1-7: `app-core` test `g1_scores_are_accepted_and_never_change_what_the_trials_decided`.
- [ ] AC-G1-8: not measured on a local endpoint. Hosted API: about 0.9 s per warm call, so about 30 s for 33 uncached cards.
- [x] AC-G1-9: `fake` backend and the local System One stand-in; no endpoint needed.
- [ ] AC-G1-10: README section and `g1-check` exist; the clean-machine check is not done.
- [x] AC-G1-11: planted-key and card-text scan over result, progress events and cache.

### Facts measured against the real API (2026-10-28)

- A named User-Agent is required (Cloudflare error 1010 otherwise).
- `GET /v1/models` lists `english` (default, 512 tokens), `multilingual` (1,024) and `typed-decisions` (English, 1,024, only on request). Without `model` the service routed our English card to `multilingual`, so the client sends `typed-decisions` by default.
- `usage.input_tokens` counts the card once per question (six questions: about 1,600 tokens for a 230-token card), so truncation is read from `usage.truncated` and `usage.state_tokens_dropped`.
- Billing is per input token, every question included: $0.0357 per 1M after a one-time 6,000-token free tier (laya.studio/pricing). The free tier is used up.
- The recording does not say which node made a tool call, so cards have no tool field and Q6 is never asked; no node role exists in a run, so cards have no role field.

### Next

1. The user adds Laya credits (estimate: 10 to 15M tokens, about $0.50 for all runs).
2. `cd python/sherlock && uv run python eval/g1_eval.py --tight 2 --stability --out ../../docs/eval/g1` (needs `eval/.g1/cases.jsonl` from `run_eval.py`).
3. `uv run python eval/g1_gen.py`, then `g1_eval.py --cases eval/.g1/gen_v1/test.jsonl --out ../../docs/eval/g1_gen`.
4. Freeze the question version, run once, apply the ship rule (the supervisor confirms the 20 percent margin first).
