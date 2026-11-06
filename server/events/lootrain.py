#!/usr/bin/env python3
"""Loot rain: for 45 seconds, items fall from the sky around every Overworld player (balls, candies, berries,
healing items, a little treasure, and one Master Ball somewhere in the storm). Pickups are counted with vanilla
picked_up statistics, rarer items score more, a sidebar shows the score live and the top scorer wins a bonus.
Usage: lootrain.py"""
import json, random, re, sys, time
sys.argv = [sys.argv[0]]
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import events as e
import rewards

SECONDS = 45
DROPS = [  # (item, count per drop, weight, points per single item)
    ("cobblemon:poke_ball", 4, 25, 1), ("cobblemon:great_ball", 3, 18, 1), ("cobblemon:ultra_ball", 2, 10, 2),
    ("cobblemon:exp_candy_s", 3, 14, 1), ("cobblemon:exp_candy_m", 2, 9, 2), ("cobblemon:exp_candy_l", 1, 4, 5),
    ("cobblemon:rare_candy", 1, 4, 6), ("cobblemon:sitrus_berry", 3, 10, 1), ("cobblemon:lum_berry", 2, 6, 1),
    ("cobblemon:full_restore", 1, 3, 4), ("cobblemon:max_revive", 1, 3, 4), ("minecraft:diamond", 1, 4, 5),
    ("minecraft:gold_ingot", 3, 8, 1), ("minecraft:emerald", 2, 6, 2), ("cobblemon:master_ball", 1, 0, 30),
]
OBJ = "cvloot"
BONUS = [("cobblemon:rare_candy", 2)]  # plus a rewards.mixed bundle of tier BONUS_TIER
BONUS_TIER = 2
# Each rcon call prints two lines to the server console. The drops are the event and stay every second, but each one
# is a single call at every Overworld player at once, and the live scores refresh only every 15 s.
SCORE_EVERY = 15
OVERWORLD = "execute in minecraft:overworld at @a[distance=0..] run"


def stat_obj(i):
    return f"cvl{i}"


def setup_scores(players):
    """One picked_up objective per item (counts only pickups from now on) plus the visible total."""
    for i, (item, *_rest) in enumerate(DROPS):
        e.rcon(f"scoreboard objectives remove {stat_obj(i)}")
        e.rcon(f"scoreboard objectives add {stat_obj(i)} minecraft.picked_up:{item.replace(':', '.')}")
        for n in players:
            e.rcon(f"scoreboard players set {n} {stat_obj(i)} 0")
    e.rcon(f"scoreboard objectives remove {OBJ}")
    e.rcon(f'scoreboard objectives add {OBJ} dummy {{"text":"Loot points","color":"gold","bold":true}}')
    e.rcon(f"scoreboard objectives setdisplay sidebar {OBJ}")
    for n in players:
        e.rcon(f"scoreboard players set {n} {OBJ} 0")


def scores(players, shown):
    """Points per player, one rcon call per item for everyone; the sidebar is set only where it changed."""
    totals = dict.fromkeys(players, 0)
    for i, (_item, _count, _weight, points) in enumerate(DROPS):
        out = e.rcon(f"execute as @a run scoreboard players get @s {stat_obj(i)}")
        for name, n in re.findall(r"(\w+) has (\d+) \[", out):
            if name in totals:
                totals[name] += int(n) * points
    for name, total in totals.items():
        if shown.get(name) != total:
            e.rcon(f"scoreboard players set {name} {OBJ} {total}")
            shown[name] = total
    return totals


def label(items):
    """Chat text for a list of (item, count), e.g. "3 Ultra Ball, 2 Sitrus Berry"."""
    return ", ".join(f"{c} {it.split(':')[1].replace('_', ' ').title()}" for it, c in items)


def say(text, color="white", to="@a"):
    e.rcon(f"tellraw {to} " + json.dumps([{"text": "[Loot Rain] ", "color": "gold", "bold": True},
                                       {"text": text, "color": color, "bold": False}], ensure_ascii=False))


