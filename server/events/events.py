#!/usr/bin/env python3
"""World events for the COBBLEVERSE server: outbreaks and legendary hunts.

Runs on the host next to the `cobbleverse` container and talks to the server only through rcon-cli, so it needs no
mod and no restart. Every 30 to 40 minutes an outbreak puts a herd of one species, picked for the biome a player is
standing in, 40 to 80 blocks from that player for 10 minutes. Every 60 to 120 minutes (at most twice in four hours)
a legendary appears 150 to 300 blocks away for 15 minutes. Both wait until at least two players are online. Chat gives only a compass direction and a rough
distance. When time is up, event Pokemon with no player within 16 blocks are removed; ones near a player (likely in
a battle) are left and checked again a minute later. Only players in the Overworld take part.
"""
import gzip
import json
import math
import os
import random
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = json.load(open(os.path.join(HERE, "events.json"), encoding="utf-8"))
CONTAINER = "cobbleverse"
DATA = os.path.expanduser("~/cobblemon/server/data")
sys.path.insert(0, os.path.expanduser("~/cvscan"))
import anvil  # noqa: E402  (NBT reader for party files)

DIRECTIONS = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"]
TAG_OUTBREAK = "cvev_outbreak"
TAG_LEGEND = "cvev_legend"
ANCHOR = "cvev_anchor"


def log(*args):
    print(time.strftime("%H:%M:%S"), *args, flush=True)


def rcon(command):
    out = subprocess.run(["docker", "exec", CONTAINER, "rcon-cli", command],
                         capture_output=True, text=True, timeout=30)
    return re.sub(r"\x1b\[[0-9;]*m", "", out.stdout).strip()


def announce(parts):
    rcon("tellraw @a " + json.dumps([{"text": "[Event] ", "color": "gold", "bold": True}] + parts,
                                    ensure_ascii=False))


def online_overworld():
    out = rcon("list")
    names = [re.sub(r"^(\[[^\]]*\]\s*)+", "", n.strip()) for n in out.split(":", 1)[1].split(",")] if ":" in out else []
    players = []
    for name in filter(None, names):
        if "minecraft:overworld" not in rcon(f"data get entity {name} Dimension"):
            continue
        pos = re.findall(r"(-?[\d.]+)d", rcon(f"data get entity {name} Pos"))
        if len(pos) == 3:
            players.append((name, *map(float, pos)))
    return players


def party_levels(name):
    """Levels in the player's saved party (written by the server every few minutes)."""
    try:
        cache = json.load(open(os.path.join(DATA, "usercache.json")))
        uuid = next(e["uuid"] for e in cache if e["name"].lower() == name.lower())
        path = os.path.join(DATA, "world/pokemon/playerpartystore", uuid[:2], uuid + ".dat")
        party = anvil.nbt(gzip.decompress(open(path, "rb").read()))
    except (OSError, StopIteration, ValueError, KeyError):
        return []
    return sorted((v["Level"] for k, v in party.items() if k.startswith("Slot") and isinstance(v, dict)
                   and "Level" in v), reverse=True)


def biome_pool(x, y, z):
    for tag, species in CONFIG["outbreak_pools"]:
        if tag == "default":
            return species
        if "passed" in rcon(f"execute positioned {x:.0f} {y:.0f} {z:.0f} if biome ~ ~ ~ #{tag}"):
            return species
    return CONFIG["outbreak_pools"][-1][1]


