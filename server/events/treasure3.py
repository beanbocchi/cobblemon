#!/usr/bin/env python3
"""Treasure hunt, three chests: chests hide 120-220 blocks from the middle of the Overworld players. Each player's
compass points at the nearest chest nobody has opened yet, updated every 30 seconds. Taking anything out of a
chest claims it for the nearest player; a sidebar shows chests found. The one with most chests at the end gets a
bonus. Usage: treasure3.py [--test]  (--test places and reads the chests, then removes them silently)"""
import json, math, random, re, sys, time
sys.argv, args = [sys.argv[0]], sys.argv[1:]
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import events as e
import rewards

CHESTS = 3
TIME_LIMIT = 900
OBJ = "cvchest"
MARK = "minecraft:compass[minecraft:custom_data={cvchest:1b}]"
LOOT = [
    [("cobblemon:ultra_ball", 8), ("cobblemon:exp_candy_l", 2), ("cobblemon:rare_candy", 2)],
    [("cobblemon:rare_candy", 3), ("cobblemon:ability_capsule", 1), ("cobblemon:full_restore", 3)],
    [("cobblemon:master_ball", 1), ("cobblemon:exp_candy_xl", 1), ("minecraft:diamond", 5)],
]
BONUS = [("cobblemon:rare_candy", 2)]  # plus a rewards.mixed bundle of tier BONUS_TIER
BONUS_TIER = 2
# Each rcon call prints two lines to the server console. One call every 15 s checks that all open chests are still
# full and one every 30 s reads every player's position. A compass is changed only when its target changes, or every
# RECHECK seconds so a lost compass comes back.
CHEST_EVERY, AIM_EVERY, RECHECK = 15, 30, 120
NUM = r"(-?[\d.]+(?:E-?\d+)?)d"


def label(items):
    """Chat text for a list of (item, count), e.g. "3 Ultra Ball, 2 Sitrus Berry"."""
    return ", ".join(f"{c} {it.split(':')[1].replace('_', ' ').title()}" for it, c in items)


def say(text, color="white", to="@a"):
    e.rcon(f"tellraw {to} " + json.dumps([{"text": "[Treasure Hunt] ", "color": "gold", "bold": True},
                                       {"text": text, "color": color, "bold": False}], ensure_ascii=False))


def item_count(x, y, z):
    """Stacks in the chest, or None while its chunk isn't loaded."""
    out = e.rcon(f"data get block {x} {y} {z} Items")
    if "following block data" not in out:
        return None
    return out.count("id:")


def all_full(chests):
    """True while every stack is still in every given chest, checked with one rcon call."""
    test = []
    for c in chests:
        x, y, z = c["pos"]
        test += [f"if data block {x} {y} {z} Items[{{Slot:{slot}b}}]" for slot in c["slots"]]
    return "passed" in e.rcon("execute " + " ".join(test))


def positions():
    """Every Overworld player's position, from one rcon call."""
    out = e.rcon("execute in minecraft:overworld as @a[distance=0..] run data get entity @s Pos")
    found = re.findall(rf"(\w+) has the following entity data: \[{NUM}, {NUM}, {NUM}\]", out)
    return [(name, *map(float, pos)) for name, *pos in found]


def compass_slot(name):
    out = e.rcon(f'data get entity {name} Inventory[{{components:{{"minecraft:custom_data":{{cvchest:1b}}}}}}].Slot')
    m = re.search(r"data: (-?\d+)b", out)
    if not m:
        return None
    slot = int(m.group(1))
    return "weapon.offhand" if slot == -106 else f"container.{slot}"


def give_compass(name):
    label = json.dumps({"text": "Treasure Compass", "color": "gold", "italic": False}, ensure_ascii=False)
    e.rcon(f"give {name} minecraft:compass[minecraft:custom_data={{cvchest:1b}},minecraft:custom_name='{label}'] 1")


def point(name, target):
    """Aim the player's compass at target; False when they had none and got a fresh, unaimed one."""
    slot = compass_slot(name)
    if slot is None:
        give_compass(name)
        return False
    mod = {"function": "minecraft:set_components", "components": {"minecraft:lodestone_tracker": {
        "target": {"pos": list(target), "dimension": "minecraft:overworld"}, "tracked": False}}}
    e.rcon(f"item modify entity {name} {slot} {json.dumps(mod)}")
    return True


def place_chests(px, pz):
    chests, chunks = [], []
    for loot in LOOT[:CHESTS]:
        for _ in range(5):
            anchor, chunk = e.place_anchor(px, pz, 120, 220)
            if anchor:
                break
            e.release_anchor(chunk)
        else:
            continue
        e.rcon(f"kill @e[tag={e.ANCHOR}]")
        x, y, z = int(math.floor(anchor[0])), int(anchor[1]), int(math.floor(anchor[2]))
        items = ",".join(f'{{Slot:{i * 2 + 10}b,id:"{k}",count:{n}}}' for i, (k, n) in enumerate(loot))
        e.rcon(f"setblock {x} {y} {z} minecraft:chest{{Items:[{items}]}}")
        e.rcon(f"setblock {x} {y + 1} {z} minecraft:air")
        chests.append({"pos": (x, y, z), "full": len(loot), "owner": None,
                       "slots": [i * 2 + 10 for i in range(len(loot))]})
        chunks.append(chunk)
    return chests, chunks


