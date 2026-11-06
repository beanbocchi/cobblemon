#!/usr/bin/env python3
"""Build one village building on the flat ground north-west of the starter station.

Usage: village_build.py <station x> <floor y> <station z> <shrine|mart|daycare|court>

The shrine (Legend Quest altar) goes up with the Legend Quest; cvlife.py builds the Poké Mart at village level 1,
the Daycare at level 2 and the Battle Court at level 3. Offsets come from a height map of the area around the
station (flat at y 63-65). Each building levels its footprint to the floor y, fills gaps below with dirt and
clears the space above, so it is safe to run again.
"""
import json
import os
import re
import subprocess
import sys
import time

CONTAINER = os.environ.get("CONTAINER", "cobbleverse")  # cobbleverse-test for the test server


def rc(c):
    out = subprocess.run(["docker", "exec", CONTAINER, "rcon-cli", c], capture_output=True, text=True).stdout
    return re.sub(r"\x1b\[[0-9;]*m", "", out).strip()


E = "execute in minecraft:overworld run "
sx, fy, sz, what = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
y = fy + 1

# (x offset, z offset, width, depth) from the station centre
SITES = {"shrine": (-18, -16, 5, 5), "mart": (-28, -17, 9, 7), "daycare": (-40, -18, 11, 9), "court": (-40, -40, 11, 11)}


def sign(x, sy, z, rot, lines):
    msgs = ",".join("'" + json.dumps(l, ensure_ascii=False) + "'" for l in lines)
    return f"setblock {x} {sy} {z} minecraft:oak_sign[rotation={rot}]{{front_text:{{messages:[{msgs}]}},is_waxed:1b}}"


def base(x0, z0, w, d, floor):
    return [f"fill {x0} {fy - 3} {z0} {x0 + w - 1} {fy - 1} {z0 + d - 1} minecraft:dirt replace #minecraft:replaceable",
            f"fill {x0} {fy - 3} {z0} {x0 + w - 1} {fy - 1} {z0 + d - 1} minecraft:dirt replace minecraft:water",
            f"fill {x0} {y} {z0} {x0 + w - 1} {y + 8} {z0 + d - 1} minecraft:air",
            f"fill {x0} {fy} {z0} {x0 + w - 1} {fy} {z0 + d - 1} {floor}"]


def shrine(x0, z0):
    c = base(x0, z0, 5, 5, "minecraft:mossy_stone_bricks")
    c += [f"fill {x0} {fy} {z0} {x0 + 4} {fy} {z0} minecraft:chiseled_stone_bricks",
          f"fill {x0} {fy} {z0 + 4} {x0 + 4} {fy} {z0 + 4} minecraft:chiseled_stone_bricks",
          f"setblock {x0 + 2} {fy} {z0 + 2} minecraft:chiseled_quartz_block"]
    for dx, dz in ((0, 0), (4, 0), (0, 4), (4, 4)):
        c += [f"fill {x0 + dx} {y} {z0 + dz} {x0 + dx} {y + 1} {z0 + dz} minecraft:mossy_stone_brick_wall",
              f"setblock {x0 + dx} {y + 2} {z0 + dz} minecraft:soul_lantern"]
    for dx, dz in ((1, 1), (3, 1), (1, 3), (3, 3)):
        c.append(f"setblock {x0 + dx} {y} {z0 + dz} minecraft:small_amethyst_bud")
    c.append(sign(x0 + 4, y, z0 + 2, 4, [{"text": "LEGEND SHRINE", "color": "dark_purple", "bold": True},
                                        {"text": "Stand on the quartz"}, {"text": "with three relics"},
                                        {"text": "Type /legend", "color": "dark_aqua"}]))
    return c


def mart(x0, z0):
    w, d = 9, 7
    x1, z1 = x0 + w - 1, z0 + d - 1
    c = base(x0, z0, w, d, "minecraft:smooth_quartz")
    c += [f"fill {x0} {y} {z0} {x1} {y + 3} {z0} minecraft:white_concrete",
          f"fill {x0} {y} {z1} {x1} {y + 3} {z1} minecraft:white_concrete",
          f"fill {x0} {y} {z0} {x0} {y + 3} {z1} minecraft:white_concrete",
          f"fill {x1} {y} {z0} {x1} {y + 3} {z1} minecraft:white_concrete",
          f"fill {x0 - 1} {y + 4} {z0 - 1} {x1 + 1} {y + 4} {z1 + 1} minecraft:light_blue_concrete",
          f"fill {x0 + 2} {y + 1} {z0} {x1 - 2} {y + 2} {z0} minecraft:glass_pane",
          f"fill {x0 + 2} {y + 1} {z1} {x1 - 2} {y + 2} {z1} minecraft:glass_pane",
          f"fill {x1} {y} {z0 + 3} {x1} {y + 1} {z0 + 3} minecraft:air",
          f"fill {x0 + 2} {y} {z0 + 1} {x0 + 2} {y} {z1 - 1} minecraft:polished_andesite",
          f"setblock {x0 + 4} {y + 3} {z0 + 3} minecraft:lantern[hanging=true]",
          f"setblock {x0 + 6} {y + 3} {z0 + 2} minecraft:lantern[hanging=true]",
          f"setblock {x0 + 6} {y + 3} {z0 + 4} minecraft:lantern[hanging=true]",
          sign(x1 + 1, y, z0 + 2, 4, [{"text": "POKé MART", "color": "blue", "bold": True}, {"text": "Shop for"},
                                     {"text": "CobbleDollars"}, {"text": ""}]),
          "kill @e[tag=cvmart]",
          f"summon cobbledollars:cobble_merchant {x0 + 1.5} {y} {z0 + 3.5} {{Tags:[\"cvmart\"],NoAI:1b,Invulnerable:1b,"
          f"PersistenceRequired:1b,Silent:1b,Rotation:[-90f,0f],CustomName:'{{\"text\":\"Poké Mart\",\"color\":\"blue\"}}'}}"]
    return c


