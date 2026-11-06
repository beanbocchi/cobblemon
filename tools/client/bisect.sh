#!/usr/bin/env bash
# Toggle groups of mods in the Modrinth profile for bisecting. Usage: bisect.sh off <jar>... | restore | status
set -euo pipefail
M="$HOME/.local/share/ModrinthApp/profiles/COBBLEVERSE-1.7.42-cm1.8.4/mods"
case "$1" in
  off) shift; for j in "$@"; do mv -v "$M/$j" "$M/$j.disabled"; done ;;
  restore) for f in "$M"/*.jar.disabled; do [ -e "$f" ] || continue; case "$(basename "$f")" in particular-1.1.2+1.21.jar.disabled) continue ;; esac; mv -v "$f" "${f%.disabled}"; done ;;
  status) ls "$M" | grep '\.disabled$' || true ;;
esac
