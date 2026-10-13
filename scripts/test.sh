#!/usr/bin/env bash
# Pre-deploy test gate: all tests in one place, separated by crate.
# Usage: ./scripts/test.sh
#
# UI builds first so the api crate embeds a fresh ui/dist via rust-embed.
set -euo pipefail

section() { echo; echo "=== $1 ==="; }

section "ui"
cd ui && npm run lint && npm run build
cd ..

section "harness (python)"
(cd harness && uv run pytest -q)

section "recorder (python/sherlock)"
(cd python/sherlock && uv run pytest -q)

section "evaluation (4 teams x fault cases, baselines, invariants; regenerates and diffs docs/eval/results.json, ~5 min)"
(cd python/sherlock && uv run python eval/run_eval.py --check ../../docs/eval/results.json)

section "app-core"
cargo test -p app-core

section "api"
cargo test -p api

section "cli"
cargo test -p cli

section "demo smoke (seeded diagnoses render in the CLI)"
cargo run -q -p cli -- diagnoses list --sherlock-dir harness/fixtures/sherlock-demo | grep -q "culprit set {retriever, extractor}"

section "clippy + fmt"
cargo clippy --all-targets -- -D warnings
cargo fmt --check

echo
echo "All green."
