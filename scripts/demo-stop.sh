#!/usr/bin/env bash
# Stop the demo servers started by scripts/demo.sh (only those; pid files in .sherlock-demo/).
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

for n in serve lab; do
  f="$DEMO/$n.pid"
  if [ -f "$f" ]; then
    pid="$(cat "$f")"
    if pid_alive "$pid"; then kill_tree "$pid"; say "stopped $n (pid $pid)"; else say "$n was not running"; fi
    rm -f "$f"
  fi
done
rm -f "$DEMO/serve.port" "$DEMO/lab.url"
say "Demo stopped."
