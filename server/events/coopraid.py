#!/usr/bin/env python3
"""Co-op raid: three linked bosses appear together near the group. All three must be defeated or caught within
12 minutes; then every listed player gets the same reward. Nobody is ranked. Usage: coopraid.py <player> <player>..."""
import json, math, random, re, subprocess, sys, time
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import rewards

PLAYERS = sys.argv[1:]
TRIOS = [["articuno", "zapdos", "moltres"], ["raikou", "entei", "suicune"], ["uxie", "mesprit", "azelf"],
         ["cobalion", "terrakion", "virizion"], ["tapukoko", "tapulele", "tapubulu"]]
LIMIT = 720
REWARD = [("cobblemon:rare_candy", 8), ("cobblemon:exp_candy_xl", 2), ("cobblemon:ultra_ball", 10)]
BAR = "cobbleverse:raid"


def rc(c):
    return re.sub(r"\x1b\[[0-9;]*m", "", subprocess.run(["docker", "exec", "cobbleverse", "rcon-cli", c],
                                                       capture_output=True, text=True).stdout).strip()


def label(items):
    """Chat text for a list of (item, count), e.g. "3 Ultra Ball, 2 Sitrus Berry"."""
    return ", ".join(f"{c} {it.split(':')[1].replace('_', ' ').title()}" for it, c in items)


def say(text, color="white", to="@a"):
    rc(f"tellraw {to} " + json.dumps([{"text": "[Co-op Raid] ", "color": "red", "bold": True},
                                   {"text": text, "color": color, "bold": False}], ensure_ascii=False))


def pos(n):
    p = re.findall(r"(-?[\d.]+)d", rc(f"data get entity {n} Pos"))
    return tuple(map(float, p[:3])) if len(p) >= 3 else None


spots = {n: p for n in PLAYERS for p in [pos(n)] if p}
here = list(spots.values())
if len(here) < 2:
    sys.exit("need 2 players")
# Around the player with the most others within 150 blocks; the midpoint of players who are far apart can be
# thousands of blocks from all of them.
anchor = max(here, key=lambda p: (sum(math.hypot(q[0] - p[0], q[2] - p[2]) < 150 for q in here), random.random()))
cx, cz = anchor[0], anchor[2]
host = next(n for n, p in spots.items() if p == anchor)
trio = random.choice(TRIOS)
lvl = 55
chunks, tags = [], []
for i, sp in enumerate(trio):
    a = i * 2 * math.pi / 3 + random.uniform(-0.3, 0.3)
    gx, gz = int(cx + math.cos(a) * 45), int(cz + math.sin(a) * 45)
    rc(f"execute in minecraft:overworld run forceload add {gx} {gz}")
    chunks.append((gx, gz))
    time.sleep(3)
    rc(f"execute in minecraft:overworld run summon minecraft:marker {gx} 300 {gz} {{Tags:[\"cvrm\"]}}")
    rc(f"execute in minecraft:overworld run spreadplayers {gx} {gz} 0 2 false @e[tag=cvrm]")
    p = re.findall(r"(-?[\d.]+)d", rc("execute as @e[tag=cvrm] run data get entity @s Pos"))
    rc("kill @e[tag=cvrm]")
    if len(p) < 3 or float(p[1]) >= 299:
        continue
    x, y, z = map(float, p[:3])
    tag = f"cvraid{i}"
    rc(f"execute in minecraft:overworld positioned {x} {y + 1} {z} run spawnpokemon {sp} level={lvl} min_perfect_ivs=3")
    rc(f"execute in minecraft:overworld positioned {x} {y + 1} {z} run tag @e[type=cobblemon:pokemon,distance=..3,"
       f"sort=nearest,limit=1,nbt={{Pokemon:{{Species:\"cobblemon:{sp}\"}}}}] add {tag}")
    nm = json.dumps({"text": f"Raid: {sp.capitalize()}", "color": "red", "bold": True}).replace("'", "\\'")
    rc(f"execute as @e[tag={tag}] run data merge entity @s {{PersistenceRequired:1b,Glowing:1b,"
       f"CustomName:'{nm}',CustomNameVisible:1b}}")
    tags.append(tag)
