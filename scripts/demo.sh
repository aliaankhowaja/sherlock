#!/usr/bin/env bash
# Start the Sherlock demo: demo teams + recorded runs + diagnoses, then the web app.
# Usage: scripts/demo.sh [start|status]      Env: PORT (default 3000), OPEN=0 (do not open a browser)
# State, pid files and logs live in .sherlock-demo/ (lab.log, serve.log).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

PORT="${PORT:-3000}"
URL="http://127.0.0.1:$PORT"
mkdir -p "$DEMO"

alive() { [ -f "$DEMO/$1.pid" ] && pid_alive "$(cat "$DEMO/$1.pid")"; }

status() {
  local rc=1
  for n in lab serve; do
    if alive "$n"; then say "$n: running (pid $(cat "$DEMO/$n.pid"))"; rc=0; else say "$n: stopped"; fi
  done
  [ -f "$DEMO/lab.url" ] && say "lab server: $(cat "$DEMO/lab.url")"
  if alive serve; then
    sp="$(cat "$DEMO/serve.port" 2>/dev/null || echo "$PORT")"
    if curl -fsS -m 3 "http://127.0.0.1:$sp/api/info" >/dev/null 2>&1; then say "web app: http://127.0.0.1:$sp (answering)"; else say "web app: http://127.0.0.1:$sp (not answering; see $DEMO/serve.log)"; fi
  fi
  say "logs: $DEMO/lab.log $DEMO/serve.log"
  return $rc
}

[ "${1:-start}" = "status" ] && { status; exit $?; }

# Already running: do not start a second copy.
if alive serve && alive lab; then
  sp="$(cat "$DEMO/serve.port" 2>/dev/null || echo "$PORT")"
  say "Demo already running: http://127.0.0.1:$sp   (stop it with: make demo-stop)"
  [ "${OPEN:-1}" = 1 ] && open_url "http://127.0.0.1:$sp" || true
  exit 0
fi
# Half-running or stale: clear it first.
if alive serve || alive lab; then bash "$ROOT/scripts/demo-stop.sh" >/dev/null; fi

if port_in_use "$PORT"; then
  die "port $PORT is already in use by another program. Pick another: PORT=3100 make demo   (or: PORT=3100 bash scripts/demo.sh)"
fi
have uv || die "uv not found. Run: bash scripts/doctor.sh"
[ -x "$REC_BIN" ] || die "Python deps missing. Run: make setup   (or: bash scripts/setup.sh)"
[ -f "$ROOT/ui/dist/index.html" ] || die "UI not built. Run: make setup   (or: bash scripts/setup.sh)"

# Build (a no-op when up to date); fall back to an existing binary if the build fails.
if ! cargo build -q -p cli; then
  [ -x "$SHERLOCK_BIN" ] || die "cargo build failed and there is no binary. See the errors above, or run: bash scripts/doctor.sh"
  warn "cargo build failed; using the existing binary"
fi
# Run a private copy so a later rebuild is not blocked by this running server (Windows locks running .exe files).
mkdir -p "$DEMO/bin"
cp -f "$SHERLOCK_BIN" "$DEMO/bin/sherlock$EXE"

# 1. Demo teams: records runs, replays them offline, writes diagnoses. Takes a minute or two.
rm -rf "$DEMO/diagnoses" "$DEMO/lab"; rm -f "$DEMO/lab.url"
say "Starting the demo lab (records four+ teams and diagnoses them; about 1-3 minutes)..."
(cd "$ROOT/python/sherlock" && PYTHONUNBUFFERED=1 nohup uv run python eval/live_demo.py "$(native "$DEMO")" >"$DEMO/lab.log" 2>&1 &
 echo $! >"$DEMO/lab.sh.pid")
lab_sh="$(cat "$DEMO/lab.sh.pid")"; rm -f "$DEMO/lab.sh.pid"
echo "$lab_sh" >"$DEMO/lab.pid"

lab_url=""
for i in $(seq 1 300); do
  lab_url="$(sed -n 's/^SERVER //p' "$DEMO/lab.log" | tr -d '\r' | tail -1)"
  [ -n "$lab_url" ] && break
  alive lab || { tail -20 "$DEMO/lab.log" >&2; rm -f "$DEMO/lab.pid"; die "demo lab exited early; log above (full log: $DEMO/lab.log)"; }
  [ $((i % 5)) = 0 ] && printf '.'
  sleep 2
done
echo
if [ -z "$lab_url" ]; then bash "$ROOT/scripts/demo-stop.sh" >/dev/null; die "demo lab did not become ready in 10 minutes; see $DEMO/lab.log"; fi
echo "$lab_url" >"$DEMO/lab.url"
say "Lab ready at $lab_url"

# 2. Web app on top of it.
(nohup "$DEMO/bin/sherlock$EXE" serve --port "$PORT" --no-open \
   --langgraph-url "$lab_url" --sherlock-dir "$(native "$DEMO")" --project "$(native "$DEMO/lab")" \
   --sherlock-rec "$(native "$REC_BIN")" >"$DEMO/serve.log" 2>&1 &
 echo $! >"$DEMO/serve.sh.pid")
serve_sh="$(cat "$DEMO/serve.sh.pid")"; rm -f "$DEMO/serve.sh.pid"
echo "$serve_sh" >"$DEMO/serve.pid"; echo "$PORT" >"$DEMO/serve.port"

for i in $(seq 1 30); do
  curl -fsS -m 2 "$URL/api/info" >/dev/null 2>&1 && break
  alive serve || { tail -20 "$DEMO/serve.log" >&2; bash "$ROOT/scripts/demo-stop.sh" >/dev/null; die "sherlock serve exited; log above"; }
  sleep 1
done
curl -fsS -m 2 "$URL/api/info" >/dev/null 2>&1 || { bash "$ROOT/scripts/demo-stop.sh" >/dev/null; die "web app did not answer on $URL; see $DEMO/serve.log"; }

say
say "Sherlock is up:  $URL"
say "  stop it:       make demo-stop   (or: bash scripts/demo-stop.sh)"
say "  status/logs:   make demo-status;  $DEMO/lab.log, serve.log"
[ "${OPEN:-1}" = 1 ] && { open_url "$URL" || say "(open the URL in your browser)"; } || true
