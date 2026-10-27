> **Working note (tier 3). Not authoritative.** It may be stale or wrong. Facts come from the code and from docs/eval. Never cite this file in anything submitted to the university.

# Architecture, rules, commands and CLI

Repo: `sherlock` — minimal suspect-agent finder for multi-agent teams.

## Layout

- `crates/app-core/` — domain logic only. Put fault-isolation logic here.
  - `ingestion` module: LangGraph data intake. Team = assistant
    (`POST /assistants/search`), team run = thread (`POST /threads/search`,
    team association via `metadata.assistant_id`), run logs = checkpoint
    history (`POST /threads/{id}/history`) expanded to per-node events.
    No I/O inside: callers inject `LangGraphTransport`; real HTTP + `serve`
    endpoints live in `cli`/`api`.
  - `steps` module: a recorded run replayed step by step (checkpoint history oldest first; per node run: input state,
    changed keys, which upstream node wrote which key, output = `tasks[].result`, error, timing, log lines; hand-off
    edges labelled with keys). `topology`: layered graph + per-node verdict evidence. `runner`: what the web app may
    run (fixed argv, id checks, project discovery). `jobs`: a job's progress events and the one-at-a-time `Board`.
  - `diagnosis` module: reads and validates `.sherlock/diagnoses/<thread_id>.json` (schema 1) and computes one
    verified status per node (`culprit` = in a G3-verified minimal set, `cleared` = tested in a complete search and in no set,
    `unverified` = pruned/untested/undecided, `abstained` = the diagnosis said "cannot say"). Refuses contradictory artifacts.
    The colour rules live here, never in the UI. `DiagnosisStore { sherlock_dir }` does the file reads.
- `crates/cli/` — thin CLI controller over `app-core` (+ triggers `api` for `serve`). Primary interface.
  `sherlock diagnoses list|show THREAD_ID [--json] [--sherlock-dir DIR]` prints verdicts; `serve --sherlock-dir DIR` (default `.sherlock`)
  `[--project DIR] [--sherlock-rec PATH]` (the run button; see "Web API").
- `crates/api/` — thin HTTP controller over `app-core`. Serves `ui/dist` via rust-embed, opens browser.
  - Proxies LangGraph for the dashboard: `GET /api/teams`, `GET /api/runs`,
    `GET /api/logs` (400 on missing `thread_id`, 502 + `{error}` JSON when
    LangGraph is down). Connection fixed at startup via `serve`
    `--langgraph-url` (default `http://127.0.0.1:2024`) / `--langgraph-api-key`.
    When `LANGSMITH_API_KEY` is set (flag, env, or `.env`), `serve` and `ingest`
    read LangSmith traces instead (`--source langgraph` forces the local server).
    Team = `metadata.assistant_id`, run = `thread_id`, logs = runs in that thread.
  - `GET /api/diagnoses` (list; empty list when none, broken files reported in `invalid`), `GET /api/diagnoses/{thread_id}`
    (summary + verified `nodes` + raw `artifact`; 400 bad id, 404 missing, 422 invalid), `GET /api/info` (source, url,
    sherlock_dir, token, run). The only endpoint that starts anything is `POST /api/diagnose` (the run button; see
    "Web API" below for every endpoint, its JSON shape and the security rules).