def main():
    test = "--test" in args
    here = e.online_overworld()
    if not here:
        sys.exit("nobody in the Overworld")
    px, pz = sum(p[1] for p in here) / len(here), sum(p[3] for p in here) / len(here)
    chests, chunks = place_chests(px, pz)
    print("chests", [c["pos"] for c in chests], flush=True)
    if test:
        for c in chests:
            print(c["pos"], "stacks", item_count(*c["pos"]), "expected", c["full"], flush=True)
            e.rcon(f"setblock {c['pos'][0]} {c['pos'][1]} {c['pos'][2]} minecraft:air")
        for ch in chunks:
            e.release_anchor(ch)
        return
    # chunks stay force-loaded so chest contents can be read from anywhere
    racers = [p[0] for p in here]
    e.rcon(f"scoreboard objectives remove {OBJ}")
    e.rcon(f'scoreboard objectives add {OBJ} dummy {{"text":"Chests found","color":"gold","bold":true}}')
    e.rcon(f"scoreboard objectives setdisplay sidebar {OBJ}")
    for n in racers:
        e.rcon(f"scoreboard players set {n} {OBJ} 0")
        e.rcon(f"clear {n} {MARK}")
        give_compass(n)
    e.rcon("title @a times 5 60 10")
    e.rcon('title @a title {"text":"TREASURE HUNT","color":"gold","bold":true}')
    e.rcon(f'title @a subtitle {{"text":"{len(chests)} chests, the compass points to the nearest","color":"yellow"}}')
    e.rcon("execute as @a at @s run playsound minecraft:event.raid.horn master @s ~ ~ ~ 0.6 1")
    say(f"{len(chests)} treasure chests are hidden 120-220 m from you. The Treasure Compass always points to the nearest "
        "chest nobody has opened yet. Chest 1: Ultra Balls and candy. Chest 2: Rare Candy and an Ability Capsule. Chest 3: "
        "a MASTER BALL. Whoever finds the most chests gets a bonus. 15 minutes!", "yellow")
    t0, aimed, aim_at, chest_at, recheck_at = time.time(), {}, 0, 0, time.time()
    while time.time() - t0 < TIME_LIMIT and any(c["owner"] is None for c in chests):
        open_chests = [c for c in chests if c["owner"] is None]
        if time.time() - recheck_at >= RECHECK:
            aimed, recheck_at = {}, time.time()
        if time.time() - aim_at >= AIM_EVERY:
            aim_at = time.time()
            for name, x, y, z in positions():
                target = min(open_chests, key=lambda c: math.hypot(c["pos"][0] - x, c["pos"][2] - z))["pos"]
                if aimed.get(name) != target and point(name, target):
                    aimed[name] = target
        if time.time() - chest_at < CHEST_EVERY:
            time.sleep(max(1, min(CHEST_EVERY - (time.time() - chest_at), TIME_LIMIT - (time.time() - t0))))
            continue
        chest_at = time.time()
        for c in ([] if all_full(open_chests) else open_chests):
            n = item_count(*c["pos"])
            if n is None or n >= c["full"]:
                continue
            cx, cy, cz = c["pos"]
            # checked only every 15 s, so the finder may have walked off a bit: nearest player within 24 blocks
            out = e.rcon(f"execute positioned {cx} {cy} {cz} as @a[distance=..24,sort=nearest,limit=1] "
                         "run data get entity @s Dimension")
            m = re.search(r"^(\w+) has the following", out, re.M)
            c["owner"] = m.group(1) if m else "?"
            if m:
                e.rcon(f"scoreboard players add {c['owner']} {OBJ} 1")
            left = sum(1 for k in chests if k["owner"] is None)
            secs = int(time.time() - t0)
            e.rcon("execute as @a at @s run playsound minecraft:ui.toast.challenge_complete master @s")
            e.rcon(f"summon minecraft:firework_rocket {cx} {cy + 2} {cz} {{LifeTime:25,FireworksItem:"
                   "{id:\"minecraft:firework_rocket\",count:1,components:{\"minecraft:fireworks\":"
                   "{explosions:[{shape:\"star\",colors:[I;16766720],has_twinkle:true}]}}}}")
            say(f"{c['owner']} opened a chest ({secs // 60}:{secs % 60:02d})! {left} left.", "green")
            aim_at = 0  # compasses that pointed at it need a new target
    counts = {n: sum(1 for c in chests if c["owner"] == n) for n in racers}
    best = max(counts.values()) if counts else 0
    leaders = [n for n in racers if counts[n] == best and best > 0]
    got = {}
    for n in leaders:
        got[n] = [g for item, k in BONUS for g in rewards.give(n, item, k)] + rewards.mixed(n, BONUS_TIER)
    board = ", ".join(f"{n} {counts[n]}" for n in sorted(racers, key=lambda n: -counts[n]))
    if leaders:
        e.rcon("title @a title " + json.dumps({"text": " and ".join(leaders) + " win!", "color": "gold",
                                                "bold": True}, ensure_ascii=False))
        say(f"It's over! {board}. {' and '.join(leaders)} get a bonus: Rare Candy and a surprise bundle (balls, "
            "berries or an evolution item).", "gold")
        for n, items in got.items():
            say(f"You got: {label(items)}.", "gold", n)
    else:
        say("Time's up, nobody found a chest.", "gray")
    for n in racers:
        e.rcon(f"clear {n} {MARK}")
    for c in chests:
        if c["owner"] is None:
            e.rcon(f"setblock {c['pos'][0]} {c['pos'][1]} {c['pos'][2]} minecraft:air")
    for ch in chunks:
        e.release_anchor(ch)
    time.sleep(15)
    e.rcon(f"scoreboard objectives remove {OBJ}")
    print("done", counts, flush=True)


if __name__ == "__main__":
    main()
