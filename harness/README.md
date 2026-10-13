# harness

Demo LangGraph teams, fault injection, gold derivation, and integration spikes for Sherlock (spec FR-E). This is Python, separate from the Rust engine and from the future `pip install sherlock` package.

## Setup

```sh
cd harness
uv sync            # Python 3.12, pinned by uv.lock
uv run pytest      # in-process tests, no server needed
```

## Layout

| Path | What it is |
|---|---|
| `sherlock_harness/teams/vendor_brief.py` | Demo team #1: five deterministic nodes and its check Z. Loaded by path by `langgraph dev`, so it must not import the rest of the package |
| `sherlock_harness/faults.py` | Fault catalogue; `run_team()`; `gold_minimal_sets()`, which derives gold by restoring subsets (FR-E3) |
| `langgraph.json` | Serves the demo teams with `langgraph dev` |
| `spikes/` | Scripts that check spec claims against a live server; results in `spikes/results/` |
| `fixtures/` | Real server responses, for Rust and Python tests |
| `tests/` | pytest |

## Serve a team and run the spikes

```sh
uv run langgraph dev --no-browser --no-reload --port 2024   # --no-reload: the spikes write files
uv run python spikes/fork_recipe.py
```

Faults are switched on per run through LangGraph runtime context:

```json
{"assistant_id": "vendor_brief", "input": {"vendor": "acme"}, "context": {"faults": ["retriever.drop_latest"]}}
```

## Adding a demo team

1. Add `sherlock_harness/teams/<name>.py` exporting `graph`, `CHECK` and `check()`. Keep it self-contained.
2. Register its faults, each with the node it lives on and whether it is harmful.
3. Add it to `langgraph.json`.
4. Add tests: the clean run passes, every harmful fault fails, gold comes from restoration.
5. Keep faults on deterministic nodes unless the team exists to test cassette replay (spec §9.1).
