#!/usr/bin/env python3
"""Dragon race: five glowing rings floating 30-45 blocks above the ground, 90-130 blocks apart, from the middle of
the Overworld players. Racers fly through them in order on a ridden Pokemon; each racer's compass points at their
next ring. Everyone online first gets a rideable dragon (it lands in the PC if the party is full) and a short
countdown. Usage: dragonrace.py [--dry] [--no-gift]"""
import json, math, random, re, sys, time
sys.argv, args = [sys.argv[0]], sys.argv[1:]
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import events as e
import rewards

STEPS = 5
TIME_LIMIT = 900
DRAGONS = ["dragonite", "charizard", "salamence", "flygon", "noivern", "altaria", "dragapult", "latios"]
WIN = [("cobblemon:rare_candy", 3), ("cobblemon:exp_candy_l", 3), ("cobblemon:ultra_ball", 10)]
FINISH = [("cobblemon:exp_candy_m", 3), ("cobblemon:great_ball", 10)]
COLORS = ["#ff5555", "#ffaa00", "#ffff55", "#55ff55", "#55ffff"]
# Each rcon call prints two lines to the server console, so one call per check reads every racer's position, and a
# racer counts as through a ring when the line between two readings passes within 6 blocks of its middle. Fliers
# can cross a ring between readings this way; checks run every second while someone could reach their next ring
# before the next one, otherwise up to 10 s apart.
RADIUS, SPEED, MIN_WAIT, MAX_WAIT, MAX_JUMP = 6, 40, 1, 10, 100


def say(parts):
    e.rcon("tellraw @a " + json.dumps([{"text": "[Dragon Race] ", "color": "light_purple", "bold": True}] + parts,
                                      ensure_ascii=False))


def compass(name, x, y, z, idx):
    label = json.dumps({"text": f"Ring {idx + 1}/{STEPS}", "color": "light_purple", "italic": False},
                       ensure_ascii=False)
    e.rcon(f"clear {name} minecraft:compass[minecraft:custom_data={{cvdragon:1b}}]")
    e.rcon(f"give {name} minecraft:compass[minecraft:lodestone_tracker={{target:{{pos:[I;{x},{y},{z}],"
           f"dimension:\"minecraft:overworld\"}},tracked:false}},minecraft:custom_data={{cvdragon:1b}},"
           f"minecraft:custom_name='{label}'] 1")


NUM = r"(-?[\d.]+(?:E-?\d+)?)d"
POS = re.compile(rf"(\w+) has the following entity data: \[{NUM}, {NUM}, {NUM}\]")


def positions():
    """Every Overworld player's position, from one rcon call."""
    out = e.rcon("execute in minecraft:overworld as @a[distance=0..] run data get entity @s Pos")
    return {m.group(1): tuple(map(float, m.group(2, 3, 4))) for m in POS.finditer(out)}


def near_path(a, b, p, r):
    """True when the straight line from a to b passes within r blocks of p (a is None: only b counts)."""
    if a is None or math.dist(a, b) > MAX_JUMP:  # first sighting, or a teleport
        return math.dist(b, p) <= r
    ab = [y - x for x, y in zip(a, b)]
    length = sum(v * v for v in ab)
    t = 0 if length == 0 else max(0, min(1, sum((q - x) * v for x, q, v in zip(a, p, ab)) / length))
    return math.dist([x + t * v for x, v in zip(a, ab)], p) <= r


