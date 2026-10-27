> **Working note (tier 3). Not authoritative.** It may be stale or wrong. Facts come from the code and from docs/eval. Never cite this file in anything submitted to the university.

# Handoff: building the G1 Laya API ranker (v0)

Written 2026-10-27 for the orchestrating session (Opus). The orchestrator plans and reviews. Sonnet subagents write the code, one step each.

## Read first, nothing else yet
1. `AGENTS.md` (rules, commands, the authority tiers). 2. `docs/notes/g1-laya-spec.md` (Ali's spec, the build plan). 3. This file.
Do not read `docs/history/`, the old spec, or the whole of `status.md` unless a step needs it.

## The task in four lines
Add a Laya-API suspicion scorer as a new G1 backend. It only reorders G3 trials. It never names a cause and never changes `minimal_sets`. Everything stays behind `--g1`, default off. Expected honest outcome: "optional, off by default"; a null result is valid.

## State on 2026-10-27
- Code repo `aliaankhowaja/sherlock`, `main` = e8e52c5, 583 tests, all earlier phases done.
- Branch `docs-restructure` (docs move, banners, AGENTS.md) is waiting for review by Ali and Ibraheem. Build work starts on `g1-laya` branched from `main`, or from `docs-restructure` if it has merged.
- The mid report is finished in the separate report repo. Its requirement, test and acceptance IDs are frozen; the spec cites them (FR-17, FR-18, TC-15, AC-6, AC-8, NFR-1..11). Never renumber them and never cite our notes in the report.

## Where the existing G1 lives (verified)
- `python/sherlock/src/sherlock/gates.py`: today's optional hosted shortlist (`G1Result`, `run_g1`, `disabled`). Env key `SHERLOCK_G1_API_KEY`. This becomes the spec's `hosted` backend; keep its behaviour.
- `python/sherlock/src/sherlock/diagnose.py`: orchestration. `g1` is a config dict passed in; results carry a `g1` object; order of trials is decided here. This is the call site for step 1.
- `python/sherlock/tests/g1_stub.py`: local stand-in used by tests.
- Rust reader for result files: `crates/app-core/src/diagnosis.rs`. Open question: does it ignore unknown fields (spec section 8)?
- The spec proposes names. Align them with the repo before coding: new package `python/sherlock/src/sherlock/g1/` (the spec's `g1/laya_client.py`); avoid clashing with the existing `G1Result` in `gates.py` (rename the new one or namespace it).

## Waves (steps are the spec's section 12)
| Wave | Step | Agent task | Needs | Exit check |
|---|---|---|---|---|
| 1 (parallel) | 1 | Backend interface, `off` and `fake` backends, hook into `diagnose.py` | nothing | AC-G1-1 with off, AC-G1-9 with fake |
| 1 | 2 | Node-card builder, golden files, redaction, name-masking mode | nothing | AC-G1-6; 10 cards read by eye incl. vendor brief |
| 1 | 5a | Seeded generator for harder cases, dev/test split, JSON Lines | nothing | byte-reproducible dataset |
| 2 | 3 | Laya client, cache, `g1-check`, fake HTTP server, tests | step 1 | AC-G1-4, 5, 11; same card twice identical |
| 3 | 4 | Zero-shot evaluation, methods 1 to 6, on the 86 cases | steps 2, 3 | metrics table; the 95 percent gate in the spec |
| 3 | 5b | Same on generated test half, methods 1 to 7; tune wording on dev half only | 5a, 3 | tables; question version bumped per change |
| 4 | 6 | `g1` result field, progress line, Rust reader, evidence panel, schema decision | step 3 | AC-G1-3, 7, 10 |
| 5 | final | Freeze question version, run once, ship decision against the pre-declared rule | all | decision recorded |

Rules for each agent: one step, small commits, tests first, stage long writes in pieces, never print or log the API key or card text, no network except the step 3 smoke test and live evaluation runs the user has approved.

## Needs from the user (the orchestrator must ask, not guess)
- `LAYA_API_KEY` and confirmation that the hosted endpoint works (`https://api.laya.studio/v1/systemone` is unverified; Ali could not read the docs). Never print the key; the user moves it by clipboard to stdin.
- Permission to send synthetic card text to the hosted API for evaluation runs. No real failures go out.
- Supervisor's view on the 20 percent ship margin (spec section 11).
- Review and merge of `docs-restructure` by Ali and Ibraheem.

## Working rules
- Authority tiers: official > submitted > evidence > notes. Notes (including this file) can be wrong; check the code.
- Commits: atomic, conventional subject, one plain value line, `Co-authored-by` trailers for the other two members (see `AGENTS.md`), no AI trailers.
- Update `docs/notes/status.md` (the G1 section) when a step's exit check passes, with the command and result as evidence.
- Keep token use low: delegate code to Sonnet, Haiku for mechanical checks, grep before reading, short reports.
