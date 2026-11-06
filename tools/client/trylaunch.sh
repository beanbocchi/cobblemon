#!/usr/bin/env bash
# Launch the port profile offline on XWayland + NVIDIA, wait for the title screen, press F2, quit.
# Prints the screenshot path (or the failure) so the caller can look at it.
set -uo pipefail
P="$HOME/.local/share/ModrinthApp/profiles/${PROFILE:-COBBLEVERSE-1.7.42-cm1.8.4}"
OUT="$(cd "$(dirname "$0")/../.." && pwd)/build/client-tests"
mkdir -p "$OUT"
tag="${1:-run}"
cmd=$(python3 -I "$(dirname "$0")/launch_cmd.py" "$P")
before=$(ls "$P/screenshots" 2>/dev/null | wc -l)

cd "$P"
# An old latest.log already says "Game took"; park it so we only see this run.
[ -f logs/latest.log ] && mv logs/latest.log "logs/pre-$tag.log"
env -u WAYLAND_DISPLAY DISPLAY=:1 __NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia \
  bash -c "exec $cmd" > "$OUT/$tag.stdout" 2>&1 &
pid=$!

deadline=$((SECONDS + 420))
ready="Game took"; [ -n "${QUICKPLAY:-}" ] && ready="joined the game"
while kill -0 $pid 2>/dev/null && ! grep -q "$ready" "$P/logs/latest.log" 2>/dev/null; do
  [ $SECONDS -gt $deadline ] && { echo "TIMEOUT waiting for load"; kill $pid; exit 2; }
  sleep 3
done
kill -0 $pid 2>/dev/null || { echo "EXITED early"; tail -30 "$OUT/$tag.stdout"; exit 3; }
sleep 12
[ -n "${QUICKPLAY:-}" ] && sleep 25

win=""
for w in $(DISPLAY=:1 xdotool search --name "." 2>/dev/null); do
  [ "$(DISPLAY=:1 xdotool getwindowpid "$w" 2>/dev/null)" = "$pid" ] && win=$w
done
echo "window=$win"
[ -z "$win" ] && { echo "no game window"; kill $pid; exit 4; }
timeout 5 env DISPLAY=:1 xdotool windowactivate "$win" 2>/dev/null
sleep 1
DISPLAY=:1 xdotool key --window "$win" F2
sleep 1
DISPLAY=:1 xdotool key F2
sleep 4
timeout 10 env DISPLAY=:1 import -window "$win" "$OUT/$tag-xwin.png" 2>/dev/null

after=$(ls "$P/screenshots" | wc -l)
shot=$(ls -t "$P/screenshots"/*.png 2>/dev/null | head -1)
[ "$after" -gt "$before" ] && { cp "$shot" "$OUT/$tag-f2.png"; echo "F2 screenshot: $OUT/$tag-f2.png"; } || echo "no new F2 screenshot"
cp "$P/logs/latest.log" "$OUT/$tag.log"
kill $pid; sleep 5; kill -9 $pid 2>/dev/null
echo "done"
