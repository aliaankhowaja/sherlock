# End-to-end verification (2026-10-14)

Product checked through the web app as a first-time user, on branch `phase-6`. Honest scope: one reviewer, one
Windows machine, one headless Chromium (`playwright-cli`), synthetic demo teams. Not a usability study with real users.

## What was run

1. `cd ui && npm run build`; `cargo build -p cli`.
2. `python/sherlock/eval/live_demo.py` (new): the real pipeline, no provider. It records a passing run per demo team and the failed
   runs on `langgraph dev` under `sherlock-rec run`, restarts that server under `--replay` inside the socket trap, runs
   `sherlock-rec diagnose` on five failed runs and leaves the replay server up so the thread ids exist.
   Results: `vendor_brief` two-cause = {retriever + extractor}; `vendor_brief` single = {writer}; `order_desk` = {assemble + stock};
   `invoice_pipeline` redundant repair = {extract} or {normalize}; `support_bot` (LLM node) = cannot say (`unrecorded_call`).
   One more failed run (`order_desk`) was left undiagnosed on purpose.
3. `sherlock serve --langgraph-url <replay server> --sherlock-dir <fresh dir>`; driven in headless Chromium:
   guide, pick team and runs, copy command, verdict, run pages, HTML and JSON downloads, `/explore`, server-down and no-diagnoses states.

## Screenshots (`docs/screenshots/`)

Replaced by the redesigned UI (see "Redesigned UI" below); the earlier guide/run-page screenshots were removed with those pages.

| File | Shows |
|---|---|
| `1-pick.png` | Step 1: team picked, its pipeline already drawn, failed and known-good runs with failed/passed and diagnosed marks |
| `2-replay.png` | Step 2: the two-cause `vendor_brief` run mid-replay: log, `extractor` input (new keys flagged) and output, ≠ on nodes that differ from the known-good run |
| `2-replay-900.png` | Same stage at 900 px wide (`invoice_pipeline`): log and current hand-off stay side by side |
| `3-diagnose.png` | Step 3: a diagnosis started from the UI, replayed on the stage (restored `parse`, re-run branches) with the step checklist |
| `4-verdict-found.png` | Step 4: "Restoring retriever and extractor together makes the run pass; neither alone does", graph by verified status, trial log, retriever evidence with output vs known-good |
| `4-verdict-abstain.png` | `support_bot` cannot say: one-line reason, full explanation, engine reason; every node "cannot say", none named |
| `explore.png` | The ingestion dashboard, now behind "Advanced" |

Both downloads work: the HTML is a single file with no `<script>`, containing the verdict and the "Must change" chips; the JSON is the artifact.

## Issues found and fixed

- **Sherlock's own trial threads were listed as runs** in the guide's pickers (a diagnosis of 3 trials added 3 fake "runs"). Now hidden in the pickers
  and labelled "Sherlock trial" in `/explore`.
- **The known gap:** diagnosed runs not on the server (seeded ids on a fresh server) were absent from step 1. Diagnoses of the selected team's graph are now
  added to the failed-run list, so the seed is reachable and tagged "diagnosed ...".
- **Known-good picker offered failed runs.** Diagnosed runs are now disabled there ("failed (already diagnosed)").
- **Abstain page repeated the same long raw reason on every node** (3x) and used engine jargon. Nodes now say "no verdict for this run"; the verdict card adds
  an "In plain words" line per reason code (13 codes, `terms.ts`). The first draft of the `unrecorded_call` text gave wrong advice (re-record); corrected.
- **Spec references in user-facing text** ("(FR-K1)", "(spec 9.2)", "(spec 4.4, secondary path)") are stripped at display time (`plain()`), since old artifacts
  on disk contain them and the engine strings feed the reproducible evaluation table.
- **Misleading colour:** `/explore` showed "idle" in green, which reads as "correct". It is now neutral with a tooltip and a header sentence that it only means "did not crash".
- ISO timestamps with microseconds shortened to `2026-10-13 22:23 UTC`.

## Judgement as a newcomer

Clear: the first screen (what it does, four numbered steps, glossary at the bottom), the plain verdict wording, the chip legend under the node list, the
trial log, the cannot-say framing ("an honest answer, not a failure"). Colour does not overclaim: red only for a node in a verified smallest fix, hatched amber
for no verdict, dashed grey for not verified.

## Remaining gaps (not fixed)

- The pickers cannot say which undiagnosed run failed and which passed (needs the check; the server only reports "idle"). A newcomer must know their runs.
- Step 3 still needs a terminal and a replay server; the "Before you run it" list is correct but dense. No in-app doctor.
- The "Found" card is red, which can read as an error although it is the success case.
- The run page is long; no table of contents. FR-U5/U6/U7 remain unbuilt (see STATUS).
- No automated UI tests; this pass is manual (screenshots, one browser, one viewport 1280 wide). Narrow/mobile widths and keyboard use were not checked.
- All data is synthetic (echo stub for the LLM team); nothing here says real failures are diagnosed.

## Redesigned UI (2026-10-14, later the same day)

Why: the guide/run-page UI was judged cluttered and hard to follow. The new UI is one guided flow with a stepper
(Pick runs -> Pipeline & replay -> Diagnose -> Verdict), a one-line "Next" banner, and one primary action per screen.

Checked in headless Chrome (Chrome DevTools MCP) against `sherlock serve --project/--sherlock-rec` on the live demo lab
(`eval/live_demo.py`, replay server from `/tmp/demo.log`), viewport 1360 and 900 wide:

1. **Replay.** `vendor_brief` two-cause failed run, stepped node by node: each node shows the input it received (keys just
   handed over flagged "new"), then its output, then the edge to the next node pulses and is labelled with the keys it carries.
   `retriever` (2 documents instead of 3) and `extractor` (`SOC 2` instead of `ISO 27001`) are marked as differing from the
   known-good run; the node card shows both values.
2. **Live diagnosis from the UI.** `order_desk` failed run `01a1391f-e082-…` with known-good `…7d12`: "Run diagnosis again"
   posted `/api/diagnose` with the token, polled `/api/jobs/2` until `done` (about 1.7 s); the stage replayed the events
   (plan: test parse, prune 3; trial 1 of budget 40: restore parse; fork; re-run of stock and pricing in parallel, then
   assemble; verdict pass) and the checklist ticked each step with its time. Verdict: {parse}, 1 trial.
3. **Verdicts.** All four teams open on `/runs/:id`: two-cause {retriever + extractor} (3 trials of 31), single {writer},
   `order_desk` {assemble + stock}, redundant {extract} or {normalize} ("Restoring extract alone makes the run pass; so does
   restoring normalize alone."), `support_bot` abstain `unrecorded_call` (no node named, all "cannot say").

Issues found on screenshots and fixed: edge labels overlapping nodes; long abstain headline; graph over-scaling on small
teams; log/inspector stacking too early at 900 px; a trial replay drawing a hand-off between two parallel branches
(now derived from supersteps); font glyphs used as icons (now drawn SVG marks plus words).

Still not done: run badges for undiagnosed runs say "not checked yet" (the server cannot tell pass from fail without the
check); the vendor_brief graph has no node kinds because this lab was started before kinds were declared; no automated UI
tests; one browser, desktop and 900 px only.
