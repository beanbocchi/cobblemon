#!/usr/bin/env python3
"""Build the starter station on a 7x7 pad: Healing Machine, PC, crafting table, the shared village chest, lanterns
and two signs. Usage: station.py <center x> <floor y> <center z> [extra]   (extra adds the level-1 second machine and PC)"""
import json, re, subprocess, sys


def rc(c):
    return re.sub(r"\x1b\[[0-9;]*m", "", subprocess.run(["docker", "exec", "cobbleverse", "rcon-cli", c],
                                                       capture_output=True, text=True).stdout).strip()


E = "execute in minecraft:overworld run "
cx, fy, cz = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
y = fy + 1


def sign_nbt(lines):
    msgs = ",".join("'" + json.dumps(l, ensure_ascii=False) + "'" for l in lines)
    return "{front_text:{messages:[" + msgs + "]},is_waxed:1b}"


if len(sys.argv) > 4 and sys.argv[4] == "extra":
    cmds = [f"setblock {cx - 2} {y} {cz + 2} cobblemon:healing_machine[facing=north]",
            f"setblock {cx - 1} {y} {cz + 2} cobblemon:pc[facing=north,part=bottom]",
            f"setblock {cx - 1} {y + 1} {cz + 2} cobblemon:pc[facing=north,part=top]"]
else:
    cmds = [
        f"fill {cx - 3} {fy} {cz - 3} {cx + 3} {fy} {cz + 3} minecraft:polished_andesite",
        f"fill {cx - 3} {y} {cz - 3} {cx + 3} {y + 3} {cz + 3} minecraft:air replace #minecraft:replaceable",
        f"fill {cx - 3} {fy} {cz - 3} {cx + 3} {fy} {cz - 3} minecraft:chiseled_stone_bricks",
        f"setblock {cx - 2} {y} {cz - 2} cobblemon:healing_machine[facing=south]",
        f"setblock {cx - 1} {y} {cz - 2} cobblemon:pc[facing=south,part=bottom]",
        f"setblock {cx - 1} {y + 1} {cz - 2} cobblemon:pc[facing=south,part=top]",
        f"setblock {cx} {y} {cz - 2} minecraft:crafting_table",
        f"setblock {cx + 1} {y} {cz - 2} minecraft:chest[facing=south,type=left]",
        f"setblock {cx + 2} {y} {cz - 2} minecraft:chest[facing=south,type=right]",
        f"setblock {cx - 3} {y} {cz - 3} minecraft:lantern",
        f"setblock {cx + 3} {y} {cz - 3} minecraft:lantern",
        f"setblock {cx - 3} {y} {cz + 3} minecraft:lantern",
        f"setblock {cx + 3} {y} {cz + 3} minecraft:lantern",
        f"setblock {cx} {y} {cz} minecraft:oak_sign[rotation=8]" + sign_nbt([
            {"text": "STARTER STATION", "color": "gold", "bold": True}, {"text": "Healing Machine, PC"},
            {"text": "Village chest on the right"}, {"text": "Type /world", "color": "dark_aqua"}]),
        f"setblock {cx + 2} {y} {cz} minecraft:oak_sign[rotation=8]" + sign_nbt([
            {"text": "VILLAGE CHEST", "color": "gold", "bold": True}, {"text": "Donate items here"},
            {"text": "to level the village"}, {"text": "Type /world", "color": "dark_aqua"}]),
    ]
for c in cmds:
    print(c.split()[0], rc(E + c)[:80], flush=True)