if len(tags) < 3:
    for t in tags:
        rc(f"execute as @e[tag={t}] at @s run tp @s ~ -200 ~")
        rc(f"execute as @e[tag={t}] at @s run kill @s")
    for gx, gz in chunks:
        rc(f"execute in minecraft:overworld run forceload remove {gx} {gz}")
    sys.exit("could not place the trio")
names = " - ".join(s.capitalize() for s in trio)
rc(f"bossbar remove {BAR}")
rc(f"bossbar add {BAR} \"Raid\"")
rc(f"bossbar set {BAR} max {LIMIT}")
rc(f"bossbar set {BAR} color red")
rc(f"bossbar set {BAR} players @a")
rc("title @a times 5 70 10")
rc('title @a title {"text":"CO-OP RAID","color":"red","bold":true}')
rc("title @a subtitle " + json.dumps({"text": names, "color": "yellow"}))
rc("execute as @a at @s run playsound minecraft:event.raid.horn master @s ~ ~ ~ 0.8 0.8")
for n in spots:
    rc(f"tellraw {n} " + json.dumps({"text": f"xaero-waypoint:Raid:R:{int(cx)}:{int(anchor[1])}:{int(cz)}:12:false:0:"
                                             "Internal-overworld-waypoints"}))
say(f"The {names} trio (level {lvl}) just appeared around {host}, each about 45 m away "
    "and glowing (waypoint added). Defeat or catch all 3 within 12 minutes and everyone gets the same reward. "
    "Split up and take one each to be quick!", "yellow")
for n, p in spots.items():
    d = math.hypot(p[0] - cx, p[2] - cz)
    if d > 150:
        say(f"You are about {int(d)} m away; /fly or /home can get you closer.", "gray", to=n)
t0 = time.time()
done = False
# Every rcon call prints two lines to the server console, so check the bosses and update the bar only every 20 s.
while time.time() - t0 < LIMIT:
    left = int(LIMIT - (time.time() - t0))
    alive = [t for t in tags if "passed" in rc(f"execute if entity @e[tag={t}]")]
    if not alive:
        done = True
        break
    rc(f"bossbar set {BAR} value {left}")
    for t in alive:  # many shader packs don't draw the glowing outline, so mark them with a column of light too
        rc(f"execute as @e[tag={t}] at @s run particle minecraft:end_rod ~ ~3 ~ 0.2 6 0.2 0.02 120 force")
    rc(f"bossbar set {BAR} name " + json.dumps({"text": f"Raid: {len(alive)}/3 left | {left // 60}:{left % 60:02d}",
                                               "color": "red"}, ensure_ascii=False))
    time.sleep(min(20, max(1, LIMIT - (time.time() - t0))))
if done:
    rc('title @a title {"text":"RAID CLEARED!","color":"gold","bold":true}')
    rc("execute as @a at @s run playsound minecraft:ui.toast.challenge_complete master @s")
    say(f"The group beat the {names} trio! Everyone in the raid gets a reward.", "gold")
    for n in PLAYERS:
        got = []
        for item, c in REWARD:
            got += rewards.give(n, item, c)
        say(f"You got: {label(got)}.", "gold", n)
    time.sleep(8)
    rc(f"bossbar remove {BAR}")
else:
    rc(f"bossbar remove {BAR}")
    say("Time's up, the trio has left. Work together faster next time!", "red")
    # A boss with a player within 16 blocks is probably in a battle: leave it and try again each minute. The chunks
    # stay force-loaded until then, so a boss nobody is near can still be found and moved.
    for _ in range(10):
        for t in tags:
            rc(f"execute as @e[tag={t}] at @s unless entity @a[distance=..16] run tp @s ~ -200 ~")
            rc(f"execute as @e[tag={t}] at @s unless entity @a[distance=..16] run kill @s")
        tags = [t for t in tags if "passed" in rc(f"execute if entity @e[tag={t}]")]
        if not tags:
            break
        time.sleep(60)
for gx, gz in chunks:
    rc(f"execute in minecraft:overworld run forceload remove {gx} {gz}")
print("done", done, flush=True)
