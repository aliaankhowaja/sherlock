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

| File | Shows |
|---|---|
| `guide.png` | Home with the four steps filled in (team, failed run, known-good run, exact command), the verdict card, all diagnoses, glossary |
| `guide-empty.png` | First launch: no LangGraph server, no diagnoses; says what is missing and how to start it |
| `guide-server-down.png` | Server down: plain error with the URL being read and the fix |
| `run-found.png` | Two-cause verdict: failed-check strip, nodes coloured by verified status, evidence, limits, trial log |
| `run-abstain.png` | `support_bot` cannot say: reason, plain-words explanation, no node coloured as a cause |
| `run-empty.png` | A run with no diagnosis: the command to create one |
| `explore.png` | Ingestion dashboard with Sherlock's own trial threads labelled |

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
