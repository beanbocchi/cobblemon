#!/usr/bin/env bash
# Build dist/<name>.mrpack from the upstream Cobbleverse pack and port.json.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
CACHE="$ROOT/.cache"
BUILD="$ROOT/build"
DIST="$ROOT/dist"
PY="python3 -I"
T="$ROOT/tools/pack"

step() { printf '\n== %s\n' "$*"; }

step "upstream pack"
mrpack="$($PY "$T/fetch_upstream.py" "$ROOT/port.json" "$CACHE")"
rm -rf "$BUILD/upstream" && mkdir -p "$BUILD/upstream"
unzip -q "$mrpack" -d "$BUILD/upstream"
chmod -R u+rwX "$BUILD/upstream"  # the zip stores files without read permission

step "analyze mods against Modrinth"
$PY "$T/analyze.py" "$BUILD/upstream/modrinth.index.json" "$BUILD/analysis.json" 2>"$BUILD/analyze.log"

step "old and new jars for the merge"
$PY "$T/fetch_jars.py" "$ROOT/port.json" "$BUILD/analysis.json" "$CACHE/jars" "$BUILD/plan.json"

step "unpack upstream datapacks"
rm -rf "$BUILD/dp" && mkdir -p "$BUILD/dp"
for z in "$BUILD"/upstream/overrides/datapacks/*.zip "$BUILD"/upstream/overrides/datapacks/extra/*.zip; do
  name="$(basename "$z" .zip)"
  mkdir -p "$BUILD/dp/$name"
  unzip -q -o "$z" -d "$BUILD/dp/$name"
done
chmod -R u+rwX "$BUILD/dp"

step "three-way merge onto the new jars"
rm -rf "$BUILD/dp-merged"
$PY "$T/merge.py" "$BUILD/plan.json" "$BUILD"/dp/* --out "$BUILD/dp-merged" --log "$BUILD/merge.log"

step "keybindings"
$PY "$T/keybinds.py" "$BUILD/upstream/overrides/config/defaultoptions/keybindings.txt" \
  "$ROOT/overrides/config/defaultoptions/keybindings.txt"

step "mrpack"
version="$(jq -r '.upstream.version + .version_suffix' "$ROOT/port.json")"
out="$DIST/COBBLEVERSE-$version.mrpack"
$PY "$T/build.py" "$ROOT/port.json" "$BUILD/upstream" "$BUILD/analysis.json" "$BUILD/dp-merged" "$ROOT/overrides" "$out"
ln -sfn "$(basename "$out")" "$DIST/latest.mrpack"
echo "dist/latest.mrpack -> $(basename "$out")"
