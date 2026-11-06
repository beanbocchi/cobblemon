#!/usr/bin/env python3
"""Snorlax Trial: a three-stage event for one player whose Munchlax needs friendship to evolve.

Usage: snorlax_trial.py <player>

Stage 1: a five-question type quiz; three or more correct gives Munchlax +40 friendship.
Stage 2: within 20 minutes, catch a wild Pokémon that knows a sleep move; reward +40 friendship and 5 Ultra Balls.
Stage 3: within 20 minutes, walk 500 m with Munchlax out of its ball; reward friendship 160 (enough to evolve on
the next level-up), 2 Rare Candy through rewards.give and a broadcast.
"""
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cvlife as c  # noqa: E402
import rewards  # noqa: E402

P = sys.argv[1]
START = int(sys.argv[2]) if len(sys.argv) > 2 else 1  # resume at this test
SLEEP = {"spore", "sleeppowder", "hypnosis", "yawn", "sing", "lovelykiss", "grasswhistle", "darkvoid"}
quiz = {"__file__": os.path.join(HERE, "typequiz.py")}
exec(open(os.path.join(HERE, "typequiz.py"), encoding="utf-8").read().split("\nplayers = online()")[0]
     .replace("sys.argv[1]", "'5'"), quiz)


def say(text, color="white", to="@a"):
    c.tell(to, [c.t(text, color)], prefix="[Snorlax Trial] ", color="gold")


def big(title, sub=""):
    c.rc(f"title {P} times 5 50 10")
    c.rc(f"title {P} subtitle " + c.json.dumps({"text": sub, "color": "yellow"}, ensure_ascii=False))
    c.rc(f"title {P} title " + c.json.dumps({"text": title, "color": "gold", "bold": True}, ensure_ascii=False))


def munchlax_slot():
    for k, v in c.party(P).items():
        if c.sp_of(v) == "munchlax":
            return k, int(v.get("Friendship", 0))
    return None, 0


def add_friendship(n, to=None):
    c.fresh_save(force=True)
    slot, f = munchlax_slot()
    if slot is None:
        say("Munchlax isn't in your party, so the friendship is saved for later. Put it in your party.", "red", P)
        return None
    new = to if to is not None else min(255, f + n)
    c.rc(f"pokemoneditother {P} {slot + 1} friendship={new}")
    return new


def online():
    return P in c.online_from_list()


score, caught = 0, None
if START == 1:
    # ---------- intro ----------
    big("SNORLAX TRIAL", "Three tests stand between Munchlax and Snorlax")
    c.snd(P, "minecraft:event.raid.horn", 1.2)
    say(f"{P} takes on the Snorlax Trial! Pass three tests and Munchlax gets enough friendship to evolve.", "gold")
    say("Test 1: five type questions. Test 2: catch a Pokémon that knows a sleep move. "
        "Test 3: walk 500 m with Munchlax out of its ball.", "yellow", P)
    time.sleep(8)

    # ---------- test 1: quiz ----------
    big("TEST 1", "Type matchups: answer A, B, C or D in chat")
    score = 0
    for i in range(1, 6):
        prompt, choices, right = quiz["question"]()
        say(f"Q{i}. {prompt}", "white", P)
        c.rc(f"tellraw {P} " + c.json.dumps({"text": "   ".join(f"{'ABCD'[k]}) {x.title()}" for k, x in enumerate(choices)),
                                            "color": "aqua"}))
        since, start = int(time.time()), time.time()
        got = {}
        while time.time() - start < 30 and P not in got:
            time.sleep(1)
            got = quiz["answers"](since, [P])
            c.bar(P, c.t(f"Q{i}: {int(30 - (time.time() - start))}s left", "gray"))
        ok = got.get(P) == right
        score += ok
        say(f"{'Correct' if ok else 'Wrong'}: {'ABCD'[right]}) {choices[right].title()}. Score {score}/{i}.",
            "green" if ok else "red", P)
        c.snd(P, "minecraft:entity.experience_orb.pickup" if ok else "minecraft:block.note_block.bass")
        time.sleep(3)
    if score >= 3:
        f = add_friendship(40)
        say(f"Test 1 passed with {score}/5! Munchlax +40 friendship" + (f" (now {f})." if f else "."), "green")
    else:
        say(f"Test 1: {score}/5, not enough for the bonus, but the trial goes on.", "yellow")
    time.sleep(4)

    # ---------- test 2: catch a sleeper ----------
    big("TEST 2", "Catch a Pokémon that knows a sleep move (20 min)")
    say("Test 2: catch any wild Pokémon that knows Hypnosis, Sing, Sleep Powder, Spore, Yawn or another sleep move. "
        "Hint: Hypno shows up at night, Wigglytuff in plains, Musharna nearby. 20 minutes.", "yellow", P)
    c.fresh_save(force=True)
    before = {str(m.get("UUID")) for m in c.mons(P)}
    caught, end = None, time.time() + 1200
    while time.time() < end and online():
        time.sleep(20)
        c.fresh_save(force=True)
        for m in c.mons(P):
            if str(m.get("UUID")) in before:
                continue
            before.add(str(m.get("UUID")))
            moves = {x.get("MoveName") for x in m.get("MoveSet", []) if isinstance(x, dict)}
            if moves & SLEEP:
                caught = (c.sp_of(m), sorted(moves & SLEEP)[0])
                break
            say(f"{c.species_name(c.sp_of(m))} doesn't know a sleep move. Keep looking!", "gray", P)
        if caught:
            break
        c.bar(P, c.t(f"Test 2: {int((end - time.time()) // 60)} min left", "gray"))
    if caught:
        f = add_friendship(40)
        rewards.give(P, "cobblemon:ultra_ball", 5)
        say(f"Test 2 passed: {P} caught a {c.species_name(caught[0])} with {caught[1]}! Munchlax +40 friendship"
            + (f" (now {f})" if f else "") + " and 5 Ultra Balls.", "green")
    else:
        say("Test 2 ran out of time. On to the last test.", "yellow")
    time.sleep(4)

# ---------- test 3: walk with Munchlax ----------
big("TEST 3", "Walk 500 m with Munchlax out of its ball (20 min)")
say("Test 3: send Munchlax out and walk 500 m with it following you. Distance only counts while it is next to you.",
    "yellow", P)
walked, last, end = 0, c.travelled(P), time.time() + 1200
while time.time() < end and walked < 500 and online():
    time.sleep(5)
    now = c.travelled(P)
    near = "passed" in c.rc(f"execute as {P} at @s if entity @e[type=cobblemon:pokemon,distance=..24,"
                            f"nbt={{Pokemon:{{Species:\"cobblemon:munchlax\"}}}}]")
    if near:
        walked += max(0, min(200, now - last))
    last = now
    c.bar(P, c.t(f"Test 3: {int(walked)}/500 m with Munchlax" + ("" if near else " (Munchlax isn't with you)"),
                 "aqua" if near else "red"))
if walked >= 500:
    f = add_friendship(0, to=160)
    rewards.give(P, "cobblemon:rare_candy", 2)
    big("TRIAL COMPLETE", "Munchlax is ready to become Snorlax")
    c.fireworks(P, 5)
    c.snd(P, "minecraft:ui.toast.challenge_complete")
    say(f"{P} completed the Snorlax Trial! Munchlax now has 160 friendship: one more level and it evolves "
        "into Snorlax. Bonus: 2 Rare Candy.", "gold")
else:
    say("Test 3 ran out of time. The trial is over; the rewards you earned stay with you.", "yellow")
print("done", score, caught, walked, flush=True)
