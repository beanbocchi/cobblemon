#!/usr/bin/env python3
"""Boss Rush: three waves of glowing, persistent bosses near the middle of the Overworld players, the last one a
legendary that arrives with a storm. A boss bar tracks how many bosses are left and the time remaining. Each
cleared wave pays everyone online; the final wave pays the most. Usage: bossrush.py"""
import json, random, re, sys, time
sys.argv = [sys.argv[0]]
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import events as e
import rewards

TAG = "cvev_rush"
BAR = "cobbleverse:rush"
TIME_LIMIT = 1200
POLL = 15  # seconds between boss checks; each rcon call prints two lines to the server console
STRONG = ["tyranitar", "garchomp", "dragonite", "metagross", "salamence", "hydreigon", "volcarona", "dragapult",
          "baxcalibur", "kingambit", "goodra", "kommoo", "haxorus", "scizor", "excadrill", "mamoswine"]
FINAL = ["mewtwo", "lugia", "hooh", "rayquaza", "groudon", "kyogre", "dialga", "palkia", "giratina", "reshiram",
         "zekrom", "kyurem", "xerneas", "yveltal", "solgaleo", "lunala", "zacian", "zamazenta", "eternatus"]
MINIONS = ["sneasel", "zorua", "houndour", "murkrow", "gastly", "deino", "gible", "larvitar", "axew", "bagon"]
BAR_COLORS = ["yellow", "red", "purple"]
SHINY_CHANCE = [0.15, 0.25, 0.35]  # per boss; the final legendary has the best odds
WAVES = [  # (count, species pool, level bonus over the strongest party member, prize per player,
           #  rewards.mixed tier per player or 0 for none)
    (2, STRONG, 0, [("cobblemon:exp_candy_l", 2), ("cobblemon:ultra_ball", 5)], 0),
    (2, STRONG, 5, [("cobblemon:rare_candy", 2)], 2),
    (1, FINAL, 10, [("cobblemon:master_ball", 1), ("cobblemon:ability_capsule", 1), ("cobblemon:rare_candy", 5),
                    ("cobblemon:exp_candy_xl", 2)], 0),
]


def label(items):
    """Chat text for a list of (item, count), e.g. "3 Ultra Ball, 2 Sitrus Berry"."""
    return ", ".join(f"{c} {it.split(':')[1].replace('_', ' ').title()}" for it, c in items)


def say(text, color="white", to="@a"):
    e.rcon(f"tellraw {to} " + json.dumps([{"text": "[Boss Rush] ", "color": "dark_red", "bold": True},
                                       {"text": text, "color": color, "bold": False}], ensure_ascii=False))


def title(top, sub, color="red"):
    e.rcon("title @a times 5 60 15")
    e.rcon("title @a title " + json.dumps({"text": top, "color": color, "bold": True}, ensure_ascii=False))
    e.rcon("title @a subtitle " + json.dumps({"text": sub, "color": "gold"}, ensure_ascii=False))


def alive():
    m = re.search(r"count: (\d+)", e.rcon(f"execute if entity @e[tag={TAG}]"), re.I)
    return int(m.group(1)) if m else 0


SHOWN = {}  # what the boss bar shows now, so only changes are sent


def bar(left, total, t0, label):
    """Update the boss bar. The time is shown in whole minutes, so the name changes about once a minute."""
    remain = max(0, int(TIME_LIMIT - (time.time() - t0)))
    name = {"text": f"{label}: {left}/{total} bosses left | {-(-remain // 60)} min left", "color": "red"}
    if SHOWN.get("name") != name:
        e.rcon(f"bossbar set {BAR} name " + json.dumps(name, ensure_ascii=False))
        e.rcon(f"bossbar set {BAR} players @a")  # people who joined since the last change
        SHOWN["name"] = name
    if SHOWN.get("max") != total:
        e.rcon(f"bossbar set {BAR} max {total}")
        SHOWN["max"] = total
    if SHOWN.get("value") != left:
        e.rcon(f"bossbar set {BAR} value {left}")
        SHOWN["value"] = left


