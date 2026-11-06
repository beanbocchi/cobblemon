#!/usr/bin/env python3
"""Memory event: show a sequence of Pokemon names on screen, the player types it back in order.
Five rounds (3..7 names); each round passed pays 2 Rare Candy + 1 Max Revive; a wrong round ends it.
Usage: memory.py <player> [first round] [rounds passed before]. To resume, e.g. `memory.py huylba 4 3` starts at
round 4 and counts 3 rounds as already passed and paid."""
import json, subprocess, sys, time, re, random, unicodedata
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import rewards
P = sys.argv[1] if len(sys.argv) > 1 else "huylba"
START = int(sys.argv[2]) if len(sys.argv) > 2 else 1
BASE = int(sys.argv[3]) if len(sys.argv) > 3 else 0
def rc(c): return subprocess.run(["docker", "exec", "cobbleverse", "rcon-cli", c], capture_output=True, text=True).stdout
def snd(s, v=1, p=1): rc(f"execute as {P} at @s run playsound {s} master @s ~ ~ ~ {v} {p}")
def title(t, c, sub=None, sc="white"):
    rc(f"title {P} title " + json.dumps({"text": t, "color": c, "bold": True}, ensure_ascii=False))
    if sub is not None:
        rc(f"title {P} subtitle " + json.dumps({"text": sub, "color": sc}, ensure_ascii=False))
def say(t, c="white"):
    rc("tellraw @a " + json.dumps([{"text": "[Pokémon Memory] ", "color": "light_purple", "bold": True},
                                   {"text": t, "color": c, "bold": False}], ensure_ascii=False))
def act(t, c): rc(f"title {P} actionbar " + json.dumps({"text": t, "color": c, "bold": True}, ensure_ascii=False))
def close(a, b):
    """True when b is a at most one edit away (typo tolerance)."""
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
def strip(s):
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9 ,]", " ", s)
POOL = ["pikachu", "eevee", "snorlax", "gengar", "mew", "onix", "ditto", "lapras", "psyduck", "zubat", "golem",
        "abra", "jynx", "togepi", "mudkip", "lucario", "riolu", "pichu", "vulpix", "growlithe", "magikarp", "machop",
        "geodude", "oddish", "ponyta", "seel", "slowpoke", "rattata", "pidgey", "jigglypuff"]
LENS = [3, 4, 5, 6, 7]
ANS = 45
# Logs are read often (docker logs is not rcon), but each rcon call prints two lines to the server console, so
# the actionbar prompt is sent only every 10 s, and the type countdown only at 30, 15 and 5 s left.
PROMPT_EVERY = 10
COUNTDOWN = (30, 15, 5)
rc(f"title {P} times 5 50 10")
title("POKÉMON MEMORY", "light_purple", "Remember the names, type them back in order", "white")
snd("minecraft:event.raid.horn", 0.6, 1.3)
say("Memory event! 5 rounds. Each round shows a list of Pokémon names one by one on screen (round 1: 3 names, round 5: 7 names, 2 seconds each). "
    "Then type the whole list back in chat in order, in one message or several. One typo per name still counts. "
    "Each round passed: +2 Rare Candy +1 Max Revive. All 5 rounds: 10 Rare Candy + 5 Max Revive. One wrong round ends it.", "yellow")
say("Type \"ready\" in chat when you are ready. The event starts only then. Waiting up to 5 minutes.", "aqua")
ready_since, ready, prompted = int(time.time()), False, 0
while time.time() - ready_since < 300 and not ready:
    out = subprocess.run(["docker", "logs", "--since", str(ready_since), "cobbleverse"], capture_output=True, text=True)
    for line in (out.stdout + out.stderr).splitlines():
        m = re.search(rf"<(?:\[[^\]]*\] )*{P}> (.*)$", line)
        if m and strip(re.sub(r"^!q\s*", "", m.group(1))).replace(" ", "") in ("sansang", "ready"):
            ready = True
            break
    if not ready and time.time() - prompted >= PROMPT_EVERY:
        act("Type \"ready\" to start", "aqua")
        prompted = time.time()
    time.sleep(2)
if not ready:
    say("No \"ready\" after 5 minutes, so the event is cancelled. Ask again when you have time.", "gray")
    print("not ready", flush=True)
    sys.exit(0)
say("Go!", "green")
time.sleep(3)
passed = BASE
for r, L in enumerate(LENS, 1):
    if r < START:
        continue
    seq = random.sample(POOL, L)
    say(f"Round {r}/5: {L} Pokémon. Watch the screen...", "light_purple")
    time.sleep(3)
    rc(f"title {P} times 0 34 3")
    for i, n in enumerate(seq, 1):
        title(n.upper(), "gold", f"{i}/{L}", "gray")
        snd("minecraft:block.note_block.pling", 1, 0.8 + i * 0.1)
        time.sleep(2.0)
    rc(f"title {P} clear")
    act("TYPE THE WHOLE LIST NOW!", "red")
    snd("minecraft:block.note_block.bell", 1, 1.5)
    start = time.time(); since = int(start); typed = []; seen = set(); marks = list(COUNTDOWN)
    while time.time() - start < ANS and len(typed) < L:
        out = subprocess.run(["docker", "logs", "--since", str(since), "cobbleverse"], capture_output=True, text=True)
        since = int(time.time())
        for line in (out.stdout + out.stderr).splitlines():
            m = re.search(rf"<(?:\[[^\]]*\] )*{P}> (.*)$", line)
            if not m or line in seen:
                continue
            seen.add(line)
            words = [w for w in re.split(r"[ ,]+", strip(re.sub(r"^[!1]q\s*", "", m.group(1)))) if w]
            typed.extend(words)
        left = max(0, int(ANS - (time.time() - start)))
        if marks and left <= marks[0] and len(typed) < L:
            while marks and left <= marks[0]:
                marks.pop(0)
            act(f"Round {r}: {left}s left to type", "red")
        time.sleep(1.2)
    got = typed[:L] if typed else None
    if got and len(got) == L and all(close(a, b) for a, b in zip(seq, got)):
        passed += 1
        say(f"Round {r}: CORRECT! (+2 Rare Candy +1 Max Revive)", "green")
        snd("minecraft:entity.experience_orb.pickup", 1, 1.2)
        time.sleep(3)
    else:
        answer = " ".join(s.capitalize() for s in seq)
        typed = (" You typed: " + " ".join(got) + ".") if got else " Time's up."
        say(f"Round {r}: wrong! The answer was {answer}.{typed}", "red")
        snd("minecraft:entity.villager.no", 1, 0.6)
        break
new = passed - BASE
candy, revive = passed * 2, passed
got = []
if new > 0:
    got += rewards.give(P, "cobblemon:rare_candy", new * 2)
    got += rewards.give(P, "cobblemon:max_revive", new)
if False:
    rewards.give(P, "cobblemon:rare_candy", candy)
    rewards.give(P, "cobblemon:max_revive", revive)
# On a resumed run only the new rounds are paid now; say that and the rounds paid so far separately
gain = ", ".join(f"{c} {it.split(':')[1].replace('_', ' ').title()}" for it, c in got) or "no reward"
if BASE:
    gain += f" this time ({passed} rounds paid in total)"
rc(f"title {P} times 5 60 10")
title(f"PASSED {passed}/5 ROUNDS", "gold" if passed >= 3 else "red", gain, "yellow")
say(f"Result: {P} passed {passed}/5 rounds: {gain}." + (" Amazing memory!" if passed == 5 else ""), "gold")
snd("minecraft:ui.toast.challenge_complete")
print("passed", passed, flush=True)
