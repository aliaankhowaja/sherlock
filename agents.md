# agents.md

Repo: `sherlock` — minimal suspect-agent finder for multi-agent teams.

## Layout

- `crates/app-core/` — domain logic only. Put fault-isolation logic here.
- `crates/cli/` — thin CLI controller over `app-core` (+ triggers `api` for `serve`). Primary interface.
- `crates/api/` — thin HTTP controller over `app-core`. Serves `ui/dist` via rust-embed, opens browser.
- `ui/` — vanilla React + Vite + TS. No router/state/framework additions without reason.

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
