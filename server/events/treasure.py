#!/usr/bin/env python3
"""One-off treasure race: hide a chest 180-240 blocks from the players, hand everyone a compass that points at it,
and announce whoever empties it first. Usage: treasure.py <center player>"""
import json, math, random, re, subprocess, sys, time

def rcon(cmd):
    out = subprocess.run(["docker", "exec", "cobbleverse", "rcon-cli", cmd], capture_output=True, text=True, timeout=30)
    return re.sub(r"\x1b\[[0-9;]*m", "", out.stdout).strip()

def say(parts):
    rcon("tellraw @a " + json.dumps([{"text": "[Treasure Hunt] ", "color": "gold", "bold": True}] + parts, ensure_ascii=False))

center = sys.argv[1]
px, py, pz = map(float, re.findall(r"(-?[\d.]+)d", rcon(f"data get entity {center} Pos")))
for _ in range(6):
    a = random.uniform(0, 2 * math.pi); d = random.uniform(180, 240)
    x, z = int(px + math.sin(a) * d), int(pz - math.cos(a) * d)
    rcon(f"forceload add {x} {z}"); time.sleep(3)
    rcon(f'summon minecraft:marker {x} 250 {z} {{Tags:["cvtreasure"]}}')
    rcon(f"spreadplayers {x} {z} 0 2 false @e[tag=cvtreasure]")
    pos = re.findall(r"(-?[\d.]+)d", rcon("data get entity @e[tag=cvtreasure,limit=1] Pos"))
    rcon("kill @e[tag=cvtreasure]")
    if len(pos) == 3 and float(pos[1]) < 249:
        tx, ty, tz = int(math.floor(float(pos[0]))), int(float(pos[1])), int(math.floor(float(pos[2])))
        break
    rcon(f"forceload remove {x} {z}")
else:
    sys.exit("no spot")
loot = [("cobblemon:master_ball", 1), ("cobblemon:rare_candy", 3), ("cobblemon:exp_candy_l", 3),
        ("cobblemon:ability_capsule", 1), ("cobblemon:ultra_ball", 10)]
items = ",".join(f'{{Slot:{i * 2 + 9}b,id:"{k}",count:{n}}}' for i, (k, n) in enumerate(loot))
rcon(f"setblock {tx} {ty} {tz} minecraft:chest{{Items:[{items}]}}")
rcon(f"setblock {tx} {ty + 1} {tz} minecraft:air")
rcon(f"forceload remove {x} {z}")
print("chest", tx, ty, tz, flush=True)
compass = ('minecraft:compass[minecraft:lodestone_tracker={target:{pos:[I;%d,%d,%d],dimension:"minecraft:overworld"},'
           'tracked:false},minecraft:custom_name=\'{"text":"Treasure Compass","color":"gold","italic":false}\']' % (tx, ty, tz))
rcon(f"give @a {compass} 1")
rcon('title @a times 5 60 10')
rcon('title @a title {"text":"TREASURE HUNT","color":"gold","bold":true}')
rcon('title @a subtitle {"text":"Follow the compass, first to open the chest wins","color":"yellow"}')
rcon("execute as @a at @s run playsound minecraft:event.raid.horn master @s ~ ~ ~ 0.6 1")
dist = int(round(math.hypot(tx - px, tz - pz), -1))
say([{"text": f"A treasure chest was just hidden about {dist} m away. Everyone has a Treasure Compass that points straight at it. "
               "Inside: a Master Ball, Rare Candy, Exp Candy L, an Ability Capsule and Ultra Balls. First to open it wins. Go!",
      "color": "white", "bold": False}])
start = time.time()
while time.time() - start < 1800:
    time.sleep(10)  # each rcon call prints two lines to the server console
    items_now = rcon(f"data get block {tx} {ty} {tz} Items")
    if "Items" not in items_now and "following block data" not in items_now:
        continue
    if "[]" in items_now or items_now.count("id:") < len(loot):
        # checked only every 10 s, so the finder may have walked off a bit: take the nearest player within 24 blocks
        names = re.findall(r"^(\w+) has", rcon(f"execute positioned {tx} {ty} {tz} as @a[distance=..24,sort=nearest,limit=1] run data get entity @s Dimension"), re.M)
        winner = names[0] if names else "Someone"
        secs = int(time.time() - start)
        say([{"text": f"{winner} found the treasure after {secs // 60} min {secs % 60} s! Congratulations!", "color": "green", "bold": False}])
        rcon(f'title @a title {{"text":"{winner} wins!","color":"gold","bold":true}}')
        rcon(f'execute positioned {tx} {ty + 2} {tz} run summon minecraft:firework_rocket ~ ~ ~ {{LifeTime:30,FireworksItem:{{id:"minecraft:firework_rocket",count:1,components:{{"minecraft:fireworks":{{explosions:[{{shape:"large_ball",colors:[I;16766720,16711680],has_twinkle:true}}]}}}}}}}}')
        print("winner", winner, secs, flush=True)
        break
