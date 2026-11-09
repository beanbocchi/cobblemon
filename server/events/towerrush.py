#!/usr/bin/env python3
"""Tower Rush: a timed event that pays extra for climbing the Battle Tower.

While it runs, every new personal best pays a bonus, floors 10/15/20/25/30 pay milestone prizes (once per player),
and a leaderboard goes out every two hours. When it ends, whoever climbed highest during the event gets the
champion prize (ties go to whoever got there first). Floors come from tower_best in life_state.json, which cvlife
updates as players clear floors. State is kept in towerrush_state.json, so a restart picks up where it left off.

Usage: towerrush.py [hours]   (default 48)
"""
import json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rewards  # noqa: E402

LIFE = os.path.join(HERE, "life_state.json")
STATE = os.path.join(HERE, "towerrush_state.json")
MILESTONES = {
    10: [("cobblemon:rare_candy", 5), ("cobblemon:ultra_ball", 10)],
    15: [("cobblemon:rare_candy", 8), ("obc:bottle_cap", 1)],
    20: [("cobblemon:exp_candy_xl", 5), ("obc:bottle_cap", 2), ("cobblemon:ability_capsule", 1)],
    25: [("cobblemon:exp_candy_xl", 8), ("obc:bottle_cap", 3)],
    30: [("cobblemon:master_ball", 1), ("obc:bottle_cap", 3)],
}
CHAMPION = [("cobblemon:master_ball", 1), ("obc:bottle_cap", 2), ("cobblemon:ability_capsule", 1)]


def rc(cmd):
    out = subprocess.run(["docker", "exec", "cobbleverse", "rcon-cli", cmd], capture_output=True, text=True).stdout
    return re.sub(r"\x1b\[[0-9;]*m", "", out)


def say(parts, to="@a"):
    rc(f"tellraw {to} " + json.dumps([{"text": "[Tower Rush] ", "color": "gold", "bold": True}] + parts))


def t(text, color="white", bold=False):
    return {"text": text, "color": color, "bold": bold}


def name_of(item):
    return item.split(":")[1].replace("_", " ").title()


def bests():
    try:
        return dict(json.load(open(LIFE, encoding="utf-8")).get("tower_best", {}))
    except (OSError, ValueError):
        return None


def online():
    m = re.search(r"online:(.*)$", rc("list").strip())
    return [n.split("]")[-1].strip() for n in m.group(1).split(",") if n.strip()] if m else []


def save(s):
    tmp = STATE + ".tmp"
    json.dump(s, open(tmp, "w", encoding="utf-8"), indent=1)
    os.replace(tmp, STATE)


def board(s):
    rows = sorted(s["climb"].items(), key=lambda kv: (-kv[1]["floor"], kv[1]["at"]))
    return [(n, v["floor"]) for n, v in rows if v["floor"] > s["start_best"].get(n, 0)]


def announce_board(s, final=False):
    rows = board(s)
    left = max(0, int((s["end"] - time.time()) // 60))
    head = "Final standings" if final else f"Standings ({left // 60}h {left % 60}m left)"
    if not rows:
        say([t(head + ": nobody has beaten their old record yet. Type ", "yellow"), t("!tower", "aqua"),
             t(" to climb!", "yellow")])
        return
    parts = [t(head + ": ", "yellow")]
    for i, (n, f) in enumerate(rows[:5]):
        parts += [t(f"{i + 1}. {n} ", "aqua" if i else "gold", bold=i == 0), t(f"floor {f}", "white"),
                  t("   ", "white")]
    say(parts)


def start(hours):
    b = bests()
    if b is None:
        sys.exit("cannot read life_state.json")
    s = {"start": time.time(), "end": time.time() + hours * 3600, "start_best": b, "seen": dict(b),
         "climb": {}, "paid": {}, "last_board": time.time(), "done": False}
    save(s)
    rc("title @a times 10 80 20")
    rc("title @a title " + json.dumps(t("TOWER RUSH", "gold", True)))
    rc("title @a subtitle " + json.dumps(t(f"{hours} hours of bonus prizes in the Battle Tower", "yellow")))
    rc("execute as @a at @s run playsound minecraft:ui.toast.challenge_complete master @s")
    say([t(f"For the next {hours} hours, every new personal best in the Battle Tower pays a bonus. ", "white"),
         t("Floors 10, 15, 20, 25 and 30 ", "aqua"), t("pay big milestone prizes (Bottle Caps, an Ability Capsule, "
                                                       "even a Master Ball at 30). ", "white"),
         t("The highest climber at the end wins a Master Ball. ", "gold"), t("Type ", "white"), t("!tower", "aqua"),
         t(" to start.", "white")])
    return s


def tick(s):
    b = bests()
    if b is None:
        return
    for n, f in b.items():
        old = s["seen"].get(n, 0)
        if f <= old:
            continue
        s["seen"][n] = f
        if f > s["start_best"].get(n, 0):
            s["climb"][n] = {"floor": f, "at": time.time()}
        pay = 50 * f
        rc(f"cobbledollars give {n} {pay}")
        got = []
        for m, items in MILESTONES.items():
            if old < m <= f and str(m) not in s["paid"].setdefault(n, []):
                s["paid"][n].append(str(m))
                for item, c in items:
                    got += rewards.give(n, item, c)
        if got:
            what = ", ".join(f"{c} {name_of(i)}" for i, c in got)
            say([t(f"{n} reached floor {f}! ", "gold", True), t(f"Milestone prize: {what}, plus ${pay}.", "yellow")])
            rc(f"execute as {n} at @s run playsound minecraft:entity.player.levelup master @s")
        else:
            say([t(f"{n} set a new record: floor {f}. ", "aqua"), t(f"Bonus ${pay}.", "yellow")])
    save(s)


def finish(s):
    announce_board(s, final=True)
    rows = board(s)
    if rows:
        n, f = rows[0]
        for item, c in CHAMPION:
            rewards.give(n, item, c)
        rc("title @a times 10 80 20")
        rc("title @a title " + json.dumps(t(f"{n} wins Tower Rush!", "gold", True)))
        rc("title @a subtitle " + json.dumps(t(f"Highest climb: floor {f}", "yellow")))
        say([t(f"{n} is the Tower Rush champion with floor {f}! ", "gold", True),
             t("Prize: " + ", ".join(f"{c} {name_of(i)}" for i, c in CHAMPION) + ".", "yellow")])
    else:
        say([t("Tower Rush is over. Nobody beat their old record this time.", "yellow")])
    s["done"] = True
    save(s)


def main():
    hours = float(sys.argv[1]) if len(sys.argv) > 1 else 48
    s = json.load(open(STATE)) if os.path.exists(STATE) else None
    if not s or s.get("done"):
        s = start(hours)
    seen_online = set(online())
    while time.time() < s["end"]:
        time.sleep(20)
        tick(s)
        now = set(online())
        for n in now - seen_online:   # remind people who join while it runs
            left = int((s["end"] - time.time()) // 3600)
            say([t(f"Tower Rush is on for about {left} more hours: new records in the Battle Tower pay bonuses. "
                   "Type ", "yellow"), t("!tower", "aqua"), t(" to climb.", "yellow")], to=n)
        seen_online = now
        if time.time() - s["last_board"] > 7200 and now:
            s["last_board"] = time.time()
            save(s)
            announce_board(s)
    finish(s)


if __name__ == "__main__":
    main()
