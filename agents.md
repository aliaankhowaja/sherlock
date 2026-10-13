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
- `crates/cli/` — thin CLI controller over `app-core` (+ triggers `api` for `serve`). Primary interface.
- `crates/api/` — thin HTTP controller over `app-core`. Serves `ui/dist` via rust-embed, opens browser.
  - Proxies LangGraph for the dashboard: `GET /api/teams`, `GET /api/runs`,
    `GET /api/logs` (400 on missing `thread_id`, 502 + `{error}` JSON when
    LangGraph is down). Connection fixed at startup via `serve`
    `--langgraph-url` (default `http://127.0.0.1:2024`) / `--langgraph-api-key`.
    When `LANGSMITH_API_KEY` is set (flag, env, or `.env`), `serve` and `ingest`
    read LangSmith traces instead (`--source langgraph` forces the local server).
    Team = `metadata.assistant_id`, run = `thread_id`, logs = runs in that thread.
- `ui/` — vanilla React + Vite + TS. No router/state/framework additions without reason.
  - `/` is the ingestion dashboard: teams → runs → error-first per-node log
    timeline (manual refresh, run filter, limit). Same-origin `/api/*` only.
- `harness/` — Python (uv, 3.12): demo LangGraph teams with fault injection, gold
  derivation, live-server spikes and fixtures. See `harness/README.md`.
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
    G3 refuses otherwise. Known-good file: `{node: {context_key: value | {"$remove": [..]}}}` (see `harness/known_good/`).
  - `sherlock-rec diagnose --thread-id ID --known-good FILE [-c sherlock.yaml] [--url URL] [--cassette PATH] [--max-trials 40] [--max-minutes 10] [--max-size 3] [--out DIR]`
    (`diagnose.py` over `search.py`): prune candidates (`plan_candidates`), probe, then singletons, pairs and up to `--max-size`
    nodes through `run_g3`; returns every 1-minimal set or an abstain with a reason code. Writes `.sherlock/diagnoses/<thread_id>.json`
    (schema 1: `status`, `minimal_sets`, `unverified_sets`, `trials` with four labels, `counts`, `pruning`, `trial_reduction`, `budget`).
    Exit 0 found, 75 cannot say, 2 error. Same server requirement as `g3`. `search.py` is pure and tested with a fake oracle.
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
cargo test -p app-core
cargo test -p api
cargo test -p cli
cargo clippy --all-targets -- -D warnings
cargo fmt --check
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
