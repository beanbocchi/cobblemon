#!/usr/bin/env python3
"""Hand each Overworld player a "Boss compass" and, every 15 seconds, point it at the nearest Pokemon with the
given tag. Stops (and takes the compasses back) once no tagged Pokemon has been around for two minutes.
Usage: bosscompass.py <entity tag> [label]"""
import json, math, re, sys, time
sys.argv, args = [sys.argv[0]], sys.argv[1:]
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import events as e

TAG = args[0]
LABEL = args[1] if len(args) > 1 else "Boss Compass"
MARK = "minecraft:compass[minecraft:custom_data={cvbosscompass:1b}]"
# Each rcon call prints two lines to the server console. Bosses are read every 15 s and players every 30 s, each with
# one call. A compass is changed only when its boss has moved at least MOVED blocks, or every RECHECK seconds so a
# lost compass comes back.
POLL, PLAYERS_EVERY, MOVED, RECHECK = 15, 30, 8, 120
NUM = r"(-?[\d.]+(?:E-?\d+)?)d"


def targets():
    out = e.rcon(f"execute as @e[tag={TAG}] run data get entity @s Pos")
    return [tuple(map(float, m)) for m in re.findall(rf"\[{NUM}, {NUM}, {NUM}\]", out)]


def players():
    """Every Overworld player's position, from one rcon call."""
    out = e.rcon("execute in minecraft:overworld as @a[distance=0..] run data get entity @s Pos")
    found = re.findall(rf"(\w+) has the following entity data: \[{NUM}, {NUM}, {NUM}\]", out)
    return [(name, *map(float, pos)) for name, *pos in found]


def slot_of(name):
    """Inventory slot holding the boss compass, as an item-command slot name, or None."""
    out = e.rcon(f'data get entity {name} Inventory[{{components:{{"minecraft:custom_data":{{cvbosscompass:1b}}}}}}].Slot')
    m = re.search(r"data: (-?\d+)b", out)
    if not m:
        return None
    slot = int(m.group(1))
    return "weapon.offhand" if slot == -106 else f"container.{slot}"


def main():
    label = json.dumps({"text": LABEL, "color": "red", "italic": False}, ensure_ascii=False)
    for name, *_ in e.online_overworld():
        e.rcon(f"clear {name} {MARK}")
        e.rcon(f"give {name} minecraft:compass[minecraft:custom_data={{cvbosscompass:1b}},"
               f"minecraft:custom_name='{label}'] 1")
    empty_since, here, here_at, aimed, aimed_at = None, [], 0, {}, time.time()
    while True:
        boss = targets()
        if not boss:  # between waves there are no bosses for a while; give up after two minutes
            empty_since = empty_since or time.time()
            if time.time() - empty_since > 120:
                break
            time.sleep(POLL)
            continue
        empty_since = None
        if time.time() - here_at >= PLAYERS_EVERY:
            here, here_at = players(), time.time()
        if time.time() - aimed_at >= RECHECK:
            aimed, aimed_at = {}, time.time()
        for name, px, py, pz in here:
            x, y, z = min(boss, key=lambda b: math.hypot(b[0] - px, b[2] - pz))
            if name in aimed and math.dist(aimed[name], (x, y, z)) < MOVED:
                continue
            slot = slot_of(name)
            if slot is None:
                e.rcon(f"give {name} minecraft:compass[minecraft:custom_data={{cvbosscompass:1b}},"
                       f"minecraft:custom_name='{label}'] 1")
                continue
            modifier = {"function": "minecraft:set_components", "components": {"minecraft:lodestone_tracker": {
                "target": {"pos": [int(x), int(y), int(z)], "dimension": "minecraft:overworld"}, "tracked": False}}}
            e.rcon(f"item modify entity {name} {slot} {json.dumps(modifier)}")
            aimed[name] = (x, y, z)
        time.sleep(POLL)
    for name, *_ in e.online_overworld():
        e.rcon(f"clear {name} {MARK}")


if __name__ == "__main__":
    main()
