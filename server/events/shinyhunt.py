#!/usr/bin/env python3
"""One-off shiny hunt: hide shiny Pokemon 60-120 blocks around a player, make them glow so they show through
walls, and count down in chat as they get caught. Usage: shinyhunt.py <per-player count> <player>..."""
import json, random, re, sys, time
sys.argv, args = [sys.argv[0]], sys.argv[1:]
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import events as e

TAG = "cvev_shiny"
SPECIES = ["eevee", "gible", "ralts", "riolu", "larvitar", "beldum", "charmander", "bulbasaur", "squirtle",
           "pikachu", "dratini", "axew", "deino", "goomy", "jangmoo", "dreepy", "frigibax", "bagon", "zorua"]

def say(text, color="white"):
    e.rcon("tellraw @a " + json.dumps([{"text": "[Shiny Hunt] ", "color": "aqua", "bold": True},
                                       {"text": text, "color": color, "bold": False}], ensure_ascii=False))

count, centers = int(args[0]), args[1:]
picked = random.sample(SPECIES, count * len(centers))
placed, hint_parts, chunks = [], [], []
for i, center in enumerate(centers):
    px, py, pz = map(float, re.findall(r"(-?[\d.]+)d", e.rcon(f"data get entity {center} Pos")))
    levels = e.party_levels(center)
    lo = max(10, int(sum(levels[:3]) / max(1, len(levels[:3]))) - 10) if levels else 25
    mine = []
    for sp in picked[i * count:(i + 1) * count]:
        anchor, loaded = e.place_anchor(px, pz, 60, 120)
        if anchor:
            e.spawn_group(sp, 1, (lo, lo + 5), 1.0, TAG, *anchor)
            placed.append(sp)
            mine.append("about %d m to the %s" % e.bearing(px, pz, anchor[0], anchor[2])[::-1])
            e.rcon(f"kill @e[tag={e.ANCHOR}]")
            chunks.append(loaded)  # stay loaded so @e still counts shinies nobody is near
        else:
            e.release_anchor(loaded)
    if mine:
        hint_parts.append(f"around {center}: " + ", ".join(mine))
# spawnpokemon's persistent=true leaves PersistenceRequired at 0, and the despawner removed shinies within a minute
e.rcon(f"execute as @e[tag={TAG}] run data merge entity @s {{PersistenceRequired:1b}}")
# the glowing status effect wore off Pokemon within minutes; the Glowing flag stays
e.rcon(f"execute as @e[tag={TAG}] run data merge entity @s {{Glowing:1b}}")
e.rcon('title @a times 5 60 10')
e.rcon('title @a title {"text":"SHINY HUNT","color":"aqua","bold":true}')
e.rcon('title @a subtitle {"text":"Glowing shiny Pokémon are hiding nearby","color":"white"}')
e.rcon("execute as @a at @s run playsound minecraft:block.amethyst_block.chime master @s ~ ~ ~ 1 0.8")
say(f"{len(placed)} glowing shiny Pokémon, " + "; ".join(hint_parts) + ". The glow shows through walls. "
    "Whoever catches the most wins. 20 minutes!")
print("placed", placed, flush=True)
left, start = len(placed), time.time()
while left and time.time() - start < 1200:
    time.sleep(10)  # each rcon call prints two lines to the server console
    out = e.rcon(f"execute if entity @e[tag={TAG}]")
    m = re.search(r"count: (\d+)", out, re.I)
    now = int(m.group(1)) if m else 0
    if now < left:
        left = now
        e.rcon("execute as @a at @s run playsound minecraft:entity.experience_orb.pickup master @s")
        say(f"A shiny was just caught (or defeated)! {left} left." if left else "All shinies caught! Show off how many you got in chat.", "yellow")
if left:
    say(f"Time's up! The last {left} shiny Pokémon have left.", "gray")
    e.rcon(f"execute as @e[tag={TAG}] at @s unless entity @a[distance=..16] run tp @s ~ -400 ~")
for x, z in chunks:
    e.rcon(f"forceload remove {x} {z}")
print("done", left, flush=True)
