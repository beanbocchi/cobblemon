#!/usr/bin/env bash
# Steps for the next planned server restart (run on the host, with nobody online):
#  1. copy the world datapack (landmarks, structure titles, first-visit biome names, cvlife:raining) into the world;
#  2. restart the container so the pack's fix mod 1.13 (/world /home /trade /challenge /landmark /goal /fly /tower) loads;
#  3. the pack also drops the No Hunger datapack; vanilla regeneration goes off for cvlife:regen
#  4. switch cvlife's messages from "!world" to "/world" and restart the daemon.
# Step 2 needs dist/latest.mrpack built from this repo with fix mod 1.13 and synced to the host first.
set -euo pipefail
EV="$HOME/cobblemon/server/events"
WORLD="$HOME/cobblemon/server/data/world"
n=$(docker exec cobbleverse rcon-cli list | sed 's/\x1b\[[0-9;]*m//g' | grep -oE 'There are [0-9]+' | grep -oE '[0-9]+')
if [ "$n" != "0" ] && [ "${FORCE:-0}" != "1" ]; then echo "$n players online, not restarting (FORCE=1 to restart anyway)"; exit 1; fi
rm -f "$HOME/cobblemon/server/data/datapacks/COBBLEVERSE - No Hunger.zip"  # dropped from the pack; hunger is back on
rm -rf "$WORLD/datapacks/cvlife"
cp -r "$EV/dp/cvlife" "$WORLD/datapacks/cvlife"
docker exec cobbleverse rcon-cli "save-all flush" >/dev/null
sleep 5
started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
docker restart cobbleverse >/dev/null
for _ in $(seq 1 120); do
  sleep 5
  docker logs --since "$started" cobbleverse 2>&1 | grep -q "Done (" && break
done
docker logs --since "$started" cobbleverse 2>&1 | grep -iE "cvlife|Failed to load function" | head -20 || true
# cvlife:regen heals players more slowly than vanilla, so vanilla regeneration goes off.
docker exec cobbleverse rcon-cli "gamerule naturalRegeneration false"
python3 - "$EV/life.json" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d["slash_commands"] = True
d["chat_only_commands"] = []  # commands the new fix mod adds (/legend in 1.15)
json.dump(d, open(p, "w"), ensure_ascii=False, indent=2)
PY
systemctl --user restart cobbleverse-life cobbleverse-events
echo "done"
