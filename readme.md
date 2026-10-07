# sherlock

Multi-agent team debugger. Finds the minimal set of agents suspected to be faulty.

## Architecture

- `crates/app-core/` — core logic (fault isolation). No CLI, HTTP, or UI code.
- `crates/cli/` — primary interface. Thin controller over `app-core`. Binary: `myapp`.
- `crates/api/` — HTTP controller over `app-core`. Serves embedded React UI (axum + rust-embed). Opened via CLI.
- `ui/` — vanilla React + Vite + TS. No meta-framework. Served by `api`, opened by `cli serve`.

CLI-first: `cli` and `api` are controllers only. All domain logic lives in `app-core`.

## Usage

```sh
cargo run -p cli -- --help
cargo run -p cli -- serve   # start API + open React GUI
```

## Develop

```sh
cargo build
cargo test
cargo clippy -- -D warnings
cargo fmt --check
cd ui && npm install && npm run dev   # UI dev server
cd ui && npm run build                # embedded by api via rust-embed
```
