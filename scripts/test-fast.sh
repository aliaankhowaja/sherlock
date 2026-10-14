#!/usr/bin/env bash
# Quick gate: everything in test.sh except the ~5 minute evaluation and the live-server tests.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
cd "$ROOT"
section() { echo; echo "=== $1 ==="; }

section "ui"
(cd ui && npm run lint && npm run build)
section "harness (python)"
(cd harness && uv run pytest -q)
section "recorder (python/sherlock, offline tests only: no live langgraph dev)"
(cd python/sherlock && uv run pytest -q --ignore=tests/test_g3_live.py --ignore=tests/test_eval_results.py)
section "app-core / api / cli"
cargo test -p app-core
cargo test -p api
cargo test -p cli
section "clippy + fmt"
cargo clippy --all-targets -- -D warnings
cargo fmt --check
echo; echo "Fast checks green (skipped: evaluation + live tests; run make test for the full gate)."
