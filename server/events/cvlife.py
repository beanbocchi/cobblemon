#!/usr/bin/env python3
"""World-life daemon for the COBBLEVERSE server.

Features: daily quest, weekly season, gym-win celebrations and next-gym guide, shared Pokedex milestones, a village
chest that levels the village, treasure map fragments, landmarks named by their first finder, a roaming legendary,
weather and weekend festivals, an evening journal, titles over players' heads, self-chosen challenges, a daily
bounty, giant Pokemon, a mystery trader, Team Rocket raids, a weekly story with a Sunday boss, challengers for a
runaway leader, and wonder trade.

Player commands come from the fix mod (WorldLifeCommands logs "[cvlife-cmd] <player> <cmd> [args]") or from chat
with "!" (!world, !home, !trade, !challenge, !landmark). The daemon follows `docker logs -f cobbleverse` and sends
rcon commands only when something happens or on a timer, so the console does not fill with RCON lines. Party, PC,
Pokedex and advancement data come from the saved files. Anything it spawns for an event keeps its chunk force-loaded
until the event ends, because `execute if entity` cannot see unloaded entities and would count them as beaten.
State: life_state.json; settings: life.json; gym route: gyms.json.
"""
import datetime
import gzip
import json
import math
import os
import random
import re
import subprocess
import sys
import threading
import time
import unicodedata
import zoneinfo

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.expanduser("~/cobblemon/server/data")
STATE_FILE = os.path.join(HERE, "life_state.json")
CONFIG = json.load(open(os.path.join(HERE, "life.json"), encoding="utf-8"))
INFO = json.load(open(os.path.join(HERE, "species_info.json"), encoding="utf-8"))
GYMS = json.load(open(os.path.join(HERE, "gyms.json"), encoding="utf-8"))
ROCKETS = json.load(open(os.path.join(HERE, "rocket_trainers.json"), encoding="utf-8"))
SPAWNS = json.load(open(os.path.join(HERE, "spawn_hints.json"), encoding="utf-8"))
TZ = zoneinfo.ZoneInfo("Asia/Ho_Chi_Minh")
sys.path.insert(0, os.path.expanduser("~/cvscan"))
import anvil  # noqa: E402
sys.path.insert(0, HERE)
import rewards  # noqa: E402

TYPES = {"normal": "Normal", "fire": "Fire", "water": "Water", "grass": "Grass", "electric": "Electric", "ice": "Ice",
         "fighting": "Fighting", "poison": "Poison", "ground": "Ground", "flying": "Flying", "psychic": "Psychic",
         "bug": "Bug", "rock": "Rock", "ghost": "Ghost", "dragon": "Dragon", "dark": "Dark", "steel": "Steel",
         "fairy": "Fairy"}
DIRS = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"]
NATURES = ["hardy", "lonely", "brave", "adamant", "naughty", "bold", "docile", "relaxed", "impish", "lax", "timid",
           "hasty", "serious", "jolly", "naive", "modest", "mild", "quiet", "bashful", "rash", "calm", "gentle",
           "sassy", "careful", "quirky"]
EARLY = ["pidgey", "rattata", "caterpie", "weedle", "zubat", "oddish", "bellsprout", "psyduck", "poliwag", "geodude",
         "magikarp", "growlithe", "abra", "machop", "ponyta", "slowpoke", "doduo", "seel", "shellder", "krabby",
         "sentret", "hoothoot", "ledyba", "spinarak", "mareep", "wooper", "zigzagoon", "wurmple", "lotad", "seedot",
         "taillow", "wingull", "ralts", "starly", "bidoof", "shinx", "buneary", "lillipup", "pidove", "fletchling"]
REGION = {"overworld": "world/region", "the_nether": "world/DIM-1/region", "the_end": "world/DIM1/region"}
WP_SET = {"overworld": "Internal-overworld-waypoints", "the_nether": "Internal-the-nether-waypoints",
          "the_end": "Internal-the-end-waypoints"}
DIM_NAME = {"overworld": "the Overworld", "the_nether": "the Nether", "the_end": "The End"}
FRAG = "minecraft:paper[minecraft:custom_data={cvmap:1b}]"
PREFIX = re.compile(r"^(\[[^\]]*\] )+")
LINE = re.compile(r"^\[\d\d:\d\d:\d\d\] \[[^\]]+\]: (.*)$")
LOCK = threading.RLock()
ONLINE = set()


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def rc(cmd):
    if len(cmd.encode()) > 1000:
        # rcon-cli hangs until the timeout on a command over about 1024 bytes (measured 2026-11-05), so refuse it.
        log("rc too long, not sent:", len(cmd.encode()), cmd[:80])
        return ""
    try:
        out = subprocess.run(["docker", "exec", "cobbleverse", "rcon-cli", cmd], capture_output=True, text=True,
                             timeout=30).stdout
    except subprocess.TimeoutExpired:
        return ""
    return re.sub(r"\x1b\[[0-9;]*m", "", out).strip()


def t(text, color="white", **kw):
    d = {"text": text, "color": color, "bold": False}
    d.update(kw)
    return d


def tell(target, parts, prefix="[COBBLEVERSE] ", color="gold"):
    if target == "@a":
        log("broadcast", prefix.strip(), "".join(p.get("text", "") for p in parts)[:70])
    rc(f"tellraw {target} " + json.dumps([{"text": prefix, "color": color, "bold": True}] + parts, ensure_ascii=False))


def bar(target, parts):
    """A short line on the action bar instead of chat, for minor news."""
    rc(f"title {target} actionbar " + json.dumps(parts if isinstance(parts, list) else [parts], ensure_ascii=False))


def waypoint(target, name, letter, x, y, z, color=11, dim="overworld"):
    """Add a Xaero's Minimap waypoint for the target. Messages say "waypoint added" instead of printing coordinates."""
    wp = re.sub(r"[^A-Za-z0-9 .]", "", strip_accents(name))[:32] or "Waypoint"
    rc(f"tellraw {target} " + json.dumps({"text": f"xaero-waypoint:{wp}:{letter[:2]}:{int(x)}:{int(y)}:{int(z)}:{color}:"
                                                  f"false:0:{WP_SET[dim]}"}))


def snd(target, sound, pitch=1.0):
    rc(f"execute as {target} at @s run playsound {sound} master @s ~ ~ ~ 1 {pitch}")


def snbt_text(obj):
    """A JSON text component as a single-quoted SNBT string."""
    return "'" + json.dumps(obj, ensure_ascii=False).replace("\\", "\\\\").replace("'", "\\'") + "'"


def C(cmd):
    """How a command is written in messages: /world once the fix mod has the commands, !world before."""
    slash = CONFIG.get("slash_commands") and cmd.split()[0] not in CONFIG.get("chat_only_commands", [])
    return ("/" if slash else "!") + cmd