def fireworks(x, y, z, colors, n=3):
    for i in range(n):
        dx, dz = random.uniform(-3, 3), random.uniform(-3, 3)
        e.rcon(f"summon minecraft:firework_rocket {x + dx:.1f} {y + 1} {z + dz:.1f} {{LifeTime:{random.randint(18, 34)},"
               "FireworksItem:{id:\"minecraft:firework_rocket\",count:1,components:{\"minecraft:fireworks\":"
               f"{{explosions:[{{shape:\"{random.choice(['large_ball', 'star', 'burst'])}\",colors:[I;{colors}],"
               "has_twinkle:true,has_trail:true}]}}}}")


def spawn_wave(count, pool, level, final, shiny_chance):
    here = e.online_overworld()
    px, pz = sum(p[1] for p in here) / len(here), sum(p[3] for p in here) / len(here)
    names, chunks, where = [], [], None
    for species in random.sample(pool, count):
        for _ in range(5):
            anchor, chunk = e.place_anchor(px, pz, 40, 60)
            if anchor:
                break
            e.release_anchor(chunk)
        else:
            continue
        e.rcon(f"kill @e[tag={e.ANCHOR}]")
        chunks.append(chunk)
        x, y, z = anchor
        if final:  # storm and thunder before the legendary lands; no lightning bolt, it starts fires
            e.rcon("weather thunder 1200")
            for _ in range(3):
                e.rcon(f"particle minecraft:explosion_emitter {x} {y + 2} {z} 1 1 1 0 3 force")
                e.rcon("execute as @a at @s run playsound minecraft:entity.lightning_bolt.thunder master @s ~ ~ ~ 1 0.8")
                time.sleep(1)
        shiny = e.spawn_group(species, 1, (level, level), shiny_chance, TAG, x, y, z, extra="min_perfect_ivs=6")
        e.rcon(f"particle minecraft:large_smoke {x} {y + 1} {z} 1 1 1 0.05 60 force")
        e.rcon(f"particle minecraft:soul_fire_flame {x} {y + 1} {z} 1.5 1.5 1.5 0.02 80 force")
        # a few weaker minions around each boss; they don't count toward the wave
        for m in random.sample(MINIONS, 3):
            e.rcon(f"execute in minecraft:overworld positioned {x + random.uniform(-5, 5):.1f} {y + 0.5} "
                   f"{z + random.uniform(-5, 5):.1f} run spawnpokemon {m} level={max(5, level - 25)}")
        names.append(("Shiny " if shiny else "") + e.display(species))
        where = e.bearing(px, pz, x, z)
    e.rcon(f"execute as @e[tag={TAG}] run data merge entity @s {{Glowing:1b,PersistenceRequired:1b}}")
    if any(n.startswith("Shiny") for n in names):
        e.rcon("execute as @a at @s run playsound minecraft:block.amethyst_block.resonate master @s ~ ~ ~ 1 1.2")
    return names, chunks, where


