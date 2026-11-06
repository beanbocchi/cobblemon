#!/usr/bin/env python3
"""Typing race for everyone online: each round a Pokemon name flashes on every screen and the first player to type
it in chat scores a point. A sidebar keeps score; the winner gets the prize, others a small consolation.
Usage: typerace.py [rounds]"""
import json, random, re, subprocess, sys, time, unicodedata
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import rewards

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 8
WINDOW = 15
OBJ = "cvtype"
PRIZE = [("cobblemon:rare_candy", 5)]  # plus a rewards.mixed bundle of tier PRIZE_TIER
PRIZE_TIER = 2
CONSOLATION = [("cobblemon:rare_candy", 1)]
CONSOLATION_TIER = 1
WORDS = ["pikachu", "bulbasaur", "charmander", "squirtle", "gengar", "snorlax", "lucario", "garchomp", "dragonite",
         "tyranitar", "metagross", "greninja", "eevee", "umbreon", "sylveon", "gardevoir", "blaziken", "infernape",
         "rayquaza", "mewtwo", "jigglypuff", "psyduck", "magikarp", "gyarados", "lapras", "ditto", "togekiss",
         "zoroark", "mimikyu", "toxapex", "ferrothorn", "salamence", "hydreigon", "volcarona", "excadrill"]


def rc(c):
    return re.sub(r"\x1b\[[0-9;]*m", "", subprocess.run(["docker", "exec", "cobbleverse", "rcon-cli", c],
                                                       capture_output=True, text=True).stdout)


def label(items):
    """Chat text for a list of (item, count), e.g. "3 Ultra Ball, 2 Sitrus Berry"."""
    return ", ".join(f"{c} {it.split(':')[1].replace('_', ' ').title()}" for it, c in items)


def say(t, c="white", to="@a"):
    rc(f"tellraw {to} " + json.dumps([{"text": "[Typing Race] ", "color": "gold", "bold": True},
                                   {"text": t, "color": c, "bold": False}], ensure_ascii=False))


def snd(s, v=1, p=1): rc(f"execute as @a at @s run playsound {s} master @s ~ ~ ~ {v} {p}")


def norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]", "", re.sub(r"^!q\s*", "", s))


def online():
    out = rc("list")
    return [re.sub(r"^(\[[^\]]*\]\s*)+", "", n.strip()) for n in out.split(":", 1)[1].split(",") if n.strip()] if ":" in out else []


players = online()
if len(players) < 1:
    sys.exit("nobody online")
score = {p: 0 for p in players}
rc(f"scoreboard objectives remove {OBJ}")
rc(f'scoreboard objectives add {OBJ} dummy {{"text":"Typing Race","color":"gold","bold":true}}')
rc(f"scoreboard objectives setdisplay sidebar {OBJ}")
for p in players:
    rc(f"scoreboard players set {p} {OBJ} 0")
rc("title @a times 5 60 10")
rc('title @a title {"text":"TYPING RACE","color":"gold","bold":true}')
rc('title @a subtitle {"text":"Who can type the Pokémon name fastest?","color":"yellow"}')
snd("minecraft:event.raid.horn", 0.6, 1.3)
say(f"Event for {' and '.join(players)}! {ROUNDS} rounds. Each round, a Pokémon name pops up on screen at a random moment. "
    "The FIRST to type it in chat gets 1 point (case doesn't matter, !q is optional). "
    "Top scorer gets Rare Candy and a surprise bundle (balls, berries or an evolution item), everyone else gets a smaller one. Starting in 10 seconds!", "yellow")
time.sleep(10)
words = random.sample(WORDS, ROUNDS)
for i, w in enumerate(words, 1):
    rc("title @a actionbar " + json.dumps({"text": f"Round {i}/{ROUNDS}: get ready...", "color": "gray"}, ensure_ascii=False))
    time.sleep(random.uniform(3, 8))
    rc(f"title @a times 0 {WINDOW * 20} 5")
    rc("title @a title " + json.dumps({"text": w.upper(), "color": "gold", "bold": True}))
    rc('title @a subtitle {"text":"TYPE IT NOW!","color":"red"}')
    snd("minecraft:block.note_block.bell", 1, 1.6)
    start = time.time(); since = int(start); winner = None; seen = set()
    while time.time() - start < WINDOW and winner is None:
        out = subprocess.run(["docker", "logs", "--since", str(since), "cobbleverse"], capture_output=True, text=True)
        for line in (out.stdout + out.stderr).splitlines():
            m = re.search(r"<(?:\[[^\]]*\] )*([A-Za-z0-9_]{1,16})> (.*)$", line)
            if not m or line in seen:
                continue
            seen.add(line)
            if m.group(1) in score and norm(m.group(2)) == w:
                winner = m.group(1)
                break
        time.sleep(0.5)
    rc("title @a clear")
    if winner:
        score[winner] += 1
        rc(f"scoreboard players set {winner} {OBJ} {score[winner]}")
        say(f"Round {i}: {winner} was fastest! ({time.time() - start:.1f}s)", "green")
        snd("minecraft:entity.experience_orb.pickup", 1, 1.2)
    else:
        say(f"Round {i}: nobody made it. The answer was {w.capitalize()}.", "gray")
    time.sleep(2)
best = max(score.values())
leaders = [p for p in score if score[p] == best and best > 0]
board = ", ".join(f"{p} {score[p]}" for p in sorted(score, key=lambda p: -score[p]))
got = {}
for p in score:
    if leaders:
        items, tier = (PRIZE, PRIZE_TIER) if p in leaders else (CONSOLATION, CONSOLATION_TIER)
        got[p] = [g for item, n in items for g in rewards.give(p, item, n)] + rewards.mixed(p, tier)
rc("title @a times 5 80 10")
if leaders:
    rc("title @a title " + json.dumps({"text": " and ".join(leaders) + " WIN!", "color": "gold", "bold": True}, ensure_ascii=False))
    rc("title @a subtitle " + json.dumps({"text": board, "color": "yellow"}, ensure_ascii=False))
    say(f"Results: {board}. {' and '.join(leaders)} win Rare Candy and a surprise bundle, everyone else gets a "
        "smaller one.", "gold")
    for p, items in got.items():
        say(f"You got: {label(items)}.", "gold", p)
else:
    say(f"Results: {board}. Nobody scored.", "gray")
snd("minecraft:ui.toast.challenge_complete")
time.sleep(15)
rc(f"scoreboard objectives remove {OBJ}")
print("done", score, flush=True)
