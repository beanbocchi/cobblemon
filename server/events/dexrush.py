#!/usr/bin/env python3
"""Pokedex Rush: for ten minutes, players race to catch species they have never caught before. Progress comes from
each player's Pokedex file (saved by the server; this script runs save-all once a minute), and a sidebar
scoreboard and a boss bar timer show it live. Every two new species pay one Exp Candy M (up to five), and anyone
with a new species gets a tier 1 rewards.mixed bundle; the leader at the end also gets Rare Candy and an Ability
Capsule. Usage: dexrush.py [minutes]"""
import gzip, json, os, re, sys, time
sys.argv, args = [sys.argv[0]], sys.argv[1:]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import events as e
import rewards

MINUTES = int(args[0]) if args else 10
OBJ = "cvdex"
BAR = "cobbleverse:dex"
WIN = [("cobblemon:rare_candy", 3), ("cobblemon:ability_capsule", 1)]
# Each rcon call prints two lines to the server console: the bar moves every 15 s, its text and the scores
# change once a minute.
BAR_EVERY, SCORE_EVERY = 15, 60


def label(items):
    """Chat text for a list of (item, count), e.g. "3 Ultra Ball, 2 Sitrus Berry"."""
    return ", ".join(f"{c} {it.split(':')[1].replace('_', ' ').title()}" for it, c in items)


def say(text, color="white", to="@a"):
    e.rcon(f"tellraw {to} " + json.dumps([{"text": "[Pokédex Rush] ", "color": "aqua", "bold": True},
                                       {"text": text, "color": color, "bold": False}], ensure_ascii=False))


def uuid_of(name):
    cache = json.load(open(os.path.join(e.DATA, "usercache.json")))
    return next(c["uuid"] for c in cache if c["name"].lower() == name.lower())


def caught(name):
    """Species the player has caught, from their saved Pokedex."""
    u = uuid_of(name)
    raw = open(os.path.join(e.DATA, "world/pokedex", u[:2], u + ".nbt"), "rb").read()
    try:
        raw = gzip.decompress(raw)
    except OSError:
        pass
    records = e.anvil.nbt(raw).get("speciesRecords", {})
    return {sp for sp, rec in records.items()
            if any(f.get("knowledge") in ("OWNED", "CAUGHT") for f in rec.get("formRecords", {}).values())}


def online():
    out = e.rcon("list")
    return [re.sub(r"^(\[[^\]]*\]\s*)+", "", n.strip()) for n in out.split(":", 1)[1].split(",") if n.strip()] if ":" in out else []


def main():
    e.rcon("save-all")
    time.sleep(3)
    players = online()
    base = {n: caught(n) for n in players}
    e.rcon(f"scoreboard objectives remove {OBJ}")
    e.rcon(f'scoreboard objectives add {OBJ} dummy {{"text":"New species caught","color":"aqua","bold":true}}')
    e.rcon(f"scoreboard objectives setdisplay sidebar {OBJ}")
    for n in players:
        e.rcon(f"scoreboard players set {n} {OBJ} 0")
    e.rcon(f"bossbar remove {BAR}")
    e.rcon(f'bossbar add {BAR} {{"text":"Pokédex Rush"}}')
    e.rcon(f"bossbar set {BAR} color blue")
    e.rcon(f"bossbar set {BAR} max {MINUTES * 60}")
    e.rcon(f"bossbar set {BAR} players @a")
    e.rcon("title @a times 5 60 10")
    e.rcon('title @a title {"text":"POKÉDEX RUSH","color":"aqua","bold":true}')
    e.rcon(f'title @a subtitle {{"text":"{MINUTES} minutes: catch as many NEW species as you can","color":"white"}}')
    e.rcon("execute as @a at @s run playsound minecraft:event.raid.horn master @s ~ ~ ~ 0.6 1.4")
    say(f"For {MINUTES} minutes, catch as many species as you can that you have NEVER caught before (species already "
        "in your Pokédex don't count). Every 2 new species give 1 Exp Candy M (up to 5), and anyone with a new species "
        "gets a surprise bundle (balls, berries or an evolution item). The leader at the end also gets Rare Candy and "
        "an Ability Capsule. The scoreboard on the right updates every minute.", "aqua")
    t0, scores, end = time.time(), {n: 0 for n in players}, time.time() + MINUTES * 60
    next_score, shown = time.time() + SCORE_EVERY, None
    while True:
        remain = max(0, int(end - time.time()))
        e.rcon(f"bossbar set {BAR} value {remain}")
        text = f"Pokédex Rush: {-(-remain // 60)} min left"
        if text != shown:
            e.rcon(f"bossbar set {BAR} name " + json.dumps({"text": text, "color": "aqua"}, ensure_ascii=False))
            shown = text
        if remain > 0 and time.time() < next_score:
            time.sleep(max(1, min(BAR_EVERY, end - time.time(), next_score - time.time())))
            continue
        next_score += SCORE_EVERY
        e.rcon("save-all")
        time.sleep(2)
        for n in players:
            try:
                new = caught(n) - base[n]
            except (OSError, StopIteration, ValueError):
                continue
            if len(new) > scores[n]:
                say(f"{n} just caught a new species! Total: {len(new)}.", "yellow")
                e.rcon(f"execute as {n} at @s run playsound minecraft:entity.experience_orb.pickup master @s")
            if len(new) != scores[n]:
                e.rcon(f"scoreboard players set {n} {OBJ} {len(new)}")
            scores[n] = len(new)
        if remain == 0:
            break
        time.sleep(max(1, min(BAR_EVERY, end - time.time(), next_score - time.time())))
    best = max(scores.values()) if scores else 0
    leaders = [n for n in players if scores[n] == best and best > 0]
    got = {}
    for n in players:
        if not scores[n]:
            continue
        got[n] = rewards.give(n, "cobblemon:exp_candy_m", min(5, scores[n] // 2)) if scores[n] >= 2 else []
        got[n] += rewards.mixed(n, 1)
        if n in leaders:
            for item, c in WIN:
                got[n] += rewards.give(n, item, c)
    board = ", ".join(f"{n} {scores[n]}" for n in sorted(players, key=lambda n: -scores[n]))
    if leaders:
        e.rcon("title @a title " + json.dumps({"text": " and ".join(leaders) + " win!", "color": "gold",
                                                "bold": True}, ensure_ascii=False))
        e.rcon("execute as @a at @s run playsound minecraft:ui.toast.challenge_complete master @s")
        say(f"Time's up! Results: {board}. First place goes to {' and '.join(leaders)}.", "gold")
        for n, items in got.items():
            say(f"You got: {label(items)}.", "gold", n)
    else:
        say(f"Time's up! Nobody caught a new species. Results: {board}.", "gray")
    time.sleep(20)
    e.rcon(f"bossbar remove {BAR}")
    e.rcon(f"scoreboard objectives remove {OBJ}")
    print("done", scores, flush=True)


if __name__ == "__main__":
    main()
