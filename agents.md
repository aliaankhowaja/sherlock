# agents.md

Repo: `sherlock` — minimal suspect-agent finder for multi-agent teams.

## Layout

- `crates/app-core/` — domain logic only. Put fault-isolation logic here.
  - `ingestion` module: LangGraph data intake. Team = assistant
    (`POST /assistants/search`), team run = thread (`POST /threads/search`,
    team association via `metadata.assistant_id`), run logs = checkpoint
    history (`POST /threads/{id}/history`) expanded to per-node events.
    No I/O inside: callers inject `LangGraphTransport`; real HTTP + `serve`
    endpoints live in `cli`/`api`.
  - `diagnosis` module: reads and validates `.sherlock/diagnoses/<thread_id>.json` (schema 1) and computes one
    verified status per node (`culprit` = in a G3-verified minimal set, `cleared` = tested in a complete search and in no set,
    `unverified` = pruned/untested/undecided, `abstained` = the diagnosis said "cannot say"). Refuses contradictory artifacts.
    The colour rules live here, never in the UI. `DiagnosisStore { sherlock_dir }` does the file reads.
- `crates/cli/` — thin CLI controller over `app-core` (+ triggers `api` for `serve`). Primary interface.
  `sherlock diagnoses list|show THREAD_ID [--json] [--sherlock-dir DIR]` prints verdicts; `serve --sherlock-dir DIR` (default `.sherlock`).
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
    sherlock_dir). Read-only: no endpoint starts a run, a diagnosis or a tool.
- `ui/` — vanilla React + Vite + TS. No router/state/framework additions without reason.
  - `/explore` is the ingestion dashboard: teams → runs → error-first per-node log
    timeline (manual refresh, run filter, limit). Same-origin `/api/*` only.
  - Paths (`history.pushState`, no router dep): `/` guided four-step flow (pick failed run, pick known-good run, copy the
    `sherlock-rec diagnose` command, read the verdict) plus glossary; `/runs/:id` run page (verdict, failed check, nodes
    coloured by verified status, evidence, trial log, read-only HTML/JSON download); `/explore` the ingestion dashboard.
    Diagnosis is a copy-paste command, not a browser button (a web page must not be able to start commands).
    Shared bits: `parts.tsx` (components), `terms.ts` (labels, glossary, command builder), `share.ts`, `api.ts`.
- `harness/` — Python (uv, 3.12): four demo LangGraph teams (`vendor_brief`, `order_desk`, `invoice_pipeline`, `support_bot` = the LLM-node team)
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
  - `sherlock-rec diagnose --thread-id ID [--good-run THREAD]... [--discover-good] [--known-good FILE] [--suspect NODE[->NODE]]... [-c sherlock.yaml] [--url URL] [--cassette PATH] [--max-trials 40] [--max-minutes 10] [--max-size 3] [--out DIR]`
    (`diagnose.py` over `search.py`): prune candidates (`plan_candidates`), probe, then singletons, pairs and up to `--max-size`
    nodes through `run_g3`; returns every 1-minimal set or an abstain with a reason code. Writes `.sherlock/diagnoses/<thread_id>.json`
    (schema 1, additive: `status`, `minimal_sets`, `unverified_sets`, `trials` (with `n`, `elapsed_s`), `counts`, `pruning` (with
    `pruned_ratio`), `trial_reduction`, `budget`, plus `clues`, `path_check`, `known_good_source`, `sources_considered`,
    `other_sources`, `intake`). Exit 0 found, 75 cannot say, 2 error. Same server requirement as `g3`.
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
  - `sherlock-rec diagnose --node-map FILE` (`{context item or key: node}`) attributes run-context differences no node name claims
    (an unprefixed fault flag, a global prompt); otherwise they still abstain `cannot_attribute`.
  - `src/sherlock/evaluation.py` (pure): baselines (`last_node`, `random_node`, `g0_only`, `paste_and_play`), scoring (exact / wrong / abstain,
    Jaccard) and artifact honesty checks. `eval/run_eval.py [--out DIR | --check results.json]` is the Phase 6 runner: records a passing run per
    team and a failing run per case against the echo stub, replays in a socket trap, runs `diagnose` and the baselines, writes
    `docs/eval/results.{json,md}` (read `docs/eval/README.md` first). `--check` regenerates and diffs (about 5 min); exit 1 on any invariant,
    expectation or reproducibility failure. `tests/test_eval_results.py` re-checks the committed results offline.
  - Tests use `tests/stub_server.py` (OpenAI-compatible stub), `tests/llm_team.py`, `tests/g3_team/llm_graph.py`; no real provider calls.
- `docs/` — `sherlock-spec.md` (scope; governs), `STATUS.md` (live progress),
  `spikes/` (dated findings from checking spec claims against real software).

## Progress tracking

`docs/STATUS.md` is the single live tracker. Read it before starting work. Update it
before stopping: tick items with evidence, add dated verified facts, decisions, and one
session-log line. Do not edit status columns inside the spec.

## Rules

1. CLI-first. New features get a CLI path first; `serve`/GUI is a view on top.
2. Controllers stay thin. `cli` and `api` parse input, call `app-core`, format output. No domain logic in them.
3. `app-core` has no dependency on `cli`, `api`, or `ui`.
4. UI stays vanilla React. No new deps unless needed.
5. Keep changes minimal; update CLI `--help` and this file if behavior changes.

## Commands

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
