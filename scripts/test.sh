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

section "app-core"
cargo test -p app-core

section "api"
cargo test -p api

section "cli"
cargo test -p cli

section "clippy + fmt"
cargo clippy --all-targets -- -D warnings
cargo fmt --check

echo
echo "All green."
