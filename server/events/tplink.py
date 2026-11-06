#!/usr/bin/env python3
"""Clickable "teleport me there" link for non-operators. Sends a chat button that runs /trigger <objective>
(players need no permission for that), then, while the given process is alive, teleports anyone who clicked to
the spot and re-arms the trigger. Usage: tplink.py <objective> <x> <z> <pid to follow> <label>"""
import json, re, subprocess, sys, time
sys.argv, args = [sys.argv[0]], sys.argv[1:]
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import events as e

obj, x, z, pid, label = args[0], int(args[1]), int(args[2]), int(args[3]), args[4]


def alive(p):
    return subprocess.run(["kill", "-0", str(p)], capture_output=True).returncode == 0


e.rcon(f"scoreboard objectives add {obj} trigger")
e.rcon(f"scoreboard players enable @a {obj}")
e.rcon("tellraw @a " + json.dumps([
    {"text": "[Claude] ", "color": "light_purple", "bold": True},
    {"text": f"[Click here to go to {label}]", "color": "green", "bold": True, "underlined": True,
     "clickEvent": {"action": "run_command", "value": f"/trigger {obj}"},
     "hoverEvent": {"action": "show_text", "contents": f"Teleport to {label}"}}], ensure_ascii=False))
while alive(pid):
    out = e.rcon(f"execute as @a[scores={{{obj}=1..}}] run data get entity @s UUID")
    for name in re.findall(r"^(\w+) has the following", out, re.M):
        e.rcon(f"execute in minecraft:overworld run spreadplayers {x} {z} 0 5 false {name}")
        e.rcon(f"scoreboard players set {name} {obj} 0")
        e.rcon(f"scoreboard players enable {name} {obj}")
    e.rcon(f"scoreboard players enable @a {obj}")  # people who joined after the link went out
    time.sleep(5)
e.rcon(f"scoreboard objectives remove {obj}")
