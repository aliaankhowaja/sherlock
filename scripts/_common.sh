# Shared helpers for the scripts in this folder. Sourced, not run.
# Works in Git Bash on Windows, macOS and Linux.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"

case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) IS_WIN=1; EXE=".exe"; VENV_BIN="Scripts" ;;
  *) IS_WIN=0; EXE=""; VENV_BIN="bin" ;;
esac

# Native (Windows-style) path for tools that are not MSYS programs.
native() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }

TARGET_DIR="${CARGO_TARGET_DIR:-$ROOT/target}"
SHERLOCK_BIN="$TARGET_DIR/debug/sherlock$EXE"
REC_BIN="$ROOT/python/sherlock/.venv/$VENV_BIN/sherlock-rec$EXE"
DEMO="${DEMO_DIR:-$ROOT/.sherlock-demo}"

say()  { printf '%s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# True when something accepts connections on 127.0.0.1:$1.
port_in_use() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

# pid files hold the bash (MSYS) pid. The Windows pid is looked up at use time: right after launch
# /proc/<pid>/winpid still points at the launcher, not the final process.
winpid() { if [ "$IS_WIN" = 1 ] && [ -r "/proc/$1/winpid" ]; then cat "/proc/$1/winpid"; else printf '%s' "$1"; fi; }

pid_alive() {
  [ -n "${1:-}" ] || return 1
  if [ "$IS_WIN" = 1 ]; then
    [ -r "/proc/$1/winpid" ] && tasklist //FI "PID eq $(winpid "$1")" //NH 2>/dev/null | grep -q "[0-9]"
  else kill -0 "$1" 2>/dev/null; fi
}
kill_tree() {
  [ -n "${1:-}" ] || return 0
  if [ "$IS_WIN" = 1 ]; then
    taskkill //PID "$(winpid "$1")" //T //F >/dev/null 2>&1 || true
  else
    local kids; kids="$(pgrep -P "$1" 2>/dev/null || true)"
    for k in $kids; do kill_tree "$k"; done
    kill "$1" 2>/dev/null || true
  fi
}

open_url() {
  if [ "$IS_WIN" = 1 ]; then cmd //c start "" "$1" >/dev/null 2>&1 || true
  elif command -v open >/dev/null 2>&1; then open "$1" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$1" >/dev/null 2>&1 || true
  else return 1; fi
}

have() { command -v "$1" >/dev/null 2>&1; }
