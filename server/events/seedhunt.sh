#!/usr/bin/env bash
# Try random seeds until the world spawn sits in a green biome (forest, plains, meadow, savanna, jungle, cherry)
# that is not snowy or ocean, with a village within 800 blocks. Leaves the server running on the chosen world.
# Usage: seedhunt.sh [max_tries]
set -u
DATA=~/cobblemon/server/data
TRIES=${1:-8}
rc() { docker exec cobbleverse rcon-cli "$1" 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g'; }
wait_up() {
  local since=$1
  for _ in $(seq 1 180); do
    sleep 5
    docker logs --since "$since" cobbleverse 2>&1 | grep -q "Done (" && [ -f "$DATA/world/level.dat" ] && return 0
  done
  return 1
}
spawn_xz() {
  python3 -I - "$DATA/world/level.dat" <<'PY'
import gzip, sys, os
sys.path.insert(0, os.path.expanduser("~/cvscan"))
import anvil
d = anvil.nbt(gzip.decompress(open(sys.argv[1], "rb").read()))["Data"]
s = d.get("spawn") or {}
pos = s.get("pos") if isinstance(s, dict) else None
if pos:
    print(pos[0], pos[2])
else:
    print(d["SpawnX"], d["SpawnZ"])
PY
}
for t in $(seq 1 "$TRIES"); do
  seed=$(( (RANDOM << 30) ^ (RANDOM << 15) ^ RANDOM ))
  docker stop cobbleverse >/dev/null 2>&1
  rm -rf "$DATA/world"
  sed -i "s/^level-seed=.*/level-seed=$seed/" "$DATA/server.properties"
  started=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  docker start cobbleverse >/dev/null
  if ! wait_up "$started"; then echo "try $t seed $seed: did not start"; continue; fi
  read -r sx sz < <(spawn_xz)
  at="execute in minecraft:overworld positioned $sx 80 $sz"
  bad=""; good=""
  for tag in "#c:is_snowy" "#minecraft:is_ocean" "#minecraft:is_beach" "#minecraft:is_river" "#c:is_desert" "#minecraft:is_badlands" "#c:is_mushroom"; do
    rc "$at if biome ~ ~ ~ $tag" | grep -q passed && bad="$bad $tag"
  done
  for tag in "#minecraft:is_forest" "#c:is_plains" "#minecraft:is_savanna" "#minecraft:is_jungle" "#c:is_flower_forest" "#minecraft:is_taiga"; do
    rc "$at if biome ~ ~ ~ $tag" | grep -q passed && good="$good $tag"
  done
  village=$(rc "$at run locate structure #minecraft:village" | grep -oE "\([0-9]+ blocks away\)" | grep -oE "[0-9]+")
  echo "try $t seed $seed spawn $sx,$sz good:[$good] bad:[$bad] village:${village:-none}"
  if [ -z "$bad" ] && [ -n "$good" ] && [ -n "$village" ] && [ "$village" -le 800 ]; then
    echo "CHOSEN seed $seed"
    exit 0
  fi
done
echo "no seed matched after $TRIES tries; last world left running"
