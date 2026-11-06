#!/usr/bin/env python3
"""Guess-the-cry race for everyone online: each round plays a Pokemon cry to all players (repeated every 8 s, with a
hint after 15 s); the first player to type the species name scores. Sidebar score, prize for the winner.
Usage: cryrace.py [rounds]"""
import json, random, re, subprocess, sys, time, unicodedata
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import rewards

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 6
WINDOW = 40
OBJ = "cvcry"
PRIZE = [("cobblemon:rare_candy", 5)]  # plus a rewards.mixed bundle of tier PRIZE_TIER
PRIZE_TIER = 2
CONSOLATION = [("cobblemon:rare_candy", 1)]
CONSOLATION_TIER = 1
POOL = [
    ("pikachu", "Yellow electric mouse, mascot of the whole series."),
    ("psyduck", "Yellow duck that always holds its aching head."),
    ("snorlax", "Weighs 460 kg, just eats, sleeps and blocks the road."),
    ("gengar", "Ghost/Poison type with a wide grin in the dark."),
    ("jigglypuff", "Sings everyone to sleep, then angrily doodles on their faces."),
    ("lucario", "Fighting/Steel type that can sense Aura."),
    ("eevee", "Can evolve into 8 different forms."),
    ("charizard", "Orange fire dragon that is not a Dragon type."),
    ("bulbasaur", "Pokémon #001, has a bulb on its back."),
    ("squirtle", "Water turtle that wears sunglasses in the anime."),
    ("meowth", "Team Rocket's cat that can talk like a human."),
    ("lapras", "Carries people across the sea, Water/Ice type."),
    ("mewtwo", "Created from Mew's DNA."),
    ("ditto", "Can transform into any Pokémon."),
    ("togepi", "Baby in an eggshell that Misty always carries."),
    ("gyarados", "Magikarp evolves into this angry dragon."),
]


def rc(c):
    return re.sub(r"\x1b\[[0-9;]*m", "", subprocess.run(["docker", "exec", "cobbleverse", "rcon-cli", c],
                                                       capture_output=True, text=True).stdout)


def label(items):
    """Chat text for a list of (item, count), e.g. "3 Ultra Ball, 2 Sitrus Berry"."""
    return ", ".join(f"{c} {it.split(':')[1].replace('_', ' ').title()}" for it, c in items)


def say(t, c="white", to="@a"):
    rc(f"tellraw {to} " + json.dumps([{"text": "[Who's That Pokémon?] ", "color": "gold", "bold": True},
                                   {"text": t, "color": c, "bold": False}], ensure_ascii=False))


def snd(s, v=1, p=1, cat="master"): rc(f"execute as @a at @s run playsound {s} {cat} @s ~ ~ ~ {v} {p}")


def norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]", "", re.sub(r"^!q\s*", "", s))


def close(a, b):
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] <= 1


def online():
    out = rc("list")
    return [re.sub(r"^(\[[^\]]*\]\s*)+", "", n.strip()) for n in out.split(":", 1)[1].split(",") if n.strip()] if ":" in out else []


players = online()
if not players:
    sys.exit("nobody online")
score = {p: 0 for p in players}
rc(f"scoreboard objectives remove {OBJ}")
rc(f'scoreboard objectives add {OBJ} dummy {{"text":"Who\'s That Pokémon?","color":"gold","bold":true}}')
rc(f"scoreboard objectives setdisplay sidebar {OBJ}")
for p in players:
    rc(f"scoreboard players set {p} {OBJ} 0")
rc("title @a times 5 60 10")
rc('title @a title {"text":"WHO\'S THAT POKÉMON?","color":"gold","bold":true}')
rc('title @a subtitle {"text":"Hear the cry, guess the name first","color":"yellow"}')
snd("minecraft:event.raid.horn", 0.6, 1.3)
say(f"Event for {' and '.join(players)}! {ROUNDS} rounds. Each round I play a Pokémon's cry for everyone to hear. "
    "The first to type the right name gets 1 point (one typo still counts, guess as often as you like). A hint comes after 15 seconds. "
    "Top scorer gets Rare Candy and a surprise bundle (balls, berries or an evolution item), everyone else gets a smaller one. Starting in 10 seconds!", "yellow")
time.sleep(10)
for i, (sp, hint) in enumerate(random.sample(POOL, ROUNDS), 1):
    say(f"Round {i}/{ROUNDS}: listen closely...", "light_purple")
    time.sleep(1.5)
    start = time.time(); since = int(start); winner = None; seen = set(); last_cry = -99; last_bar = -99; hinted = False
    while time.time() - start < WINDOW and winner is None:
        el = time.time() - start
        if el - last_cry >= 8:
            snd(f"cobblemon:pokemon.{sp}.cry", 1.5, 1, "neutral"); last_cry = el
        if el >= 15 and not hinted:
            say(f"Hint: {hint}", "aqua"); hinted = True
        out = subprocess.run(["docker", "logs", "--since", str(since), "cobbleverse"], capture_output=True, text=True)
        for line in (out.stdout + out.stderr).splitlines():
            m = re.search(r"<(?:\[[^\]]*\] )*([A-Za-z0-9_]{1,16})> (.*)$", line)
            if not m or line in seen:
                continue
            seen.add(line)
            if m.group(1) in score and close(sp, norm(m.group(2))):
                winner = m.group(1)
                break
        if el - last_bar >= 3:  # docker logs above is not rcon, but every actionbar is an rcon call
            rc("title @a actionbar " + json.dumps({"text": f"Round {i}: {max(0, int(WINDOW - el))}s left", "color": "light_purple"}, ensure_ascii=False))
            last_bar = el
        time.sleep(1)
    if winner:
        score[winner] += 1
        rc(f"scoreboard players set {winner} {OBJ} {score[winner]}")
        say(f"{winner} got it: {sp.capitalize()}! ({time.time() - start:.0f}s)", "green")
        snd("minecraft:entity.experience_orb.pickup", 1, 1.2)
    else:
        say(f"Nobody got it. It was {sp.capitalize()}.", "red")
        snd("minecraft:entity.villager.no", 1, 0.7)
    time.sleep(3)
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
