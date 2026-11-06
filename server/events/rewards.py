"""Shared reward giving for every COBBLEVERSE script, with a daily Rare Candy cap.

Each player can get at most CAP Rare Candy a day (Asia/Ho_Chi_Minh) from all scripts together; an Exp Candy XL
counts as one. Anything over the cap is swapped for balls, berries or an evolution item, so rewards still feel
like rewards without making gyms trivial. The ledger is candy_ledger.json next to this file, guarded by a file lock
because several scripts can give at the same time.

    import rewards
    rewards.give("huylba", "cobblemon:rare_candy", 10)   # gives up to the cap, swaps the rest, returns a list
    rewards.mixed("huylba", tier=2)                     # a random non-candy bundle for event prizes
"""
import datetime
import fcntl
import json
import os
import random
import re
import subprocess
import zoneinfo

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(HERE, "candy_ledger.json")
CAP = 30
TZ = zoneinfo.ZoneInfo("Asia/Ho_Chi_Minh")
CANDY = {"cobblemon:rare_candy": 1, "cobblemon:exp_candy_xl": 1}
BALLS = ["cobblemon:great_ball", "cobblemon:ultra_ball", "cobblemon:quick_ball", "cobblemon:dusk_ball",
         "cobblemon:timer_ball", "cobblemon:net_ball", "cobblemon:dive_ball", "cobblemon:luxury_ball"]
BERRIES = ["cobblemon:sitrus_berry", "cobblemon:lum_berry", "cobblemon:oran_berry", "cobblemon:leppa_berry",
           "cobblemon:pomeg_berry", "cobblemon:kelpsy_berry", "cobblemon:qualot_berry", "cobblemon:hondew_berry",
           "cobblemon:grepa_berry", "cobblemon:tamato_berry"]
EVOLUTION = ["cobblemon:fire_stone", "cobblemon:water_stone", "cobblemon:thunder_stone", "cobblemon:leaf_stone",
             "cobblemon:moon_stone", "cobblemon:sun_stone", "cobblemon:ice_stone", "cobblemon:shiny_stone",
             "cobblemon:dusk_stone", "cobblemon:dawn_stone", "cobblemon:link_cable", "cobblemon:metal_coat",
             "cobblemon:kings_rock", "cobblemon:dragon_scale", "cobblemon:upgrade", "cobblemon:razor_claw",
             "cobblemon:oval_stone", "cobblemon:protector", "cobblemon:electirizer", "cobblemon:magmarizer"]


def _rc(cmd):
    out = subprocess.run(["docker", "exec", "cobbleverse", "rcon-cli", cmd], capture_output=True, text=True,
                         timeout=30).stdout
    return re.sub(r"\x1b\[[0-9;]*m", "", out).strip()


def _today():
    return datetime.datetime.now(TZ).strftime("%Y-%m-%d")


def _take_allowance(name, want):
    """Reserve up to `want` candy for today and return how many fit under the cap."""
    with open(LEDGER + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = json.load(open(LEDGER, encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        day = data.setdefault(_today(), {})
        data = {k: v for k, v in data.items() if k >= _today()}  # keep only today
        data[_today()] = day
        used = day.get(name, 0)
        ok = max(0, min(want, CAP - used))
        day[name] = used + ok
        tmp = LEDGER + ".tmp"
        json.dump(data, open(tmp, "w", encoding="utf-8"))
        os.replace(tmp, LEDGER)
        return ok


def used_today(name):
    try:
        return json.load(open(LEDGER, encoding="utf-8")).get(_today(), {}).get(name, 0)
    except (OSError, ValueError):
        return 0


def substitute(units):
    """Non-candy items worth about `units` candy: balls first, then berries, an evolution item at 5+."""
    out = []
    if units >= 5:
        out.append((random.choice(EVOLUTION), 1))
        units -= 5
    if units > 0:
        out.append((random.choice(BALLS), max(2, units * 2)))
    if units >= 3:
        out.append((random.choice(BERRIES), units))
    return out


def mixed(name, tier=1, announce=True):
    """A random non-candy prize bundle (tier 1-3) for events, so prizes vary between balls, berries and items."""
    kind = random.choice(["balls", "berries", "evolution"])
    if kind == "balls":
        items = [(random.choice(BALLS), 6 * tier)]
    elif kind == "berries":
        items = [(random.choice(BERRIES), 3 * tier), (random.choice(BERRIES), 3 * tier)]
    else:
        items = [(random.choice(EVOLUTION), tier)]
    for item, c in items:
        _rc(f"give {name} {item} {c}")
    return items


def give(name, item, count, announce=True):
    """Give an item; candy goes through the daily cap and the excess is swapped. Returns what was given."""
    if item not in CANDY:
        _rc(f"give {name} {item} {count}")
        return [(item, count)]
    units = count * CANDY[item]
    ok = _take_allowance(name, units)
    given = []
    if ok:
        _rc(f"give {name} {item} {ok // CANDY[item]}")
        given.append((item, ok // CANDY[item]))
    over = units - ok
    if over > 0:
        swap = substitute(over)
        for it, c in swap:
            _rc(f"give {name} {it} {c}")
        given += swap
        if announce:
            what = ", ".join(f"{c} {it.split(':')[1].replace('_', ' ').title()}" for it, c in swap)
            _rc(f"tellraw {name} " + json.dumps([
                {"text": "[Rewards] ", "color": "gold", "bold": True},
                {"text": f"You reached today's limit of {CAP} Rare Candy, so the rest became: {what}.",
                 "color": "yellow", "bold": False}]))
    return given
