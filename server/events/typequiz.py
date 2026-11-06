#!/usr/bin/env python3
"""Type matchup quiz for everyone online: each round asks which type is super effective against another, or which
type an attack can't hit, with four choices. Players type A, B, C or D in chat within the time limit; the first
answer each player sends in a round counts. Every correct answer pays 2 Dive Balls and 2 Dusk Balls; the top scorer
(3 or more correct) also gets 3 Rare Candy and an Exp Candy XL through rewards.give, so the daily candy cap applies.
Usage: typequiz.py [rounds]"""
import json, os, random, re, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rewards

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 5
WINDOW = 30
OBJ = "cvquiz"
# Attacking type -> defending types it hits for double damage (Gen 6+ chart).
SE = {"fire": ["grass", "ice", "bug", "steel"], "water": ["fire", "ground", "rock"], "electric": ["water", "flying"],
      "grass": ["water", "ground", "rock"], "ice": ["grass", "ground", "flying", "dragon"],
      "fighting": ["normal", "ice", "rock", "dark", "steel"], "poison": ["grass", "fairy"],
      "ground": ["fire", "electric", "poison", "rock", "steel"], "flying": ["grass", "fighting", "bug"],
      "psychic": ["fighting", "poison"], "bug": ["grass", "psychic", "dark"], "rock": ["fire", "ice", "flying", "bug"],
      "ghost": ["psychic", "ghost"], "dragon": ["dragon"], "dark": ["psychic", "ghost"],
      "steel": ["ice", "rock", "fairy"], "fairy": ["fighting", "dragon", "dark"]}
# Attacking type -> defending types it can't hit at all.
IMMUNE = {"normal": ["ghost"], "electric": ["ground"], "fighting": ["ghost"], "poison": ["steel"],
          "ground": ["flying"], "psychic": ["dark"], "ghost": ["normal"], "dragon": ["fairy"]}
TYPES = sorted({t for v in SE.values() for t in v} | set(SE) | {"normal"})


def rc(c):
    return re.sub(r"\x1b\[[0-9;]*m", "", subprocess.run(["docker", "exec", "cobbleverse", "rcon-cli", c],
                                                       capture_output=True, text=True).stdout)


def say(parts, to="@a"):
    if isinstance(parts, str):
        parts = [{"text": parts, "color": "white"}]
    rc(f"tellraw {to} " + json.dumps([{"text": "[Quiz] ", "color": "gold", "bold": True}] + parts, ensure_ascii=False))


def snd(s, v=1, p=1):
    rc(f"execute as @a at @s run playsound {s} master @s ~ ~ ~ {v} {p}")


def online():
    out = rc("list")
    if ":" not in out:
        return []
    return [re.sub(r"^(\[[^\]]*\]\s*)+", "", n.strip()) for n in out.split(":", 1)[1].split(",") if n.strip()]


def question():
    """(prompt, four choices, index of the right one)."""
    if random.random() < 0.7:
        att = random.choice([t for t in SE if SE[t]])
        right = random.choice(SE[att])
        wrong = random.sample([t for t in TYPES if t not in SE[att] and t != att], 3)
        prompt = f"A {att.title()}-type attack is super effective against which type?"
    else:
        att = random.choice(list(IMMUNE))
        right = random.choice(IMMUNE[att])
        wrong = random.sample([t for t in TYPES if t not in IMMUNE[att]], 3)
        prompt = f"Which type takes NO damage from {att.title()}-type attacks?"
    choices = wrong + [right]
    random.shuffle(choices)
    return prompt, choices, choices.index(right)


def answers(since, players):
    """{player: letter} for the first A-D each player typed in chat since `since`."""
    out = subprocess.run(["docker", "logs", "--since", str(since), "cobbleverse"], capture_output=True, text=True)
    got = {}
    for line in (out.stdout + out.stderr).splitlines():
        m = re.search(r"<(?:\[[^\]]*\] )*([A-Za-z0-9_]{1,16})> (?:!q\s*)?([A-Da-d])\s*$", line)
        if m and m.group(1) not in got:
            got[m.group(1)] = "ABCD".index(m.group(2).upper())
    return got