def place_anchor(px, pz, min_d, max_d):
    """Put a marker on the ground min_d..max_d blocks from (px, pz) and force-load its chunk.

    Returns (marker position or None, force-loaded x/z for release_anchor)."""
    angle = random.uniform(0, 2 * math.pi)
    dist = random.uniform(min_d, max_d)
    x, z = int(px + math.sin(angle) * dist), int(pz - math.cos(angle) * dist)
    rcon(f"forceload add {x} {z}")
    rcon(f"kill @e[tag={ANCHOR}]")
    # The chunk loads a tick or more after forceload; until then the marker can't be summoned or spread and
    # would stay at y=200, dropping the herd from the sky.
    for _ in range(5):
        time.sleep(2)
        rcon(f"summon minecraft:marker {x} 200 {z} {{Tags:[\"{ANCHOR}\"]}}")
        # spreadplayers drops the marker onto the highest safe block (not lava, not fire)
        rcon(f"spreadplayers {x} {z} 0 3 false @e[tag={ANCHOR}]")
        pos = re.findall(r"(-?[\d.]+)d", rcon(f"data get entity @e[tag={ANCHOR},limit=1] Pos"))
        if len(pos) == 3 and float(pos[1]) < 199:
            return tuple(map(float, pos)), (x, z)
        rcon(f"kill @e[tag={ANCHOR}]")
    return None, (x, z)


def release_anchor(loaded):
    rcon(f"kill @e[tag={ANCHOR}]")
    rcon(f"forceload remove {loaded[0]} {loaded[1]}")


def bearing(px, pz, x, z):
    dist = math.hypot(x - px, z - pz)
    angle = (math.degrees(math.atan2(x - px, -(z - pz))) + 360) % 360
    return DIRECTIONS[round(angle / 45) % 8], int(round(dist, -1))


def spawn_group(species, count, level_range, shiny_chance, tag, ax, ay, az, extra=""):
    shinies = 0
    for _ in range(count):
        dx, dz = random.uniform(-3, 3), random.uniform(-3, 3)
        level = random.randint(*level_range)
        shiny = random.random() < shiny_chance
        shinies += shiny
        props = f"level={level}" + (" shiny=yes" if shiny else "") + (" " + extra if extra else "")
        rcon(f"execute in minecraft:overworld positioned {ax + dx:.1f} {ay + 0.5:.1f} {az + dz:.1f} "
             f"run spawnpokemon {species} {props}")
    rcon(f"execute in minecraft:overworld positioned {ax:.1f} {ay:.1f} {az:.1f} run tag "
         f"@e[type=cobblemon:pokemon,distance=..8,tag=!{TAG_OUTBREAK},tag=!{TAG_LEGEND},"
         f"nbt={{Pokemon:{{Species:\"cobblemon:{species}\"}}}}] add {tag}")
    return shinies


def display(species):
    return CONFIG["names"].get(species, species.replace("_", " ").title())


def outbreak():
    players = online_overworld()
    if not players:
        return None
    name, px, py, pz = random.choice(players)
    species = random.choice(biome_pool(px, py, pz))
    levels = party_levels(name)
    top = sum(levels[:3]) / len(levels[:3]) if levels else 20
    lo = max(5, int(top) - 8)
    anchor, loaded = place_anchor(px, pz, 40, 80)
    if not anchor:
        release_anchor(loaded)
        log("outbreak: no ground found")
        return None
    ax, ay, az = anchor
    count = random.randint(6, 8)
    spawn_group(species, count, (lo, lo + 6), CONFIG["outbreak_shiny_chance"], TAG_OUTBREAK, ax, ay, az)
    release_anchor(loaded)
    direction, dist = bearing(px, pz, ax, az)
    announce([{"text": f"Outbreak! A herd of {display(species)} ", "color": "yellow"},
              {"text": f"appeared about {dist} m {direction} of {name}. ", "color": "white"},
              {"text": "10 minutes left. Each one has a small shiny chance.", "color": "gray"}])
    log("outbreak", species, count, "near", name, f"{ax:.0f} {ay:.0f} {az:.0f}")
    return time.time() + 600, TAG_OUTBREAK, loaded


