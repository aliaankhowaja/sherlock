# sherlock

Multi-agent team debugger. Finds the minimal set of agents suspected to be faulty.

## Architecture

- `crates/app-core/` — core logic (fault isolation). No CLI, HTTP, or UI code.
- `crates/cli/` — primary interface. Thin controller over `app-core`. Binary: `sherlock`.
- `crates/api/` — HTTP controller over `app-core`. Serves embedded React UI (axum + rust-embed). Opened via CLI.
- `ui/` — vanilla React + Vite + TS. No meta-framework. Served by `api`, opened by `cli serve`.

CLI-first: `cli` and `api` are controllers only. All domain logic lives in `app-core`.

## First-time setup

```sh
source "$HOME/.cargo/env"   # if cargo is not on PATH yet
cd ui && npm install && npm run build && cd ..
cargo build
```

## Try the GUI (what’s implemented today)

Ingestion dashboard: **teams → runs → per-node logs**, backed by a LangGraph API server.

1. Run a LangGraph Agent Server on **`http://127.0.0.1:2024`** (default). This repo does not ship a graph app — use your own LangGraph project and `langgraph dev`. See [Run a local server](https://docs.langchain.com/oss/python/langgraph/local-server) and `agents.md` for API mapping and flags.
2. Start sherlock:

```sh
cargo run -p cli -- serve
```

3. Open **http://127.0.0.1:3000**. Use refresh on each pane. Threads need **`metadata.assistant_id`** for team filtering in the UI.

Without LangGraph, the shell and `/api/health` still work; teams/runs/logs will error until the upstream is up.

## Usage

```sh
cargo run -p cli -- --help
cargo run -p cli -- serve
cargo run -p cli -- ingest teams
cargo run -p cli -- ingest runs --limit 20
cargo run -p cli -- ingest logs --thread-id <THREAD_ID>
```

## Develop

```sh
cargo build
cargo test
./scripts/test.sh
cargo clippy -- -D warnings
cargo fmt --check
cd ui && npm install && npm run dev   # UI dev server
cd ui && npm run build                # embedded by api via rust-embed
```

Live ingestion test (optional; LangGraph must be running):

```sh
SHERLOCK_LIVE_URL=http://127.0.0.1:2024 cargo test -p app-core --test live_langgraph -- --nocapture
```