- `ui/` — vanilla React + Vite + TS. No router/state/framework additions without reason.
  - `/explore` is the ingestion dashboard: teams → runs → error-first per-node log
    timeline (manual refresh, run filter, limit). Same-origin `/api/*` only.
  - Paths (`history`, no router dep): `/` the guided flow `Flow.tsx` with a stepper 1 Pick runs (`Pick.tsx`) ->
    2 Pipeline & replay (`Replay.tsx`) -> 3 Diagnose (`Diagnose.tsx`) -> 4 Verdict (`Verdict.tsx`) and a one-line "Next"
    banner; `/runs/:id` opens the same flow on step 4; `/explore` (linked as "Advanced") the ingestion dashboard.
    `Stage.tsx` (`PipelineStage`) is the shared player: `Graph.tsx` (hand-rolled SVG from the server's layer/row),
    play/pause/step/reset + speed over frames built in `script.ts` from `/api/runs/{id}/steps` (`stepFrames`) or a job's
    progress events (`jobFrames`), log panel, current input -> output (`Kv.tsx`), node card (`NodeCard.tsx`).
    The run button (`POST /api/diagnose`) shows only when `/api/info` says `run.enabled`; the command is always in a
    collapsible. Shared bits: `model.ts` (API shapes, glyph paths), `terms.ts`, `share.ts`, `api.ts`, `jobs.ts`.
- `harness/` — Python (uv, 3.12): seven demo LangGraph teams: the small `vendor_brief`, `order_desk`, `invoice_pipeline`, `support_bot` (LLM node) and three 30+ node ones built with `teams/_kit.py` (`support_desk` 33 nodes, `loan_underwriting` 32, `revenue_report` 33; parallel branches, conditional routes, tool and LLM-stub nodes)
  with fault injection, gold derivation, seeded visible/hidden cases and hard-slice tags (`sherlock_harness/catalog.py`), live-server spikes and
  fixtures. See `harness/README.md`.
- `python/sherlock/` — Python engine for recording, checks and G3 (uv, 3.12; deps: pyyaml, jsonschema; the bootstrap itself is stdlib-only).
  Console script `sherlock-rec` (not `sherlock`, which is the Rust binary); `python -m sherlock` is the same.
  `cd python/sherlock && uv run pytest -q` (includes live `langgraph dev` tests, about 2 min).
  - `sherlock-rec run [--replay] [--cassette PATH] [--match hash|sequence] [--allow-tool NAME]... <cmd>` puts `src/sherlock/_bootstrap`
    (a `sitecustomize`) on `PYTHONPATH`. `_hook` patches modules on first import; `shim_httpx` and `shim_tools`
    record or replay into the SQLite `cassette` (`.sherlock/cassette.db`). Replay never goes live; a miss raises
    `CannotSay` (an Exception, stored in the cassette) and the launcher exits 75 with `cannot say: ...`.
    `--allow-tool` limits replay to read-safe tools (FR-G3.8). Stored requests are redacted (`redact.py`, FR-R8).
  - `sherlock-rec check [-c sherlock.yaml] [--output TEXT | --output-file F | stdin]`: promptfoo-style assertions
    (`checks.py`, FR-C1-C6; exit 0 pass, 1 fail, 2 error).
  - `sherlock-rec g3 --thread-id ID --restore a,b --known-good FILE [-c sherlock.yaml] [--url URL] [--cassette PATH]`
    (`g3.py`): fork a recorded run over HTTP, restore known-good behaviour via run `context`, resume from the cassette, apply Z.
    Exit 0 pass, 1 fail, 75 abstain, 2 error. The server must be running under `sherlock-rec run --replay langgraph dev ...`;
    G3 refuses otherwise. Known-good file: `{node: {context_key: value | {"$remove": [..], "$add": [..]}}}` (see `harness/known_good/`).
  - `sherlock-rec diagnose --thread-id ID [--good-run THREAD]... [--discover-good] [--known-good FILE] [--suspect NODE[->NODE]]... [-c sherlock.yaml] [--url URL] [--cassette PATH] [--max-trials N] [--max-minutes 10] [--max-size 3] [--g1-url URL --g1-model NAME [--g1-samples 1] [--g1-key K]] [--out DIR]`
    (`diagnose.py` over `search.py`): prune candidates (`plan_candidates`), probe, then singletons, pairs and up to `--max-size`
    nodes through `run_g3`; returns every 1-minimal set or an abstain with a reason code. Writes `.sherlock/diagnoses/<thread_id>.json`
    (schema 1, additive: `status`, `minimal_sets`, `unverified_sets`, `trials` (with `n`, `elapsed_s`), `counts`, `pruning` (with
    `pruned_ratio`), `trial_reduction`, `budget`, plus `clues`, `path_check`, `known_good_source`, `sources_considered`,
    `other_sources`, `intake`; Phase 6b adds `g1`, `gate_summary`, `trials[].gates`, `screen`). Exit 0 found, 75 cannot say, 2 error. Same server requirement as `g3`.
    - Large pipelines (`search.py`): up to 6 candidates every set up to `--max-size` is tried, in priority order (G0 clues, then G1 nominations).
      Above 6, minimal sets are found by duality: shrink a passing set (halving chunks of the lowest-priority nodes), then probe
      "all candidates except one node of each set found"; when every probe fails nothing else exists, and the size cutoff does not apply
      (`screen: {mode: "duality"|"enumeration", proved_no_others}`). It relies on monotonicity (restoring more never un-fixes a run), as the
      superset skip already did. An untestable probe is never proof. `--max-trials` unset = 40, or 3 per candidate + 20 when that is larger.
      Measured: 30/40/60 nodes, 5 planted shapes, 6-41 trials (2^60 exhaustive); 100 nodes 25 trials, 300 nodes 31.
    - G1 (`gates.py`, optional, off by default): `--g1-url` is an OpenAI-compatible base URL (`/chat/completions` is appended), key from
      `--g1-key`, `SHERLOCK_G1_API_KEY` or `OPENAI_API_KEY`. One call per sample, zero tools, node summaries redacted (`redact.py`), reply parsed
      into node names on the path. Samples only union. G1 only reorders trials (after G0 clue weight); it never adds, removes or labels a node.
      No usable answer (or the endpoint is down) = `g1.fallback: "g0_only"` and the diagnosis goes on unchanged. `g1` in the artifact:
      `{enabled, model, endpoint (no key/path), strength: "weak", tools_offered: 0, samples_requested, samples_ok, per_sample, nominated, ignored,
      prompt_chars, redactions, fallback, error, note}`; `enabled: false` when off. `tests/g1_stub.py --nodes a,b` is a deterministic stub for demos.
    - Per-gate attribution: `trials[].gates` = which gates put the restored nodes forward (`g0` clue, `g1` nominated, `g2` kept suspect, always `g3`);
      `gate_summary: {nodes_total, pruned_by_ancestry, pruned_other, g0_flagged, g1_nominated, g2_cut, g3_trials, exhaustive_count}`.
      `pruning.exhaustive_trials` is an exact Python integer (2^n - 1) and passes 2^53 above 53 nodes: show it as 2^n, not as a JS number.
    `search.py`, `clues.py`, `sources.py` are pure and tested without a server.
    - Known-good: `--good-run` names a prior successful run of the same input (`sources.py`): nodes with the same output are
      skipped, the run-context difference becomes a per-node patch (context items are attributed to a node by name prefix,
      e.g. `retriever.drop_latest`; anything else abstains `cannot_attribute`). Several successes are ranked (fewest differing
      nodes, then newest), each searched, disagreement abstains `sources_disagree`. `--known-good FILE` still works and overrides
      the derived patch per node. `--discover-good` also lists unconfirmed same-graph runs (never Sherlock's own forks).
    - G0 clues (`clues.py`): node errors, empty values, malformed JSON, loops, extractive tokens, tool-call errors, differs-from-passing-run.
      They are evidence (`strength: "clue"`), order the search, and widen it only when marked `widens`. G2 (`--suspect`): a suspect
      needs a recorded arrow on the tape or it is discarded; none left abstains `path_check_failed`.
  - `sherlock-rec intake --thread-id ID [--expected TEXT | --expected-file F | --check FILE] [--note T] [--dir .sherlock]`
    (`intake.py`): writes `.sherlock/intake/<id>.json`. With none of the three it is the "Wrong" click (no node named). `diagnose`
    reads it next to the cassette: an expected output becomes an `equals` check; with no check anywhere it returns the clues and
    abstains `no_check`.
  - `tests/seed_demo.py OUTDIR` regenerates the demo artifacts with the real pipeline (live `langgraph dev`, no provider);
    the checked-in copy is `harness/fixtures/sherlock-demo/` (try `sherlock serve --sherlock-dir harness/fixtures/sherlock-demo`).
  - `eval/live_demo.py OUTDIR` records all seven demo teams, diagnoses eleven failed runs (small and 30+ node teams: two-cause, AND across branches, redundant fix, crash, route change) and leaves three undiagnosed with the real pipeline,
    writes `OUTDIR/diagnoses/` and leaves the replay server running (prints `SERVER <url>`), so the web app can be tried end to end:
    `sherlock serve --langgraph-url <url> --sherlock-dir OUTDIR`. Ctrl-C stops it.
  - `sherlock-rec diagnose --node-map FILE` (`{context item or key: node}`) attributes run-context differences no node name claims
    (an unprefixed fault flag, a global prompt); otherwise they still abstain `cannot_attribute`.
  - `src/sherlock/evaluation.py` (pure): baselines (`last_node`, `random_node`, `g0_only`, `paste_and_play`), scoring (exact / wrong / abstain,
    Jaccard) and artifact honesty checks. `eval/run_eval.py [--out DIR | --check results.json]` is the Phase 6 runner: records a passing run per
    team and a failing run per case against the echo stub, replays in a socket trap, runs `diagnose` and the baselines, writes
    `docs/eval/results.{json,md}` (read `docs/eval/README.md` first). `--check` regenerates and diffs (about 5 min); exit 1 on any invariant,
    expectation or reproducibility failure. `tests/test_eval_results.py` re-checks the committed results offline.
  - Tests use `tests/stub_server.py` (OpenAI-compatible stub), `tests/llm_team.py`, `tests/g3_team/llm_graph.py`; no real provider calls.
- `docs/` — `notes/spec.md` (scope), `notes/status.md` (working tracker),
  `notes/fork-recipe.md` (dated findings from checking spec claims against real software); see `docs/README.md`.

## Progress tracking

`docs/notes/status.md` is the single live tracker. Read it before starting work. Update it
before stopping: tick items with evidence, add dated verified facts, decisions, and one
session-log line. Do not edit status columns inside the spec.

## Rules

1. CLI-first. New features get a CLI path first; `serve`/GUI is a view on top.
2. Controllers stay thin. `cli` and `api` parse input, call `app-core`, format output. No domain logic in them.
3. `app-core` has no dependency on `cli`, `api`, or `ui`.
4. UI stays vanilla React. No new deps unless needed.
5. Keep changes minimal; update CLI `--help` and this file if behavior changes.

## Commands

Teammate quickstart (`make` is a thin wrapper; the logic is in `scripts/*.sh`, so `bash scripts/<name>.sh` works without make, e.g. Git Bash on Windows):

```sh
make help         # list targets
make setup        # once: check tools (uv, Python 3.12, node+npm, cargo), npm ci, uv sync x2, build ui + cargo build -p cli
make doctor       # tools, versions, free ports, build state, with fixes
make demo         # live_demo.py -> .sherlock-demo/ (waits for the SERVER line), then sherlock serve on $PORT (default 3000); opens the browser
make demo-status  # make demo-stop / make clean
make test-fast    # no evaluation, no live-server tests: ui lint+build, harness, recorder offline, app-core/api/cli, clippy, fmt
make test         # = ./scripts/test.sh
make eval         # regenerate docs/eval
make serve        # dev server against your own `langgraph dev` on :2024
```

`demo` runs a private copy of the binary (`.sherlock-demo/bin/`) so rebuilds are not blocked by a running server on Windows, uses pid files and a port check (a second `make demo` does nothing), and logs to `.sherlock-demo/{lab,serve}.log`. `PORT=3100 make demo` changes the port, `OPEN=0` skips the browser.

Pre-deploy gate — all tests in one place, separated by crate. Run before shipping the CLI:

```sh
./scripts/test.sh
```

What it runs, in order:

```sh
cd ui && npm run lint && npm run build   # fresh dist so api embeds it
(cd harness && uv run pytest -q)   # demo teams + gold derivation
(cd python/sherlock && uv run pytest -q)   # recorder, checks, G3, diagnose (incl. live langgraph dev)
(cd python/sherlock && uv run python eval/run_eval.py --check ../../docs/eval/results.json)   # evaluation: reproducible table + invariants
cargo test -p app-core
cargo test -p api
cargo test -p cli
cargo run -q -p cli -- diagnoses list --sherlock-dir harness/fixtures/sherlock-demo   # demo smoke
cargo clippy --all-targets -- -D warnings
cargo fmt --check
```

## CLI diagnoses

```sh
sherlock diagnoses list [--sherlock-dir DIR] [--json]
sherlock diagnoses show THREAD_ID [--sherlock-dir DIR] [--json]
```

## CLI ingestion

```sh
sherlock ingest teams [--base-url URL] [--api-key KEY]
sherlock ingest runs [--assistant-id ID] [--limit N] [--offset N]
sherlock ingest logs --thread-id ID [--limit N] [--run-id RID]
```

Defaults to LangSmith when `LANGSMITH_API_KEY` is set, otherwise the local
dev server (`http://127.0.0.1:2024`). Prints pretty JSON. Live smoke test
(skipped unless the env var is set):

```sh
SHERLOCK_LIVE_URL=http://127.0.0.1:2024 cargo test -p app-core --test live_langgraph -- --nocapture
```