def daycare(x0, z0):
    w, d = 11, 9
    x1, z1 = x0 + w - 1, z0 + d - 1
    c = base(x0, z0, w, d, "minecraft:grass_block")
    c += [f"fill {x0} {y} {z0} {x1} {y} {z0} minecraft:oak_fence", f"fill {x0} {y} {z1} {x1} {y} {z1} minecraft:oak_fence",
          f"fill {x0} {y} {z0} {x0} {y} {z1} minecraft:oak_fence", f"fill {x1} {y} {z0} {x1} {y} {z1} minecraft:oak_fence",
          f"setblock {x1} {y} {z0 + 4} minecraft:oak_fence_gate[facing=east]",
          f"fill {x0 + 1} {fy} {z0 + 4} {x1} {fy} {z0 + 4} minecraft:dirt_path"]
    for pz in (z0 + 2, z0 + 6):
        c += [f"setblock {x0 + 2} {y} {pz} cobblemon:pasture[facing=east,part=bottom,on=false]",
              f"setblock {x0 + 2} {y + 1} {pz} cobblemon:pasture[facing=east,part=top,on=false]"]
    c += [f"setblock {x0 + 1} {y} {z0 + 1} minecraft:hay_block", f"setblock {x0 + 1} {y} {z1 - 1} minecraft:hay_block",
          f"setblock {x0 + 8} {y} {z0 + 1} minecraft:water_cauldron[level=3]",
          f"setblock {x0 + 8} {y} {z1 - 1} minecraft:composter"]
    for dx, dz, f in ((5, 2, "poppy"), (6, 6, "dandelion"), (4, 7, "cornflower"), (7, 1, "oxeye_daisy"),
                      (3, 4, "azure_bluet"), (8, 5, "allium")):
        c.append(f"setblock {x0 + dx} {y} {z0 + dz} minecraft:{f}")
    for dx, dz in ((0, 0), (w - 1, 0), (0, d - 1), (w - 1, d - 1)):
        c.append(f"setblock {x0 + dx} {y + 1} {z0 + dz} minecraft:lantern")
    c.append(sign(x1 + 1, y, z0 + 2, 4, [{"text": "DAYCARE", "color": "dark_green", "bold": True},
                                        {"text": "Two pastures"}, {"text": "for your Pokémon"}, {"text": ""}]))
    return c


def court(x0, z0):
    w = 11
    x1, z1 = x0 + w - 1, z0 + w - 1
    c = base(x0, z0, w, w, "minecraft:smooth_stone")
    c += [f"fill {x0} {fy} {z0} {x1} {fy} {z0} minecraft:white_concrete", f"fill {x0} {fy} {z1} {x1} {fy} {z1} minecraft:white_concrete",
          f"fill {x0} {fy} {z0} {x0} {fy} {z1} minecraft:white_concrete", f"fill {x1} {fy} {z0} {x1} {fy} {z1} minecraft:white_concrete",
          f"fill {x0} {fy} {z0 + 5} {x1} {fy} {z0 + 5} minecraft:white_concrete",
          f"fill {x0 + 4} {fy} {z0 + 4} {x0 + 6} {fy} {z0 + 6} minecraft:white_concrete",
          f"setblock {x0 + 5} {fy} {z0 + 5} minecraft:smooth_stone",
          f"fill {x0 + 4} {fy} {z0 + 1} {x0 + 6} {fy} {z0 + 2} minecraft:red_concrete",
          f"fill {x0 + 4} {fy} {z1 - 2} {x0 + 6} {fy} {z1 - 1} minecraft:blue_concrete"]
    for dx, dz in ((0, 0), (w - 1, 0), (0, w - 1), (w - 1, w - 1)):
        c += [f"setblock {x0 + dx} {y} {z0 + dz} minecraft:stone_brick_wall", f"setblock {x0 + dx} {y + 1} {z0 + dz} minecraft:lantern"]
    c.append(sign(x1 + 1, y, z0 + 5, 4, [{"text": "BATTLE COURT", "color": "red", "bold": True},
                                        {"text": "Settle it here"}, {"text": "1 vs 1"}, {"text": ""}]))
    return c


ox, oz, w, d = SITES[what]
x0, z0 = sx + ox, sz + oz
rc(f"{E}forceload add {x0 - 2} {z0 - 2} {x0 + w + 2} {z0 + d + 2}")
time.sleep(3)
for cmd in {"shrine": shrine, "mart": mart, "daycare": daycare, "court": court}[what](x0, z0):
    out = rc(E + cmd)
    if "rror" in out or "nknown" in out or "ncorrect" in out or "Invalid" in out:
        print("FAILED", cmd[:90], "->", out[:120], flush=True)
rc(f"{E}forceload remove {x0 - 2} {z0 - 2} {x0 + w + 2} {z0 + d + 2}")
print("built", what, "at", x0, fy, z0)
