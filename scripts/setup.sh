#!/usr/bin/env bash
# One-time setup: check tools, install dependencies, build the UI and the sherlock binary.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
cd "$ROOT"

say "== 1/5 checking prerequisites =="
bash scripts/doctor.sh --prereq || die "install the missing tools above, then run setup again"

say; say "== 2/5 Python 3.12 (via uv) =="
uv python install 3.12

say; say "== 3/5 Python dependencies (harness, python/sherlock) =="
(cd harness && uv sync)
(cd python/sherlock && uv sync)

say; say "== 4/5 UI (npm ci, build) =="
(cd ui && npm ci --no-audit --no-fund && npm run build)

say; say "== 5/5 sherlock binary (cargo build -p cli; first build takes a few minutes) =="
cargo build -p cli

say
say "Setup done. Next: make demo   (or: bash scripts/demo.sh)"