def strip_accents(s):
    s = unicodedata.normalize("NFD", s.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def fireworks(name, n=4):
    colors = [16766720, 16711680, 65280, 33023, 16711935, 16777215]
    for i in range(n):
        dx, dz = random.choice([-7, -5, 5, 7]), random.choice([-7, -5, 5, 7])
        rc(f"execute at {name} run summon minecraft:firework_rocket ~{dx} ~1 ~{dz} "
           f"{{LifeTime:{25 + i * 2},FireworksItem:{{id:\"minecraft:firework_rocket\",count:1,components:{{"
           f"\"minecraft:fireworks\":{{explosions:[{{shape:\"{random.choice(['large_ball', 'star', 'burst'])}\","
           f"colors:[I;{random.choice(colors)},{random.choice(colors)}],has_twinkle:true,has_trail:true}}]}}}}}}}}")
        time.sleep(0.3)


def species_name(sp):
    return INFO.get(sp, {}).get("n", sp.replace("_", " ").title())


def item_name(item):
    return item.split(":")[-1].replace("_", " ").title()


# ---------- state ----------

def load_state():
    try:
        return json.load(open(STATE_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save():
    tmp = STATE_FILE + ".tmp"
    json.dump(S, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_FILE)


S = load_state()
for k, v in {"seen": [], "pending": {}, "dex_milestone": 0, "village_level": 0, "landmarks": {}, "roamer": None,
             "challenges": {}, "titles": {}, "day": {}, "journal_done": "", "raid_done": "", "festival_note": "",
             "events": {}, "trades": {}, "news": [], "last_seen": {}, "goals": {}, "tips": {}, "fly": {},
             "fly_spots": {}, "tower": {}, "tower_best": {}, "tower_return": {}, "tower_resume": {}, "outbreak": None,
             "grotto": None, "legend": {}, "legend_spots": {}, "legend_active": {},
             "finder": {}, "finder_given": [], "requests": {}, "requests_day": {}, "fishing": None, "expedition": None,
             "partner_km": {}, "partner_last": {}}.items():
    S.setdefault(k, v)
# names saved while title prefixes leaked into them ("[Kẻ lạc đường] huylba")
S["seen"] = sorted({PREFIX.sub("", n) for n in S["seen"]})
for _name in list(S["pending"]):
    _clean = PREFIX.sub("", _name)
    if _clean != _name:
        S["pending"].setdefault(_clean, []).extend(S["pending"].pop(_name))


def now():
    return datetime.datetime.now(TZ)


def today():
    return now().strftime("%Y-%m-%d")


def week_key():
    y, w, _ = now().isocalendar()
    return f"{y}-W{w:02d}"


def give(name, item, count):
    """Rewards go through rewards.py (daily Rare Candy cap); offline players get them on their next join."""
    if name in ONLINE:
        rewards.give(name, item, count)
    else:
        S["pending"].setdefault(name, []).append([item, count])
        save()


def give_all_seen(items):
    for n in S["seen"]:
        for item, c in items:
            give(n, item, c)


def online_from_list():
    # rcon replies can arrive mixed with another command's output, so read only the "players online:" line and keep
    # only strings that are valid player names.
    m = re.search(r"players online:(.*)", rc("list"))
    names = {PREFIX.sub("", n.strip()) for n in m.group(1).split(",")} if m else set()
    return {n for n in names if re.fullmatch(r"[A-Za-z0-9_]{1,16}", n)}


# ---------- player data ----------

def uuid_of(name):
    try:
        for c in json.load(open(os.path.join(DATA, "usercache.json"))):
            if c["name"].lower() == name.lower():
                return c["uuid"]
    except (OSError, ValueError):
        pass
    return None


def read_nbt(path):
    raw = open(path, "rb").read()
    try:
        raw = gzip.decompress(raw)
    except OSError:
        pass
    return anvil.nbt(raw)


def party(name):
    """{slot index 0-5: Pokemon NBT} from the saved party file (up to ~30 s behind the live party)."""
    u = uuid_of(name)
    if not u:
        return {}
    try:
        d = read_nbt(os.path.join(DATA, "world/pokemon/playerpartystore", u[:2], u + ".dat"))
    except Exception:
        return {}
    return {int(k[4:]): v for k, v in d.items() if k.startswith("Slot") and isinstance(v, dict)}


def mons(name, party_only=False):
    """Every saved Pokemon NBT of the player (party and PC)."""
    u = uuid_of(name)
    out = []
    if not u:
        return out

    def walk(d):
        if isinstance(d, dict):
            if "Species" in d:
                out.append(d)
                return
            for v in d.values():
                walk(v)
        elif isinstance(d, list):
            for v in d:
                walk(v)
    for store in ("playerpartystore",) + (() if party_only else ("pcstore",)):
        p = os.path.join(DATA, "world/pokemon", store, u[:2], u + ".dat")
        if os.path.exists(p):
            try:
                walk(read_nbt(p))
            except Exception as e:
                log("read", p, repr(e))
    return out


def sp_of(m):
    return str(m.get("Species", "")).split(":")[-1]


def dex_set(name):
    u = uuid_of(name)
    if not u:
        return set()
    p = os.path.join(DATA, "world/pokedex", u[:2], u + ".nbt")
    if not os.path.exists(p):
        return set()
    try:
        recs = read_nbt(p).get("speciesRecords", {})
    except Exception:
        return set()
    return {sp.split(":")[-1] for sp, r in recs.items()
            if any(f.get("knowledge") in ("OWNED", "CAUGHT") for f in r.get("formRecords", {}).values())}


def seen_species():
    out = set()
    for n in S["seen"]:
        u = uuid_of(n)
        p = u and os.path.join(DATA, "world/pokedex", u[:2], u + ".nbt")
        if p and os.path.exists(p):
            try:
                out |= {sp.split(":")[-1] for sp in read_nbt(p).get("speciesRecords", {})}
            except Exception:
                pass
    return out


def advancements(name):
    u = uuid_of(name)
    try:
        adv = json.load(open(os.path.join(DATA, "world/advancements", u + ".json"), encoding="utf-8")) if u else {}
    except (OSError, ValueError):
        adv = {}
    # The advancement file is written on save, minutes after a win; count wins seen in the log as done. Entries are
    # the log's advancement keys ("advancements.cobbleverse.kanto.defeat_ltsurge"), matched on region and trainer,
    # because names repeat across regions (two Elite Four Brunos).
    for key in S.get("beaten_adv", {}).get(name, []):
        m = re.search(r"\.([a-z0-9]+)\.(defeat_[a-z0-9_]+)$", key)
        for g in GYMS:
            if m and g["adv"].endswith(f"/{m.group(1)}/{m.group(2)}") and not (adv.get(g["adv"]) or {}).get("done"):
                adv[g["adv"]] = {"done": True}
    return adv


def travelled(name):
    total = 0
    for obj in ("cvwalk", "cvsprint"):
        m = re.search(r"has (\d+) \[", rc(f"scoreboard players get {name} {obj}"))
        total += int(m.group(1)) if m else 0
    return total // 100


LAST_SAVE = [0.0]


def fresh_save(force=False):
    """save-all at most every 60 s on demand and every 300 s otherwise."""
    if time.time() - LAST_SAVE[0] > (60 if force else 300):
        rc("save-all")
        time.sleep(3)
        LAST_SAVE[0] = time.time()


def snapshot(name):
    ms = mons(name)
    sp = [sp_of(m) for m in ms]
    return {"catch": len(ms), "types": {ty: sum(1 for s in sp if ty in INFO.get(s, {}).get("t", [])) for ty in TYPES},
            "dex": sorted(dex_set(name)), "walk": travelled(name), "shiny": sum(1 for m in ms if m.get("Shiny")),
            "magikarp": sp.count("magikarp"), "legend": sum(1 for s in sp if INFO.get(s, {}).get("l")),
            "species": sp, "natures": [f"{sp_of(m)}:{str(m.get('Nature', '')).split(':')[-1]}" for m in ms]}


def party_top_level(name):
    lv = [v.get("Level", 0) for v in party(name).values()]
    return max(lv) if lv else None


def player_pos(name):
    # rcon replies can carry another client's answer when several scripts share the console. Only trust a reply
    # that names this player; a wrong position once ended huylba's Battle Tower run as "left the arena" (2026-11-09).
    dim = rc(f"data get entity {name} Dimension")
    out = rc(f"data get entity {name} Pos")
    if f"{name} has the following entity data" not in out or f"{name} has the following entity data" not in dim:
        return None
    p = re.findall(r"(-?[\d.]+)d", out.split(f"{name} has the following entity data", 1)[1])
    if len(p) < 3:
        return None
    d = "overworld" if "overworld" in dim else "the_end" if "the_end" in dim else "the_nether"
    return d, *map(float, p[:3])


def bearing(fx, fz, x, z):
    ang = (math.degrees(math.atan2(x - fx, -(z - fz))) + 360) % 360
    return DIRS[int((ang + 22.5) // 45) % 8], int(math.hypot(x - fx, z - fz))


# ---------- chunk holds and despawning ----------

def hold(x, z):
    rc(f"execute in minecraft:overworld run forceload add {int(x) - 16} {int(z) - 16} {int(x) + 16} {int(z) + 16}")


def release(x, z):
    rc(f"execute in minecraft:overworld run forceload remove {int(x) - 16} {int(z) - 16} {int(x) + 16} {int(z) + 16}")


def ground_near(x, z, rmin, rmax):
    """A standable Overworld spot rmin..rmax from (x, z), with its 3x3 chunks force-loaded (call release())."""
    for _ in range(6):
        a = random.uniform(0, 2 * math.pi)
        r = random.uniform(rmin, rmax)
        gx, gz = int(x + math.cos(a) * r), int(z + math.sin(a) * r)
        hold(gx, gz)
        time.sleep(3)
        rc(f"execute in minecraft:overworld run summon minecraft:marker {gx} 300 {gz} {{Tags:[\"cvlm\"]}}")
        out = rc(f"execute in minecraft:overworld run spreadplayers {gx} {gz} 0 2 false @e[tag=cvlm]")
        p = re.findall(r"(-?[\d.]+)d", rc("execute as @e[tag=cvlm] run data get entity @s Pos"))
        rc("kill @e[tag=cvlm]")
        if "Spread" in out and len(p) >= 3 and float(p[1]) < 299:
            return float(p[0]), float(p[1]), float(p[2]), (gx, gz)
        release(gx, gz)
    return None


def spawn_tagged(sp, props, x, y, z, tag, name_component=None, glow=True):
    rc(f"execute in minecraft:overworld positioned {x} {y + 1} {z} run spawnpokemon {sp} {props}")
    rc(f"execute in minecraft:overworld positioned {x} {y + 1} {z} run tag @e[type=cobblemon:pokemon,distance=..4,"
       f"sort=nearest,limit=1,tag=!{tag},nbt={{Pokemon:{{Species:\"cobblemon:{sp}\"}}}}] add {tag}")
    extra = (f",CustomName:{snbt_text(name_component)},CustomNameVisible:1b" if name_component else "") + \
            (",Glowing:1b" if glow else "")
    rc(f"execute as @e[tag={tag}] run data merge entity @s {{PersistenceRequired:1b{extra}}}")
    return "passed" in rc(f"execute if entity @e[tag={tag}]")


def alive(tag):
    return "passed" in rc(f"execute if entity @e[tag={tag}]")


def despawn(tag, chunk=None):
    """Remove a tagged event entity unless a player is next to it (likely battling). True when it is gone."""
    rc(f"execute as @e[tag={tag}] at @s unless entity @a[distance=..16] run tp @s ~ -200 ~")
    rc(f"execute as @e[tag={tag}] at @s unless entity @a[distance=..16] run kill @s")
    gone = not alive(tag)
    if gone and chunk:
        release(*chunk)
    return gone


def start_event(key, tag, chunk, minutes, **extra):
    S["events"][key] = {"tag": tag, "chunk": list(chunk) if chunk else None, "until": time.time() + minutes * 60, **extra}
    save()


def end_event(key):
    ev = S["events"].pop(key, None)
    save()
    return ev


# ---------- daily quest ----------

def make_quest(date):
    r = random.Random(date)
    kind = r.choice(["catch", "type", "dex", "walk"])
    if kind == "catch":
        return {"kind": kind, "n": 8, "text": "Catch 8 Pokémon"}
    if kind == "type":
        ty = r.choice(list(TYPES))
        return {"kind": kind, "type": ty, "n": 3, "text": f"Catch 3 {TYPES[ty]}-type Pokémon"}
    if kind == "dex":
        return {"kind": kind, "n": 4, "text": "Register 4 new species in your Pokédex"}
    return {"kind": kind, "n": 2000, "text": "Travel 2000 blocks on foot"}


def quest_prize(date):
    """Today's quest prize: Rare Candy on some days, balls, berries or an evolution item on others."""
    r = random.Random("prize" + date)
    kind = r.choice(["candy", "balls", "berries", "evolution"])
    if kind == "candy":
        return [["cobblemon:rare_candy", 5]]
    if kind == "balls":
        return [[r.choice(rewards.BALLS), 10]]
    if kind == "berries":
        return [[r.choice(rewards.BERRIES), 4], [r.choice(rewards.BERRIES), 4]]
    return [[r.choice(rewards.EVOLUTION), 1], ["cobblemon:rare_candy", 2]]


def prize_text(items):
    return ", ".join(f"{c} {item_name(i)}" for i, c in items)


def quest():
    if S.get("quest", {}).get("date") != today():
        S["quest"] = {"date": today(), **make_quest(today()), "base": {}, "done": []}
        S["day"] = {"date": today(), "base": {}, "wins": {}}
        save()
        if ONLINE:
            tell("@a", [t("Today's quest: ", "yellow"), t(S["quest"]["text"], "aqua"),
                        t(f". Reward: {prize_text(quest_prize(today()))}. Progress in {C('world')}.", "yellow")])
    return S["quest"]


def quest_progress(name, snap):
    q = quest()
    b = q["base"].get(name)
    if b is None:
        return 0
    if q["kind"] == "catch":
        return max(0, snap["catch"] - b["catch"])
    if q["kind"] == "type":
        return max(0, snap["types"].get(q["type"], 0) - b["types"].get(q["type"], 0))
    if q["kind"] == "dex":
        return len(set(snap["dex"]) - set(b["dex"]))
    return max(0, snap["walk"] - b["walk"])


# ---------- season ----------

def season():
    if S.get("season", {}).get("week") != week_key():
        old = S.get("season")
        if old:
            finish_season(old)
        S["season"] = {"week": week_key(), "base": {}, "points": {}, "last_dex": {}}
        save()
    return S["season"]


def scores(se):
    names = set(se["points"]) | set(se["base"])
    return {n: se["points"].get(n, 0) + max(0, se["last_dex"].get(n, se["base"].get(n, 0)) - se["base"].get(n, 0))
            for n in names}


def finish_season(old):
    ranked = [kv for kv in sorted(scores(old).items(), key=lambda kv: -kv[1]) if kv[1] > 0]
    if not ranked:
        return
    lines = []
    for i, (n, p) in enumerate(ranked[:len(CONFIG["season_rewards"])]):
        for item, c in CONFIG["season_rewards"][i]:
            give(n, item, c)
        lines.append(f"{i + 1}. {n} ({p} pts)")
    tell("@a", [t(f"Season {old['week']} is over! ", "gold", bold=True), t(" | ".join(lines), "yellow"),
                t(". Prizes delivered, a new season starts now.", "yellow")])


def add_points(name, n):
    se = season()
    se["points"][name] = se["points"].get(name, 0) + n
    save()


# ---------- shared Pokedex ----------

def shared_dex():
    allsp = set()
    for n in S["seen"]:
        allsp |= dex_set(n)
    for need, items in CONFIG["shared_dex_milestones"]:
        if len(allsp) >= need > S["dex_milestone"]:
            S["dex_milestone"] = need
            save()
            give_all_seen(items)
            what = ", ".join(f"{c} {item_name(i)}" for i, c in items)
            news(f"The shared Pokédex reached {need} species and everyone got a gift")
            tell("@a", [t(f"The server's shared Pokédex reached {need} species! ", "gold", bold=True),
                        t(f"Everyone gets: {what}.", "yellow")])
            rc("execute as @a at @s run playsound minecraft:ui.toast.challenge_complete master @s")
    return allsp


# ---------- village chest ----------

def chest_items():
    total = {}
    for x, y, z in CONFIG.get("village_chest") or []:
        out = rc(f"execute in minecraft:overworld run data get block {x} {y} {z} Items")
        # one entry per item: {count: 5, Slot: 0b, id: "minecraft:x", components: {...}}
        for entry in re.split(r"\}, \{(?=count|Slot|id)", out):
            m_id = re.search(r'id: "([^"]+)"', entry)
            m_c = re.search(r"count: (\d+)", entry)
            if m_id and m_c:
                total[m_id.group(1)] = total.get(m_id.group(1), 0) + int(m_c.group(1))
    total["balls"] = sum(c for i, c in total.items() if i.startswith("cobblemon:") and i.endswith("_ball"))
    return total


def chest_entries():
    """(chest x, y, z, slot, count, item id) for every stack in the village chest."""
    out_list = []
    for x, y, z in CONFIG.get("village_chest") or []:
        out = rc(f"execute in minecraft:overworld run data get block {x} {y} {z} Items")
        for entry in re.split(r"\}, \{(?=count|Slot|id)", out):
            m_s, m_c, m_i = re.search(r"Slot: (\d+)b", entry), re.search(r"count: (\d+)", entry), re.search(r'id: "([^"]+)"', entry)
            if m_s and m_c and m_i:
                out_list.append((x, y, z, int(m_s.group(1)), int(m_c.group(1)), m_i.group(1)))
    return out_list


def consume(need):
    """Take the items a village level costs out of the chest, so they can't be lent and taken back."""
    left = dict(need)
    plan = []
    for x, y, z, slot, cnt, item in chest_entries():
        key = "balls" if item.startswith("cobblemon:") and item.endswith("_ball") and "balls" in left else item
        if left.get(key, 0) > 0:
            take = min(cnt, left[key])
            left[key] -= take
            plan.append((x, y, z, slot, take))
    if any(v > 0 for v in left.values()):
        return False  # someone took items out between the count and now
    for x, y, z, slot, take in plan:
        rc(f"execute in minecraft:overworld run item modify block {x} {y} {z} container.{slot} "
           + json.dumps({"function": "minecraft:set_count", "count": -take, "add": True}))
    return True


def village_check():
    lv = S["village_level"]
    levels = CONFIG["village_levels"]
    if lv >= len(levels):
        return
    have = chest_items()
    if all(have.get(k, 0) >= v for k, v in levels[lv]["need"].items()):
        if not consume(levels[lv]["need"]):
            return
        S["village_level"] = lv + 1
        save()
        news(f"The village reached level {lv + 1}")
        tell("@a", [t(f"THE VILLAGE REACHED LEVEL {lv + 1}! ", "gold", bold=True),
                    t(f"Unlocked: {levels[lv]['unlock']}.", "yellow")])
        rc("execute as @a at @s run playsound minecraft:ui.toast.challenge_complete master @s")
        st = CONFIG.get("station")
        if lv + 1 == 1 and st:
            subprocess.run(["python3", os.path.join(HERE, "station.py"), str(st[0]), str(st[1]), str(st[2]), "extra"],
                           capture_output=True)
        building = {1: "mart", 2: "daycare", 3: "court"}.get(lv + 1)
        if building and st:
            subprocess.run(["python3", os.path.join(HERE, "village_build.py"), str(st[0]), str(st[1]), str(st[2]),
                            building], capture_output=True)
        if lv + 1 == 3:
            give_all_seen([["cobblemon:rare_candy", 10]])


# ---------- gym route ----------

def next_gym(name):
    done = advancements(name)
    return next((g for g in GYMS if not (done.get(g["adv"]) or {}).get("done")), None)


def box_placed(b, dim):
    """False when a structure's chunks are generated but its box holds only air: a start that never placed its
    pieces (seen with a Lt. Surge gym at 4666 171 2736). Boxes in chunks nobody has generated yet count as placed."""
    sys.path.insert(0, os.path.expanduser("~/cvscan"))
    try:
        from anvil import World
    except ImportError:
        return True
    w, seen = World(os.path.join(DATA, REGION[dim])), False
    for x in range(b[0], b[3] + 1, 3):
        for z in range(b[2], b[5] + 1, 3):
            for y in range(b[1], b[4] + 1, 3):
                c = w.chunk(x >> 4, z >> 4)
                if not c or "full" not in str(c.get("Status", "")):
                    continue  # not generated yet, or only a proto-chunk with the structure start
                bl = w.block(x, y, z)
                if bl is None:
                    continue
                seen = True
                if not bl.endswith("air"):
                    return True
    return not seen


def gym_boxes(g):
    cache = os.path.expanduser(f"~/cvscan/gyms_{g['dim']}.json")
    try:
        out = subprocess.run(["python3", "-I", os.path.expanduser("~/cvscan/structindex.py"),
                              os.path.join(DATA, REGION[g["dim"]]), cache, "^" + re.escape(g["struct"]) + "$"],
                             capture_output=True, text=True, timeout=120).stdout
    except subprocess.TimeoutExpired:
        return []
    boxes = []
    for line in out.splitlines():
        p = line.split()
        if len(p) == 7 and p[0] == g["struct"]:
            boxes.append(tuple(map(int, p[1:])))
    return [b for b in boxes if box_placed(b, g["dim"])]


def guide(name, intro=""):
    g = next_gym(name)
    if not g:
        tell(name, [t(intro + "You have beaten every gym and league there is. Legendary!", "gold")],
             prefix="[Gym] ", color="gold")
        return
    head = [t(intro, "green"), t(f"Next: {g['name']}", "gold", bold=True), t(f" ({g['type']} type)", "yellow")]
    if g["counters"]:
        head.append(t(f", bring {g['counters']}", "white"))
    boxes = cached_boxes(g)
    pos = player_pos(name)
    if pos and boxes and pos[0] == g["dim"]:
        _, px, py, pz = pos
        b = min(boxes, key=lambda b: math.hypot((b[0] + b[3]) / 2 - px, (b[2] + b[5]) / 2 - pz))
        x, y, z = (b[0] + b[3]) // 2, b[1] + 2, (b[2] + b[5]) // 2
        d, dist = bearing(px, pz, x, z)
        tell(name, head + [t(f". The nearest is about {dist} m to the {d}; waypoint added.", "white")],
             prefix="[Gym] ", color="gold")
        waypoint(name, g["name"], "G", x, y, z, 11, g["dim"])
    elif boxes:
        tell(name, head + [t(f". It is in {DIM_NAME[g['dim']]}; type {C('world')} there for directions and a waypoint.",
                             "white")], prefix="[Gym] ", color="gold")
    else:
        where = g["biome"] or "far away"
        tell(name, head + [t(f". Nobody has found one yet. Look in {where} ({DIM_NAME[g['dim']]}), craft a "
                             f"{g['cartography']} for a map, or explore and type {C('world')} again.", "white")],
             prefix="[Gym] ", color="gold")


# ---------- celebrations ----------

def label_of(key):
    m = re.search(r"defeat_(.+)$", key)
    if not m:
        return None
    k = m.group(1)
    if k.startswith("champion_"):
        return "Champion " + k.split("_", 1)[1].capitalize()
    if k.startswith("elite_"):
        return "Elite Four " + k.split("_", 1)[1].capitalize()
    return "Gym " + k.replace("_", " ").title()


def celebrate(name, label, champion=False):
    pts = CONFIG["badge_points"] * (3 if champion else 1)
    add_points(name, pts)
    S["day"].setdefault("wins", {}).setdefault(name, []).append(label)
    save()
    rc("title @a times 10 70 20")
    rc("title @a title " + json.dumps({"text": "CHAMPION!" if champion else "VICTORY!", "color": "gold", "bold": True}))
    rc("title @a subtitle " + json.dumps({"text": f"{name} defeated {label}", "color": "yellow"}))
    rc("execute as @a at @s run playsound minecraft:ui.toast.challenge_complete master @s")
    fireworks(name, 8 if champion else 4)
    tell("@a", [t(f"Congratulations, {name} defeated {label}! ", "gold"), t(f"+{pts} season points.", "yellow")])
    news(f"{name} defeated {label}")
    challenge_badge(name, label)
    time.sleep(3)
    guide(name, intro="Well done! ")


# ---------- challenges ----------

def challenge_rules(ch):
    return f"only {TYPES[ch['type']]}-type Pokémon in the party" if ch["rule"] == "mono" else "no Master Balls"


def challenge_check(name):
    ch = S["challenges"].get(name)
    if not ch or ch.get("failed"):
        return
    if ch["rule"] == "mono":
        bad = [sp_of(m) for m in mons(name, party_only=True) if ch["type"] not in INFO.get(sp_of(m), {}).get("t", [])]
        if bad:
            ch["failed"] = True
            save()
            tell("@a", [t(f"{name} broke their challenge ({challenge_rules(ch)}): {species_name(bad[0])} is in the party. "
                          "Challenge failed!", "red")])
    else:
        mb = sum(1 for m in mons(name) if str(m.get("CaughtBall", "")).endswith("master_ball"))
        if mb > ch.get("mb", 0):
            ch["failed"] = True
            save()
            tell("@a", [t(f"{name} used a Master Ball, so the no-Master-Ball challenge failed!", "red")])


def challenge_badge(name, label):
    ch = S["challenges"].get(name)
    if not ch or ch.get("failed"):
        return
    challenge_check(name)
    if ch.get("failed"):
        return
    ch.setdefault("badges", []).append(label)
    save()
    nm = snbt_text({"text": f"Challenge Badge: {label} ({challenge_rules(ch)})", "color": "light_purple", "italic": False})
    rc(f"give {name} minecraft:nether_star[minecraft:custom_name={nm},minecraft:enchantment_glint_override=true] 1")
    tell("@a", [t(f"{name} beat {label} while keeping the rule \"{challenge_rules(ch)}\"! ", "light_purple"),
                t("They earned a Challenge Badge.", "yellow")])


def challenge_cmd(name, args):
    ch = S["challenges"].get(name)
    if not args:
        if ch:
            state = "failed" if ch.get("failed") else f"holding, {len(ch.get('badges', []))} badges"
            tell(name, [t(f"Your challenge: {challenge_rules(ch)} ({state}). {C('challenge cancel')} drops it.", "yellow")])
        else:
            tell(name, [t("Pick a challenge: ", "yellow"), t(C("challenge mono <type>"), "aqua"),
                        t(f" (for example {C('challenge mono fire')}) or ", "yellow"), t(C("challenge nomaster"), "aqua"),
                        t(". Keep the rule until you beat a gym to earn a Challenge Badge.", "yellow")])
        return
    word = args[0].lower()
    if word in ("cancel", "huy"):
        S["challenges"].pop(name, None)
        save()
        tell(name, [t("Challenge cancelled.", "gray")])
        return
    fresh_save(force=True)
    if word == "mono" and len(args) > 1:
        want = strip_accents(" ".join(args[1:]).lower()).replace(" ", "")
        vi = {"lua": "fire", "nuoc": "water", "co": "grass", "dien": "electric", "bang": "ice", "giacdau": "fighting",
              "doc": "poison", "dat": "ground", "bay": "flying", "sieulinh": "psychic", "bo": "bug", "da": "rock",
              "ma": "ghost", "rong": "dragon", "bongtoi": "dark", "thep": "steel", "tien": "fairy", "thuong": "normal"}
        ty = want if want in TYPES else vi.get(want)
        if not ty:
            tell(name, [t("Unknown type. Try fire, water, grass, electric, dragon, ghost...", "red")])
            return
        S["challenges"][name] = {"rule": "mono", "type": ty, "since": today()}
    elif word == "nomaster":
        S["challenges"][name] = {"rule": "nomaster", "since": today(),
                                 "mb": sum(1 for m in mons(name) if str(m.get("CaughtBall", "")).endswith("master_ball"))}
    else:
        challenge_cmd(name, [])
        return
    save()
    bar(name, t(f"Challenge started: {challenge_rules(S['challenges'][name])}. Good luck!", "light_purple"))


# ---------- checks ----------

def ensure_baselines(name, snap):
    q, se = quest(), season()
    q["base"].setdefault(name, snap)
    se["base"].setdefault(name, len(snap["dex"]))
    S["day"].setdefault("base", {}).setdefault(name, {k: snap[k] for k in ("dex", "catch", "shiny", "species")})
    se["last_dex"][name] = len(snap["dex"])
    save()


def check(name, roll=False):
    snap = snapshot(name)
    ensure_baselines(name, snap)
    q = quest()
    prog = quest_progress(name, snap)
    last = q.setdefault("prog", {}).get(name, 0)
    if name not in q["done"] and prog > last and prog < q["n"]:
        bar(name, [t("Quest: ", "yellow"), t(f"{min(prog, q['n'])}/{q['n']} ", "aqua"), t(q["text"], "white")])
        snd(name, "minecraft:entity.experience_orb.pickup", 1.4)
    q["prog"][name] = prog
    if name not in q["done"] and prog >= q["n"]:
        q["done"].append(name)
        prize = quest_prize(today())
        for item, c in prize:
            give(name, item, c)
        add_points(name, CONFIG["quest_points"])
        tell("@a", [t(f"{name} finished today's quest ", "green"), t(f"({q['text']})", "aqua"),
                    t(f" and gets {prize_text(prize)}!", "green")])
        snd(name, "minecraft:ui.toast.challenge_complete")
    challenge_check(name)
    bounty_check(name, snap)
    goal_tick(name, snap) if roll else None
    coach_party(name)
    if roll:  # only the 10-minute timer rolls fragments, so commands can't farm them
        if random.random() < CONFIG["map_fragment_chance"]:
            nm = snbt_text({"text": "Treasure Map Fragment", "color": "gold", "italic": False})
            rc(f"give {name} minecraft:paper[minecraft:custom_data={{cvmap:1b}},minecraft:custom_name={nm}] 1")
            bar(name, t("You found a Treasure Map Fragment! Three of them combine on their own.", "gold"))
        m = re.search(r"Found (\d+)", rc(f"clear {name} {FRAG} 0"))
        if m and int(m.group(1)) >= 3:
            treasure(name)
    save()
    return snap


def check_all(roll=False):
    fresh_save()
    snaps = {}
    for n in list(ONLINE):
        try:
            snaps[n] = check(n, roll=roll)
        except Exception as e:
            log("check", n, repr(e))
    return snaps


# ---------- titles ----------

TITLE_DEFS = [("magikarp", "Magikarp King", "gold"), ("walk", "Lost Wanderer", "aqua"), ("shiny", "Eagle Eye", "yellow"),
              ("legend", "Legend Hunter", "light_purple"), ("catch", "Pokémon Vacuum", "green")]


def update_titles(snaps):
    taken, result = set(), {}
    for key, title, color in TITLE_DEFS:
        cands = [(s[key], n) for n, s in snaps.items() if s.get(key, 0) > 0 and n not in taken]
        if cands:
            best = max(cands)
            result[best[1]] = (title, color)
            taken.add(best[1])
    for n in ONLINE:
        team = "cvt_" + re.sub(r"[^a-z0-9]", "", n.lower())[:12]
        if n in result:
            title, color = result[n]
            if S["titles"].get(n) != title:
                rc(f"team add {team}")
                rc(f"team modify {team} prefix " + json.dumps({"text": f"[{title}] ", "color": color}))
                rc(f"team join {team} {n}")
                bar(n, [t("New title: ", "gray"), t(f"[{title}]", color)])
                S["titles"][n] = title
        elif S["titles"].get(n):
            rc(f"team leave {n}")
            S["titles"].pop(n, None)
    save()


# ---------- treasure maps ----------

def treasure(name):
    pos = player_pos(name)
    if not pos or pos[0] != "overworld":
        tell(name, [t("You have 3 map fragments. They will put themselves together once you are in the Overworld.", "yellow")])
        return
    m = re.search(r"Removed (\d+)", rc(f"clear {name} {FRAG} 3"))
    taken = int(m.group(1)) if m else 0

    def refund():
        if taken:
            nm = snbt_text({"text": "Treasure Map Fragment", "color": "gold", "italic": False})
            rc(f"give {name} minecraft:paper[minecraft:custom_data={{cvmap:1b}},minecraft:custom_name={nm}] {taken}")
    if taken < 3:
        refund()
        return
    _, px, py, pz = pos
    spot = ground_near(px, pz, 250, 500)
    if not spot:
        refund()
        tell(name, [t("The map is too faded to read right now. Your fragments are back in your inventory.", "gray")])
        return
    x, y, z, ch = int(spot[0]), int(spot[1]), int(spot[2]), spot[3]
    loot = random.choice([
        [("cobblemon:master_ball", 1), ("cobblemon:rare_candy", 3), ("minecraft:diamond", 6)],
        [("cobblemon:rare_candy", 4), ("cobblemon:ability_capsule", 1), ("cobblemon:ultra_ball", 16)],
        [(random.choice(rewards.EVOLUTION), 2), (random.choice(rewards.BERRIES), 6), ("cobblemon:quick_ball", 12)],
        [("cobblemon:exp_candy_xl", 4), ("obc:bottle_cap", 2), ("minecraft:emerald", 16)],
    ])
    items = ",".join(f'{{Slot:{i * 2 + 10}b,id:"{k}",count:{n}}}' for i, (k, n) in enumerate(loot))
    rc(f"execute in minecraft:overworld run setblock {x} {y - 1} {z} minecraft:chest{{Items:[{items}]}}")
    release(*ch)
    d, dist = bearing(px, pz, x, z)
    tell(name, [t("The three fragments form a map! A treasure chest is buried ", "gold"),
                t(f"{dist} m to the {d}", "aqua"), t(", right under the surface. Waypoint added.", "gold")])
    waypoint(name, "Treasure", "T", x, y, z, 6)
    snd(name, "minecraft:item.book.page_turn")


# ---------- landmarks ----------

def culinary(name):
    """Cobblemon's "Culinary World Tour" advancement: the player has cooked all ten regional delicacies."""
    used(name, "delicacy")
    done = S.setdefault("culinary", [])
    if name in done:
        return
    done.append(name)
    save()
    give(name, "cobblemon:ability_capsule", 1)
    give(name, "cobblemon:rare_candy", 3)
    got = rewards.mixed(name, 3)
    fireworks(name, 4)
    add_points(name, 10)
    news(f"{name} cooked every regional delicacy")
    tell("@a", [t(f"{name} has cooked all ten regional delicacies! ", "gold"),
                t(f"An Ability Capsule, 3 Rare Candy, {prize_text(got)} and 10 season points.", "yellow")],
         prefix="[Chef] ", color="gold")


def landmark_found(name, lid):
    lm = next((l for l in CONFIG["landmarks"] if l["id"] == lid), None)
    if not lm or lid in S["landmarks"]:
        return
    S["landmarks"][lid] = {"finder": name, "name": None, "at": time.time()}
    save()
    news(f"{name} found the {lm['hint']}")
    tell("@a", [t(f"{name} is the first to find the {lm['hint']}! ", "gold"),
                t(f"{name} has 5 minutes to name it with ", "yellow"), t(C("landmark name <name>"), "aqua")])
    fireworks(name, 3)
    add_points(name, 5)


def landmark_name(name, text):
    for lid, rec in S["landmarks"].items():
        if rec["finder"] == name and not rec["name"] and time.time() - rec["at"] < 300:
            text = re.sub(r"[^\w \-']", "", text).strip()[:24]
            if not text:
                return
            rec["name"] = text
            save()
            lm = next(l for l in CONFIG["landmarks"] if l["id"] == lid)
            x, y, z = lm["pos"]
            tell("@a", [t("New landmark: ", "gold"), t(text, "aqua", bold=True),
                        t(f", named by {name}. Everyone got a waypoint.", "yellow")])
            for n in ONLINE:
                waypoint(n, text, "L", x, y, z, 9)
            return
    tell(name, [t("You have no landmark waiting for a name.", "gray")])


# ---------- roaming legendary ----------

def roam():
    r = S.get("roamer")
    st = CONFIG["station"]
    if r and r.get("x") is not None:
        hold(r["x"], r["z"])
        time.sleep(4)
        is_alive = alive(r["tag"])
        if is_alive:
            # leave it alone while someone is next to it (probably in a battle)
            if "passed" in rc(f"execute as @e[tag={r['tag']}] at @s if entity @a[distance=..24]"):
                release(r["x"], r["z"])
                return
            rc(f"kill @e[tag={r['tag']}]")
        release(r["x"], r["z"])
        if not is_alive:
            bar("@a", t(f"Rumour: nobody has seen {r['name']} roaming lately. Maybe someone caught it...", "gray"))
            S["roamer"] = None
            save()
            return
    species = r["species"] if r else random.choice(CONFIG["roamers"])
    base = (r["x"], r["z"]) if r else (st[0], st[2])
    spot = ground_near(base[0], base[1], 300, 700)
    if not spot:
        return
    x, y, z, ch = spot
    spawn_tagged(species, "level=60", x, y, z, "cvroam", glow=False)
    release(*ch)
    S["roamer"] = {"species": species, "name": species_name(species), "tag": "cvroam", "x": int(x), "z": int(z)}
    save()
    d, dist = bearing(st[0], st[2], x, z)
    news(f"{species_name(species)} was seen {d} of the village")
    bar("@a", [t("Rumour: ", "dark_aqua", bold=True),
               t(f"{species_name(species)} was seen {d} of the village, about {dist // 100 * 100} m out", "aqua")])


# ---------- festivals ----------

def festival_tick():
    wd = now().weekday()
    raining = "passed" in rc("execute if predicate cvlife:raining")
    m = re.search(r"(\d+)", rc("time query day") or "")
    day = int(m.group(1)) if m else 1
    m = re.search(r"(\d+)", rc("time query daytime") or "")
    dtime = int(m.group(1)) if m else 0
    kind = None
    if wd == 5:
        kind = ("eevee", ["eevee"], 0.03)
    elif wd == 6:
        kind = ("shiny", None, 0.25 if S["village_level"] >= 2 else 0.12)
    elif raining:
        kind = ("rain", "water", 0.01)
    elif day % 8 == 0 and 13000 <= dtime <= 23000:
        kind = ("moon", "ghost", 0.01)
    if not kind:
        return
    note = f"{today()}-{kind[0]}"
    if S["festival_note"] != note:
        S["festival_note"] = note
        save()
        msg = {"eevee": "It's the Eevee Festival! Eevee are showing up around everyone.",
               "shiny": "It's Shiny Sunday! Pokémon appearing around everyone have much better shiny odds.",
               "rain": "It's raining, and Water types are gathering.",
               "moon": "Full moon tonight. Ghost types are wandering about."}[kind[0]]
        bar("@a", t(msg, "light_purple"))
    for n in list(ONLINE):
        pos = player_pos(n)
        if not pos or pos[0] != "overworld":
            continue
        _, px, py, pz = pos
        if kind[0] in ("rain", "moon"):
            pool = [s for s, v in INFO.items() if kind[1] in v["t"] and not v["l"]]
        elif kind[0] == "eevee":
            pool = ["eevee"]
        else:
            pool = [s for s, v in INFO.items() if not v["l"]]
        for _ in range(2):
            sp = random.choice(pool)
            a, r = random.uniform(0, 2 * math.pi), random.uniform(12, 24)
            shiny = " shiny=yes" if random.random() < kind[2] else ""
            rc(f"execute in minecraft:overworld positioned {px + math.cos(a) * r:.1f} {py + 2:.1f} "
               f"{pz + math.sin(a) * r:.1f} run spawnpokemon {sp} level={random.randint(10, 40)}{shiny}")


# ---------- co-op raid ----------

def coop_raid():
    here = [n for n in ONLINE if (p := player_pos(n)) and p[0] == "overworld"]
    if len(here) < 2:
        return False
    subprocess.Popen(["python3", os.path.join(HERE, "coopraid.py")] + here,
                     stdout=open(os.path.join(HERE, "coopraid.log"), "a"), stderr=subprocess.STDOUT)
    return True


# ---------- journal ----------

def journal():
    fresh_save(force=True)
    base = S["day"].get("base", {})
    lines = []
    for n in sorted(set(base) | set(S["day"].get("wins", {}))):
        b = base.get(n)
        if not b:
            continue
        ms = mons(n)
        species = [sp_of(m) for m in ms]
        new_dex = len(dex_set(n) - set(b["dex"]))
        caught = max(0, len(ms) - b["catch"])
        shinies = max(0, sum(1 for m in ms if m.get("Shiny")) - b["shiny"])
        legends = [s for s in set(species) - set(b["species"]) if INFO.get(s, {}).get("l")]
        bits = []
        if caught:
            bits.append(f"caught {caught} Pokémon")
        if new_dex:
            bits.append(f"{new_dex} new species")
        if shinies:
            bits.append(f"{shinies} shiny")
        if legends:
            bits.append("befriended " + ", ".join(species_name(s) for s in legends))
        bits += [f"beat {w}" for w in S["day"].get("wins", {}).get(n, [])]
        if bits:
            lines.append(f"{n}: " + ", ".join(bits))
    if not lines:
        return
    rc("execute as @a at @s run playsound minecraft:block.bell.use master @s ~ ~ ~ 1 1")
    tell("@a", [t(f"Journey journal for {now().strftime('%d/%m')}", "gold", bold=True)], prefix="[News] ", color="dark_aqua")
    for l in lines:
        tell("@a", [t(l, "white")], prefix=" • ", color="dark_aqua")
    if S.get("roamer"):
        tell("@a", [t(f"{S['roamer']['name']} is still roaming somewhere. Who will catch it?", "gray")], prefix=" • ",
             color="dark_aqua")


# ---------- bounty board ----------

def bounty():
    b = S.get("bounty")
    if not b or b.get("date") != today():
        r = random.Random("bounty" + today())
        pool = sorted(s for s in seen_species() if s in INFO and not INFO[s]["l"]) or EARLY
        S["bounty"] = b = {"date": today(), "species": r.choice(pool), "nature": r.choice(NATURES), "base": {},
                           "claimed": []}
        save()
        if ONLINE:
            tell("@a", [t("Today's bounty: ", "red", bold=True),
                        t(f"{species_name(b['species'])} with a {b['nature'].title()} nature", "yellow"),
                        t(". Catch one for 8 Rare Candy and an Ability Capsule.", "white")],
                 prefix="[Bounty] ", color="red")
    return b


def bounty_check(name, snap):
    b = bounty()
    if name in b["claimed"]:
        return
    want = f"{b['species']}:{b['nature']}"
    have = snap["natures"].count(want)
    if name not in b["base"]:
        b["base"][name] = have
        save()
        return
    if have > b["base"][name]:
        b["claimed"].append(name)
        save()
        give(name, "cobblemon:rare_candy", 8)
        give(name, "cobblemon:ability_capsule", 1)
        add_points(name, 5)
        tell("@a", [t(f"{name} caught the wanted {species_name(b['species'])} ({b['nature'].title()})! ", "gold"),
                    t("Reward: 8 Rare Candy and an Ability Capsule.", "yellow")], prefix="[Bounty] ", color="red")
        snd(name, "minecraft:ui.toast.challenge_complete")


# ---------- giant Pokemon ----------

def giant():
    if "giant" in S["events"]:
        return
    here = [(n, p) for n in ONLINE if (p := player_pos(n)) and p[0] == "overworld"]
    if not here:
        return
    n, (_, px, py, pz) = random.choice(here)
    spot = ground_near(px, pz, 60, 110)
    if not spot:
        return
    x, y, z, ch = spot
    pool = sorted(s for s in seen_species() if s in INFO and not INFO[s]["l"]) or EARLY
    sp = random.choice(pool)
    top = max([m for m in (party_top_level(p) for p in ONLINE) if m] or [20])
    lvl = max(5, min(100, top + random.randint(-3, 5)))
    scale = round(random.uniform(2.2, 3.0), 2)
    if not spawn_tagged(sp, f"level={lvl} scale_modifier={scale} min_perfect_ivs=2", x, y, z, "cvgiant", glow=False):
        release(*ch)
        return
    start_event("giant", "cvgiant", ch, 20)
    rc("execute as @a at @s run playsound minecraft:entity.ravager.roar master @s ~ ~ ~ 0.6 0.5")
    d, dist = bearing(px, pz, x, z)
    tell("@a", [t(f"A GIANT {species_name(sp)} ({scale}x size) appeared about {dist} m {d} of {n}! ", "light_purple"),
                t("It keeps its size if you catch it.", "yellow")], prefix="[Giant] ", color="dark_purple")


# ---------- mystery trader ----------

TRADES = [("cobblemon:master_ball", 1, 40), ("cobblemon:ability_patch", 1, 30), ("cobblemon:ability_capsule", 1, 16),
          ("obc:bottle_cap", 1, 14), ("cobblemon:rare_candy", 4, 8), ("cobblemon:exp_candy_xl", 2, 10),
          ("cobblemon:ultra_ball", 8, 6), ("cobblemon:dusk_ball", 8, 6), ("cobblemon:quick_ball", 8, 6),
          ("cobblemon:shiny_stone", 1, 12), ("cobblemon:dusk_stone", 1, 12), ("cobblemon:dawn_stone", 1, 12),
          ("cobblemon:oval_stone", 1, 10), ("cobblemon:razor_claw", 1, 12), ("cobblemon:kings_rock", 1, 12),
          ("cobblemon:metal_coat", 1, 12), ("cobblemon:dragon_scale", 1, 14), ("cobblemon:upgrade", 1, 14)]


def villages():
    """Village starts from the structure index of generated chunks; no `locate`, which freezes the server."""
    try:
        out = subprocess.run(["python3", "-I", os.path.expanduser("~/cvscan/structindex.py"), os.path.join(DATA, "world/region"),
                              os.path.expanduser("~/cvscan/villages.json"), r"^minecraft:village_"],
                             capture_output=True, text=True, timeout=180).stdout
    except subprocess.TimeoutExpired:
        return []
    found = []
    for line in out.splitlines():
        p = line.split()
        if len(p) == 7:
            x1, _, z1, x2, _, z2 = map(int, p[1:])
            found.append(((x1 + x2) // 2, (z1 + z2) // 2))
    return found


def trader():
    st = CONFIG["station"]
    far = [v for v in villages() if 400 <= math.hypot(v[0] - st[0], v[1] - st[2]) <= 2500]
    if not far:
        return
    vx, vz = random.choice(far)
    spot = ground_near(vx, vz, 0, 8)
    if not spot:
        return
    x, y, z, ch = spot
    offers = random.sample(TRADES, 4)
    recipes = ",".join(
        f'{{buy:{{id:"minecraft:emerald",count:{price}}},sell:{{id:"{item}",count:{cnt}}},'
        f'maxUses:{1 if price >= 30 else 3},rewardExp:0b}}' for item, cnt, price in offers)
    nm = snbt_text({"text": "Mystery Trader", "color": "light_purple"})
    rc(f"execute in minecraft:overworld run summon minecraft:wandering_trader {x} {y} {z} {{Tags:[\"cvtrader\"],"
       f"CustomName:{nm},CustomNameVisible:1b,DespawnDelay:144000,Glowing:1b,Offers:{{Recipes:[{recipes}]}}}}")
    release(*ch)
    S["trader"] = {"x": int(x), "z": int(z), "until": time.time() + 7200}
    save()
    d, dist = bearing(st[0], st[2], x, z)
    goods = ", ".join(item_name(i) for i, _, _ in offers)
    news(f"A Mystery Trader camped at a village {d} of the village (until about {datetime.datetime.fromtimestamp(S['trader']['until'], TZ).strftime('%H:%M')})")
    tell("@a", [t("Rumour: a Mystery Trader set up camp at a village ", "light_purple"),
                t(f"{d} of the village, about {dist // 100 * 100} m away", "aqua"),
                t(f". They sell {goods} for emeralds and leave in about 2 hours.", "light_purple")],
         prefix="[Trader] ", color="dark_purple")


def trader_tick():
    tr = S.get("trader")
    if tr and time.time() > tr["until"]:
        hold(tr["x"], tr["z"])
        time.sleep(3)
        rc("kill @e[tag=cvtrader]")
        release(tr["x"], tr["z"])
        S["trader"] = None
        save()


# ---------- Team Rocket raid ----------

ROCKET_MONS = ["rattata", "zubat", "ekans", "koffing", "meowth", "grimer", "drowzee", "houndour", "murkrow"]


def rocket_defeats(name):
    m = re.search(r"(\d+)", rc(f"rctmod player get type_defeats team_rocket {name}"))
    return int(m.group(1)) if m else 0


def summon_trainer(player, tid, tags, dim, x, y, z, yaw=0):
    """RCT only summons with a player as the caller, at that player's feet; move the trainer where it belongs."""
    rc(f"execute as {player} at @s run rctmod trainer summon {tid} " + "{Tags:[" + ",".join(f'"{g}"' for g in tags) + "]}")
    rc(f"execute in minecraft:{dim} run tp @e[tag={tags[-1]},limit=1,sort=nearest] {x} {y} {z} {yaw} 0")


def rocket_raid():
    st = CONFIG["station"]
    top = max([m for m in (party_top_level(p) for p in ONLINE) if m] or [15])
    use_trainers = top >= ROCKETS[0][1]
    tags = []
    if use_trainers:
        pick = [r for r in ROCKETS if r[1] <= top + 5] or ROCKETS[:3]
        caller = next(iter(sorted(ONLINE)), None)
        for i, (tid, _) in enumerate(random.sample(pick, min(3, len(pick)))):
            if caller:
                summon_trainer(caller, tid, ["cvrocket", f"cvrocket_t{i}"], "overworld", st[0] + (i - 1) * 4, st[1] + 1,
                               st[2] + 6, 180)
        need = 3
    else:
        nm = {"text": "Team Rocket's Pokémon", "color": "dark_red"}
        for i in range(4):
            sp = random.choice(ROCKET_MONS)
            if spawn_tagged(sp, f"level={max(5, top + 2)}", st[0] + (i - 2) * 3, st[1], st[2] + 7, f"cvrocket{i}", nm):
                tags.append(f"cvrocket{i}")
        need = len(tags)
    if not need:
        return
    S["rocket"] = {"until": time.time() + 720, "base": {n: rocket_defeats(n) for n in ONLINE},
                   "trainers": use_trainers, "tags": tags, "need": need}
    save()
    news("Team Rocket attacked the village")
    tell("@a", [t("TEAM ROCKET IS ATTACKING THE VILLAGE! ", "red", bold=True),
                t(f"They are after the village chest. Get to the station ({C('home')}) and drive them off within "
                  "12 minutes, or they will steal some of it.", "yellow")], prefix="[Raid] ", color="dark_red")
    rc("title @a times 5 60 10")
    rc('title @a title {"text":"TEAM ROCKET!","color":"dark_red","bold":true}')
    rc('title @a subtitle {"text":"Protect the village chest","color":"red"}')
    rc("execute as @a at @s run playsound minecraft:event.raid.horn master @s ~ ~ ~ 1 0.7")


def rocket_tick():
    r = S.get("rocket")
    if not r:
        return
    if r["trainers"]:
        won = sum(max(0, rocket_defeats(n) - r["base"].get(n, rocket_defeats(n))) for n in ONLINE) >= r["need"]
    else:
        won = not any(alive(tg) for tg in r["tags"])
    if won:
        S["rocket"] = None
        save()
        rc("kill @e[tag=cvrocket]")
        for n in ONLINE:
            give(n, "cobblemon:great_ball", 8)
            rewards.mixed(n, 2)
        tell("@a", [t("Team Rocket has been driven off and the chest is safe! Every defender gets 8 Great Balls and a "
                      "surprise bundle.", "gold")], prefix="[Raid] ", color="dark_red")
        rc("execute as @a at @s run playsound minecraft:ui.toast.challenge_complete master @s")
        return
    if time.time() > r["until"]:
        if not all(despawn(tg) for tg in r["tags"]):
            return  # someone is still battling one of them; try again next minute
        rc("kill @e[tag=cvrocket]")
        S["rocket"] = None
        save()
        stolen = rocket_steal()
        tell("@a", [t("Time's up! Team Rocket got away" + (f" with {stolen} from the village chest." if stolen else "."), "red"),
                    t(" Defend the village sooner next time!", "gray")], prefix="[Raid] ", color="dark_red")


def rocket_steal():
    entries = chest_entries()
    if not entries:
        return None
    x, y, z, slot, cnt, item = random.choice(entries)
    take = max(1, cnt // 3)
    rc(f"execute in minecraft:overworld run item modify block {x} {y} {z} container.{slot} "
       + json.dumps({"function": "minecraft:set_count", "count": -take, "add": True}))
    return f"{take} {item_name(item)}"


# ---------- weekly story ----------

STORY = [
    {"title": "Chapter 1: The Bell Below",
     "pages": ["Last night the villagers heard a bell ringing from deep underground, northeast of the village.",
               "The elders speak of a buried city where a Pokémon guards the last light.",
               "Look for the hidden landmarks around the village. On Sunday the city's guardian will rise."],
     "boss": ["gengar", "Guardian of Shadows"]},
    {"title": "Chapter 2: The Witch's Curse",
     "pages": ["A witch left a diary in a hut in the swamp, about a Pokémon that eats dreams.",
               "Since then the villagers sleep badly and wake to find their Pokémon exhausted.",
               "On Sunday the dream eater will appear near the village. Bring Dark and Bug types."],
     "boss": ["hypno", "The Dream Eater"]},
    {"title": "Chapter 3: Frost in Summer",
     "pages": ["The lonely igloo stands where no snow falls. Icy footprints lead toward the village.",
               "Something is chilling the land, and it is getting closer.",
               "On Sunday it arrives. Bring Fire, Steel and Rock types."],
     "boss": ["glalie", "The Frost Phantom"]},
    {"title": "Chapter 4: The Last Traveler",
     "pages": ["Three times the village has been saved. An unsigned letter slid under the station door.",
               "\"You are strong enough now. Come and meet me one last time.\"",
               "On Sunday the writer will show themselves. Next week the story begins again."],
     "boss": ["lucario", "The Mysterious Traveler"]},
]


def story_book(ch):
    pages = ",".join("{raw:" + snbt_text({"text": p}) + "}" for p in ch["pages"])
    title = ch["title"].split(":")[0][:31]
    return f'minecraft:written_book[minecraft:written_book_content={{title:"{title}",author:"The Village",pages:[{pages}]}}] 1'


def story_week():
    if S.get("story_week") == week_key():
        return
    idx = S.get("story_idx", -1) + 1
    S["story_idx"], S["story_week"], S["story_boss_done"] = idx, week_key(), ""
    ch = STORY[idx % len(STORY)]
    for n in S["seen"]:
        if n in ONLINE:
            rc(f"give {n} {story_book(ch)}")
        else:
            S["pending"].setdefault(n, []).append(["__book__", idx % len(STORY)])
    save()
    tell("@a", [t(f"{ch['title']} ", "gold", bold=True), t("has arrived (a book in your inventory).", "yellow")],
         prefix="[Story] ", color="dark_aqua")


def story_boss():
    here = [n for n in ONLINE if (p := player_pos(n)) and p[0] == "overworld"]
    if not here:
        return False
    ch = STORY[S.get("story_idx", 0) % len(STORY)]
    st = CONFIG["station"]
    spot = ground_near(st[0], st[2], 80, 160)
    if not spot:
        return False
    x, y, z, chunk = spot
    sp, title = ch["boss"]
    top = max([m for m in (party_top_level(n) for n in here) if m] or [20])
    if not spawn_tagged(sp, f"level={min(100, top + 8)} min_perfect_ivs=6", x, y, z, "cvstory",
                        {"text": title, "color": "dark_purple", "bold": True}):
        release(*chunk)
        return False
    start_event("story", "cvstory", chunk, 30, players=here)
    d, dist = bearing(st[0], st[2], x, z)
    tell("@a", [t(f"{title} has appeared about {dist} m {d} of the village! ", "light_purple"),
                t(f"Defeat it to close {ch['title'].split(':')[0]}. Everyone online when it falls gets a reward.", "yellow")],
         prefix="[Story] ", color="dark_aqua")
    return True


# ---------- challenger ----------

def challenger_check():
    if "rival" in S["events"]:
        return
    sc = scores(season())
    if len(sc) < 2:
        return
    ranked = sorted(sc.items(), key=lambda kv: -kv[1])
    leader = ranked[0][0]
    if ranked[0][1] - ranked[1][1] < 15 or leader not in ONLINE or S.get("challenger_day", {}).get(leader) == today():
        return
    pos = player_pos(leader)
    team = [v for v in party(leader).values() if not INFO.get(sp_of(v), {}).get("l")]
    if not pos or pos[0] != "overworld" or not team:
        return
    best = max(team, key=lambda v: v.get("Level", 0))
    sp, lvl = sp_of(best), min(100, best.get("Level", 20) + 3)
    _, px, py, pz = pos
    spot = ground_near(px, pz, 25, 45)
    if not spot:
        return
    x, y, z, ch = spot
    if not spawn_tagged(sp, f"level={lvl} min_perfect_ivs=6", x, y, z, "cvrival",
                        {"text": f"{leader}'s Challenger", "color": "red", "bold": True}):
        release(*ch)
        return
    S.setdefault("challenger_day", {})[leader] = today()
    start_event("rival", "cvrival", ch, 15, player=leader)
    d, dist = bearing(px, pz, x, z)
    tell("@a", [t(f"{leader} is leading by a mile! A Challenger with a level {lvl} {species_name(sp)} (6 IVs) appeared "
                  f"{dist} m {d} of them. ", "red"), t("Beat it within 15 minutes for 5 Rare Candy and an Ability Capsule.",
                                                        "yellow")], prefix="[Challenger] ", color="red")


def events_tick():
    """Finish timed events: pay when the tagged boss is gone from its held chunks, clean up when time runs out."""
    for key in list(S["events"]):
        ev = S["events"][key]
        if not alive(ev["tag"]):
            end_event(key)
            if ev.get("chunk"):
                release(*ev["chunk"])
            if key == "story":
                for n in set(ev.get("players", [])) | ONLINE:
                    give(n, "cobblemon:rare_candy", 5)
                    if n in ONLINE:
                        rewards.mixed(n, 3)
                tell("@a", [t("The story boss has fallen! Everyone gets 5 Rare Candy and a surprise bundle (balls, berries "
                              "or an evolution item). A new chapter arrives on Monday.", "gold")], prefix="[Story] ",
                     color="dark_aqua")
            elif key == "rival":
                give(ev["player"], "cobblemon:rare_candy", 5)
                give(ev["player"], "cobblemon:ability_capsule", 1)
                tell("@a", [t(f"{ev['player']} beat their Challenger! 5 Rare Candy and an Ability Capsule.", "gold")],
                     prefix="[Challenger] ", color="red")
        elif time.time() > ev["until"] and despawn(ev["tag"], ev.get("chunk")):
            end_event(key)
            msg = {"story": "The story boss retreated into the shadows...",
                   "rival": f"The Challenger left; {ev.get('player')} missed the chance this time."}.get(key)
            if msg:
                tell("@a", [t(msg, "gray")], prefix="[World] ", color="gray")


# ---------- wonder trade ----------

STAT_KEYS = {"cobblemon:hp": "hp", "cobblemon:attack": "attack", "cobblemon:defence": "defence",
             "cobblemon:special_attack": "special_attack", "cobblemon:special_defence": "special_defence",
             "cobblemon:speed": "speed"}


def props_of(v):
    parts = [sp_of(v), f"level={v.get('Level', 5)}"]
    if v.get("Shiny"):
        parts.append("shiny=yes")
    nat = str(v.get("Nature", "")).split(":")[-1]
    if nat:
        parts.append(f"nature={nat}")
    g = str(v.get("Gender", "")).lower()
    if g in ("male", "female"):
        parts.append(f"gender={g}")
    form = str(v.get("FormId", "normal"))
    if form and form != "normal":
        parts.append(f"form={form}")
    ab = (v.get("Ability") or {}).get("AbilityName")
    if ab:
        parts.append(f"ability={ab}")
    for k, iv in ((v.get("IVs") or {}).get("Base") or {}).items():
        if k in STAT_KEYS:
            parts.append(f"{STAT_KEYS[k]}_iv={iv}")
    sm = v.get("ScaleModifier")
    if sm and abs(float(sm) - 1.0) > 0.2:
        parts.append(f"scale_modifier={round(float(sm), 2)}")
    return " ".join(parts)


def wt_seed_pool():
    if S.get("wt_pool"):
        return
    pool = []
    for _ in range(8):
        sp = random.choice(EARLY + ["eevee", "dratini", "larvitar", "bagon", "beldum", "gible", "riolu", "togepi"])
        shiny = " shiny=yes" if random.random() < 0.08 else ""
        pool.append({"props": f"{sp} level={random.randint(8, 25)} min_perfect_ivs=1{shiny}", "from": "server",
                     "label": species_name(sp)})
    S["wt_pool"] = pool
    save()


def wonder_trade(name, args):
    """Two steps: /trade <slot> shows what would go, the same command 30 s to 3 min later sends it. The wait lets the
    party file (saved by Cobblemon every 30 s) catch up with the live party."""
    if not args or not args[0].isdigit() or not 1 <= int(args[0]) <= 6:
        tell(name, [t("Wonder trade: ", "yellow"), t(C("trade <slot 1-6>"), "aqua"),
                    t(" puts the Pokémon in that party slot into the mystery box and gives you a random one back. Moves "
                      "and EVs reset. 3 trades a day.", "yellow")], prefix="[Wonder Trade] ", color="light_purple")
        return
    used = S.setdefault("wt_used", {})
    if used.get("date") != today():
        used.clear()
        used["date"] = today()
    if used.get(name, 0) >= 3:
        tell(name, [t("You have used your 3 trades today. Come back tomorrow.", "gray")], prefix="[Wonder Trade] ",
             color="light_purple")
        return
    slot = int(args[0])
    req = S["trades"].get(name)
    fresh = req and req["slot"] == slot and 30 <= time.time() - req["at"] <= 180
    p = party(name)
    v = p.get(slot - 1)
    if not v:
        tell(name, [t(f"Slot {slot} looks empty (the saved party can be up to 30 s old).", "gray")],
             prefix="[Wonder Trade] ", color="light_purple")
        return
    label = str(v.get("Nickname") or "") or species_name(sp_of(v))
    problem = None
    if len(p) < 2:
        problem = "You need at least 2 Pokémon in your party."
    elif INFO.get(sp_of(v), {}).get("l"):
        problem = "Legendary and mythical Pokémon can't be traded."
    elif v.get("Tradeable") == 0:
        problem = f"{label} can't be traded."
    if problem:
        S["trades"].pop(name, None)
        save()
        tell(name, [t(problem, "gray")], prefix="[Wonder Trade] ", color="light_purple")
        return
    if not fresh:
        S["trades"][name] = {"slot": slot, "at": time.time()}
        save()
        shiny = " (shiny)" if v.get("Shiny") else ""
        tell(name, [t(f"You are about to trade {label}{shiny}, level {v.get('Level')}. ", "yellow"),
                    t(f"Run {C(f'trade {slot}')} again in 30 seconds to 3 minutes to confirm, and don't move your party.",
                      "white")], prefix="[Wonder Trade] ", color="light_purple")
        return
    S["trades"].pop(name, None)
    out = rc(f"takepokemon {name} {slot}")
    m = re.match(r"(.+?) was removed", out)
    if not m:
        tell(name, [t("The trade failed: " + out[:80], "gray")], prefix="[Wonder Trade] ", color="light_purple")
        return
    removed = m.group(1).strip()
    if removed.lower() not in (label.lower(), species_name(sp_of(v)).lower(), sp_of(v)):
        # the party changed after the last save: give it back as well as we can and stop
        rc(f"pokegiveother {name} {re.sub(r'[^a-z0-9]', '', removed.lower()) or sp_of(v)} level={v.get('Level', 10)}")
        tell(name, [t(f"Your party changed while trading, so {removed} was returned and nothing was traded. Sorry! "
                      "Its moves and IVs may have reset.", "red")], prefix="[Wonder Trade] ", color="light_purple")
        save()
        return
    held = v.get("HeldItem") or {}
    if isinstance(held, dict) and held.get("id") and held.get("id") != "minecraft:air":
        rc(f"give {name} {held['id']} {held.get('count', 1)}")
    entry = {"props": props_of(v), "label": species_name(sp_of(v)), "from": name}
    wt_seed_pool()
    pool = S["wt_pool"]
    choices = [i for i, e in enumerate(pool) if e.get("from") != name] or list(range(len(pool)))
    pick = random.choice(choices)
    got = pool[pick]
    res = rc(f"pokegiveother {name} {got['props']}")
    if "Gave" not in res:
        rc(f"pokegiveother {name} {entry['props']}")
        tell(name, [t("The mystery box jammed, so your Pokémon was returned (moves reset). Try again later.", "gray")],
             prefix="[Wonder Trade] ", color="light_purple")
        log("wonder trade give failed", got, res)
        save()
        return
    pool.pop(pick)
    pool.append(entry)
    used[name] = used.get(name, 0) + 1
    save()
    shiny = " (SHINY!)" if "shiny=yes" in got["props"] else ""
    src = "the server" if got.get("from") == "server" else got["from"]
    tell("@a", [t(f"{name} put {entry['label']} in the mystery box and got ", "light_purple"),
                t(f"{got['label']}{shiny}", "gold"), t(f" from {src}!", "light_purple")],
         prefix="[Wonder Trade] ", color="light_purple")
    snd(name, "minecraft:entity.player.levelup", 1.4)


# ---------- commands ----------

LAST_CMD = {}
ALIASES = {"nv": "world", "nhiemvu": "world", "bxh": "world", "rank": "world", "dex": "world", "lang": "world",
           "village": "world", "quest": "world", "truyna": "world", "bounty": "world", "diadanh": "world",
           "dd": "world", "help": "world", "lenh": "world", "doi": "trade", "thuthach": "challenge", "dat": "landmark"}


def help_text(name):
    tell(name, [t("Commands: ", "yellow"), t(C("world"), "aqua"), t(" your quest, bounty, rank, shared Pokédex, village "
                                                                    "and next gym; ", "white"),
                t(C("home"), "aqua"), t(" back to the station; ", "white"), t(C("trade <slot>"), "aqua"),
                t(" wonder trade; ", "white"), t(C("challenge"), "aqua"), t(" challenge runs; ", "white"), t(C("goal <pokemon>"), "aqua"),
                t(" track a Pokémon; ", "white"), t(C("fly"), "aqua"), t(" Fly Taxi; ", "white"),
                t(C("tower"), "aqua"), t(" Battle Tower; ", "white"), t(C("legend"), "aqua"), t(" Legend Quest; ", "white"),
                t("!q <question>", "aqua"), t(" ask the assistant.", "white")])


def command(name, msg):
    parts = msg.split()
    cmd = ALIASES.get(parts[0].lower().lstrip("!/"), parts[0].lower().lstrip("!/"))
    args = parts[1:]
    if cmd == "landmark" and args and args[0].lower() == "name":
        args = args[1:]
    if time.time() - LAST_CMD.get((name, cmd), 0) < (2 if cmd in ("fly", "tower", "legend", "guide") else 10):
        bar(name, t("Wait a few seconds before running that again.", "gray"))
        return
    LAST_CMD[(name, cmd)] = time.time()
    log("cmd", name, cmd, *args)
    used(name, cmd)
    if cmd in ("world", "trade", "challenge"):
        bar(name, t("Loading...", "gray"))
    if cmd == "world":
        world_summary(name)
    elif cmd == "home":
        h = CONFIG.get("home")
        if name in S.get("tower", {}):
            bar(name, t(f"You are in the Battle Tower; {C('tower quit')} takes you back.", "yellow"))
        elif h:
            rc(f"execute in minecraft:overworld run tp {name} {h[0]} {h[1]} {h[2]}")
            snd(name, "minecraft:entity.enderman.teleport")
    elif cmd == "trade":
        wonder_trade(name, args)
    elif cmd == "challenge":
        challenge_cmd(name, args)
    elif cmd == "landmark":
        landmark_name(name, " ".join(args))
    elif cmd in ("goal", "muctieu"):
        goal_cmd(name, args)
    elif cmd == "fly":
        fly_cmd(name, args)
    elif cmd == "tower":
        tower_cmd(name, args)
    elif cmd == "legend":
        legend_cmd(name, args)
    elif cmd == "guide":
        guide_book(name)


def compact(parts):
    """Drop the default "bold": false that t() adds, to keep tellraw short."""
    return [{k: v for k, v in p.items() if not (k == "bold" and v is False)} for p in parts]


def tell_rows(name, head, rows, limit=880):
    """Send rows as few tellraw messages as fit under the rcon packet limit (one message per rcon call is slow)."""
    msg = compact(head)
    for r in rows:
        line = compact([t("\n • ", "gold")] + r)
        if msg and len(json.dumps(msg + line, ensure_ascii=False, separators=(",", ":")).encode()) > limit:
            rc(f"tellraw {name} " + json.dumps(msg, ensure_ascii=False, separators=(",", ":")))
            msg = compact([t(" • ", "gold")] + r)
        else:
            msg += line
    if msg:
        rc(f"tellraw {name} " + json.dumps(msg, ensure_ascii=False, separators=(",", ":")))


def where_from(name, pos):
    """'about 600 m to the northwest' from the player, or from the village when they are in another dimension."""
    pp = player_pos(name)
    if pp and pp[0] == "overworld":
        d, dist = bearing(pp[1], pp[3], pos[0], pos[2])
        return f"about {dist} m to the {d} of you (check your waypoints)"
    st = CONFIG["station"]
    d, dist = bearing(st[0], st[2], pos[0], pos[2])
    return f"about {dist} m {d} of the village"


def world_summary(name):
    T = [time.time()]  # no save-all here: it costs 3 s, and party files are at most ~30 s behind anyway
    T.append(time.time())
    snap = check(name)
    q, se, b = quest(), season(), bounty()
    prog = quest_progress(name, snap)
    ranked = sorted(scores(se).items(), key=lambda kv: -kv[1])
    pos = next((i + 1 for i, (n, _) in enumerate(ranked) if n == name), None)
    pts = scores(se).get(name, 0)
    dex = len(shared_dex())
    nxt = next((need for need, _ in CONFIG["shared_dex_milestones"] if need > dex), None)
    lv, levels = S["village_level"], CONFIG["village_levels"]
    st = CONFIG["station"]
    missing = [l for l in CONFIG["landmarks"] if l["id"] not in S["landmarks"]]
    rows = [
        [t("Quest: ", "yellow"), t(q["text"], "aqua"),
         t(f" {min(prog, q['n'])}/{q['n']}" + (" (done)" if name in q["done"] else ""), "white")],
        [t("Bounty: ", "yellow"), t(f"{species_name(b['species'])}, {b['nature'].title()} nature", "aqua"),
         t(" (caught)" if name in b["claimed"] else "", "green")],
        [t("Weekly rank: ", "yellow"), t(f"#{pos}/{len(ranked)}, {pts} pts" if pos else f"{pts} pts", "white"),
         t(" | " + " ".join(f"{i + 1}.{n} {p}" for i, (n, p) in enumerate(ranked[:3])), "gray")],
        [t("Shared Pokédex: ", "yellow"), t(f"{dex} species" + (f", next gift at {nxt}" if nxt else ""), "white")],
        [t("Village: ", "yellow"), t(f"level {lv}" + (f", next level needs {levels[lv]['text']} in the village chest"
                                                      if lv < len(levels) else " (max)"), "white")],
        [t("Battle Tower: ", "yellow"), t(f"your best is floor {S['tower_best'].get(name, 0)}", "white"),
         t(" | " + " ".join(f"{n} {f}" for n, f in sorted(S["tower_best"].items(), key=lambda kv: -kv[1])[:3]), "gray")
         if S["tower_best"] else t("", "white")],
        [t("Team Expedition: ", "yellow"), t(f"{expedition()['text']}: {expedition_progress(expedition())}/"
                                            f"{expedition()['goal']}" + (" (done)" if expedition()["done"] else ""), "gold")],
    ] + ([[t("Fishing Hole: ", "yellow"), t(f"{S['fishing']['left']} rare water Pokémon, "
                                            + where_from(name, S['fishing']['pos']), "aqua")]] if S.get("fishing") else []) + ([[t("Hidden Grotto: ", "yellow"), t(grotto_hint(S["grotto"], close=S["grotto"]["hint2"]), "dark_green")]]
         if S.get("grotto") else []) + ([[t("Outbreak: ", "yellow"), t(f"{species_name(S['outbreak']['species'])}, "
                                         + where_from(name, S['outbreak']['pos']), "light_purple")]] if S.get("outbreak") else []) + [
        [t("Landmarks: ", "yellow"), t(f"{len(CONFIG['landmarks']) - len(missing)}/{len(CONFIG['landmarks'])} found", "white")]
        + ([t(" | still hidden: " + ", ".join(bearing(st[0], st[2], l["pos"][0], l["pos"][2])[0] for l in missing), "gray")]
           if missing else []),
    ]
    rows.append([t("More: ", "yellow"), t(" ".join(C(c) for c in ("fly", "tower", "legend", "goal", "trade", "challenge",
                                                                   "guide")), "aqua")])
    T.append(time.time())
    tell_rows(name, [{"text": "[COBBLEVERSE] ", "color": "gold", "bold": True}, t(f"{name}'s world", "gold", bold=True)], rows)
    T.append(time.time())
    guide(name)
    T.append(time.time())
    log("world timing", name, [round(b - a, 1) for a, b in zip(T, T[1:])])


def on_join(name):
    ONLINE.add(name)
    first = name not in S["seen"]
    if first:
        S["seen"].append(name)
    finder_give(name)
    back = S.get("tower_return", {}).pop(name, None)
    if back:
        time.sleep(2)
        tower_return(name, *back)
    for item, c in S["pending"].pop(name, []):
        if item == "__book__":
            rc(f"give {name} {story_book(STORY[c])}")
        else:
            rewards.give(name, item, c)
    save()
    time.sleep(4)
    q = quest()
    tell(name, [t(("Welcome to COBBLEVERSE, " if first else "Welcome back, ") + name + "! ", "green"),
                t("Today's quest: ", "yellow"), t(q["text"], "aqua"),
                t(f" (reward: {prize_text(quest_prize(today()))}).", "yellow")])
    recap(name)
    today_line(name)
    guide_give(name)
    if first:
        tell(name, [t("You got a COBBLEVERSE Guide book and an Itemfinder. ", "green"),
                    t(C("world"), "aqua"), t(" shows everything in one place.", "white")])
        guide(name, intro="Your journey begins! ")
    else:
        tip = next_tip(name)
        if tip:
            tip_line(name, *tip)
    try:
        fresh_save()
        check(name)
    except Exception as e:
        log("join check", repr(e))


# ---------- news recap (shown on join) ----------

def news(text):
    S["news"].append([time.time(), text])
    S["news"] = [n for n in S["news"] if time.time() - n[0] < 3 * 86400][-40:]
    save()


def today_line(name):
    """One line with what is on today, so a returning player sees the daily features without a list of commands."""
    bits = []
    if S.get("grotto"):
        bits.append(f"a Hidden Grotto in {S['grotto']['biome']} land")
    if S.get("fishing"):
        bits.append("a Fishing Hole")
    if S.get("outbreak"):
        bits.append(f"a {species_name(S['outbreak']['species'])} outbreak")
    e = S.get("expedition")
    if e and e["week"] == week_key() and not e["done"]:
        bits.append(f"the Team Expedition ({expedition_progress(e)}/{e['goal']})")
    if bits:
        tell(name, [t("Today: ", "yellow"), t(", ".join(bits) + ". ", "white"), t(C("world"), "aqua"),
                    t(" for details.", "white")])


def recap(name):
    since = S["last_seen"].get(name)
    if not since:
        return
    items = [txt for at, txt in S["news"] if at > since and not txt.startswith(name + " ")][-4:]
    if items:
        tell(name, [t("While you were away: ", "gold"), t("; ".join(items) + ".", "white")], prefix="[News] ",
             color="dark_aqua")


# ---------- coach tips (each shown once per player) ----------

def tip(name, key, text):
    done = S["tips"].setdefault(name, [])
    if key in done:
        return
    done.append(key)
    save()
    tell(name, [t("Tip: ", "green", bold=True), t(text, "white")], prefix="", color="green")
    snd(name, "minecraft:block.note_block.chime", 1.2)


def coach_party(name):
    p = party(name)
    if len(p) >= 6:
        tip(name, "full_party", "Your party is full. New catches go to the PC; there is one at the starter station.")
    for v in p.values():
        held = str((v.get("HeldItem") or {}).get("id", ""))
        if held.endswith("_stone") and held != "cobblemon:everstone":
            tip(name, "held_stone", f"{species_name(sp_of(v))} is holding a {item_name(held)}. Holding a stone does "
                                    "nothing; hold it in your hand and right-click the Pokémon to evolve it.")
        if v.get("Shiny"):
            tip(name, "first_shiny", "A shiny! Shinies are rare, so keep it safe in your party or PC.")
        if INFO.get(sp_of(v), {}).get("l"):
            tip(name, "first_legend", "You caught a legendary. Legendaries can't be wonder traded, and the Challenger "
                                      "never copies them.")


def coach_place(name, pos):
    if pos[0] == "the_nether":
        tip(name, "nether", "The Nether: Fire and Dark types live here, and Gym Blaine is in a crimson forest. Bring "
                            "Fire Resistance and don't sleep in a bed.")
    elif pos[0] == "the_end":
        tip(name, "end", "The End: the Elite Four live in the Kanto League on the outer islands, far from the centre.")


# ---------- personal goal ----------

def spawn_hint(sp):
    rows = SPAWNS.get(sp) or []
    if not rows:
        return "it doesn't spawn in the wild; look for an evolution or another way to get it"
    r = rows[0]
    bits = [r.get("bucket") or "", ("fishing" if r.get("pos") == "fishing" else "") or "",
            ", ".join(r.get("biomes") or []), r.get("time") or "", f"level {r['level']}" if r.get("level") else ""]
    return ", ".join(b for b in bits if b)


def goal_cmd(name, args):
    if not args:
        g = S["goals"].get(name)
        if g:
            tell(name, [t(f"Your goal: {species_name(g['species'])} ({spawn_hint(g['species'])}). ", "yellow"),
                        t(f"{C('goal clear')} removes it.", "gray")])
        else:
            tell(name, [t("Set a goal with ", "yellow"), t(C("goal <pokemon>"), "aqua"),
                        t(" and the action bar reminds you where it lives until you catch it.", "yellow")])
        return
    if args[0].lower() in ("clear", "cancel", "huy"):
        S["goals"].pop(name, None)
        save()
        bar(name, t("Goal cleared.", "gray"))
        return
    want = re.sub(r"[^a-z0-9]", "", strip_accents(" ".join(args).lower()))
    sp = next((k for k, v in INFO.items() if want in (k, re.sub(r"[^a-z0-9]", "", v.get("n", "").lower()))), None)
    if not sp:
        tell(name, [t("I don't know that Pokémon. Use its English name, like dragonite.", "red")])
        return
    have = [sp_of(m) for m in mons(name)].count(sp)
    S["goals"][name] = {"species": sp, "base": have, "since": time.time()}
    save()
    tell(name, [t(f"Goal set: {species_name(sp)}. ", "green"), t(f"Where: {spawn_hint(sp)}.", "white")])


def goal_tick(name, snap):
    g = S["goals"].get(name)
    if not g:
        return
    if snap["species"].count(g["species"]) > g["base"]:
        S["goals"].pop(name, None)
        save()
        tell("@a", [t(f"{name} reached their goal and caught {species_name(g['species'])}!", "gold")])
        snd(name, "minecraft:ui.toast.challenge_complete")
        news(f"{name} caught their goal Pokémon, {species_name(g['species'])}")
    elif time.time() - g.get("reminded", 0) > 900:
        g["reminded"] = time.time()
        save()
        bar(name, [t("Goal: ", "yellow"), t(species_name(g["species"]), "aqua"), t(f" ({spawn_hint(g['species'])})", "gray")])


# ---------- context: places and sounds ----------

BOX_CACHE = {}


def cached_boxes(g):
    hit = BOX_CACHE.get(g["struct"])
    if hit and time.time() - hit[0] < 900:
        return hit[1]
    boxes = gym_boxes(g)
    BOX_CACHE[g["struct"]] = (time.time(), boxes)
    return boxes


def context_tick():
    """Per-player position pass every 5 minutes: place tips and a chime when the next gym is close."""
    for n in list(ONLINE):
        pos = player_pos(n)
        if not pos:
            continue
        coach_place(n, pos)
        g = next_gym(n)
        if not g or g["dim"] != pos[0]:
            continue
        _, px, py, pz = pos
        for b in cached_boxes(g):
            cx, cz = (b[0] + b[3]) / 2, (b[2] + b[5]) / 2
            if math.hypot(cx - px, cz - pz) < 90:
                key = f"near_{g['struct']}"
                if S.setdefault("near", {}).get(n) != key:
                    S["near"][n] = key
                    save()
                    rc(f"execute as {n} at @s run playsound minecraft:block.bell.use master @s ~ ~ ~ 0.8 0.7")
                    bar(n, [t(f"You are close to {g['name']}", "gold"), t(f" ({g['type']} type)", "yellow")])
                break


# ---------- loops ----------

# ---------- Fly Taxi ----------
# /fly lists the places a player can fly to: home, every gym they have beaten (where they stood when they won,
# or a spot next to the nearest gym of that kind), and every landmark someone has found. A flight costs
# CobbleDollars by distance; the player holds still for 5 seconds while the Pidgeot arrives.

FLY_PENDING = {}


def money(name):
    m = re.search(r"\$\s*([\d.,]+)\s*([KMB]?)", rc(f"cobbledollars query {name}"))
    if not m:
        return None
    return int(float(m.group(1).replace(",", "")) * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[m.group(2)])


def fly_record(name, adv):
    """Remember where a player stood when they beat a gym, as that gym's Fly Taxi stop."""
    g = next((g for g in GYMS if g["adv"].split("/")[-1] in adv), None)
    pos = player_pos(name)
    if g and pos:
        S.setdefault("fly", {}).setdefault(name, {})[g["adv"]] = [pos[0], round(pos[1], 1), round(pos[2]), round(pos[3], 1)]
        save()


def fly_stops(name):
    h = CONFIG["home"]
    stops = [{"key": "home", "label": "Home (village station)", "dim": "overworld", "spot": h}]
    done = advancements(name)
    mine = S.setdefault("fly", {}).get(name, {})
    st = CONFIG["station"]
    for g in GYMS:
        if not (done.get(g["adv"]) or {}).get("done"):
            continue
        rec = mine.get(g["adv"])
        if rec:
            stops.append({"key": g["adv"], "label": g["name"], "dim": rec[0], "spot": rec[1:]})
        elif g["dim"] == "overworld":
            boxes = cached_boxes(g)
            if boxes:
                b = min(boxes, key=lambda b: math.hypot((b[0] + b[3]) / 2 - st[0], (b[2] + b[5]) / 2 - st[2]))
                r = math.hypot(b[3] - b[0], b[5] - b[2]) / 2
                stops.append({"key": g["adv"], "label": g["name"], "dim": "overworld", "spot": None,
                              "near": [(b[0] + b[3]) / 2, (b[2] + b[5]) / 2, r + 3, r + 10]})
    for l in CONFIG["landmarks"]:
        if l["id"] in S["landmarks"]:
            stops.append({"key": "lm|" + l["id"], "label": S["landmarks"][l["id"]].get("name") or l["hint"].title(),
                          "dim": "overworld", "spot": None, "near": [l["pos"][0], l["pos"][2], 4, 14]})
    # Other online players go last so the numbers of the fixed stops don't shift. The spot is only used for the
    # price; the flight goes to wherever the player is when the Pidgeot leaves.
    for other in sorted(ONLINE):
        p = player_pos(other) if other != name else None
        if p:
            stops.append({"key": "player|" + other, "label": other, "dim": p[0], "spot": list(p[1:]), "player": other})
    return stops


def fly_cost(pos, stop):
    if stop["key"] == "home":
        return 0, None
    if not pos or pos[0] != stop["dim"]:
        return 400, None
    x, z = (stop["spot"][0], stop["spot"][2]) if stop["spot"] else (stop["near"][0], stop["near"][1])
    dist = int(math.hypot(x - pos[1], z - pos[3]))
    return min(800, 50 + dist // 20), dist


def fly_cmd(name, args):
    if name in S.get("tower", {}):
        tell(name, [t("You can't fly out of the Battle Tower. Use ", "yellow"), t(C("tower quit"), "aqua"), t(" first.", "yellow")],
             prefix="[Fly] ", color="aqua")
        return
    stops, pos = fly_stops(name), player_pos(name)
    if not args or not args[0].isdigit():
        tell(name, [t("Fly Taxi: ", "aqua", bold=True), t("click a stop or type ", "white"), t(C("fly <number>"), "aqua"),
                    t(". You can fly to gyms you have beaten, landmarks someone has found, home and other online players.", "white")],
             prefix="[Fly] ", color="aqua")
        click = "run_command" if CONFIG.get("slash_commands") else "suggest_command"
        for i, s in enumerate(stops, 1):
            cost, dist = fly_cost(pos, s)
            info = "free" if not cost else f"${cost}" + (f", {dist} m" if dist is not None else f", in {DIM_NAME[s['dim']]}")
            rc(f"tellraw {name} " + json.dumps([
                {"text": f" {i}. ", "color": "gray"},
                {"text": f"[{s['label']}]", "color": "aqua", "underlined": True,
                 "clickEvent": {"action": click, "value": C(f"fly {i}")},
                 "hoverEvent": {"action": "show_text", "contents": f"Fly to {s['label']}"}},
                {"text": f" {info}", "color": "gray"}], ensure_ascii=False))
        return
    i = int(args[0])
    if not 1 <= i <= len(stops):
        bar(name, t(f"There is no stop {i}. Type {C('fly')} for the list.", "red"))
        return
    stop = stops[i - 1]
    cost, _ = fly_cost(pos, stop)
    have = money(name)
    if cost and (have is None or have < cost + 10):
        tell(name, [t(f"The flight to {stop['label']} costs ${cost}; you have ${have or 0}.", "red")], prefix="[Fly] ",
             color="aqua")
        return
    FLY_PENDING[name] = {"stop": stop, "cost": cost, "pos": pos, "at": time.time() + 5}
    tell(name, [t(f"A Pidgeot is on its way to take you to {stop['label']}" + (f" for ${cost}" if cost else "") +
                  ". Hold still for 5 seconds.", "aqua")], prefix="[Fly] ", color="aqua")
    snd(name, "minecraft:entity.parrot.fly", 0.6)


def fly_tick():
    for name, f in list(FLY_PENDING.items()):
        if time.time() < f["at"]:
            continue
        FLY_PENDING.pop(name, None)
        pos = player_pos(name)
        if (name not in ONLINE or not pos or not f["pos"] or pos[0] != f["pos"][0]
                or math.dist(pos[1:], f["pos"][1:]) > 2.5):
            bar(name, t("The Pidgeot flew off because you moved. Type the command again to call it back.", "yellow"))
            continue
        stop = f["stop"]
        if stop.get("player"):
            fly_to_player(name, stop["player"], f["cost"])
            continue
        spot, chunk = stop["spot"], None
        if not spot:
            got = ground_near(*stop["near"][:2], stop["near"][2], stop["near"][3])
            if not got:
                bar(name, t("The Pidgeot couldn't find a place to land there. Try again in a minute.", "red"))
                continue
            spot, chunk = got[:3], got[3]
            if stop["key"].startswith("lm|"):
                S.setdefault("fly_spots", {})[stop["key"]] = list(spot)
                save()
        if f["cost"] and "Removed" not in rc(f"cobbledollars remove {name} {f['cost']}"):
            bar(name, t("The payment didn't go through, so the flight is off.", "red"))
            if chunk:
                release(*chunk)
            continue
        rc(f"execute at {name} run particle minecraft:cloud ~ ~1 ~ 0.6 0.6 0.6 0.05 40")
        rc(f"execute in minecraft:{stop['dim']} run tp {name} {spot[0]} {spot[1]} {spot[2]}")
        rc(f"effect give {name} minecraft:slow_falling 6 0 true")
        rc(f"title {name} times 5 40 15")
        rc(f"title {name} title " + json.dumps({"text": "Fly!", "color": "aqua", "bold": True}))
        rc(f"title {name} subtitle " + json.dumps({"text": stop["label"], "color": "white"}, ensure_ascii=False))
        snd(name, "minecraft:entity.ender_dragon.flap", 1.4)
        if chunk:
            time.sleep(2)
            release(*chunk)


def fly_to_player(name, target, cost):
    if target not in ONLINE or not player_pos(target):
        bar(name, t(f"{target} is no longer online, so the flight is off.", "yellow"))
        return
    if target in S.get("tower", {}):
        bar(name, t(f"{target} is in the Battle Tower. Try again when they are out.", "yellow"))
        return
    if cost and "Removed" not in rc(f"cobbledollars remove {name} {cost}"):
        bar(name, t("The payment didn't go through, so the flight is off.", "red"))
        return
    rc(f"execute at {name} run particle minecraft:cloud ~ ~1 ~ 0.6 0.6 0.6 0.05 40")
    rc(f"tp {name} {target}")
    rc(f"effect give {name} minecraft:slow_falling 6 0 true")
    rc(f"title {name} times 5 40 15")
    rc(f"title {name} title " + json.dumps({"text": "Fly!", "color": "aqua", "bold": True}))
    rc(f"title {name} subtitle " + json.dumps({"text": target, "color": "white"}))
    snd(name, "minecraft:entity.ender_dragon.flap", 1.4)
    tell(target, [t(f"{name} just flew in to join you.", "aqua")], prefix="[Fly] ", color="aqua")


# ---------- mass outbreaks ----------
# Every 75-120 minutes, one species appears in a group of about ten somewhere 600-1400 m from a player. The
# species fits the biome at that spot, a few may be shiny, and the outbreak lasts 30 minutes.

OB_BIOMES = ["forest", "jungle", "plains", "savanna", "taiga", "swamp", "desert", "badlands", "hills", "mountain",
             "floral", "grassland", "arid", "temperate", "snowy forest", "tundra", "beach", "coast", "river",
             "freshwater", "lush", "bamboo", "cherry blossom", "spooky", "magical", "mushroom", "snowy taiga", "peak",
             "glacial", "floral meadow", "volcanic"]
SPECIAL = {"legendary", "mythical", "ultra_beast", "paradox"}


def level_cap(name):
    m = re.search(r"(\d+)\s*$", rc(f"rctmod player get level_cap {name}"))
    return int(m.group(1)) if m else 100


def count_tag(tag):
    m = re.search(r"count: (\d+)", rc(f"execute if entity @e[tag={tag}]"))
    return int(m.group(1)) if m else 0


def ob_hold(x, z, on):
    """Keep 7x7 chunks around an outbreak loaded, so the group can wander without vanishing into unloaded land."""
    rc(f"execute in minecraft:overworld run forceload {'add' if on else 'remove'} {x - 48} {z - 48} {x + 48} {z + 48}")


def outbreak_start():
    if S.get("outbreak"):
        return False
    here = [(n, p) for n in ONLINE for p in [player_pos(n)] if p and p[0] == "overworld"]
    if not here:
        return False
    who, (_, px, _, pz) = random.choice(here)
    got = ground_near(px, pz, 600, 1400)
    if not got:
        return False
    x, y, z, chunk = got
    release(*chunk)
    chunk = (int(x), int(z))
    ob_hold(*chunk, True)
    found = [b for b in OB_BIOMES if "passed" in rc(f"execute in minecraft:overworld if biome {int(x)} {int(y)} {int(z)} "
                                                       f"#cobblemon:is_{b.replace(' ', '_')}")]
    cap = level_cap(who)
    pool = []
    for sp, entries in SPAWNS.items():
        if SPECIAL & set(INFO.get(sp, {}).get("l", [])):
            continue
        for e in entries:
            if e["bucket"] not in ("common", "uncommon", "rare") or e.get("pos") != "grounded":
                continue
            if not set(e["biomes"]) & set(found):
                continue
            lo, hi = (list(map(int, e["level"].split("-"))) + [0])[:2] if e.get("level") else (5, 30)
            if lo > cap:
                continue
            pool.append((sp, lo, max(lo, min(hi, cap)), {"common": 3, "uncommon": 2, "rare": 1}[e["bucket"]]))
    if not pool:
        ob_hold(*chunk, False)
        log("outbreak: no species for", found, "at", int(x), int(z))
        return False
    sp, lo, hi, _ = random.choices(pool, weights=[p[3] for p in pool])[0]
    n = 0
    for i in range(10):
        props = f"level={random.randint(lo, hi)}" + (" shiny=yes" if random.random() < 1 / 40 else "")
        if spawn_tagged(sp, props, int(x), int(y), int(z), f"cvob{i}", glow=False):
            rc(f"tag @e[tag=cvob{i}] add cvob")
            n += 1
    if not n:
        ob_hold(*chunk, False)
        return False
    rc(f"execute in minecraft:overworld run spreadplayers {int(x)} {int(z)} 2 9 false @e[tag=cvob]")
    S["outbreak"] = {"species": sp, "pos": [int(x), int(y), int(z)], "chunk": list(chunk), "until": time.time() + 1800,
                     "n": n}
    save()
    name = species_name(sp)
    news(f"A {name} outbreak appeared")
    for p in ONLINE:
        pp = player_pos(p)
        where = ""
        if pp and pp[0] == "overworld":
            d, dist = bearing(pp[1], pp[3], x, z)
            where = f", about {dist} m to the {d} of you"
            waypoint(p, f"Outbreak {name}", "O", x, y, z, 14)
        tell(p, [t("MASS OUTBREAK! ", "light_purple", bold=True),
                 t(f"A big group of {name} appeared{where}. Some might be shiny! It lasts 30 minutes."
                   + (" Waypoint added." if where else ""), "white")], prefix="[Outbreak] ", color="light_purple")
        snd(p, "minecraft:block.bell.resonate", 1.2)
    return True


def outbreak_tick():
    ob = S.get("outbreak")
    if not ob:
        return
    left = count_tag("cvob")
    name = species_name(ob["species"])
    if left == 0:
        S["outbreak"] = None
        save()
        ob_hold(*ob["chunk"], False)
        near = [p for p in ONLINE if (pp := player_pos(p)) and pp[0] == "overworld"
                and math.hypot(pp[1] - ob["pos"][0], pp[3] - ob["pos"][2]) < 128]
        for p in near:
            rewards.mixed(p, 1)
        tell("@a", [t(f"The {name} outbreak is over: every one was caught or beaten." +
                      (" Trainers nearby get a surprise bundle." if near else ""), "light_purple")],
             prefix="[Outbreak] ", color="light_purple")
        return
    if time.time() > ob["until"]:
        rc("execute as @e[tag=cvob] at @s unless entity @a[distance=..24] run tp @s ~ -200 ~")
        rc("execute as @e[tag=cvob] at @s unless entity @a[distance=..24] run kill @s")
        if count_tag("cvob") == 0:
            S["outbreak"] = None
            save()
            ob_hold(*ob["chunk"], False)
            tell("@a", [t(f"The {name} outbreak has moved on.", "gray")], prefix="[Outbreak] ", color="light_purple")


# ---------- Battle Tower ----------
# /tower takes a player to their own arena high above the world and sends trainers at them one floor at a time.
# Trainers get stronger each floor but stay under the player's level cap; they are regular RCT trainers the player
# has never beaten, so a win doesn't change gym progress. The team heals every 3 floors. The run ends on a full
# faint, a floor taking over 10 minutes, leaving the server or /tower quit. Rewards come every floor, bigger every 5.

TOWER = json.load(open(os.path.join(HERE, "tower_trainers.json"), encoding="utf-8"))


def tower_base(i):
    o, gap = CONFIG["tower"]["origin"], CONFIG["tower"]["spacing"]
    return o[0] + i * gap, o[1], o[2]


def tower_build(i):
    x, y, z = tower_base(i)
    rc(f"execute in minecraft:overworld run forceload add {x - 2} {z - 2} {x + 18} {z + 28}")
    time.sleep(3)
    for c in [f"fill {x - 1} {y - 1} {z - 1} {x + 17} {y + 9} {z + 27} minecraft:barrier hollow",
              f"fill {x} {y} {z} {x + 16} {y + 8} {z + 26} minecraft:polished_blackstone_bricks hollow",
              f"fill {x + 1} {y} {z + 1} {x + 15} {y} {z + 25} minecraft:smooth_quartz",
              f"fill {x + 1} {y + 8} {z + 1} {x + 15} {y + 8} {z + 25} minecraft:sea_lantern",
              f"fill {x + 1} {y} {z + 13} {x + 15} {y} {z + 13} minecraft:red_concrete",
              f"fill {x + 7} {y} {z + 21} {x + 9} {y} {z + 23} minecraft:light_blue_concrete",
              f"fill {x + 7} {y} {z + 3} {x + 9} {y} {z + 5} minecraft:red_concrete",
              f"fill {x} {y + 3} {z + 6} {x} {y + 5} {z + 20} minecraft:light_blue_stained_glass",
              f"fill {x + 16} {y + 3} {z + 6} {x + 16} {y + 5} {z + 20} minecraft:light_blue_stained_glass"]:
        rc("execute in minecraft:overworld run " + c)
    rc(f"execute in minecraft:overworld run forceload remove {x - 2} {z - 2} {x + 18} {z + 28}")
    S.setdefault("tower_built", []).append(i)
    save()


def rct_defeats(tid, name):
    m = re.search(r"(\d+)\s*$", rc(f"rctmod player get defeats {tid} {name}"))
    return int(m.group(1)) if m else 0


def tower_pick(name, floor, cap, used):
    target = max(5, min(cap - 5, cap - 22 + 2 * floor))
    size = min(6, 2 + floor // 2)
    for spread in (2, 5, 10):
        pool = [r for r in TOWER if abs(r[2] - target) <= spread and r[3] >= min(size, 3) and r[0] not in used]
        pool.sort(key=lambda r: (abs(r[3] - size), random.random()))
        for r in pool[:20]:
            if rct_defeats(r[0], name):
                continue
            m = re.search(r"(\d+)\s*$", rc(f"rctmod trainer get required_level_cap {r[0]} {name}"))
            if m and int(m.group(1)) > cap:
                continue
            if "normal" not in rc(f"rctmod trainer get type {r[0]}").lower():
                continue
            return r
    return None


def tower_cmd(name, args):
    runs = S.setdefault("tower", {})
    if args and args[0].lower() == "quit":
        if name in runs:
            tower_end(name, "You left the tower.")
        else:
            bar(name, t("You are not in the Battle Tower.", "gray"))
        return
    if name in runs:
        r = runs[name]
        tell(name, [t(f"Floor {r['floor']}: {r.get('trainer_name', 'next trainer')}. ", "gold"),
                    t("Type ", "white"), t(C("tower quit"), "aqua"), t(" to leave.", "white")], prefix="[Tower] ")
        return
    pos = player_pos(name)
    if not pos:
        return
    if pos[0] != "overworld":
        bar(name, t("The Battle Tower takes trainers from the Overworld only.", "yellow"))
        return
    used = {r["arena"] for r in runs.values()}
    free = [i for i in range(CONFIG["tower"]["arenas"]) if i not in used]
    if not free:
        bar(name, t("Every arena is busy. Try again in a few minutes.", "yellow"))
        return
    i = free[0]
    if i not in S.get("tower_built", []):
        tower_build(i)
    gm = re.search(r"(\d+)\s*$", rc(f"data get entity {name} playerGameType"))
    x, y, z = tower_base(i)
    # A run the server cut short by mistake resumes at the floor it reached (set in tower_resume by an admin).
    start = S.setdefault("tower_resume", {}).pop(name, 1)
    runs[name] = {"arena": i, "floor": start, "origin": list(pos), "gm": int(gm.group(1)) if gm else 0,
                  "cap": level_cap(name), "state": "wait", "next_at": time.time() + 6, "used": [], "fainted": 0}
    save()
    rc(f"execute in minecraft:overworld run tp {name} {x + 8.5} {y + 1} {z + 22.5} 180 0")
    rc(f"gamemode adventure {name}")
    rc(f"title {name} times 10 50 15")
    rc(f"title {name} title " + json.dumps({"text": "Battle Tower", "color": "gold", "bold": True}))
    rc(f"title {name} subtitle " + json.dumps({"text": "How high can you climb?", "color": "yellow"}))
    snd(name, "minecraft:block.beacon.activate", 1.0)
    tell(name, [t("Welcome to the Battle Tower! ", "gold", bold=True),
                t("A trainer arrives each floor; walk up and right-click them to battle. Your team heals every 3 "
                  "floors, and every floor pays out, more every 5th. The run ends if your whole team faints. ", "white"),
                t(C("tower quit"), "aqua"), t(" takes you back.", "white")], prefix="[Tower] ")


def tower_summon(name, r):
    pick = tower_pick(name, r["floor"], r["cap"], r["used"])
    if not pick:
        tower_end(name, "There are no more trainers for you to face right now. Impressive!")
        return
    tid, tname, top, size = pick
    x, y, z = tower_base(r["arena"])
    rc(f"execute in minecraft:overworld positioned {x + 1} {y + 1} {z + 1} run kill @e[type=cobblemon:pokemon,dx=14,dy=6,"
       f"dz=24,nbt={{Pokemon:{{PokemonOriginalTrainerType:\"NONE\"}}}}]")
    tag = "cvtw_" + re.sub(r"[^a-z0-9]", "", name.lower())[:12]
    rc(f"kill @e[tag={tag}]")
    summon_trainer(name, tid, ["cvtw", tag], "overworld", x + 8.5, y + 1, z + 4.5, 0)
    if not alive(tag):
        log("tower: summon failed", tid)
        tower_end(name, "The trainer didn't show up, sorry. Try again in a minute.")
        return
    r.update(state="fight", tid=tid, trainer_name=tname, base=rct_defeats(tid, name), floor_until=time.time() + 600,
             started=time.time(), fainted=0)
    r["used"].append(tid)
    save()
    rc(f"title {name} times 5 40 10")
    rc(f"title {name} title " + json.dumps({"text": f"Floor {r['floor']}", "color": "gold", "bold": True}))
    rc(f"title {name} subtitle " + json.dumps({"text": f"{tname} ({size} Pokémon, up to level {top})", "color": "yellow"},
                                              ensure_ascii=False))
    snd(name, "minecraft:block.note_block.bell", 1.2)


def tower_party_out(name):
    p = party(name)
    return bool(p) and all(v.get("Health", 1) <= 0 for v in p.values())


def tower_tick():
    runs = S.get("tower", {})
    for name, r in list(runs.items()):
        if name not in ONLINE:
            continue
        if r["state"] == "wait":
            if time.time() >= r["next_at"]:
                tower_summon(name, r)
            continue
        x, y, z = tower_base(r["arena"])
        pos = player_pos(name)
        if not pos:
            continue  # no clear reply this tick; check again next time instead of ending the run
        if pos[0] != "overworld" or not (x - 2 <= pos[1] <= x + 18 and y - 2 <= pos[2] <= y + 10
                                         and z - 2 <= pos[3] <= z + 28):
            # Two bad reads in a row before ending, so one stray reply can't end a run.
            r["outside"] = r.get("outside", 0) + 1
            if r["outside"] < 2:
                continue
            tower_end(name, "You left the arena, so the run is over.")
            continue
        r["outside"] = 0
        if rct_defeats(r["tid"], name) > r["base"]:
            tower_floor_won(name, r)
            continue
        if time.time() > r["floor_until"]:
            tower_end(name, f"Floor {r['floor']} took over 10 minutes, so the run is over.")
            continue
        if time.time() - r["started"] > 40 and time.time() - r.get("checked", 0) > 15:
            r["checked"] = time.time()
            r["fainted"] = r["fainted"] + 1 if tower_party_out(name) else 0
            if r["fainted"] >= 2:
                tower_end(name, f"Your whole team fainted on floor {r['floor']}.")


def tower_floor_won(name, r):
    f = r["floor"]
    rc(f"kill @e[tag=cvtw_{re.sub(r'[^a-z0-9]', '', name.lower())[:12]}]")
    pay = 30 * f
    rc(f"cobbledollars give {name} {pay}")
    extra = ""
    if f % 5 == 0:
        give(name, "cobblemon:rare_candy", 2)
        got = rewards.mixed(name, min(3, f // 5))
        extra = ", 2 Rare Candy and " + prize_text(got)
    healed = f % 3 == 0
    if healed:
        rc(f"pokeheal {name}")
    best = S.setdefault("tower_best", {})
    record = f > best.get(name, 0)
    if record:
        best[name] = f
    r.update(state="wait", floor=f + 1, next_at=time.time() + 8)
    save()
    tell(name, [t(f"Floor {f} cleared! ", "gold", bold=True), t(f"+${pay}{extra}.", "yellow"),
                t(" Your team is healed." if healed else "", "green"), t(" Next trainer in a few seconds.", "white")],
         prefix="[Tower] ")
    rc(f"execute as {name} at @s run playsound minecraft:ui.toast.challenge_complete master @s")
    if record and f >= 3:
        tell("@a", [t(f"{name} reached floor {f} of the Battle Tower, a new personal best!", "gold")], prefix="[Tower] ")
        news(f"{name} cleared floor {f} of the Battle Tower")


def tower_end(name, why):
    r = S.get("tower", {}).pop(name, None)
    if not r:
        return
    rc(f"kill @e[tag=cvtw_{re.sub(r'[^a-z0-9]', '', name.lower())[:12]}]")
    cleared = r["floor"] - 1
    if name in ONLINE:
        tower_return(name, r["origin"], r["gm"])
        tell(name, [t(why + " ", "yellow"), t(f"You cleared {cleared} floor{'s' if cleared != 1 else ''}; your best is "
                                              f"{S.get('tower_best', {}).get(name, 0)}.", "white")], prefix="[Tower] ")
    else:
        S.setdefault("tower_return", {})[name] = [r["origin"], r["gm"]]
    save()


def tower_return(name, origin, gm):
    d, x, y, z = origin
    # The origin is wherever they typed the command, often mid-air on a flying Pokémon that is no longer under
    # them; slow falling keeps that from becoming a fall death (huylba, 2026-11-06).
    rc(f"effect give {name} minecraft:slow_falling 20 0 true")
    rc(f"execute in minecraft:{d} run tp {name} {x} {y} {z}")
    rc(f"gamemode {['survival', 'creative', 'adventure', 'spectator'][gm]} {name}")


def fast():
    """Every 5 s: Fly Taxi countdowns and Battle Tower floors."""
    while True:
        time.sleep(5)
        if FLY_PENDING:
            step(fly_tick)
        if S.get("tower"):
            step(tower_tick)
        if ONLINE:
            step(legend_tick)
            step(fishing_bubbles)


# ---------- Hidden Grotto ----------
# Once a day a hidden grotto appears 400-1200 m from the village: three Pokémon of different species that fit the
# biome there, each with its hidden ability, around a small patch of moss and flowers. The first hint names the
# biome, a direction and a rough distance; a closer hint comes 2 hours later, and a player within 48 blocks hears
# rustling. Whoever gets there first catches them. Leftovers and the decoration go at midnight.

HIDDEN = json.load(open(os.path.join(HERE, "hidden_abilities.json"), encoding="utf-8"))
GROTTO_BIOMES = ["cherry blossom", "bamboo", "mushroom", "spooky", "magical", "floral meadow", "snowy taiga",
                 "snowy forest", "glacial", "volcanic", "badlands", "desert", "jungle", "swamp", "savanna", "taiga",
                 "forest", "beach", "river", "peak", "mountain", "hills", "floral", "tundra", "plains", "grassland"]


def grotto_hint(g, close=False):
    st = CONFIG["station"]
    d, dist = bearing(st[0], st[2], g["pos"][0], g["pos"][2])
    if close:
        return (f"The Hidden Grotto is about {round(dist, -2):.0f} m {d} of the village, around height "
                f"{round(g['pos'][1], -1):.0f}.")
    band = "not far" if dist < 700 else "a good walk away" if dist < 1000 else "far out"
    return f"Today's Hidden Grotto is somewhere in {g['biome']} land, {d} of the village and {band}."


def grotto_new():
    st = CONFIG["station"]
    got = ground_near(st[0], st[2], 400, 1200)
    if not got:
        return False
    x, y, z, chunk = got
    x, y, z = int(x), int(y), int(z)
    found = [b for b in GROTTO_BIOMES if "passed" in rc(f"execute in minecraft:overworld if biome {x} {y} {z} "
                                                         f"#cobblemon:is_{b.replace(' ', '_')}")]
    caps = [level_cap(n) for n in ONLINE] or [30]
    cap = max(caps)
    pool = {}
    for sp, entries in SPAWNS.items():
        if sp not in HIDDEN or SPECIAL & set(INFO.get(sp, {}).get("l", [])):
            continue
        for e in entries:
            if e["bucket"] not in ("common", "uncommon", "rare") or e.get("pos") != "grounded":
                continue
            if not set(e["biomes"]) & set(found):
                continue
            lo = int(e["level"].split("-")[0]) if e.get("level") else 5
            if lo <= cap:
                pool[sp] = max(pool.get(sp, 0), lo)
    if len(pool) < 3:
        release(*chunk)
        log("grotto: too few species for", found, "at", x, z)
        return False
    decor = []
    for dx in range(-3, 4):
        for dz in range(-3, 4):
            if dx * dx + dz * dz > 10 or random.random() < 0.35:
                continue
            block = random.choice(["minecraft:moss_carpet"] * 6 + ["minecraft:flowering_azalea", "minecraft:lantern",
                                                                      "minecraft:blue_orchid", "minecraft:lily_of_the_valley"])
            px, pz = x + dx, z + dz
            out = rc(f"execute in minecraft:overworld if block {px} {y} {pz} minecraft:air unless block {px} {y - 1} {pz} "
                     f"minecraft:air unless block {px} {y - 1} {pz} #minecraft:leaves run setblock {px} {y} {pz} {block}")
            if "Changed" in out:
                decor.append([px, y, pz, block])
    picks = random.sample(sorted(pool), 3)
    for i, sp in enumerate(picks):
        lo = pool[sp]
        lv = max(lo, random.randint(max(5, cap - 12), max(5, cap - 4)))
        props = f"level={min(lv, max(lo, cap))} ability={HIDDEN[sp]}" + (" shiny=yes" if random.random() < 1 / 64 else "")
        if spawn_tagged(sp, props, x, y, z, f"cvgr{i}", glow=False):
            rc(f"tag @e[tag=cvgr{i}] add cvgr")
    rc(f"execute in minecraft:overworld run spreadplayers {x} {z} 1 3 false @e[tag=cvgr]")
    left = count_tag("cvgr")
    release(*chunk)
    if not left:
        return False
    biome = next((b for b in GROTTO_BIOMES if b in found), "wild")
    S["grotto"] = {"day": today(), "pos": [x, y, z], "species": picks, "biome": biome, "hint2_at": time.time() + 7200,
                   "hint2": False, "decor": decor, "left": left, "near": []}
    save()
    news("A Hidden Grotto appeared")
    tell("@a", [t("HIDDEN GROTTO! ", "dark_green", bold=True),
                t(grotto_hint(S["grotto"]) + " Its Pokémon have their hidden abilities. First come, first served!",
                  "white")], prefix="[Grotto] ", color="dark_green")
    rc("execute as @a at @s run playsound minecraft:block.amethyst_block.resonate master @s ~ ~ ~ 1 0.8")
    return True


def grotto_end():
    g = S.get("grotto")
    if not g:
        return
    x, _, z = g["pos"]
    hold(x, z)
    time.sleep(3)
    rc("execute as @e[tag=cvgr] run tp @s ~ -200 ~")
    rc("execute as @e[tag=cvgr] run kill @s")
    for px, py, pz, block in g["decor"]:
        rc(f"execute in minecraft:overworld if block {px} {py} {pz} {block} run setblock {px} {py} {pz} minecraft:air")
    release(x, z)
    S["grotto"] = None
    save()


def grotto_tick():
    g = S.get("grotto")
    if g and g["day"] != today():
        grotto_end()
        g = None
    if not g:
        if ONLINE and S.get("grotto_day") != today() and now().hour >= 8:
            S["grotto_day"] = today()
            save()
            grotto_new()
        return
    if not g["hint2"] and time.time() > g["hint2_at"]:
        g["hint2"] = True
        save()
        tell("@a", [t(grotto_hint(g, close=True), "white")], prefix="[Grotto] ", color="dark_green")
    near = []
    for p in ONLINE:
        pp = player_pos(p)
        if pp and pp[0] == "overworld":
            dist = math.hypot(pp[1] - g["pos"][0], pp[3] - g["pos"][2])
            if dist < 64:
                near.append((dist, p))
            if dist < 48 and p not in g["near"]:
                g["near"].append(p)
                save()
                bar(p, t("You hear rustling in the undergrowth... the Hidden Grotto is close.", "dark_green"))
                snd(p, "minecraft:block.azalea_leaves.hit", 0.7)
    if not near:
        return  # nobody has its chunks loaded, so the count would read zero
    left = count_tag("cvgr")
    if left < g["left"]:
        finder = min(near)[1]
        used(finder, "grotto")
        g["left"] = left
        save()
        tell("@a", [t(f"{finder} found a Pokémon in the Hidden Grotto" +
                      (f"; {left} still hiding there." if left else ", and it is now empty."), "white")],
             prefix="[Grotto] ", color="dark_green")
        if not left:
            grotto_end()


# ---------- Legend Quest ----------
# Each legendary needs three relics, one at each of the three nearest structures of one kind (igloos for Articuno,
# ruined portals for Moltres, shipwrecks for Lugia, trail ruins for Zapdos, ancient cities for Ho-Oh). A player
# picks a relic up by walking into the structure. With all three they stand on the quartz block of the Legend
# Shrine by the village; the legendary appears there for them to battle and catch. If it gets away (not caught
# within 15 minutes, or knocked out) they can call it again. Progress is per player and kept in life_state.json.

LEGENDS = [
    {"id": "articuno", "name": "Articuno", "relic": "Frost Feather", "color": "aqua", "where": "igloos",
     "struct": r"igloo", "level": 50},
    {"id": "moltres", "name": "Moltres", "relic": "Flame Feather", "color": "red", "where": "ruined portals",
     "struct": r"^minecraft:ruined_portal", "level": 50},
    {"id": "lugia", "name": "Lugia", "relic": "Silver Wing", "color": "white", "where": "shipwrecks",
     "struct": r"^minecraft:shipwreck", "level": 60},
    {"id": "zapdos", "name": "Zapdos", "relic": "Thunder Feather", "color": "yellow", "where": "trail ruins",
     "struct": r"^minecraft:trail_ruins$", "level": 50},
    {"id": "hooh", "name": "Ho-Oh", "relic": "Rainbow Wing", "color": "gold", "where": "ancient cities",
     "struct": r"^minecraft:ancient_city$", "level": 60},
]
SHRINE = (-3052, 65, -1288)


def legend_spots(q):
    """The three structures of a quest's kind nearest the village, chosen once and kept."""
    spots = S.setdefault("legend_spots", {})
    if len(spots.get(q["id"], [])) >= 3:
        return spots[q["id"]]
    try:
        out = subprocess.run(["python3", "-I", os.path.expanduser("~/cvscan/structindex.py"), os.path.join(DATA, "world/region"),
                              os.path.expanduser("~/cvscan/overworld.json"), q["struct"]],
                             capture_output=True, text=True, timeout=180).stdout
    except subprocess.TimeoutExpired:
        return spots.get(q["id"], [])
    st = CONFIG["station"]
    boxes = []
    for line in out.splitlines():
        p = line.split()
        if len(p) == 7 and not line.startswith("#"):
            b = list(map(int, p[1:]))
            boxes.append((math.hypot((b[0] + b[3]) / 2 - st[0], (b[2] + b[5]) / 2 - st[2]), b))
    spots[q["id"]] = [b for _, b in sorted(boxes)[:3]]
    save()
    return spots[q["id"]]


def legend_prog(name, qid):
    return S.setdefault("legend", {}).setdefault(name, {}).setdefault(qid, {"relics": [], "done": False})


def relic_item(q, i):
    nm = snbt_text({"text": f"{q['relic']} ({i + 1}/3)", "color": q["color"], "italic": False})
    lore = snbt_text({"text": f"Bring all three to the Legend Shrine to call {q['name']}.", "color": "gray"})
    return (f"minecraft:feather[minecraft:custom_name={nm},minecraft:lore=[{lore}],"
            f"minecraft:enchantment_glint_override=true,minecraft:custom_data={{cvrelic:\"{q['id']}\"}}] 1")


def legend_cmd(name, args):
    pos = player_pos(name)
    if args and args[0] == "call":
        if name in S.get("legend_active", {}):
            bar(name, t("A legendary you called is still here. Catch it or wait for it to leave.", "yellow"))
        elif not on_shrine(pos, reach=3):
            bar(name, t("Stand on the quartz of the Legend Shrine to call a legendary.", "yellow"))
        else:
            legend_summon(name, args[1] if len(args) > 1 else None)
        return
    tell(name, [t("Legend Quest: ", "dark_purple", bold=True),
                t("find three relics for a legendary, then stand on the quartz of the Legend Shrine next to the "
                  "station (waypoint added).", "white")], prefix="[Legend] ", color="dark_purple")
    waypoint(name, "Legend Shrine", "LS", *SHRINE, 13)
    for q in LEGENDS:
        p = legend_prog(name, q["id"])
        spots = legend_spots(q)
        if p["done"]:
            line = [t(f"{q['name']}: ", q["color"]), t("caught. ", "green")]
        elif len(p["relics"]) >= 3:
            line = [t(f"{q['name']}: ", q["color"]), t("3/3 relics. Go to the Legend Shrine!", "light_purple")]
        else:
            line = [t(f"{q['name']}: ", q["color"]), t(f"{len(p['relics'])}/3 {q['relic']}s", "white")]
            todo = [(i, b) for i, b in enumerate(spots) if i not in p["relics"]]
            if todo and pos and pos[0] == "overworld":
                i, b = min(todo, key=lambda ib: math.hypot((ib[1][0] + ib[1][3]) / 2 - pos[1], (ib[1][2] + ib[1][5]) / 2 - pos[3]))
                d, dist = bearing(pos[1], pos[3], (b[0] + b[3]) / 2, (b[2] + b[5]) / 2)
                line.append(t(f"; the nearest rests in one of the {q['where']}, about {round(dist, -2):.0f} m {d} of you.", "gray"))
            elif not spots:
                line.append(t(f"; none of the {q['where']} has been found yet. Explore and check again.", "gray"))
        tell(name, line, prefix=" • ", color="dark_purple")


def legend_tick():
    """Every 5 s: relic pickups inside structures, the shrine, and summoned legendaries."""
    for name in list(ONLINE):
        pos = player_pos(name)
        if not pos or pos[0] != "overworld":
            continue
        _, px, py, pz = pos
        for q in LEGENDS:
            p = legend_prog(name, q["id"])
            if p["done"] or len(p["relics"]) >= 3:
                continue
            for i, b in enumerate(S.get("legend_spots", {}).get(q["id"], [])):
                if i in p["relics"]:
                    continue
                if b[0] - 4 <= px <= b[3] + 4 and b[2] - 4 <= pz <= b[5] + 4 and b[1] - 40 <= py <= b[4] + 10:
                    # Wide vertical margin: a structure start saved before its chunk generates (shipwrecks) can
                    # carry a y 30 or more blocks off from where the structure is finally placed.
                    p["relics"].append(i)
                    save()
                    rc(f"give {name} {relic_item(q, len(p['relics']) - 1)}")  # numbered by how many they have
                    snd(name, "minecraft:block.amethyst_block.resonate", 1.4)
                    rc(f"title {name} times 5 50 15")
                    rc(f"title {name} title " + json.dumps({"text": q["relic"], "color": q["color"], "bold": True}))
                    rc(f"title {name} subtitle " + json.dumps({"text": f"Relic {len(p['relics'])}/3 for {q['name']}",
                                                               "color": "white"}))
                    news(f"{name} found a {q['relic']}")
        if math.hypot(px - SHRINE[0] - 0.5, pz - SHRINE[2] - 0.5) < 1.2 and abs(py - SHRINE[1]) < 1.5:
            legend_summon(name)
        m = re.search(r"has (\d+) \[", rc(f"scoreboard players get {name} cv_legend"))
        if m and int(m.group(1)):
            rc(f"scoreboard players set {name} cv_legend 0")
            k = int(m.group(1)) - 1
            if 0 <= k < len(LEGENDS):
                legend_cmd(name, ["call", LEGENDS[k]["id"]])
    for name, s in list(S.get("legend_active", {}).items()):
        legend_watch(name, s)


def on_shrine(pos, reach=1.2):
    return bool(pos) and pos[0] == "overworld" and math.hypot(pos[1] - SHRINE[0] - 0.5, pos[3] - SHRINE[2] - 0.5) < reach \
        and abs(pos[2] - SHRINE[1]) < 1.5


def legend_menu(name, ready):
    """With relics for several legendaries, let the player click which one to call."""
    if time.time() - LAST_CMD.get((name, "shrine_menu"), 0) < 20:
        return
    LAST_CMD[(name, "shrine_menu")] = time.time()
    tell(name, [t("The shrine answers several relics. Click the legendary to call:", "light_purple")],
         prefix="[Legend] ", color="dark_purple")
    # /legend takes no arguments in the fix mod, so the click uses a trigger objective that any player may set.
    rc(f"scoreboard players enable {name} cv_legend")
    rc(f"tellraw {name} " + json.dumps([{"text": " "}] + [
        {"text": f"[{q['name']}] ", "color": q["color"], "bold": True,
         "clickEvent": {"action": "run_command", "value": f"/trigger cv_legend set {LEGENDS.index(q) + 1}"},
         "hoverEvent": {"action": "show_text", "contents": f"Call {q['name']}"}} for q in ready], separators=(",", ":")))


def legend_summon(name, pick=None):
    if name in S.setdefault("legend_active", {}):
        return
    ready = [q for q in LEGENDS if not legend_prog(name, q["id"])["done"] and len(legend_prog(name, q["id"])["relics"]) >= 3]
    if pick:
        q = next((q for q in ready if q["id"] == pick), None)
        if not q:
            bar(name, t("You don't have three relics for that legendary.", "red"))
            return
    elif len(ready) > 1:
        legend_menu(name, ready)
        return
    else:
        q = ready[0] if ready else None
    if not q:
        if time.time() - LAST_CMD.get((name, "shrine"), 0) > 30:
            LAST_CMD[(name, "shrine")] = time.time()
            bar(name, t(f"The shrine is silent. Bring three relics of one legendary ({C('legend')}).", "gray"))
        return
    lv = min(q["level"], max(30, level_cap(name) + 10))
    tag = "cvlg_" + re.sub(r"[^a-z0-9]", "", name.lower())[:12]
    x, y, z = SHRINE
    rc(f"clear {name} minecraft:feather[minecraft:custom_data={{cvrelic:\"{q['id']}\"}}]")
    rc(f"execute in minecraft:overworld run particle minecraft:end_rod {x + 0.5} {y + 1} {z + 0.5} 1 2 1 0.05 120")
    rc("execute as @a at @s run playsound minecraft:entity.wither.spawn master @s ~ ~ ~ 0.6 1.4")
    nm = {"text": f"{q['name']} (called by {name})", "color": q["color"]}
    if not spawn_tagged(q["id"], f"level={lv}", x + 4, y - 1, z, tag, nm, glow=True):
        bar(name, t("The relics glowed, but nothing came. Try again in a moment.", "red"))
        return
    S["legend_active"][name] = {"q": q["id"], "tag": tag, "until": time.time() + 900, "had": legend_has(name, q["id"])}
    legend_prog(name, q["id"])["called"] = time.time()
    save()
    tell("@a", [t(f"{name} offered three {q['relic']}s at the Legend Shrine, and {q['name']} answered! ", q["color"],
                  bold=True), t("Battle it to catch it; it leaves in 15 minutes.", "white")], prefix="[Legend] ",
         color="dark_purple")
    news(f"{name} called {q['name']} at the Legend Shrine")


def legend_has(name, sp):
    return sum(1 for m in mons(name) if sp_of(m) == sp)


def legend_watch(name, s):
    q = next(q for q in LEGENDS if q["id"] == s["q"])
    near = "passed" in rc(f"execute in minecraft:overworld positioned {SHRINE[0]} {SHRINE[1]} {SHRINE[2]} "
                          f"if entity @a[distance=..64]")
    gone = near and not alive(s["tag"])
    if not gone and time.time() < s["until"]:
        return
    if not gone:
        if not despawn(s["tag"]):
            return  # someone is battling it right next to it
    fresh_save(force=True)
    caught = legend_has(name, q["id"]) > s["had"]
    if not caught:
        # fresh_save runs at most once a minute, so a catch can be missing from the saved party for a while.
        # Keep checking for 90 s before calling it an escape.
        s.setdefault("check_until", time.time() + 90)
        if time.time() < s["check_until"]:
            return
    S["legend_active"].pop(name, None)
    if caught:
        legend_prog(name, q["id"])["done"] = True
        save()
        fireworks(name, 6) if name in ONLINE else None
        add_points(name, 15)
        tell("@a", [t(f"{name} caught {q['name']}! ", q["color"], bold=True), t("+15 season points.", "yellow")],
             prefix="[Legend] ", color="dark_purple")
    else:
        save()
        tell("@a", [t(f"{q['name']} slipped away from {name}. The relics' power remains: stand on the shrine again to "
                      "call it.", "gray")], prefix="[Legend] ", color="dark_purple")


# ---------- Night Market ----------
# Every in-game night a Night Merchant sets up next to the Legend Shrine with five night-themed offers for
# emeralds, and leaves at dawn.

NIGHT_GOODS = [("cobblemon:moon_stone", 1, 10), ("cobblemon:dusk_stone", 1, 10), ("cobblemon:reaper_cloth", 1, 12),
               ("cobblemon:razor_fang", 1, 12), ("cobblemon:razor_claw", 1, 12), ("cobblemon:dusk_ball", 8, 5),
               ("cobblemon:moon_ball", 8, 5), ("cobblemon:spell_tag", 1, 8), ("cobblemon:black_glasses", 1, 8),
               ("cobblemon:black_augurite", 1, 14), ("cobblemon:dawn_stone", 1, 12), ("cobblemon:shiny_stone", 1, 12),
               ("cobblemon:exp_candy_l", 3, 9), ("cobblemon:ability_capsule", 1, 20)]
NIGHT_SPOT = (-3047.5, 65, -1285.5)


def night_tick():
    m = re.search(r"(\d+)", rc("time query daytime"))
    if not m:
        return
    t_ = int(m.group(1)) % 24000
    night = 13000 <= t_ < 23000
    here = "passed" in rc("execute if entity @e[tag=cvnight]")
    if night and ONLINE and not here and S.get("night_market") != int(rc_day()):
        S["night_market"] = int(rc_day())
        save()
        offers = random.sample(NIGHT_GOODS, 5)
        recipes = ",".join(
            f'{{buy:{{id:"minecraft:emerald",count:{price}}},sell:{{id:"{item}",count:{cnt}}},maxUses:2,rewardExp:0b}}'
            for item, cnt, price in offers)
        nm = snbt_text({"text": "Night Merchant", "color": "dark_purple"})
        x, y, z = NIGHT_SPOT
        rc(f"execute in minecraft:overworld run summon minecraft:wandering_trader {x} {y} {z} {{Tags:[\"cvnight\"],"
           f"CustomName:{nm},CustomNameVisible:1b,NoAI:1b,Invulnerable:1b,PersistenceRequired:1b,DespawnDelay:0,"
           f"Rotation:[90f,0f],Offers:{{Recipes:[{recipes}]}}}}")
        rc(f"execute in minecraft:overworld run setblock {int(x - 0.5)} {y} {int(z - 0.5) + 1} minecraft:soul_lantern keep")
        goods = ", ".join(item_name(i) for i, _, _ in offers)
        if S.get("night_announced") != today():
            S["night_announced"] = today()
            save()
            tell("@a", [t("The Night Merchant opened a stall by the Legend Shrine: ", "dark_purple"), t(goods, "light_purple"),
                        t(" for emeralds, until dawn. It comes back every night.", "dark_purple")], prefix="[Night] ",
                 color="dark_purple")
        else:
            st = CONFIG["station"]
            rc(f"execute in minecraft:overworld positioned {st[0]} {st[1]} {st[2]} as @a[distance=..150] run title @s "
               "actionbar " + json.dumps([t("The Night Merchant is open by the Legend Shrine.", "dark_purple")]))
    elif not night and here:
        rc("kill @e[tag=cvnight]")
        x, y, z = NIGHT_SPOT
        rc(f"execute in minecraft:overworld if block {int(x - 0.5)} {y} {int(z - 0.5) + 1} minecraft:soul_lantern run "
           f"setblock {int(x - 0.5)} {y} {int(z - 0.5) + 1} minecraft:air")


def rc_day():
    m = re.search(r"(\d+)", rc("time query day"))
    return m.group(1) if m else "0"


# ---------- Itemfinder ----------
# Every player gets an Itemfinder (a carrot on a stick). Using it beeps on the action bar: more bars and a higher
# pitch the closer the nearest of today's five hidden items is, with the direction. Standing within 2.5 blocks of it
# and using the Itemfinder digs the item up. The five spots are picked 60-200 blocks around where the player first
# uses it each day; nothing is placed in the world.

FINDER = ("minecraft:carrot_on_a_stick[minecraft:custom_name='{\"text\":\"Itemfinder\",\"color\":\"aqua\",\"italic\":false}',"
          "minecraft:lore=['{\"text\":\"Use it to search for hidden items nearby\",\"color\":\"gray\"}'],"
          "minecraft:unbreakable={},minecraft:custom_data={cvfinder:1b}] 1")
FINDER_LOOT = ([("cobblemon:rare_candy", 1, 4), ("cobblemon:exp_candy_m", 2, 6), ("cobblemon:exp_candy_l", 1, 3),
                ("obc:bottle_cap", 1, 1), ("cobblemon:ability_capsule", 1, 1), ("cobblemon:pp_up", 1, 3),
                ("cobblemon:relic_coin", 2, 4), ("minecraft:emerald", 3, 5), ("minecraft:diamond", 1, 2)]
               + [(e, 1, 1) for e in rewards.EVOLUTION] + [(b, 4, 1) for b in rewards.BALLS]
               + [(b, 3, 1) for b in rewards.BERRIES])


def finder_spots(name, pos):
    f = S.setdefault("finder", {}).get(name)
    if f and f["day"] == today():
        return f
    spots = []
    for _ in range(5):
        a, r = random.uniform(0, 2 * math.pi), random.uniform(60, 200)
        item, cnt, _ = random.choices(FINDER_LOOT, weights=[w for _, _, w in FINDER_LOOT])[0]
        spots.append([int(pos[1] + math.cos(a) * r), int(pos[3] + math.sin(a) * r), item, cnt, False])
    S["finder"][name] = {"day": today(), "spots": spots}
    save()
    tell(name, [t("Your Itemfinder picked up five signals within 200 blocks. Use it to follow the beeps.", "aqua")],
         prefix="[Itemfinder] ", color="aqua")
    return S["finder"][name]


def finder_ping(name):
    pos = player_pos(name)
    if not pos or pos[0] != "overworld":
        bar(name, t("The Itemfinder only works in the Overworld.", "gray"))
        return
    used(name, "finder")
    f = finder_spots(name, pos)
    left = [s for s in f["spots"] if not s[4]]
    if not left:
        bar(name, t("No more signals today. The Itemfinder finds new ones tomorrow.", "gray"))
        return
    s = min(left, key=lambda s: math.hypot(s[0] - pos[1], s[1] - pos[3]))
    dist = math.hypot(s[0] - pos[1], s[1] - pos[3])
    if dist <= 2.5:
        s[4] = True
        save()
        give(name, s[2], s[3])
        rc(f"execute at {name} run particle minecraft:happy_villager ~ ~0.5 ~ 0.6 0.3 0.6 0 25")
        snd(name, "minecraft:block.rooted_dirt.break", 0.8)
        snd(name, "minecraft:entity.player.levelup", 1.6)
        bar(name, [t("You dug up ", "white"), t(f"{s[3]} {item_name(s[2])}", "gold"),
                   t(f"! {len(left) - 1} signal{'s' if len(left) != 2 else ''} left today.", "white")])
        return
    k = max(1, 5 - int(dist // 40))
    d, _ = bearing(pos[1], pos[3], s[0], s[1])
    near = "right under your feet" if dist < 6 else f"{round(dist)} m to the {d}"
    bar(name, [t("Beep ", "aqua"), t("▮" * k + "▯" * (5 - k), "green" if k >= 4 else "yellow"), t(f"  {near}", "white")])
    snd(name, "minecraft:block.note_block.bit", 0.5 + 0.3 * k)


def finder_poll():
    """Every second: who used a carrot on a stick, and was it the Itemfinder."""
    while True:
        time.sleep(1)
        if not ONLINE or "passed" not in rc("execute if entity @a[scores={cv_use=1..}]"):
            continue
        with LOCK:
            for n in list(ONLINE):
                if re.search(r"has [1-9]\d* \[", rc(f"scoreboard players get {n} cv_use")):
                    rc(f"scoreboard players set {n} cv_use 0")
                    held = rc(f"execute if entity @a[name={n},nbt={{SelectedItem:{{components:{{\"minecraft:custom_data\":"
                              f"{{cvfinder:1b}}}}}}}}]")
                    if "passed" in held:
                        try:
                            finder_ping(n)
                        except Exception as e:
                            log("finder", repr(e))


def finder_give(name):
    if name in S.setdefault("finder_given", []):
        return
    S["finder_given"].append(name)
    save()
    rc(f"give {name} {FINDER}")
    tell(name, [t("You got an Itemfinder! ", "aqua", bold=True),
                t("Five items are hidden around you every day. Hold it and right-click to search.", "white")],
         prefix="[Itemfinder] ", color="aqua")


# ---------- Pokémon requests ----------
# Now and then a party Pokémon asks for something that fits its type: a biome, a height, the night or the rain.
# Doing it within 45 minutes raises its friendship by 30 and gives a small bundle. At most two a day per player.

REQUESTS = [
    ({"fire"}, "wants to warm up in a desert or badlands", "biome", ["desert", "badlands", "arid", "volcanic"]),
    ({"water"}, "wants to splash around by the sea", "biome", ["ocean", "warm ocean", "coast", "beach"]),
    ({"grass", "fairy"}, "wants to roll around in a field of flowers", "biome", ["floral", "floral meadow", "cherry blossom"]),
    ({"bug", "grass"}, "wants to explore a forest or jungle", "biome", ["forest", "jungle", "bamboo"]),
    ({"ice"}, "wants to play in the snow", "biome", ["snowy forest", "snowy taiga", "tundra", "glacial", "freezing"]),
    ({"poison", "dark"}, "wants to wade through a swamp", "biome", ["swamp"]),
    ({"flying", "dragon"}, "wants to feel the wind somewhere high (above height 140)", "high", 140),
    ({"rock", "ground", "steel"}, "wants to explore deep underground (below height 30)", "low", 30),
    ({"ghost", "dark", "psychic", "fairy"}, "wants a walk under the night sky", "night", None),
    ({"electric", "water"}, "wants to feel the rain", "rain", None),
    ({"normal", "fighting", "psychic"}, "wants to visit the village", "village", None),
]


def request_check(name, r, pos):
    kind, param = r["kind"], r["param"]
    _, x, y, z = pos
    if kind == "biome":
        return any("passed" in rc(f"execute in minecraft:overworld if biome {int(x)} {int(y)} {int(z)} "
                                  f"#cobblemon:is_{b.replace(' ', '_')}") for b in param)
    if kind == "high":
        return y >= param
    if kind == "low":
        return y <= param
    if kind == "night":
        m = re.search(r"(\d+)", rc("time query daytime"))
        return bool(m) and 13000 <= int(m.group(1)) % 24000 < 23000 and y >= 55
    if kind == "rain":
        return "passed" in rc("execute if predicate cvlife:raining")
    st = CONFIG["station"]
    return math.hypot(x - st[0], z - st[2]) < 48


def requests_tick():
    reqs = S.setdefault("requests", {})
    for name in list(ONLINE):
        r = reqs.get(name)
        if r and time.time() > r["until"]:
            reqs.pop(name)
            save()
            bar(name, t(f"{r['label']} gave up on its wish for now.", "gray"))
            continue
        pos = player_pos(name)
        if not pos or pos[0] != "overworld":
            continue
        if not r:
            day = S.setdefault("requests_day", {}).get(name, {})
            if day.get("day") != today():
                day = {"day": today(), "n": 0, "last": 0}
            if day["n"] >= 2 or time.time() - day["last"] < 5400 or random.random() > 0.2:
                continue
            p = party(name)
            if not p:
                continue
            slot = random.choice(sorted(p))
            m = p[slot]
            sp = sp_of(m)
            types = set(INFO.get(sp, {}).get("t", []))
            fits = [q for q in REQUESTS if q[0] & types] or [REQUESTS[-1]]
            _, text, kind, param = random.choice(fits)
            label = str(m.get("Nickname") or species_name(sp))
            if label.startswith("{"):
                label = species_name(sp)
            reqs[name] = {"uuid": m.get("UUID"), "label": label, "text": text, "kind": kind, "param": param,
                          "until": time.time() + 2700}
            day.update(n=day["n"] + 1, last=time.time())
            S["requests_day"][name] = day
            save()
            tell(name, [t(f"{label} tugs at your sleeve: ", "light_purple"), t(f"it {text}.", "white"),
                        t(" (45 minutes)", "gray")], prefix="[Partner] ", color="light_purple")
            snd(name, "minecraft:entity.allay.ambient_with_item", 1.2)
            continue
        if not request_check(name, r, pos):
            continue
        p = party(name)
        slot = next((k for k, v in p.items() if v.get("UUID") == r["uuid"]), None)
        if slot is None:
            continue  # not in the party right now
        f = int(p[slot].get("Friendship", 0))
        rc(f"pokemoneditother {name} {slot + 1} friendship={min(255, f + 30)}")
        reqs.pop(name)
        save()
        got = rewards.mixed(name, 1)
        tell(name, [t(f"{r['label']} is overjoyed! ", "light_purple", bold=True),
                    t(f"+30 friendship, and it found {prize_text(got)} for you.", "white")], prefix="[Partner] ",
             color="light_purple")
        rc(f"execute at {name} run particle minecraft:heart ~ ~1.5 ~ 0.6 0.4 0.6 0 8")
        snd(name, "minecraft:entity.player.levelup", 1.4)


# ---------- Fishing Hole ----------
# Once a day from 08:00, bubbles mark a spot of open water 300-1000 m from the village with four rare water
# Pokémon of species that live in that water. Everyone gets a waypoint; whoever gets there first catches them.

FH_BIOMES = ["warm ocean", "lukewarm ocean", "cold ocean", "frozen ocean", "deep ocean", "ocean", "river",
             "freshwater", "swamp", "coast", "beach"]


def fishing_new():
    st = CONFIG["station"]
    for _ in range(8):
        a, r = random.uniform(0, 2 * math.pi), random.uniform(300, 1000)
        x, z = int(st[0] + math.cos(a) * r), int(st[2] + math.sin(a) * r)
        hold(x, z)
        time.sleep(3)
        ok = all("passed" in rc(f"execute in minecraft:overworld if block {x} {yy} {z} minecraft:water") for yy in (61, 62)) \
            and "passed" in rc(f"execute in minecraft:overworld if block {x} 63 {z} minecraft:air")
        if ok:
            break
        release(x, z)
    else:
        return False
    found = [b for b in FH_BIOMES if "passed" in rc(f"execute in minecraft:overworld if biome {x} 62 {z} "
                                                     f"#cobblemon:is_{b.replace(' ', '_')}")]
    cap = max([level_cap(n) for n in ONLINE] or [30])
    pool = {}
    for sp, entries in SPAWNS.items():
        if SPECIAL & set(INFO.get(sp, {}).get("l", [])):
            continue
        for e in entries:
            if e["bucket"] not in ("rare", "ultra-rare") or e.get("pos") not in ("fishing", "submerged", "surface"):
                continue
            if set(e["biomes"]) & set(found):
                lo = int(e["level"].split("-")[0]) if e.get("level") else 10
                if lo <= cap:
                    pool[sp] = max(pool.get(sp, 0), lo)
    if len(pool) < 2:
        release(x, z)
        log("fishing hole: no species for", found, "at", x, z)
        return False
    picks = random.sample(sorted(pool), min(4, len(pool)))
    for i, sp in enumerate(picks):
        lv = max(pool[sp], random.randint(max(5, cap - 10), max(5, cap - 3)))
        props = f"level={min(lv, max(pool[sp], cap))}" + (" shiny=yes" if random.random() < 1 / 64 else "")
        if spawn_tagged(sp, props, x + random.randint(-2, 2), 60, z + random.randint(-2, 2), f"cvfh{i}", glow=False):
            rc(f"tag @e[tag=cvfh{i}] add cvfh")
    left = count_tag("cvfh")
    release(x, z)
    if not left:
        return False
    S["fishing"] = {"day": today(), "pos": [x, 62, z], "species": picks, "left": left}
    save()
    d, dist = bearing(st[0], st[2], x, z)
    news("A Fishing Hole bubbled up")
    tell("@a", [t("FISHING HOLE! ", "aqua", bold=True),
                t(f"Bubbles rose on the water about {round(dist, -2):.0f} m {d} of the village. {left} rare water "
                  "Pokémon gathered there. Waypoint added.", "white")], prefix="[Fishing] ", color="aqua")
    for p in ONLINE:
        waypoint(p, "Fishing Hole", "F", x, 63, z, 3)
    return True


def fishing_end():
    f = S.get("fishing")
    if not f:
        return
    hold(f["pos"][0], f["pos"][2])
    time.sleep(3)
    rc("execute as @e[tag=cvfh] run tp @s ~ -200 ~")
    rc("execute as @e[tag=cvfh] run kill @s")
    release(f["pos"][0], f["pos"][2])
    S["fishing"] = None
    save()


def fishing_tick():
    f = S.get("fishing")
    if f and f["day"] != today():
        fishing_end()
        f = None
    if not f:
        if ONLINE and S.get("fishing_day") != today() and now().hour >= 8:
            S["fishing_day"] = today()
            save()
            fishing_new()
        return
    x, y, z = f["pos"]
    near = [(math.hypot(pp[1] - x, pp[3] - z), p) for p in ONLINE for pp in [player_pos(p)]
            if pp and pp[0] == "overworld" and math.hypot(pp[1] - x, pp[3] - z) < 64]
    if not near:
        return
    left = count_tag("cvfh")
    if left < f["left"]:
        f["left"] = left
        used(min(near)[1], "fishing")
        save()
        tell("@a", [t(f"{min(near)[1]} landed a Pokémon at the Fishing Hole" +
                      (f"; {left} left." if left else ", and it went quiet."), "white")], prefix="[Fishing] ", color="aqua")
        if not left:
            fishing_end()


def fishing_bubbles():
    f = S.get("fishing")
    if f:
        x, y, z = f["pos"]
        rc(f"execute in minecraft:overworld positioned {x} {y} {z} if entity @a[distance=..64] run particle "
           f"minecraft:splash ~ ~1 ~ 2 0 2 0.3 60")
        rc(f"execute in minecraft:overworld positioned {x} {y} {z} if entity @a[distance=..64] run particle "
           f"minecraft:bubble_pop ~ ~1 ~ 2 0 2 0.05 30")


# ---------- Team Expedition ----------
# A weekly goal the whole group works on at any time: catch Pokémon of one type, catch any Pokémon, walk, beat
# trainers or register new species. Progress counts from the first time each player is checked that week.
# When the team reaches the goal everyone who took part gets 5 Rare Candy, 500 CobbleDollars and a bundle.

EXPEDITIONS = [("type", 12, "Catch {n} {ty}-type Pokémon"), ("catch", 40, "Catch {n} Pokémon"),
               ("walk", 25000, "Walk {km} km"), ("trainers", 12, "Beat {n} trainers"), ("dex", 15, "Register {n} new species")]
EXP_TYPES = ["bug", "water", "grass", "fire", "normal", "flying", "poison", "electric", "ground", "rock", "psychic",
             "fighting", "dark", "fairy", "steel", "ghost", "ice", "dragon"]


def expedition():
    e = S.get("expedition")
    if e and e["week"] == week_key():
        return e
    kind, n, text = random.choice(EXPEDITIONS)
    ty = random.choice(EXP_TYPES)
    if kind == "type" and ty in ("ghost", "ice", "dragon", "steel", "fairy", "dark", "fighting"):
        n = 6
    label = text.format(n=n, ty=TYPES.get(ty, ty.title()), km=n // 1000) + " together"
    S["expedition"] = {"week": week_key(), "kind": kind, "type": ty, "goal": n, "text": label, "base": {}, "last": {},
                       "team_base": len(shared_dex()) if kind == "dex" else 0, "done": False, "half": False}
    save()
    tell("@a", [t("New Team Expedition: ", "gold", bold=True), t(label + " this week.", "white")],
         prefix="[Expedition] ", color="gold")
    return S["expedition"]


def expedition_value(name, e, snap):
    if e["kind"] == "type":
        return snap["types"].get(e["type"], 0)
    if e["kind"] == "catch":
        return snap["catch"]
    if e["kind"] == "walk":
        return snap["walk"]
    if e["kind"] == "trainers":
        m = re.search(r"(\d+)\s*$", rc(f"rctmod player get type_defeats normal {name}"))
        return int(m.group(1)) if m else 0
    return 0


def expedition_progress(e):
    if e["kind"] == "dex":
        return max(0, len(shared_dex()) - e["team_base"])
    return sum(max(0, e["last"].get(n, b) - b) for n, b in e["base"].items())


def expedition_tick(snaps):
    e = expedition()
    if e["done"]:
        return
    for n, snap in snaps.items():
        v = expedition_value(n, e, snap)
        e["base"].setdefault(n, v)
        e["last"][n] = v
    prog = expedition_progress(e)
    save()
    if not e["half"] and prog * 2 >= e["goal"]:
        e["half"] = True
        save()
        tell("@a", [t(f"Team Expedition halfway: {prog}/{e['goal']}.", "gold")], prefix="[Expedition] ", color="gold")
    if prog >= e["goal"]:
        e["done"] = True
        save()
        team = set(e["base"]) | (set(S["seen"]) if e["kind"] == "dex" else set())
        for n in team:
            give(n, "cobblemon:rare_candy", 5)
            give(n, random.choice(rewards.EVOLUTION), 1)
            rc(f"cobbledollars give {n} 500")
            if n in ONLINE:
                fireworks(n, 3)
        news(f"The team finished the expedition: {e['text']}")
        tell("@a", [t("TEAM EXPEDITION COMPLETE! ", "gold", bold=True),
                    t(f"{e['text']}: done. Everyone gets 5 Rare Candy, an evolution item and $500.", "white")],
             prefix="[Expedition] ", color="gold")


# ---------- Partner Walk ----------
# A Pokémon sent out next to its trainer counts the distance they walk together. Every 1000 m it gains 15
# friendship; at 10 km it becomes the player's Partner: full friendship, a Soothe Bell and an announcement.

def partner_tick():
    km = S.setdefault("partner_km", {})
    last = S.setdefault("partner_last", {})
    for name in list(ONLINE):
        pos = player_pos(name)
        if not pos or pos[0] != "overworld":
            continue
        u = re.search(r"\[I;\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+)\]", rc(f"data get entity {name} UUID"))
        if not u:
            continue
        arr = ",".join(u.groups())
        out = rc(f"execute as {name} at @s as @e[type=cobblemon:pokemon,distance=..24,limit=1,sort=nearest,"
                 f"nbt={{Owner:[I;{arr}]}}] run data get entity @s Pokemon.UUID")
        m = re.search(r"\[I;\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+)\]", out)
        walked = travelled(name)
        prev = last.get(name)
        last[name] = {"uuid": list(map(int, m.groups())) if m else None, "walk": walked}
        if m:
            used(name, "partner")
        if not m or not prev or prev["uuid"] != last[name]["uuid"]:
            continue
        step_m = max(0, min(600, walked - prev["walk"]))
        if not step_m:
            continue
        key = ",".join(m.groups())
        before = km.get(key, 0)
        after = before + step_m
        km[key] = after
        if int(after // 1000) > int(before // 1000):
            p = party(name)
            slot = next((k for k, v in p.items() if v.get("UUID") == last[name]["uuid"]), None)
            label = species_name(sp_of(p[slot])) if slot is not None else "Your Pokémon"
            done = int(after // 1000)
            if slot is not None:
                f = int(p[slot].get("Friendship", 0))
                rc(f"pokemoneditother {name} {slot + 1} friendship={255 if done >= 10 else min(255, f + 15)}")
            if done == 10:
                give(name, "cobblemon:soothe_bell", 1)
                tell("@a", [t(f"{name} and {label} have walked 10 km together. {label} is now {name}'s Partner!", "gold")],
                     prefix="[Partner] ", color="light_purple")
                fireworks(name, 3)
            else:
                bar(name, [t(f"{label} loved the walk: ", "light_purple"), t(f"{done} km together, +15 friendship", "white")])
                rc(f"execute at {name} run particle minecraft:heart ~ ~1.5 ~ 0.5 0.3 0.5 0 4")
    save()


# ---------- feature guide ----------
# Players forget features exist and new players never hear of them. Every player gets a guidebook (again with
# /guide). cvlife remembers which features each player has used; on join, and at most twice more a day while
# playing, it shows one tip for a feature they haven't tried, and a few tips come up where they matter (far from
# home, next to the shrine, at the station).

GUIDE_TIPS = [
    ("world", "world", "Type {c} for today's quest, bounty, rank, your next gym and what is happening in the world."),
    ("fly", "fly", "{c} flies you to gyms you have beaten, landmarks, home (free) and other online players."),
    ("finder", None, "Hold your Itemfinder and right-click: five items are hidden around you every day."),
    ("legend", "legend", "{c} shows the Legend Quest: three relics call Articuno, Moltres, Zapdos, Lugia or Ho-Oh."),
    ("tower", "tower", "{c} starts a Battle Tower run: one trainer per floor and a reward for every floor."),
    ("grotto", None, "A Hidden Grotto with three hidden-ability Pokémon appears every day; {w} has the hint."),
    ("fishing", None, "A Fishing Hole with rare water Pokémon bubbles up every day; {w} says where."),
    ("partner", None, "Send a Pokémon out and walk together: every 1 km raises its friendship, 10 km makes it your Partner."),
    ("goal", "goal", "{c} <pokemon> tracks a Pokémon and tells you where and when it spawns."),
    ("trade", "trade", "{c} <slot> sends a party Pokémon into Wonder Trade for a random one (3 a day)."),
    ("delicacy", None, "Regional delicacies from the Campfire Pot each have their own effect; cook all ten for a prize."),
    ("night", None, "At night a Night Merchant sells evolution items by the Legend Shrine, next to the station."),
    ("village", None, "Poké Balls in the village chest at the station level the village up: a Poké Mart comes at 128."),
    ("challenge", "challenge", "{c} sets a rule for your gym run (one type, or no Master Ball) for a special badge."),
]
GUIDE_PAGES = [
    "COBBLEVERSE\n\nThis book lists what the server adds. Get a new copy any time with /guide.\n\n/world shows "
    "your quest, rank, next gym and today's events in one place.",
    "TRAVEL\n\n/home: back to the station.\n\n/fly: a Pidgeot flies you to gyms you have beaten and to landmarks, "
    "for CobbleDollars.\n\nLandmarks: the first to find one names it.",
    "EVERY DAY\n\nItemfinder: right-click it; five items are hidden around you.\n\nHidden Grotto: three Pokémon "
    "with hidden abilities.\n\nFishing Hole: rare water Pokémon.\n\nMass outbreaks every hour or two.",
    "BATTLES\n\nGyms: /world points to the next one.\n\n/tower: Battle Tower, one trainer a floor.\n\n/challenge: "
    "a rule for your gym run.\n\nRaids, Team Rocket and story bosses come to the village.",
    "LEGENDS\n\n/legend: find three relics for a legendary (igloos, ruined portals, shipwrecks, trail ruins, ancient "
    "cities), then stand on the quartz of the Legend Shrine by the station.",
    "YOUR POKéMON\n\nWalk with a Pokémon sent out: friendship up every 1 km.\n\nPokémon ask for things now and then; "
    "do it for friendship.\n\n/goal <pokemon>: where it spawns.\n\n/trade <slot>: Wonder Trade.",
    "THE VILLAGE\n\nPut Poké Balls in the village chest at the station to level the village: a Poké Mart, a Daycare, "
    "a Battle Court.\n\nNight Merchant: at night by the shrine.\n\nTeam Expedition: a weekly goal for everyone.",
]


def used(name, key):
    u = S.setdefault("used", {}).setdefault(name, [])
    if key not in u:
        u.append(key)
        save()


def guide_book(name):
    """The book is longer than one rcon command can be, so it lives in the world datapack (cvlife:guide)."""
    rc(f"execute as {name} run function cvlife:guide")


def guide_function():
    """The give command for dp/cvlife/data/cvlife/function/guide.mcfunction, from GUIDE_PAGES."""
    pages = ",".join(snbt_text({"text": p}) for p in GUIDE_PAGES)
    return ("give @s minecraft:written_book[minecraft:written_book_content={title:\"COBBLEVERSE Guide\","
            f"author:\"Server\",pages:[{pages}]}}] 1\n")


def guide_give(name):
    if name in S.setdefault("guide_given", []):
        return
    S["guide_given"].append(name)
    save()
    guide_book(name)


def tip_line(name, key, cmd, text):
    click = "run_command" if CONFIG.get("slash_commands") and cmd not in CONFIG.get("chat_only_commands", []) else "suggest_command"
    parts = [{"text": "[Tip] ", "color": "green", "bold": True}]
    body = text.replace("{w}", C("world"))
    if cmd and "{c}" in body:
        a, b = body.split("{c}", 1)
        parts += [{"text": a, "color": "white"}, {"text": C(cmd), "color": "aqua", "underlined": True,
                                                   "clickEvent": {"action": click, "value": C(cmd)}},
                  {"text": b, "color": "white"}]
    else:
        parts.append({"text": body, "color": "white"})
    rc(f"tellraw {name} " + json.dumps(parts, ensure_ascii=False))
    shown = S.setdefault("tips_shown", {}).setdefault(name, {})
    shown[key] = shown.get(key, 0) + 1
    save()


def next_tip(name):
    u = set(S.setdefault("used", {}).get(name, []))
    shown = S.setdefault("tips_shown", {}).get(name, {})
    cands = [tp for tp in GUIDE_TIPS if tp[0] not in u and shown.get(tp[0], 0) < 2]
    return min(cands, key=lambda tp: shown.get(tp[0], 0)) if cands else None


def guide_tick():
    """Every 5 minutes: one tip per player at most every 45 minutes, three a day including the join tip."""
    day = S.setdefault("tips_day", {})
    for name in list(ONLINE):
        d = day.get(name, {})
        if d.get("day") != today():
            d = {"day": today(), "n": 0, "last": time.time()}
        if d["n"] >= 3 or time.time() - d["last"] < 2700:
            day[name] = d
            continue
        pos = player_pos(name)
        st = CONFIG["station"]
        u = set(S.setdefault("used", {}).get(name, []))
        tip = None
        if pos and pos[0] == "overworld":
            dist = math.hypot(pos[1] - st[0], pos[3] - st[2])
            if dist > 800 and "fly" not in u:
                tip = ("fly", "fly", "Far from home? {c} 1 takes you home for free, and you can fly to gyms and landmarks.")
            elif dist < 24 and "legend" not in u:
                tip = next(tp for tp in GUIDE_TIPS if tp[0] == "legend")
        tip = tip or next_tip(name)
        if tip:
            tip_line(name, *tip)
            d.update(n=d["n"] + 1, last=time.time())
        day[name] = d
    save()


def step(fn, *a):
    """Run one feature under the lock; one feature failing doesn't stop the others. Logs waits and runs over 3 s."""
    t0 = time.time()
    with LOCK:
        t1 = time.time()
        try:
            return fn(*a)
        except Exception as e:
            log(fn.__name__, repr(e))
        finally:
            if time.time() - t0 > 3:
                log("slow", fn.__name__, f"waited {t1 - t0:.1f}s ran {time.time() - t1:.1f}s")


def periodic():
    last = {"check": 0, "fest": 0, "roam": time.time() - 1500, "dex": 0, "titles": 0, "giant": time.time() - 1800,
            "trader": S.get("trader_at", 0)}
    while True:
        time.sleep(60)
        tn = time.time()
        step(quest)
        step(season)
        step(story_week)
        step(bounty)
        step(rocket_tick)
        step(events_tick)
        step(trader_tick)
        step(outbreak_tick)
        step(grotto_tick)
        step(night_tick)
        step(fishing_tick)
        if not ONLINE:
            continue
        step(requests_tick)
        step(partner_tick)
        if not S.get("outbreak") and tn > S.get("outbreak_next", 0):
            S["outbreak_next"] = tn + random.randint(75, 120) * 60
            step(save)
            step(outbreak_start)
        if tn - last["check"] > 300:
            last["check"] = tn
            snaps = step(check_all, True) or {}
            step(expedition_tick, snaps)
            if tn - last["titles"] > 3600:
                last["titles"] = tn
                step(update_titles, snaps)
            step(village_check)
            step(challenger_check)
            step(guide_tick)
            step(context_tick)
        if tn - last["dex"] > 1800:
            last["dex"] = tn
            step(shared_dex)
        if tn - last["fest"] > 900:
            last["fest"] = tn
            step(festival_tick)
        if tn - last["roam"] > 1800:
            last["roam"] = tn
            step(roam)
        if tn - last["giant"] > 2700:
            last["giant"] = tn
            if random.random() < 0.5:
                step(giant)
        if tn - last["trader"] > 3 * 3600:
            last["trader"] = S["trader_at"] = tn
            step(save)
            step(trader)
        h = now().hour
        if (len(ONLINE) >= 2 and not S.get("rocket") and S.get("rocket_day") != today() and 16 <= h <= 22
                and random.random() < 0.08):
            S["rocket_day"] = today()
            step(save)
            step(rocket_raid)
        if (now().weekday() == 6 and h >= 19 and S.get("story_boss_done") != S.get("story_week")
                and "story" not in S["events"]):
            if step(story_boss):
                S["story_boss_done"] = S.get("story_week")
                step(save)
        if h >= CONFIG["journal_hour"] and S["journal_done"] != today():
            S["journal_done"] = today()
            step(save)
            step(journal)
        if h == CONFIG["raid_hour"] and S["raid_done"] != today() and len(ONLINE) >= 2:
            if step(coop_raid):
                S["raid_done"] = today()
                step(save)


def handle(msg):
    m = re.match(r"\[cvlife-cmd\] ([A-Za-z0-9_]{1,16}) (\S+)(?: (.*))?$", msg)
    if m:
        command(m.group(1), (m.group(2) + " " + (m.group(3) or "")).strip())
        return
    m = re.match(r"(?:\[Not Secure\] )?<(?:\[[^\]]*\] )*([A-Za-z0-9_]{1,16})> (!\S+.*)$", msg)
    if m:
        if not re.match(r"!(q|p)\b", m.group(2).lower()):
            command(m.group(1), m.group(2).strip())
        return
    msg = PREFIX.sub("", msg)
    m = re.match(r"([A-Za-z0-9_]{1,16}) joined the game$", msg)
    if m:
        on_join(m.group(1))
        return
    m = re.match(r"([A-Za-z0-9_]{1,16}) left the game$", msg)
    if m:
        ONLINE.discard(m.group(1))
        S["last_seen"][m.group(1)] = time.time()
        FLY_PENDING.pop(m.group(1), None)
        tower_end(m.group(1), "You left the server.")
        save()
        return
    m = re.match(r"([A-Za-z0-9_]{1,16}) has (?:made the advancement|reached the goal|completed the challenge) \[(.+?)\]$", msg)
    if m:
        adv = m.group(2)
        if "defeat_" in adv:
            fly_record(m.group(1), adv)
            label = label_of(adv)
            S.setdefault("beaten_adv", {}).setdefault(m.group(1), []).append(adv)
            save()
            if label:
                celebrate(m.group(1), label, champion="champion" in adv)
        if adv == "Culinary World Tour":
            culinary(m.group(1))
        lm = next((l for l in CONFIG["landmarks"] if adv in l.get("titles", [])), None)
        if lm:
            landmark_found(m.group(1), lm["id"])


def main():
    ONLINE.update(online_from_list())
    for n in ONLINE:
        if n not in S["seen"]:
            S["seen"].append(n)
    rc("scoreboard objectives add cvwalk minecraft.custom:minecraft.walk_one_cm")
    rc("scoreboard objectives add cvsprint minecraft.custom:minecraft.sprint_one_cm")
    rc("scoreboard objectives add cv_use minecraft.used:minecraft.carrot_on_a_stick")
    rc("scoreboard objectives add cv_legend trigger")
    with LOCK:
        quest()
        season()
        wt_seed_pool()
        for q in LEGENDS:
            legend_spots(q)
        for n in ONLINE:
            finder_give(n)
            guide_give(n)
        expedition()
        save()
    threading.Thread(target=periodic, daemon=True).start()
    threading.Thread(target=fast, daemon=True).start()
    threading.Thread(target=finder_poll, daemon=True).start()
    log("started, online:", sorted(ONLINE))
    while True:
        p = subprocess.Popen(["docker", "logs", "-f", "--since", "1s", "cobbleverse"], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, errors="replace")
        for raw in p.stdout:
            m = LINE.match(re.sub(r"\x1b\[[0-9;]*m", "", raw.rstrip("\n")))
            if m:
                step(handle, m.group(1))
        time.sleep(10)
        with LOCK:
            ONLINE.clear()
            ONLINE.update(online_from_list())


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("journal", "roam", "trader", "giant"):
        with LOCK:
            ONLINE.update(online_from_list())
            {"journal": journal, "roam": roam, "trader": trader, "giant": giant}[sys.argv[1]]()
    else:
        main()
