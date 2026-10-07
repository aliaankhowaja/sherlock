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
- `ui/` — vanilla React + Vite + TS. No router/state/framework additions without reason.
  - `/` is the ingestion dashboard: teams → runs → error-first per-node log
    timeline (manual refresh, run filter, limit). Same-origin `/api/*` only.

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

Defaults to the local dev server (`http://127.0.0.1:2024`). Prints pretty
JSON. Live smoke test (skipped unless the env var is set):

```sh
SHERLOCK_LIVE_URL=http://127.0.0.1:2024 cargo test -p app-core --test live_langgraph -- --nocapture
```
