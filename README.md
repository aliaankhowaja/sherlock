# Sherlock

Sherlock finds which agent in a multi-agent LangGraph team broke a run. You give it a failed run and a run that passed.
It replays the recorded run offline (no live model calls), swaps one agent's behaviour at a time, and tells you the smallest set of agents to blame, or says "cannot say".

## Quickstart

```sh
git clone <repo-url> sherlock && cd sherlock
make setup     # once: checks tools, installs dependencies, builds everything (first run: several minutes)
make demo      # starts the demo teams and the web app, opens http://127.0.0.1:3000
```

No `make` (common on Windows)? Use Git Bash and run the scripts it wraps: `bash scripts/setup.sh`, then `bash scripts/demo.sh`.
Stop with `make demo-stop` (`bash scripts/demo-stop.sh`). Not sure what is missing? `make doctor`.

## What you will see

The demo records several example agent teams with injected faults, then opens the web app. It walks through four steps:

1. **Pick runs**: choose a team, a failed run and a run that passed.
2. **Pipeline and replay**: watch the failed run replayed node by node, with what each agent received and produced.
3. **Diagnose**: press the button; Sherlock re-runs the team with one agent at a time restored to known-good behaviour.
4. **Verdict**: the smallest set of agents that fixes the run (for example, "retriever and extractor together; neither alone"), with the evidence.

## Tests

```sh
make test-fast   # a few minutes: unit tests, lint, build, clippy, fmt
make test        # full gate, adds the ~5 minute evaluation (docs/eval)
```

## Optional: G1 trial ordering with Laya

Off by default. `sherlock-rec diagnose --g1 laya --g1-allow-remote` asks the Laya System One API, zero-shot, how likely each remaining agent is to need restoring, and tests the likeliest first. It only changes the order of trials: the answer is the same with it on or off, and if the API fails the run continues as if it were off.

- **Key:** set `LAYA_API_KEY` in the environment or in a `.env` file in the directory you run from. It is never a flag and is never written to results, logs or the cache.
- **Privacy:** the endpoint (default `https://api.laya.studio`, or `--g1-endpoint` / `LAYA_API_BASE`) is remote, so a short, redacted card per agent leaves your machine. That is why `--g1-allow-remote` is required; a local endpoint (`localhost`) needs neither the flag nor a key.
- **Check first:** `sherlock-rec g1-check --g1-allow-remote` sends the built-in sample card twice and prints the model, token use and every answer.
- **Model:** `typed-decisions` by default (English, 1,024-token context; `--g1-model` to change). Without a model name the service guesses the language and can pick its multilingual model.
- **Reproducible:** answers are cached in `.sherlock/g1_cache/`, so a re-run gives the same order offline. `--g1-no-cache` always calls the API.
- **Expect little:** Laya is used zero-shot (never trained on these questions), and zero-shot results for such models are reported close to chance. Treat its order as a weak hint.

## Where things are

`AGENTS.md` has the layout, commands and team rules. `docs/README.md` explains the docs; `docs/notes/status.md` is the working tracker (orientation only).
In short: `crates/` (Rust engine, CLI, web server), `ui/` (React app), `python/sherlock/` (recorder, replay, diagnose), `harness/` (demo teams).

## Troubleshooting

| Problem | Fix |
|---|---|
| `port 3000 is already in use` | `PORT=3100 make demo` |
| `uv not found` | Install uv: https://docs.astral.sh/uv/ (Windows: `winget install astral-sh.uv`), then open a new terminal |
| `cargo not found` | Install Rust from https://rustup.rs, open a new terminal |
| `make: command not found` (Windows) | Use Git Bash and `bash scripts/setup.sh`, `bash scripts/demo.sh`, `bash scripts/demo-stop.sh` |
| Demo hangs or fails to start | Read `.sherlock-demo/lab.log` and `.sherlock-demo/serve.log`; then `make demo-stop` and retry |
| Rebuild fails with "access denied" on Windows | A running server locks its binary; `make demo` runs a private copy, so only your own `cargo run` serve causes this: stop it |
| Anything else | `make doctor` lists missing tools with fixes |

`make help` lists every target.
