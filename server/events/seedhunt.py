#!/usr/bin/env python3
"""Try random seeds until the world spawn is green and has a village close by.

For each seed: stop the server, delete world/, set level-seed, start, wait for "Done", save, then read the biome
palettes of the 5x5 chunks around the spawn from the region files. A seed passes when those biomes contain no
snow, ice, ocean, beach, desert, badlands, mushroom or swamp, at least one green biome, and `locate` finds a village
within 600 blocks. The server is left running on the chosen world. Usage: seedhunt.py [tries]"""
import datetime, gzip, os, random, re, subprocess, sys, time

DATA = os.path.expanduser("~/cobblemon/server/data")
sys.path.insert(0, os.path.expanduser("~/cvscan"))
import anvil  # noqa: E402

BAD = ("snow", "frozen", "ice", "ocean", "beach", "desert", "badlands", "mushroom", "swamp", "mangrove", "frost",
       "glacier", "tundra", "dune", "volcan", "wasteland")
GOOD = ("forest", "plain", "meadow", "cherry", "grove", "savanna", "jungle", "birch", "lavender", "sakura",
        "blossom", "orchard", "steppe", "prairie", "valley", "highland", "garden", "flower", "taiga", "wood")


def rc(c):
    return re.sub(r"\x1b\[[0-9;]*m", "", subprocess.run(["docker", "exec", "cobbleverse", "rcon-cli", c],
                                                       capture_output=True, text=True).stdout)


def wait_up(since):
    for _ in range(180):
        time.sleep(5)
        out = subprocess.run(["docker", "logs", "--since", since, "cobbleverse"], capture_output=True, text=True)
        if "Done (" in out.stdout + out.stderr and os.path.exists(f"{DATA}/world/level.dat"):
            return True
    return False


def spawn_xz():
    d = anvil.nbt(gzip.decompress(open(f"{DATA}/world/level.dat", "rb").read()))["Data"]
    if "SpawnX" in d:
        return d["SpawnX"], d["SpawnZ"]
    sp = d.get("spawn", {})
    return sp["pos"][0], sp["pos"][2]


def biomes_near(x, z, r=2):
    w = anvil.World(f"{DATA}/world/region")
    names = set()
    for cx in range(x // 16 - r, x // 16 + r + 1):
        for cz in range(z // 16 - r, z // 16 + r + 1):
            c = w.chunk(cx, cz)
            if not c:
                continue
            for sec in c.get("sections", []):
                if 3 <= sec.get("Y", 0) <= 6:  # y 48..111, the surface band
                    names.update(sec.get("biomes", {}).get("palette", []))
    return names


def set_seed(seed):
    p = f"{DATA}/server.properties"
    s = open(p).read()
    open(p, "w").write(re.sub(r"(?m)^level-seed=.*$", f"level-seed={seed}", s))


def main():
    tries = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    for t in range(1, tries + 1):
        seed = random.getrandbits(48)
        subprocess.run(["docker", "stop", "cobbleverse"], capture_output=True)
        subprocess.run(["rm", "-rf", f"{DATA}/world"])
        set_seed(seed)
        since = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        subprocess.run(["docker", "start", "cobbleverse"], capture_output=True)
        if not wait_up(since):
            print(f"try {t} seed {seed}: did not start", flush=True)
            continue
        rc("save-all flush")
        time.sleep(5)
        try:
            x, z = spawn_xz()
            names = biomes_near(int(x), int(z))
        except Exception as e:
            print(f"try {t} seed {seed}: read error {e!r}", flush=True)
            continue
        bad = sorted(n for n in names if any(k in n for k in BAD))
        good = sorted(n for n in names if any(k in n for k in GOOD))
        m = re.search(r"\((\d+) blocks away\)", rc(f"execute in minecraft:overworld positioned {x} 80 {z} run locate structure #minecraft:village"))
        village = int(m.group(1)) if m else None
        print(f"try {t} seed {seed} spawn {x},{z} biomes {sorted(names)} village {village}", flush=True)
        if not bad and good and village is not None and village <= 600:
            print(f"CHOSEN seed {seed}", flush=True)
            return
    print("no seed matched; last world left running", flush=True)


if __name__ == "__main__":
    main()
