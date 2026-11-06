#!/usr/bin/env python3
"""Safari Zone: a crowd of uncommon and rare Pokemon (a few of them shiny) appears in a 15-block circle 30-50
blocks from the middle of the Overworld players, marked by a ring of soul-fire particles. Everyone gets Safari
Balls. After eight minutes whatever is left wanders off. Usage: safari.py"""
import json, math, random, sys, time
sys.argv = [sys.argv[0]]
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import events as e

TAG = "cvev_safari"
RING = "cvev_safari_ring"
MINUTES = 8
COUNT = 20
SHINIES = 3
POOL = ["eevee", "ralts", "riolu", "larvitar", "gible", "beldum", "axew", "deino", "bagon", "dratini", "goomy",
        "jangmoo", "dreepy", "frigibax", "zorua", "togepi", "snorlax", "lapras", "chansey", "scyther", "pinsir",
        "heracross", "tauros", "kangaskhan", "absol", "skarmory", "rotom", "spiritomb", "ditto", "porygon",
        "sneasel", "larvesta", "litwick", "honedge", "mimikyu", "sinistea", "applin", "tinkatink", "charcadet"]


def say(text, color="white"):
    e.rcon("tellraw @a " + json.dumps([{"text": "[Safari Zone] ", "color": "dark_green", "bold": True},
                                       {"text": text, "color": color, "bold": False}], ensure_ascii=False))


def main():
    here = e.online_overworld()
    if not here:
        sys.exit("nobody in the Overworld")
    px, pz = sum(p[1] for p in here) / len(here), sum(p[3] for p in here) / len(here)
    levels = [lv for p in here for lv in e.party_levels(p[0])[:3]]
    lo = max(15, int(sum(levels) / len(levels)) - 15) if levels else 25
    for _ in range(5):
        anchor, chunk = e.place_anchor(px, pz, 30, 50)
        if anchor:
            break
        e.release_anchor(chunk)
    else:
        sys.exit("no ground")
    e.rcon(f"kill @e[tag={e.ANCHOR}]")
    cx, cy, cz = anchor
    shiny_slots = set(random.sample(range(COUNT), SHINIES))
    for i in range(COUNT):
        a, r = random.uniform(0, 2 * math.pi), random.uniform(2, 14)
        x, z = cx + math.cos(a) * r, cz + math.sin(a) * r
        sp = random.choice(POOL)
        props = f"level={random.randint(lo, lo + 10)}" + (" shiny=yes" if i in shiny_slots else "")
        e.rcon(f"execute in minecraft:overworld positioned {x:.1f} {cy + 1:.1f} {z:.1f} run spawnpokemon {sp} {props}")
        # tag only the one just spawned, so nobody's own sent-out Pokemon gets swept up at the end
        e.rcon(f"execute in minecraft:overworld positioned {x:.1f} {cy + 1:.1f} {z:.1f} run tag "
               f"@e[type=cobblemon:pokemon,distance=..2,tag=!{TAG},limit=1,sort=nearest,"
               f"nbt={{Pokemon:{{Species:\"cobblemon:{sp}\"}}}}] add {TAG}")
    e.rcon(f"execute as @e[tag={TAG}] run data merge entity @s {{PersistenceRequired:1b}}")
    for name, *_ in here:
        e.rcon(f"give {name} cobblemon:safari_ball 20")
    direction, dist = e.bearing(px, pz, cx, cz)
    e.rcon("title @a times 5 60 10")
    e.rcon('title @a title {"text":"SAFARI ZONE","color":"dark_green","bold":true}')
    e.rcon(f'title @a subtitle {{"text":"{COUNT} Pokémon, {SHINIES} shiny, {MINUTES} minutes","color":"green"}}')
    e.rcon("execute as @a at @s run playsound minecraft:entity.player.levelup master @s ~ ~ ~ 1 0.6")
    for k in range(24):  # markers on the edge, so one rcon call can light the whole ring
        a = 2 * math.pi * k / 24
        e.rcon(f"summon minecraft:marker {cx + math.cos(a) * 15:.1f} {cy + 1:.1f} {cz + math.sin(a) * 15:.1f} "
               f"{{Tags:[\"{RING}\"]}}")
    say(f"A Safari Zone just opened about {dist} m to the {direction} of you: {COUNT} rare Pokémon "
        f"({SHINIES} of them shiny), level {lo}-{lo + 10}. Everyone gets 20 Safari Balls. "
        f"A ring of blue fire marks the edge. {MINUTES} minutes!", "green")
    end, warned = time.time() + MINUTES * 60, set()
    while time.time() < end:
        # one rcon call every 10 s (each prints two lines to the server console) lights the soul-fire ring
        e.rcon(f"execute at @e[tag={RING}] run particle minecraft:soul_fire_flame ~ ~ ~ 0 0.5 0 0.01 4 force")
        left = int((end - time.time()) // 60)
        if left in (3, 1) and left not in warned:
            warned.add(left)
            say(f"About {left} minute{'' if left == 1 else 's'} left!", "yellow")
        time.sleep(min(10, max(1, end - time.time())))
    say("The Safari Zone is closed. The remaining Pokémon ran back into the wild.", "gray")
    e.rcon(f"execute as @e[tag={TAG}] at @s unless entity @a[distance=..10] run tp @s ~ -400 ~")
    e.rcon(f"kill @e[tag={RING}]")
    e.release_anchor(chunk)
    print("done", flush=True)


if __name__ == "__main__":
    main()
