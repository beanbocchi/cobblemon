#!/usr/bin/env python3
"""One-off troll for a player who just joined after the Johto restart: a fake "your team was reset to Magikarp"
update screen, then the reveal and a real welcome message. Nothing in the party or inventory changes.
Usage: jointroll.py <player>"""
import json, subprocess, sys, time
P = sys.argv[1] if len(sys.argv) > 1 else "huylba"
def rc(c): subprocess.run(["docker", "exec", "cobbleverse", "rcon-cli", c], capture_output=True)
def snd(s, v=1, p=1): rc(f"execute as {P} at @s run playsound {s} master @s ~ ~ ~ {v} {p}")
def title(t, c, sub=None, sc="white"):
    rc(f"title {P} title " + json.dumps({"text": t, "color": c, "bold": True}, ensure_ascii=False))
    if sub:
        rc(f"title {P} subtitle " + json.dumps({"text": sub, "color": sc}, ensure_ascii=False))
def sysm(t, c="red"):
    rc(f"tellraw {P} " + json.dumps([{"text": "[System] ", "color": "dark_red", "bold": True},
                                     {"text": t, "color": c, "bold": False}], ensure_ascii=False))
def act(t, c): rc(f"title {P} actionbar " + json.dumps({"text": t, "color": c, "bold": True}, ensure_ascii=False))
rc(f"title {P} times 5 60 10")
snd("minecraft:block.beacon.deactivate", 1, 0.5)
title("JOHTO UPDATE", "red", "Migrating player data...", "yellow"); time.sleep(4)
sysm("The Johto update requires resetting all Pokémon to their starting state."); time.sleep(2.5)
for p, name in [(12, "Rayquaza"), (31, "Arceus"), (48, "Mewtwo"), (67, "Necrozma"), (85, "Giratina"), (100, "Hoopa")]:
    act(f"Resetting: {name} -> Magikarp level 1 ({p}%)", "red"); snd("minecraft:block.note_block.bit", 1, 0.5 + p / 100); time.sleep(1.2)
title("YOUR TEAM: 6x MAGIKARP", "dark_red", "New level cap: 25. Good luck in Johto!", "red")
snd("minecraft:entity.villager.no", 1, 0.5); snd("minecraft:entity.fish.swim", 1, 1); time.sleep(4)
sysm("Rare Candy left: 0. Master Balls: 0. Friends: 0.", "gray"); time.sleep(3.5)
rc(f"title {P} times 5 70 10")
title("Just kidding :)", "green", "Nothing changed. Johto is open, go get your Johto Trainer Card!", "yellow")
snd("minecraft:entity.player.levelup", 1, 1)
rc(f"tellraw {P} " + json.dumps([{"text": "[Assistant] ", "color": "aqua", "bold": True},
    {"text": "Welcome back! The server restarted and Johto content is now open (Johto gyms appear in newly explored land). "
             "Your Pokémon team is untouched. Next step: get the Johto Trainer Card at the Trainer Association, then find the first gym, Valerio.",
     "color": "white", "bold": False}], ensure_ascii=False))
print("trolled", flush=True)
