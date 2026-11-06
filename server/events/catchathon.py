#!/usr/bin/env python3
"""Catch-a-thon: six minutes to catch as many Pokemon as possible. A mixed herd (10 per player, two of them shiny)
appears 25-45 blocks from every Overworld player and everyone gets Ultra Balls. Catches are counted from each
player's saved party + PC (save-all once a minute), so releasing Pokemon during the event lowers the score. A sidebar
shows the count; the top catcher wins a bonus. Usage: catchathon.py"""
import gzip, json, math, os, random, sys, time
sys.argv = [sys.argv[0]]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import events as e
import rewards

MINUTES = 6
TAG = "cvev_catch"
OBJ = "cvcatch"
BAR = "cobbleverse:catch"
PER_PLAYER = 10
SHINIES = 2
POOL = ["eevee", "ralts", "riolu", "gible", "beldum", "axew", "deino", "bagon", "dratini", "goomy", "jangmoo",
        "dreepy", "frigibax", "zorua", "togepi", "growlithe", "ponyta", "mareep", "shinx", "pawniard", "rockruff",
        "litleo", "fletchling", "skwovet", "wooloo", "nickit", "fidough", "lechonk", "tandemaus", "pawmi",
        "sprigatito", "fuecoco", "quaxly", "cyndaquil", "totodile", "chikorita", "piplup", "chimchar", "turtwig"]
BONUS = [("cobblemon:rare_candy", 4), ("cobblemon:exp_candy_xl", 1), ("cobblemon:ability_capsule", 1)]
# Each rcon call prints two lines to the server console: the bar moves every 15 s, its text and the scores
# change once a minute.
BAR_EVERY, SCORE_EVERY = 15, 60


def say(text, color="white"):
    e.rcon("tellraw @a " + json.dumps([{"text": "[Catch-a-thon] ", "color": "green", "bold": True},
                                       {"text": text, "color": color, "bold": False}], ensure_ascii=False))


def owned(name):
    """Pokemon in the player's saved party and PC."""
    def count(d):
        if isinstance(d, dict):
            return ("Species" in d) + sum(count(v) for v in d.values())
        if isinstance(d, list):
            return sum(count(v) for v in d)
        return 0
    cache = json.load(open(os.path.join(e.DATA, "usercache.json")))
    u = next(c["uuid"] for c in cache if c["name"].lower() == name.lower())
    total = 0
    for store in ("playerpartystore", "pcstore"):
        path = os.path.join(e.DATA, "world/pokemon", store, u[:2], u + ".dat")
        if os.path.exists(path):
            total += count(e.anvil.nbt(gzip.decompress(open(path, "rb").read())))
    return total


def spawn_herd(name, px, pz, level):
    for _ in range(5):
        anchor, chunk = e.place_anchor(px, pz, 25, 45)
        if anchor:
            break
        e.release_anchor(chunk)
    else:
        return None
    e.rcon(f"kill @e[tag={e.ANCHOR}]")
    cx, cy, cz = anchor
    shiny = set(random.sample(range(PER_PLAYER), SHINIES))
    for i in range(PER_PLAYER):
        a, r = random.uniform(0, 2 * math.pi), random.uniform(1, 8)
        x, z = cx + math.cos(a) * r, cz + math.sin(a) * r
        sp = random.choice(POOL)
        props = f"level={random.randint(level, level + 8)}" + (" shiny=yes" if i in shiny else "")
        e.rcon(f"execute in minecraft:overworld positioned {x:.1f} {cy + 1:.1f} {z:.1f} run spawnpokemon {sp} {props}")
        # tag only the one just spawned, so nobody's own sent-out Pokemon is swept up at the end
        e.rcon(f"execute in minecraft:overworld positioned {x:.1f} {cy + 1:.1f} {z:.1f} run tag "
               f"@e[type=cobblemon:pokemon,distance=..2,tag=!{TAG},limit=1,sort=nearest,"
               f"nbt={{Pokemon:{{Species:\"cobblemon:{sp}\"}}}}] add {TAG}")
    e.rcon(f"execute as @e[tag={TAG}] run data merge entity @s {{PersistenceRequired:1b}}")
    return chunk, e.bearing(px, pz, cx, cz)