def legend():
    players = online_overworld()
    if not players:
        return None
    name, px, py, pz = random.choice(players)
    species = random.choice(CONFIG["legendaries"])
    levels = party_levels(name)
    top = levels[0] if levels else 50
    level = min(75, max(50, top + random.randint(0, 5)))
    anchor, loaded = place_anchor(px, pz, 150, 300)
    if not anchor:
        release_anchor(loaded)
        log("legend: no ground found")
        return None
    ax, ay, az = anchor
    spawn_group(species, 1, (level, level), 0, TAG_LEGEND, ax, ay, az)
    # 150-300 blocks is past the despawner's far distance; without this it vanishes before anyone arrives
    rcon(f"execute as @e[tag={TAG_LEGEND}] run data merge entity @s {{PersistenceRequired:1b}}")
    release_anchor(loaded)
    direction, dist = bearing(px, pz, ax, az)
    announce([{"text": f"Legendary! A level {level} {display(species)} ", "color": "light_purple", "bold": True},
              {"text": f"just landed about {dist} m {direction} of {name}. ", "color": "white",
               "bold": False},
              {"text": "It stays for only 15 minutes.", "color": "gray", "bold": False}])
    log("legend", species, level, "near", name, f"{ax:.0f} {ay:.0f} {az:.0f}")
    return time.time() + 900, TAG_LEGEND, loaded


def clean_up(tag, area=None):
    """Remove the event's Pokemon unless a player is near them; returns how many are left.

    The Pokemon may sit in chunks nobody has loaded since the event started, where `@e` can't see them, so the
    area around the event's anchor is force-loaded for the check and released afterwards."""
    if area:
        rcon(f"forceload add {area[0] - 48} {area[1] - 48} {area[0] + 48} {area[1] + 48}")
        time.sleep(4)
    rcon(f"execute as @e[tag={tag}] at @s unless entity @a[distance=..16] run tp @s ~ -400 ~")
    rcon(f"execute as @e[tag={tag}] at @s unless entity @a[distance=..16] run kill @s")
    if area:
        out = rcon(f"execute if entity @e[tag={tag}]")
        rcon(f"forceload remove {area[0] - 48} {area[1] - 48} {area[0] + 48} {area[1] + 48}")
        m = re.search(r"count: (\d+)", out, re.I)
        return int(m.group(1)) if m else (1 if "passed" in out else 0)
    out = rcon(f"execute if entity @e[tag={tag}]")
    m = re.search(r"count: (\d+)", out, re.I)
    return int(m.group(1)) if m else (1 if "passed" in out else 0)


def online_count():
    out = rcon("list")
    m = re.search(r"There are (\d+)", out)
    return int(m.group(1)) if m else 0


def main():
    pending = []  # (deadline, tag)
    next_outbreak = time.time() + random.uniform(*CONFIG["outbreak_minutes"]) * 60 / 3
    next_legend = time.time() + random.uniform(*CONFIG["legend_minutes"]) * 60 / 2
    legend_times = []
    log("started")
    while True:
        time.sleep(30)
        now = time.time()
        try:
            for item in list(pending):
                if now >= item[0] and clean_up(item[1], item[2] if len(item) > 2 else None) == 0:
                    pending.remove(item)
            if not CONFIG.get("outbreaks", True):
                next_outbreak = now + 3600  # cvlife's mass outbreaks replace these
            if now >= next_outbreak and online_count() < 2:
                next_outbreak = now + 300  # wait for a second player, check again in 5 minutes
            if now >= next_outbreak:
                event = outbreak()
                if event:
                    pending.append(event)
                next_outbreak = now + random.uniform(*CONFIG["outbreak_minutes"]) * 60
            legend_times = [t for t in legend_times if now - t < 4 * 3600]
            if now >= next_legend and len(legend_times) < 2 and online_count() < 2:
                next_legend = now + 300
            if now >= next_legend and len(legend_times) < 2:
                event = legend()
                if event:
                    pending.append(event)
                    legend_times.append(now)
                next_legend = now + random.uniform(*CONFIG["legend_minutes"]) * 60
        except Exception as e:  # rcon down during a restart: try again next round
            log("error", repr(e))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("outbreak", "legend"):
        print(outbreak() if sys.argv[1] == "outbreak" else legend())
    else:
        main()