def drop(where, item, count, dx, dy, dz):
    """Summon an item dx dy dz from each position that `where` (an execute prefix ending in "run") picks."""
    e.rcon(f'{where} summon minecraft:item ~{dx:.1f} ~{dy:.1f} ~{dz:.1f} '
           f'{{Item:{{id:"{item}",count:{count}}},PickupDelay:10s}}')


def main():
    here = e.online_overworld()
    if not here:
        sys.exit("nobody in the Overworld")
    e.rcon("weather rain 1200")
    e.rcon("title @a times 5 50 10")
    e.rcon('title @a title {"text":"LOOT RAIN","color":"gold","bold":true}')
    e.rcon('title @a subtitle {"text":"Grab it fast, loot is falling everywhere!","color":"yellow"}')
    e.rcon("execute as @a at @s run playsound minecraft:entity.player.levelup master @s ~ ~ ~ 1 0.5")
    say(f"For {SECONDS} seconds, items fall from the sky around everyone: balls, candy, berries, "
        "medicine, diamonds... and one Master Ball somewhere. Run around and grab them!", "yellow")
    players = [p[0] for p in here]
    setup_scores(players)
    master_at = random.uniform(10, SECONDS - 5)
    items, weights = [d[:2] for d in DROPS], [d[2] for d in DROPS]
    t0, shown, scored, sparkled = time.time(), {}, time.time(), 0
    while time.time() - t0 < SECONDS:
        # the same random offsets around every Overworld player, so each drop is one rcon call for everyone
        for _ in range(2):
            item, count = random.choices(items, weights)[0]
            drop(OVERWORLD, item, count, random.uniform(-12, 12), random.uniform(15, 22), random.uniform(-12, 12))
        if time.time() - sparkled >= 3:  # end rod particles last about 3 s
            sparkled = time.time()
            e.rcon(f"{OVERWORLD} particle minecraft:end_rod ~ ~12 ~ 8 3 8 0.02 30 force")
        if master_at and time.time() - t0 > master_at:
            name = random.choice(here)[0]
            mx, mz = random.uniform(-8, 8), random.uniform(-8, 8)
            drop(f"execute at {name} run", "cobblemon:master_ball", 1, mx, 20, mz)
            e.rcon(f"execute at {name} run particle minecraft:totem_of_undying ~{mx:.1f} ~18 ~{mz:.1f} 0.5 3 0.5 0.1 120 force")
            e.rcon("execute as @a at @s run playsound minecraft:block.amethyst_block.resonate master @s ~ ~ ~ 1 1.5")
            say(f"A MASTER BALL just dropped near {name}! Look for the golden sparkle!", "light_purple")
            master_at = None
        if time.time() - scored >= SCORE_EVERY:
            scored = time.time()
            scores(players, shown)
        time.sleep(1)
    e.rcon("weather clear")
    time.sleep(8)  # last items are still falling
    totals = scores(players, shown)
    best = max(totals.values()) if totals else 0
    leaders = [n for n in players if totals[n] == best and best > 0]
    board = ", ".join(f"{n} {totals[n]} pts" for n in sorted(players, key=lambda n: -totals[n]))
    if leaders:
        got = {}
        for n in leaders:
            got[n] = [g for item, c in BONUS for g in rewards.give(n, item, c)] + rewards.mixed(n, BONUS_TIER)
        e.rcon("title @a title " + json.dumps({"text": " and ".join(leaders) + " win!", "color": "gold",
                                                "bold": True}, ensure_ascii=False))
        e.rcon("execute as @a at @s run playsound minecraft:ui.toast.challenge_complete master @s")
        say(f"The rain is over! Results: {board}. {' and '.join(leaders)} grabbed the most and get a bonus: Rare "
            "Candy and a surprise bundle (balls, berries or an evolution item).", "gold")
        for n, items in got.items():
            say(f"You got: {label(items)}.", "gold", n)
    else:
        say(f"The rain is over! Nobody picked anything up. {board}.", "gray")
    time.sleep(15)
    for i in range(len(DROPS)):
        e.rcon(f"scoreboard objectives remove {stat_obj(i)}")
    e.rcon(f"scoreboard objectives remove {OBJ}")
    print("done", totals, flush=True)


if __name__ == "__main__":
    main()
