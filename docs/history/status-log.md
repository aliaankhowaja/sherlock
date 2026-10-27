> **Working note (tier 3). Not authoritative.** It may be stale or wrong. Facts come from the code and from docs/eval. Never cite this file in anything submitted to the university.

# Sherlock status log (moved from status.md)

## Decision log

- **2026-10-12/13 — team meeting; spec by Ibraheem.** Final scope is `docs/notes/spec.md`. No live calls: cache or abstain. The 9 October brief is superseded on method.
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
  - **Phase 6b (large pipelines, G1):** (1) above 6 candidates use set duality instead of enumeration (assumes monotonicity like the superset skip; an abstained probe is never proof; falls back to priority-ordered enumeration when more than 64 probes would be needed); (2) trials are ordered by highest priority index so a tight `--max-trials` finds the answer early; (3) `--max-trials` unset scales as 3 per candidate + 20 (min 40); (4) open item 3 (G1 empty after widening): fall back to G0-only ordering and record `g1.fallback: "g0_only"` in the artifact, never abstain, because G1 never decides anything; (5) G1 is reorder-only: it cannot add or remove a candidate, so it cannot make Sherlock miss a culprit (NFR-5); prompt injection through node text is a documented limitation (NFR-19).
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


## Session log

- **2026-10-15** — Must-requirement sweep on `phase-6` (3 parallel agents):
  - FR-U9/NFR-12: `/` opens on a finished two-cause verdict (live, else seeded vendor_brief) with "Try your own run".
  - FR-U6: nodes that differ from the known-good run read "ran ok, output differs"; ok nodes say "check failed downstream".
  - FR-U7: `app_core::health` checklist for empty/broken recordings (5 tests), rendered by the UI.
  - FR-U2 partial: expected/actual strip is derived from the assertion reason; Python should add `check.results[].expected/.actual`.
  - FR-I5: `POST /api/intake` (same guards as diagnose, 3 tests) and a Wrong button. FR-R9: "cannot diagnose: no usable history".
  - NFR-23 partial: server version is in `/api/info` and `/steps`, not inside diagnosis artifacts.
  - FR-X7: exit codes 0 pass / 100 check failed / 1 error / 75 cannot say / 2 usage.
  - FR-K2: `diagnose --known-good-output NODE=@file|JSON` (a context patch; source recorded as `pasted`).
  - FR-G3.10: interrupt in history abstains `interrupt_unsupported`; limitation stated in the artifact.
  - NFR-10: `--max-cassette-mb` (default 500), WAL and busy timeout, two-connection test.
  - NFR-3: `requests` and `urllib.request` record/replay (`shim_http.py`); `aiohttp` not covered.
  - NFR-21: wheel-build test only; PyPI publishing and Rust-in-wheel out of scope. FR-D10 and the console-script rename skipped.
  - FR-E4: baselines `g0_g2` 49/86 exact, `llm_guess_stub` 6/86 (a fixed heuristic, not a model), `plain_retry` 0 of 258 reruns passed; Sherlock 84/86.
  - FR-E9: live time-travel without the cassette fails `vendor_brief:retriever.drop_latest+extractor.legacy_pattern`; a one-cause control passes (`invariants.live_time_travel`).
  - NFR-11 partial: 24 s from `sherlock-rec run` to first diagnosis (clean install not timed). NFR-14: needs a user test, not measured.

- **2026-10-14** - Large demo teams on `phase-6`: `_kit.Pipeline` plus `support_desk` (33 nodes), `loan_underwriting` (32), `revenue_report` (33), 105 faults, 54 planned and seeded cases; `run_eval.py` covers 7 teams with gate probes and a scale table (84/86 exact, at most 7 trials vs up to 2^32 exhaustive); live demo with 11 diagnoses up at `http://127.0.0.1:58469`; found and worked around the invisible list-edge join in the run history. Harness 180 tests green.
- **2026-10-14** - Teammate setup on `phase-6`: thin `Makefile` over `scripts/{setup,demo,demo-stop,doctor,test-fast}.sh`, short `readme.md`, `.gitattributes` (this line was restored from a truncated view after an accidental overwrite of the working file; its author should re-check it).
- **2026-10-14** — Phase 6b on `phase-6`: diagnosis engine scaled to 30-300 node pipelines (duality search, priority-ordered enumeration, auto trial budget), optional G1 shortlist (`gates.py`, `--g1-*`), per-gate attribution in the artifact. 271 recorder tests (incl. `test_scale.py` 22, `test_g1.py` 8) and 49 harness tests green. FR-D10 still not built (cassette replay is deterministic).

- **2026-10-14** — UI for large teams (`2ce3250`, `1f788ac`): pan/zoom/fit/follow, minimap, stage grouping, search, dimming, gate strip from `gate_summary`, per-trial gate tags; checked on the synthetic 40-node `/dev/big` (real big teams not served yet).
- **2026-10-14** — Redesigned web UI on `phase-6` (4 UI commits): guided stepper, `PipelineStage` replay of recorded runs and of live diagnosis jobs, verdict page; old Guide/RunPage removed. Driven in headless Chrome on the live demo lab: vendor_brief two-cause replay, a real diagnosis of the order_desk run started from the UI (job 2, done, {parse}), all four verdicts incl. support_bot abstain; screenshots refreshed. `./scripts/test.sh` result in `docs/notes/verification.md`.

- **2026-10-14** — Final verification pass on `phase-6` (3 commits): drove the real product through the web app, fixed the newcomer-facing issues above, added `eval/live_demo.py`, refreshed `docs/screenshots/`, wrote `docs/notes/verification.md`. Gate `./scripts/test.sh` green (48 harness, 228 recorder, evaluation reproducible, app-core 23, api 16, cli 21, clippy, fmt); gaps are listed in `verification.md`.

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