def main():
    here = e.online_overworld()
    if not here:
        sys.exit("nobody in the Overworld")
    top = max((e.party_levels(p[0])[:1] or [50])[0] for p in here)
    total = sum(w[0] for w in WAVES)
    e.rcon(f"bossbar remove {BAR}")
    e.rcon(f'bossbar add {BAR} {{"text":"Boss Rush"}}')
    e.rcon(f"bossbar set {BAR} color red")
    e.rcon(f"bossbar set {BAR} style notched_10")
    e.rcon("time set midnight")
    e.rcon("effect give @a minecraft:darkness 4 0 true")
    e.rcon("execute as @a at @s run playsound minecraft:entity.ender_dragon.growl master @s ~ ~ ~ 1 0.7")
    time.sleep(3)
    title("BOSS RUSH", "3 waves of bosses, the last one is a legendary")
    e.rcon("execute as @a at @s run playsound minecraft:event.raid.horn master @s ~ ~ ~ 1 0.8")
    for name, x, y, z in here:
        e.rcon(f"particle minecraft:totem_of_undying {x} {y + 1} {z} 1 1 1 0.5 150 force")
    say(f"3 waves, {total} bosses in total, 20 minutes. Defeat or catch a whole wave and everyone online gets a reward, "
        "then the next wave appears. The last wave is a high-level legendary. Bosses glow, so you can see them through walls.", "gold")
    time.sleep(5)
    t0, cleared, left_total, chunks = time.time(), 0, total, []
    for i, (count, pool, bonus, prize, tier) in enumerate(WAVES):
        final = i == len(WAVES) - 1
        level = min(100, top + bonus)
        title(f"WAVE {i + 1}" if not final else "FINAL WAVE", "A legendary is coming..." if final else f"{count} level {level} bosses")
        e.rcon(f"bossbar set {BAR} color {BAR_COLORS[i]}")
        if final:
            e.rcon("execute as @a at @s run playsound minecraft:music_disc.pigstep record @s ~ ~ ~ 0.8 1")
        names, wave_chunks, where = spawn_wave(count, pool, level, final, SHINY_CHANCE[i])
        chunks += wave_chunks
        if not names:
            say("Could not find a spot for the bosses, skipping this wave.", "gray")
            continue
        direction, dist = where
        say(f"Wave {i + 1}: {', '.join(names)} (level {level}, perfect IVs), about {dist} m to the {direction}.",
            "red" if not final else "light_purple")
        spawned = left = alive()
        while left > 0 and time.time() - t0 < TIME_LIMIT:
            bar(left_total - (spawned - left), total, t0, f"Wave {i + 1}/{len(WAVES)}")
            time.sleep(min(POLL, max(1, TIME_LIMIT - (time.time() - t0))))
            left = alive()
        if left > 0:
            break
        left_total -= spawned
        cleared += 1
        e.rcon("execute as @a at @s run playsound minecraft:ui.toast.challenge_complete master @s")
        say(f"Wave {i + 1} cleared! Everyone online gets a reward.", "green")
        for n in [re.sub(r"^(\[[^\]]*\]\s*)+", "", n.strip()) for n in e.rcon("list").split(":", 1)[1].split(",") if n.strip()]:
            got = []
            for item, c in prize:
                got += rewards.give(n, item, c)
            if tier:
                got += rewards.mixed(n, tier)
            say(f"You got: {label(got)}.", "green", n)
        if not final:
            say("Next wave in 20 seconds, heal up!", "yellow")
            bar(left_total, total, t0, "Break")
            time.sleep(20)
    if cleared == len(WAVES):
        title("VICTORY!", "The whole Boss Rush is cleared", "gold")
        e.rcon("weather clear")
        here = e.online_overworld()
        e.rcon("stopsound @a record")
        e.rcon("execute as @a at @s run playsound minecraft:ui.toast.challenge_complete master @s ~ ~ ~ 1 1")
        for _ in range(4):  # four volleys of fireworks around everyone
            for name, x, y, z in here:
                fireworks(x, y, z, "16766720,16711680,65535,16711935", 3)
                e.rcon(f"particle minecraft:totem_of_undying {x} {y + 1} {z} 1 1 1 0.6 100 force")
            time.sleep(1.5)
        secs = int(time.time() - t0)
        say(f"All {total} bosses down in {secs // 60} min {secs % 60} s. Awesome!", "gold")
    else:
        say(f"Time's up! {cleared}/{len(WAVES)} waves cleared. The remaining bosses have left.", "gray")
        e.rcon(f"execute as @e[tag={TAG}] at @s unless entity @a[distance=..16] run tp @s ~ -400 ~")
        e.rcon("stopsound @a record")
        e.rcon("weather clear")
    e.rcon(f"bossbar remove {BAR}")
    for c in chunks:
        e.release_anchor(c)
    print("done", cleared, flush=True)


if __name__ == "__main__":
    main()