def main():
    dry = "--dry" in args
    here = e.online_overworld()
    px, pz = sum(p[1] for p in here) / len(here), sum(p[3] for p in here) / len(here)
    points, loaded, cx, cz = [], [], px, pz
    for _ in range(STEPS * 3):  # some spots have no safe ground (ocean, lava); try again from the same point
        if len(points) == STEPS:
            break
        anchor, chunk = e.place_anchor(cx, cz, 90, 130)
        if not anchor:
            e.release_anchor(chunk)
            continue
        e.rcon(f"kill @e[tag={e.ANCHOR}]")
        loaded.append(chunk)
        x, y, z = int(math.floor(anchor[0])), int(anchor[1]) + random.randint(30, 45), int(math.floor(anchor[2]))
        points.append((x, y, z))
        cx, cz = x, z
    print("points", points, flush=True)
    if dry or len(points) < STEPS:
        for c in loaded:
            e.release_anchor(c)
        return
    prev = (px, pz)
    for x, y, z in points:  # a hollow 9x9 glowstone hoop, facing the way in from the previous ring
        along_x = abs(x - prev[0]) > abs(z - prev[1])
        for a, b in ((-4, -4), (4, 4)):
            if along_x:   # travel along x: hoop lies in the z/y plane
                e.rcon(f"fill {x} {y - 4} {z + a} {x} {y + 4} {z + a} minecraft:glowstone replace minecraft:air")
                e.rcon(f"fill {x} {y + b} {z - 4} {x} {y + b} {z + 4} minecraft:glowstone replace minecraft:air")
            else:
                e.rcon(f"fill {x + a} {y - 4} {z} {x + a} {y + 4} {z} minecraft:glowstone replace minecraft:air")
                e.rcon(f"fill {x - 4} {y + b} {z} {x + 4} {y + b} {z} minecraft:glowstone replace minecraft:air")
        prev = (x, z)
    racers = [p[0] for p in here]
    if "--no-gift" not in args:
        for n in racers:
            dragon = random.choice(DRAGONS)
            e.rcon(f"pokegiveother {n} {dragon} level=50")
            e.rcon("tellraw " + n + " " + json.dumps([{"text": "[Dragon Race] ", "color": "light_purple", "bold": True},
                {"text": f"You just got a level 50 {e.display(dragon)} to ride (it is in your PC if your party is full). "
                         "Send it out, interact with it to mount, and jump to fly up.", "color": "white", "bold": False}],
                ensure_ascii=False))
        say([{"text": "60 seconds to get ready: send out your dragon and climb on!", "color": "yellow", "bold": False}])
        time.sleep(60)
    progress = {n: 0 for n in racers}
    for n in racers:
        compass(n, *points[0], 0)
    e.rcon("title @a times 5 40 10")
    for i in (3, 2, 1):
        e.rcon(f'title @a title {{"text":"{i}","color":"light_purple","bold":true}}')
        e.rcon("execute as @a at @s run playsound minecraft:block.note_block.pling master @s ~ ~ ~ 1 1")
        time.sleep(1)
    e.rcon('title @a title {"text":"FLY!","color":"light_purple","bold":true}')
    e.rcon("execute as @a at @s run playsound minecraft:event.raid.horn master @s ~ ~ ~ 0.6 1.2")
    say([{"text": f"{STEPS} glowing rings float in the sky. Fly through them in order. Your compass points to the next ring. "
                  "First to finish gets 3 Rare Candy, 3 Exp Candy L and 10 Ultra Balls. Everyone who finishes gets a gift. "
                  "15 minutes!", "color": "white", "bold": False}])
    t0, winner, finished, last_fw, fw_turn, last, wait = time.time(), None, [], 0, 0, {}, MIN_WAIT
    while time.time() - t0 < TIME_LIMIT and len(finished) < len(racers):
        time.sleep(max(0.5, min(wait, TIME_LIMIT - (time.time() - t0))))
        if time.time() - last_fw > 10:  # one firework every 10 s, taking turns over the rings someone is heading to
            last_fw = time.time()
            active = sorted({p for p in progress.values() if p < STEPS})
            if active:
                i = active[fw_turn % len(active)]
                fw_turn += 1
                x, y, z = points[i]
                color = int(COLORS[i][1:], 16)
                e.rcon(f"summon minecraft:firework_rocket {x} {y + 5} {z} {{LifeTime:20,FireworksItem:"
                       f"{{id:\"minecraft:firework_rocket\",count:1,components:{{\"minecraft:fireworks\":"
                       f"{{explosions:[{{shape:\"small_ball\",colors:[I;{color}]}}]}}}}}}}}")
        now_pos, wait = positions(), MAX_WAIT
        for n in racers:
            i = progress[n]
            if i >= STEPS or n not in now_pos:
                continue
            pos, prev = now_pos[n], last.get(n)
            last[n] = pos
            if not near_path(prev, pos, points[i], RADIUS):
                wait = min(wait, max(MIN_WAIT, (math.dist(pos, points[i]) - RADIUS) / SPEED))
                continue
            wait = MIN_WAIT
            progress[n] = i + 1
            secs = int(time.time() - t0)
            e.rcon(f"execute as {n} at @s run playsound minecraft:entity.experience_orb.pickup master @s")
            if i + 1 < STEPS:
                compass(n, *points[i + 1], i + 1)
                say([{"text": f"{n} flew through ring {i + 1}/{STEPS} ({secs // 60}:{secs % 60:02d}).",
                      "color": "yellow", "bold": False}])
                continue
            e.rcon(f"clear {n} minecraft:compass[minecraft:custom_data={{cvdragon:1b}}]")
            finished.append(n)
            prize = WIN if winner is None else FINISH
            for item, count in prize:
                rewards.give(n, item, count)
            if winner is None:
                winner = n
                e.rcon(f'title @a title {{"text":"{n} wins!","color":"gold","bold":true}}')
                e.rcon(f"execute at {n} run summon minecraft:firework_rocket ~ ~1 ~ {{LifeTime:25,FireworksItem:"
                       "{id:\"minecraft:firework_rocket\",count:1,components:{\"minecraft:fireworks\":"
                       "{explosions:[{shape:\"large_ball\",colors:[I;16766720],has_twinkle:true}]}}}}")
                say([{"text": f"{n} finished first in {secs // 60} min {secs % 60} s and takes first prize!",
                      "color": "gold", "bold": False}])
            else:
                say([{"text": f"{n} also finished ({secs // 60}:{secs % 60:02d}) and gets a finisher gift.",
                      "color": "yellow", "bold": False}])
    if len(finished) < len(racers):
        say([{"text": "Time's up! Thanks for playing.", "color": "gray", "bold": False}])
    for n in racers:
        e.rcon(f"clear {n} minecraft:compass[minecraft:custom_data={{cvdragon:1b}}]")
    for x, y, z in points:
        e.rcon(f"fill {x - 4} {y - 4} {z - 4} {x + 4} {y + 4} {z + 4} minecraft:air replace minecraft:glowstone")
    for c in loaded:
        e.release_anchor(c)
    print("done", winner, finished, flush=True)


if __name__ == "__main__":
    main()
