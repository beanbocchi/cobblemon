#!/usr/bin/env python3
"""Checkpoint race: three checkpoints in a chain, 120-180 blocks apart, starting from the middle of the
players in the Overworld. Each racer gets a
compass to their next checkpoint; reaching it (within 4 blocks) swaps the compass for the next one. Checkpoints
are marked by a glowstone pillar and a firework every 10 seconds. First to finish wins the prize; everyone who
finishes gets a smaller one. Usage: race.py [--dry]"""
import json, math, random, re, sys, time
sys.argv, args = [sys.argv[0]], sys.argv[1:]
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import events as e
import rewards

STEPS = 3
TIME_LIMIT = 900
WIN = [("cobblemon:rare_candy", 3), ("cobblemon:exp_candy_l", 3), ("cobblemon:ultra_ball", 10)]
FINISH = [("cobblemon:exp_candy_m", 3), ("cobblemon:great_ball", 10)]
COLORS = ["#ff5555", "#ffaa00", "#55ff55"]
# Each rcon call prints two lines to the server console, so one call per check reads every racer's position, and a
# racer counts as through a checkpoint when the line between two readings passes within 4 blocks of it. Checks
# run every second while someone could reach their next checkpoint before the next one, otherwise up to 10 s apart.
RADIUS, SPEED, MIN_WAIT, MAX_WAIT, MAX_JUMP = 4, 20, 1, 10, 100


def say(parts):
    e.rcon("tellraw @a " + json.dumps([{"text": "[Checkpoint Race] ", "color": "green", "bold": True}] + parts,
                                      ensure_ascii=False))


def compass(name, x, y, z, idx):
    label = json.dumps({"text": f"Checkpoint {idx + 1}/{STEPS}", "color": "green", "italic": False},
                       ensure_ascii=False)
    e.rcon(f"clear {name} minecraft:compass[minecraft:custom_data={{cvrace:1b}}]")
    e.rcon(f"give {name} minecraft:compass[minecraft:lodestone_tracker={{target:{{pos:[I;{x},{y},{z}],"
           f"dimension:\"minecraft:overworld\"}},tracked:false}},minecraft:custom_data={{cvrace:1b}},"
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
        anchor, chunk = e.place_anchor(cx, cz, 120, 180)
        if not anchor:
            e.release_anchor(chunk)
            continue
        e.rcon(f"kill @e[tag={e.ANCHOR}]")
        loaded.append(chunk)
        x, y, z = int(math.floor(anchor[0])), int(anchor[1]), int(math.floor(anchor[2]))
        points.append((x, y, z))
        cx, cz = x, z
    print("points", points, flush=True)
    if dry or len(points) < STEPS:
        for c in loaded:
            e.release_anchor(c)
        return
    for x, y, z in points:  # a 4-block glowstone pillar, visible from far and at night
        e.rcon(f"fill {x} {y} {z} {x} {y + 3} {z} minecraft:glowstone")
    racers = [p[0] for p in here]
    progress = {n: 0 for n in racers}
    for n in racers:
        compass(n, *points[0], 0)
    e.rcon("title @a times 5 40 10")
    for i in (3, 2, 1):
        e.rcon(f'title @a title {{"text":"{i}","color":"green","bold":true}}')
        e.rcon("execute as @a at @s run playsound minecraft:block.note_block.pling master @s ~ ~ ~ 1 1")
        time.sleep(1)
    e.rcon('title @a title {"text":"GO!","color":"green","bold":true}')
    e.rcon("execute as @a at @s run playsound minecraft:event.raid.horn master @s ~ ~ ~ 0.6 1.2")
    say([{"text": f"There are {STEPS} checkpoints, each a glowing glowstone pillar. Your compass points to the next "
                  "checkpoint; touch the pillar and the compass switches to the next one. First to finish gets 3 Rare Candy, "
                  "3 Exp Candy L and 10 Ultra Balls. Everyone who finishes gets a gift. 15 minutes!", "color": "white", "bold": False}])
    t0, winner, finished, last_fw, fw_turn, last, wait = time.time(), None, [], 0, 0, {}, MIN_WAIT
    while time.time() - t0 < TIME_LIMIT and len(finished) < len(racers):
        time.sleep(max(0.5, min(wait, TIME_LIMIT - (time.time() - t0))))
        if time.time() - last_fw > 10:  # one firework every 10 s, taking turns over the checkpoints someone is heading to
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
                say([{"text": f"{n} reached checkpoint {i + 1}/{STEPS} ({secs // 60}:{secs % 60:02d}).",
                      "color": "yellow", "bold": False}])
                continue
            e.rcon(f"clear {n} minecraft:compass[minecraft:custom_data={{cvrace:1b}}]")
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
        e.rcon(f"clear {n} minecraft:compass[minecraft:custom_data={{cvrace:1b}}]")
    for x, y, z in points:
        e.rcon(f"fill {x} {y} {z} {x} {y + 3} {z} minecraft:air replace minecraft:glowstone")
    for c in loaded:
        e.release_anchor(c)
    print("done", winner, finished, flush=True)


if __name__ == "__main__":
    main()
