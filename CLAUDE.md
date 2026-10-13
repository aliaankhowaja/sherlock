@agents.md

## Every session

- **Before starting:** read `docs/STATUS.md` (live progress) and the relevant part of `docs/sherlock-spec.md`. The spec governs scope.
- **Before stopping:** update `docs/STATUS.md`.
  - Tick items, with evidence.
  - Add dated verified facts.
  - Record decisions.
  - Add one session-log line.
- Never edit the status columns inside the spec. `docs/STATUS.md` is the only live status.

## Model and tokens

- Build sessions run Sonnet with an Opus advisor: `claude --model sonnet --advisor opus`.
- The advisor reads the whole conversation on every call. Keep sessions to one task and run `/clear` between tasks; `STATUS.md` carries the state.
- The token budget is tight. Don't stop for routine confirmations, keep output short, and grep instead of reading whole files.

## Commits

- Atomic: one logical change per commit.
- Never add Claude or AI co-author trailers, or "Generated with" lines.
- Add the **other two** team members as trailers. The committer is not listed.
  ```
  Co-authored-by: Wajih-Ur-Raza Asif <152525473+wajih-rathore@users.noreply.github.com>
  Co-authored-by: Ibraheem Farooq <ibraheemfrq@gmail.com>
  Co-authored-by: Ali Aan Khowaja <aliaankhowaja@gmail.com>
  ```
- Message: a conventional subject, then one plain-language line on why it matters, then the details.

## Windows

- Rust on the dev machine is `stable-x86_64-pc-windows-gnu`, using msys64 gcc; there is no MSVC. If `cargo` is not on `PATH`, prefix with `~/.cargo/bin/`.
