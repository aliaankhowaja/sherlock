# AGENTS.md

Sherlock finds which agent in a multi-agent LangGraph team broke a run. Given a failed run and a run that passed, it replays the recording offline (no live model calls), restores one agent's known-good behaviour at a time, and reports the smallest set of agents to blame, or "cannot say".

## Layout

- `python/sherlock/src/sherlock/` — the diagnosis engine (record, replay, checks, G3 fork, search, diagnose). Console script `sherlock-rec`.
- `crates/app-core/` — Rust domain logic: ingestion, run replay (`steps`), topology, diagnosis validation.
- `crates/cli/` — the `sherlock` CLI, a thin controller over `app-core`.
- `crates/api/` — the HTTP server for the web app (`sherlock serve`), a thin controller over `app-core`.
- `ui/` — the web app (vanilla React + Vite + TS).
- `harness/` — demo LangGraph teams with injected faults.
- `scripts/` — what `make` wraps (`setup`, `demo`, `test`, `doctor`).
- `docs/` — evaluation evidence (`docs/eval`) and working notes. Start at `docs/README.md`.

## Commands

```sh
make setup       # once: check tools, install deps, build ui + cli
make demo        # demo teams + web app on http://127.0.0.1:3000
make test-fast   # unit tests, lint, build, clippy, fmt (no evaluation, no live server)
make test        # full gate (adds the ~5 minute evaluation); = ./scripts/test.sh
make doctor      # missing tools, versions, ports, with fixes
```

No `make`: run `bash scripts/<name>.sh`. Per language:
`cd python/sherlock && uv run pytest -q` · `cd harness && uv run pytest -q` ·
`cargo test -p app-core|api|cli` · `cargo clippy --all-targets -- -D warnings` · `cargo fmt --check` · `cd ui && npm run lint && npm run build`.

## Team rules

- Atomic conventional commits: one logical change each.
- After the subject, one plain-language line saying why it matters, then the details.
- Never add Claude or AI trailers, or "Generated with" lines.
- Add the **other two** members as trailers (the committer is not listed):
  `Co-authored-by: Wajih-Ur-Raza Asif <152525473+wajih-rathore@users.noreply.github.com>`
  `Co-authored-by: Ibraheem Farooq <ibraheemfrq@gmail.com>`
  `Co-authored-by: Ali Aan Khowaja <aliaankhowaja@gmail.com>`
- Update `docs/notes/status.md` before stopping a work session.

## Windows

Rust is `stable-x86_64-pc-windows-gnu` with msys64 gcc; there is no MSVC. If `cargo` is not on `PATH`, use `~/.cargo/bin/cargo`.

## Authority tiers

0 Official (university documents), 1 Submitted (proposal, mid report), 2 Evidence (code, test output, `docs/eval/results.json`),
3 Working notes (everything we or agents wrote: status, specs, plans, logs).
Tier 3 is orientation only: it can be stale and is never cited as truth. If a note disagrees with the code or tiers 0-2, the note is wrong.
Details: `docs/README.md`.

## Current work

The active build plan is `docs/notes/g1-laya-spec.md`: the G1 Laya API ranker (v0, six build steps), default off behind `--g1`.

## More

- `docs/README.md` — doc tiers and index
- `docs/notes/architecture.md` — module layout, rules, CLI
- `docs/notes/ui-api-contract.md` — web API contract for the UI
