#!/usr/bin/env bash
# Check that this machine can build and run Sherlock. Prints a fix for every problem.
# Usage: scripts/doctor.sh [--prereq]   (--prereq: tools only, skip ports and build state)
# Exit code 1 when a required tool is missing.
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

PORT="${PORT:-3000}"
bad=0
ok()   { printf '  ok       %-14s %s\n' "$1" "$2"; }
miss() { printf '  MISSING  %-14s %s\n' "$1" "$2"; bad=1; }
note() { printf '  note     %-14s %s\n' "$1" "$2"; }

say "Tools"
if have uv; then ok uv "$(uv --version | cut -d' ' -f2)"
else miss uv "install: https://docs.astral.sh/uv/getting-started/installation/  (Windows: winget install astral-sh.uv)"; fi

if have uv && uv python find 3.12 >/dev/null 2>&1; then ok python3.12 "$(uv python find 3.12)"
elif have uv; then note python3.12 "not found yet; 'make setup' installs it (uv python install 3.12)"
else miss python3.12 "needs uv first, then: uv python install 3.12"; fi

if have node; then
  v="$(node -v | tr -d v)"
  if [ "${v%%.*}" -ge 20 ] 2>/dev/null; then ok node "$v"; else miss node "$v is too old, need 20+: https://nodejs.org"; fi
else miss node "install Node 20+ (includes npm): https://nodejs.org  (Windows: winget install OpenJS.NodeJS.LTS)"; fi
if have npm; then ok npm "$(npm -v)"; else miss npm "comes with Node: https://nodejs.org"; fi

if have cargo; then
  ok cargo "$(cargo --version | cut -d' ' -f2)"
  host="$(rustc -vV 2>/dev/null | sed -n 's/^host: //p')"
  case "$host" in
    *msvc*) have link || note linker "msvc toolchain but link.exe not on PATH: install Visual Studio Build Tools (C++)" ;;
    *gnu*)  if [ "$IS_WIN" = 1 ] && ! have gcc; then miss gcc "gnu toolchain needs gcc: install MSYS2 (https://www.msys2.org) and add ucrt64/bin to PATH, or 'rustup default stable-x86_64-pc-windows-msvc'"; fi ;;
  esac
else miss cargo "install Rust via https://rustup.rs  (then open a new terminal, or: source \"\$HOME/.cargo/env\")"; fi

have curl && ok curl "" || miss curl "needed to wait for the servers; install curl"
have make && ok make "" || note make "not installed: fine, use 'bash scripts/<name>.sh' (setup, demo, demo-stop, doctor, test-fast)"
have git && ok git "" || note git "not found"

if [ "${1:-}" != "--prereq" ]; then
  say; say "Ports (free = good)"
  for p in "$PORT"; do
    if port_in_use "$p"; then
      if [ -f "$DEMO/serve.pid" ] && pid_alive "$(cat "$DEMO/serve.pid")"; then ok "port $p" "in use by the Sherlock demo (make demo-stop to free it)"
      else miss "port $p" "in use by another program. Free it, or pick another: PORT=3100 make demo"; fi
    else ok "port $p" "free"; fi
  done
  if port_in_use 2024; then note "port 2024" "in use (fine if it is your 'langgraph dev' for 'make serve')"; else note "port 2024" "free ('make serve' expects your langgraph dev here)"; fi

  say; say "Build state"
  [ -d "$ROOT/ui/node_modules" ] && ok ui-deps "" || note ui-deps "missing: run make setup"
  [ -f "$ROOT/ui/dist/index.html" ] && ok ui-build "" || note ui-build "missing: run make setup"
  [ -x "$SHERLOCK_BIN" ] && ok sherlock "$SHERLOCK_BIN" || note sherlock "not built: run make setup"
  [ -x "$REC_BIN" ] && ok sherlock-rec "" || note sherlock-rec "not installed: run make setup"
fi

say
if [ "$bad" = 1 ]; then say "Fix the MISSING items above, then re-run: bash scripts/doctor.sh"; exit 1; fi
say "All required tools present."