def main():
    here = e.online_overworld()
    if not here:
        sys.exit("nobody in the Overworld")
    e.rcon("save-all")
    time.sleep(3)
    players = [p[0] for p in here]
    base = {n: owned(n) for n in players}
    chunks, hints = [], []
    for name, px, py, pz in here:
        levels = e.party_levels(name)[:3]
        level = max(10, int(sum(levels) / len(levels)) - 20) if levels else 20
        got = spawn_herd(name, px, pz, level)
        if got:
            chunks.append(got[0])
            hints.append(f"{name}: about {got[1][1]} m to the {got[1][0]}")
        e.rcon(f"give {name} cobblemon:ultra_ball 15")
    e.rcon(f"scoreboard objectives remove {OBJ}")
    e.rcon(f'scoreboard objectives add {OBJ} dummy {{"text":"Pokémon caught","color":"green","bold":true}}')
    e.rcon(f"scoreboard objectives setdisplay sidebar {OBJ}")
    for n in players:
        e.rcon(f"scoreboard players set {n} {OBJ} 0")
    e.rcon(f"bossbar remove {BAR}")
    e.rcon(f'bossbar add {BAR} {{"text":"Catch-a-thon"}}')
    e.rcon(f"bossbar set {BAR} color green")
    e.rcon(f"bossbar set {BAR} max {MINUTES * 60}")
    e.rcon(f"bossbar set {BAR} players @a")
    e.rcon("title @a times 5 60 10")
    e.rcon('title @a title {"text":"CATCH-A-THON","color":"green","bold":true}')
    e.rcon(f'title @a subtitle {{"text":"{MINUTES} minutes, most catches wins","color":"white"}}')
    e.rcon("execute as @a at @s run playsound minecraft:event.raid.horn master @s ~ ~ ~ 0.6 1.3")
    say(f"{MINUTES} minutes: catch as many Pokémon as you can, any kind counts. Everyone has a herd of {PER_PLAYER} "
        f"nearby ({SHINIES} of them shiny), " + "; ".join(hints) + ". Everyone gets 15 Ultra Balls. "
        "Don't release Pokémon during the event, it lowers your score. The top catcher gets 4 Rare Candy, "
        "1 Exp Candy XL and 1 Ability Capsule.", "green")
    end, scores = time.time() + MINUTES * 60, {n: 0 for n in players}
    next_score, shown = time.time() + SCORE_EVERY, None
    while True:
        remain = max(0, int(end - time.time()))
        e.rcon(f"bossbar set {BAR} value {remain}")
        text = f"Catch-a-thon: {-(-remain // 60)} min left"
        if text != shown:
            e.rcon(f"bossbar set {BAR} name " + json.dumps({"text": text, "color": "green"}, ensure_ascii=False))
            shown = text
        if remain > 0 and time.time() < next_score:
            time.sleep(max(1, min(BAR_EVERY, end - time.time(), next_score - time.time())))
            continue
        next_score += SCORE_EVERY
        e.rcon("save-all")
        time.sleep(3)
        for n in players:
            try:
                now = max(0, owned(n) - base[n])
            except (OSError, StopIteration, ValueError):
                continue
            if now > scores[n]:
                e.rcon(f"execute as {n} at @s run playsound minecraft:entity.experience_orb.pickup master @s")
            if now != scores[n]:
                e.rcon(f"scoreboard players set {n} {OBJ} {now}")
            scores[n] = now
        if remain == 0:
            break
        time.sleep(max(1, min(BAR_EVERY, end - time.time(), next_score - time.time())))
    best = max(scores.values()) if scores else 0
    leaders = [n for n in players if scores[n] == best and best > 0]
    board = ", ".join(f"{n} {scores[n]}" for n in sorted(players, key=lambda n: -scores[n]))
    if leaders:
        for n in leaders:
            for item, c in BONUS:
                rewards.give(n, item, c)
        e.rcon("title @a title " + json.dumps({"text": " and ".join(leaders) + " win!", "color": "gold",
                                                "bold": True}, ensure_ascii=False))
        e.rcon("execute as @a at @s run playsound minecraft:ui.toast.challenge_complete master @s")
        say(f"Time's up! Results: {board}. {' and '.join(leaders)} win the bonus.", "gold")
    else:
        say(f"Time's up! Nobody caught anything. {board}.", "gray")
    e.rcon(f"execute as @e[tag={TAG}] at @s unless entity @a[distance=..10] run tp @s ~ -400 ~")
    for c in chunks:
        e.release_anchor(c)
    time.sleep(15)
    e.rcon(f"bossbar remove {BAR}")
    e.rcon(f"scoreboard objectives remove {OBJ}")
    print("done", scores, flush=True)


if __name__ == "__main__":
    main()
