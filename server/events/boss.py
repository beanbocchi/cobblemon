#!/usr/bin/env python3
"""Boss fight: one strong Pokemon (top party level + 8, perfect IVs) appears 40-60 blocks from the middle of the
players in the Overworld, glowing and kept from despawning. Whoever defeats or catches it within 15 minutes
earns a prize for everyone online. Usage: boss.py"""
import json, random, re, sys, time
sys.argv = [sys.argv[0]]
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import events as e
import rewards

TAG = "cvev_boss"
TIME_LIMIT = 900
POLL = 10  # each rcon call prints two lines to the server console
SPECIES = ["tyranitar", "garchomp", "dragonite", "metagross", "salamence", "hydreigon", "volcarona", "snorlax",
           "aggron", "dragapult", "baxcalibur", "kingambit", "lucario", "gyarados"]
PRIZE = [("cobblemon:rare_candy", 2), ("cobblemon:exp_candy_l", 2), ("cobblemon:ultra_ball", 5)]


def say(text, color="white"):
    e.rcon("tellraw @a " + json.dumps([{"text": "[Boss] ", "color": "red", "bold": True},
                                       {"text": text, "color": color, "bold": False}], ensure_ascii=False))


def main():
    here = e.online_overworld()
    if not here:
        sys.exit("nobody in the Overworld")
    px, pz = sum(p[1] for p in here) / len(here), sum(p[3] for p in here) / len(here)
    top = max((e.party_levels(p[0])[:1] or [40])[0] for p in here)
    level = min(100, top + 8)
    species = random.choice(SPECIES)
    for _ in range(5):
        anchor, chunk = e.place_anchor(px, pz, 40, 60)
        if anchor:
            break
        e.release_anchor(chunk)
    else:
        sys.exit("no ground")
    e.rcon(f"kill @e[tag={e.ANCHOR}]")
    e.spawn_group(species, 1, (level, level), 0.0, TAG, *anchor, extra="min_perfect_ivs=6")
    # Glowing flag and PersistenceRequired, not the status effect or persistent=true: those wore off in testing
    e.rcon(f"execute as @e[tag={TAG}] run data merge entity @s {{Glowing:1b,PersistenceRequired:1b}}")
    if "passed" not in e.rcon(f"execute if entity @e[tag={TAG}]"):
        e.release_anchor(chunk)
        sys.exit("spawn failed")
    name = e.display(species)
    direction, dist = e.bearing(px, pz, anchor[0], anchor[2])
    e.rcon("title @a times 5 60 10")
    e.rcon('title @a title {"text":"A BOSS APPEARS","color":"red","bold":true}')
    e.rcon(f'title @a subtitle {{"text":"Level {level} {name}","color":"gold"}}')
    e.rcon("execute as @a at @s run playsound minecraft:entity.wither.spawn master @s ~ ~ ~ 0.5 1")
    say(f"A level {level} {name} with perfect IVs just appeared about {dist} m to the {direction} of you, "
        "and it is glowing. Defeat or catch it within 15 minutes and everyone online gets 2 Rare Candy, "
        "2 Exp Candy L and 5 Ultra Balls. If you lose, heal up and try again!", "gold")
    print("boss", species, level, anchor, flush=True)
    t0 = time.time()
    while time.time() - t0 < TIME_LIMIT:
        time.sleep(min(POLL, max(1, TIME_LIMIT - (time.time() - t0))))
        if "passed" in e.rcon(f"execute if entity @e[tag={TAG}]"):
            continue
        secs = int(time.time() - t0)
        for n in [re.sub(r"^(\[[^\]]*\]\s*)+", "", n.strip()) for n in e.rcon("list").split(":", 1)[1].split(",") if n.strip()]:
            for item, count in PRIZE:
                rewards.give(n, item, count)
        e.rcon('title @a title {"text":"BOSS DEFEATED!","color":"gold","bold":true}')
        e.rcon("execute as @a at @s run playsound minecraft:ui.toast.challenge_complete master @s")
        say(f"{name} was defeated (or caught) after {secs // 60} min {secs % 60} s! Everyone got their reward.",
            "green")
        print("defeated", secs, flush=True)
        break
    else:
        say(f"Time's up, {name} has left. Better luck next time!", "gray")
        e.rcon(f"execute as @e[tag={TAG}] at @s unless entity @a[distance=..16] run tp @s ~ -400 ~")
        print("timeout", flush=True)
    e.release_anchor(chunk)


if __name__ == "__main__":
    main()
