#!/usr/bin/env bash
# Final G1 Laya ordering evaluation on the large public-trace corpus (docs/eval/public_traces).
# Usage: make g1-public   (or: bash scripts/g1-public.sh)
#
# Runs eval/public_g1.py over docs/eval/public_traces/cases.jsonl (5,032 traces: 4,112 headline rows
# and 920 mathchat two_role rows, which only appear in the appendix) and writes public_g1.md and
# public_g1.json into docs/eval/public_traces. The corpus file is gitignored; if it is missing the
# script expands cases.jsonl.gz.
#
# LOCAL mode (the default, for the A100 box) runs the `laya` package in this process through
# `uv run --with laya`: nothing leaves the machine and no key is needed. Set LOCAL=false and
# LAYA_API_KEY to use the hosted endpoint instead. Card scores are cached in
# python/sherlock/eval/.g1/public_cache, so a re-run after a failure only pays for what is missing.
#
# Shutdown: once the evaluation is armed (after the smoke test), the machine shuts down when the
# script ends, even if the evaluation failed (the cache makes a re-run cheap). Shutdown is armed
# SHUTDOWN_DELAY_MIN minutes ahead, so the printed results can be read and `sudo shutdown -c`
# cancels it. `SHUTDOWN=0 make g1-public` skips the shutdown entirely.
SHUTDOWN_DELAY_MIN="${SHUTDOWN_DELAY_MIN:-5}"
set -euo pipefail
cd "$(dirname "$0")/.."

section() { echo; echo "=== $1 ==="; }
truthy() { case "${1:-}" in 1|true|TRUE|True|yes|YES|Yes|on|ON|On) return 0;; *) return 1;; esac; }
falsy() { case "${1:-}" in 0|false|FALSE|False|no|NO|No|off|OFF|Off) return 0;; *) return 1;; esac; }

if [ -f .env ]; then
  if [ -z "${LAYA_API_KEY:-}" ]; then
    LAYA_API_KEY="$(grep '^LAYA_API_KEY=' .env | head -1 | cut -d= -f2- | tr -d '\r"'"'"'' || true)"
    [ -z "$LAYA_API_KEY" ] || export LAYA_API_KEY
  fi
  if [ -z "${LOCAL:-}" ]; then
    LOCAL="$(grep '^LOCAL=' .env | head -1 | cut -d= -f2- | tr -d '\r"'"'"'' || true)"
    [ -z "$LOCAL" ] || export LOCAL
  fi
fi

if truthy "${SHUTDOWN:-1}"; then
  if ! sudo -n true 2>/dev/null; then
    echo "g1-public: sudo needs a password, so the shutdown at the end would hang forever." >&2
    echo "  Either skip the shutdown:        SHUTDOWN=0 make g1-public" >&2
    echo "  Or allow it passwordless, then run again:" >&2
    echo "    echo \"\$(id -un) ALL=(root) NOPASSWD: /usr/sbin/shutdown\" | sudo tee /etc/sudoers.d/shutdown" >&2
    echo "    sudo chmod 440 /etc/sudoers.d/shutdown" >&2
    exit 1
  fi
fi
# The delay is a user knob; go through sudo like every shutdown below.
[ -n "${SHUTDOWN_DELAY_MIN:-}" ] || SHUTDOWN_DELAY_MIN=5

armed=0
shut_down() {
  [ "$armed" = 1 ] || return 0
  if truthy "${SHUTDOWN:-1}"; then
    echo
    section "shutting down in ${SHUTDOWN_DELAY_MIN} minutes (cancel with: sudo shutdown -c)"
    sudo shutdown -h +"$SHUTDOWN_DELAY_MIN" \
      "sherlock: the final g1 (laya) evaluation finished; this machine shuts down"
  else
    echo
    echo "SHUTDOWN=0: leaving the machine on."
  fi
}
trap shut_down EXIT

if [ ! -f docs/eval/public_traces/cases.jsonl ]; then
  section "expanding the corpus: gunzip -k docs/eval/public_traces/cases.jsonl.gz"
  gunzip -k docs/eval/public_traces/cases.jsonl.gz
fi
[ -f docs/eval/public_traces/cases.jsonl ] \
  || { echo "g1-public: docs/eval/public_traces/cases.jsonl is missing (and cases.jsonl.gz did not produce it)" >&2; exit 1; }

if falsy "${LOCAL:-}"; then
  [ -n "${LAYA_API_KEY:-}" ] || { echo "g1-public: LOCAL=false needs LAYA_API_KEY (environment or .env)" >&2; exit 1; }
  RUN=(uv run)
  smoke_args=(--g1-allow-remote)
  label="endpoint"
else
  # Default: final evaluations run locally, in-process (A100 box). LOCAL=true also lands here.
  RUN=(uv run --with laya)
  smoke_args=()
  label="local"
  export LOCAL=true
fi

cd python/sherlock

section "1/2 smoke test: Laya answers the sample card ($label)"
"${RUN[@]}" sherlock-rec g1-check "${smoke_args[@]}"

armed=1
section "2/2 final run: public_g1 over the 5,032-trace public corpus (the long step; results print at the end)"
"${RUN[@]}" python eval/public_g1.py \
  --cases ../../docs/eval/public_traces/cases.jsonl \
  --backend laya --out ../../docs/eval/public_traces

echo
echo "Done. public_g1.md and public_g1.json are in docs/eval/public_traces; commit them afterwards."