players = online()
if not players:
    sys.exit("nobody online")
score = {p: 0 for p in players}
rc(f"scoreboard objectives remove {OBJ}")
rc(f'scoreboard objectives add {OBJ} dummy {{"text":"Type Quiz","color":"gold","bold":true}}')
rc(f"scoreboard objectives setdisplay sidebar {OBJ}")
for p in players:
    rc(f"scoreboard players set {p} {OBJ} 0")
rc("title @a times 5 60 10")
rc('title @a title {"text":"TYPE QUIZ","color":"gold","bold":true}')
rc('title @a subtitle {"text":"Know your type matchups?","color":"yellow"}')
snd("minecraft:event.raid.horn", 0.6, 1.3)
say([{"text": f"{ROUNDS} questions about type matchups. Type ", "color": "yellow"},
     {"text": "A, B, C or D", "color": "aqua"},
     {"text": f" in chat within {WINDOW} seconds; your first answer counts.", "color": "yellow"}])
say([{"text": "Each correct answer: 2 Dive Balls and 2 Dusk Balls. Top scorer (3+ correct): 3 Rare Candy and an "
              "Exp Candy XL. Starting in 10 seconds!", "color": "yellow"}])
time.sleep(10)
for i in range(1, ROUNDS + 1):
    prompt, choices, right = question()
    rc("title @a times 5 40 10")
    rc("title @a title " + json.dumps({"text": f"Question {i}/{ROUNDS}", "color": "gold", "bold": True}))
    snd("minecraft:block.note_block.bell", 1, 1.4)
    say([{"text": f"Q{i}. {prompt}", "color": "white", "bold": True}])
    say([{"text": "   ".join(f"{'ABCD'[k]}) {c.title()}" for k, c in enumerate(choices)), "color": "aqua"}])
    since = int(time.time())
    start = time.time()
    while time.time() - start < WINDOW:
        left = int(WINDOW - (time.time() - start))
        rc("title @a actionbar " + json.dumps({"text": f"Q{i}: {left}s left. Type A, B, C or D", "color": "gray"}))
        got = answers(since, score)
        if got and all(p in got for p in online()):
            break
        time.sleep(1)
    got = answers(since, score)
    correct = [p for p, a in got.items() if a == right]
    for p in correct:
        score[p] = score.get(p, 0) + 1
        rc(f"scoreboard players set {p} {OBJ} {score[p]}")
    say([{"text": f"Answer: {'ABCD'[right]}) {choices[right].title()}. ", "color": "green"},
         {"text": ("Correct: " + ", ".join(correct)) if correct else "Nobody got it.", "color": "white"}])
    snd("minecraft:entity.experience_orb.pickup" if correct else "minecraft:block.note_block.bass", 1, 1.2)
    time.sleep(4)

best = max(score.values()) if score else 0
leaders = [p for p, s in score.items() if s == best and s >= 3]
board = ", ".join(f"{p} {s}/{ROUNDS}" for p, s in sorted(score.items(), key=lambda kv: -kv[1]))
online_now = set(online())
for p, s in score.items():
    if not s:
        continue
    items = [("cobblemon:dive_ball", 2 * s), ("cobblemon:dusk_ball", 2 * s)]
    if p in leaders:
        items += [("cobblemon:rare_candy", 3), ("cobblemon:exp_candy_xl", 1)]
    if p not in online_now:
        continue
    got = [g for item, n in items for g in rewards.give(p, item, n)]
    say([{"text": "You got: " + ", ".join(f"{c} {it.split(':')[1].replace('_', ' ').title()}" for it, c in got) + ".",
          "color": "gold"}], to=p)
rc("title @a times 5 80 10")
rc("title @a title " + json.dumps({"text": (" and ".join(leaders) + " WIN!") if leaders else "Quiz over",
                                   "color": "gold", "bold": True}))
rc("title @a subtitle " + json.dumps({"text": board, "color": "yellow"}))
say([{"text": f"Results: {board}.", "color": "gold"}])
snd("minecraft:ui.toast.challenge_complete")
time.sleep(15)
rc(f"scoreboard objectives remove {OBJ}")
print("done", score, flush=True)
