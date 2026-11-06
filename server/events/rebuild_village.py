#!/usr/bin/env python3
"""Rebuild the burned buildings of the village nearest a point.

Usage: rebuild_village.py <x> <z> [--dry-run]

Reads the village structure start from the region files, compares every building piece with its template, and
re-places the pieces that lost wood or wool to air or fire. Before placing, it records the items in every container
inside those pieces and puts them back afterwards. Fire inside the village bounds is removed first. Templates come
from the vanilla server jar and the mod jars in /data/mods.
"""
import collections
import glob
import gzip
import json
import math
import os
import re
import subprocess
import sys
import time
import zipfile

sys.path.insert(0, os.path.expanduser("~/cvscan"))
import anvil  # noqa: E402

CONTAINER = os.environ.get("CONTAINER", "cobbleverse")
E = "execute in minecraft:overworld run "
ROT = {"NONE": "none", "CLOCKWISE_90": "clockwise_90", "CLOCKWISE_180": "180", "COUNTERCLOCKWISE_90": "counterclockwise_90"}
WOODISH = ("plank", "log", "wood", "wool", "stairs", "slab", "fence", "door", "carpet", "bookshelf", "hay", "bed",
           "leaves", "trapdoor")
SKIP_POOLS = ("/streets/", "/paths", "/decor", "/berries", "/lamp_posts", "/villagers", "/store_workers", "/animals/",
              "/zombie/")


def rc(c):
    out = subprocess.run(["docker", "exec", CONTAINER, "rcon-cli", c], capture_output=True, text=True).stdout
    return re.sub(r"\x1b\[[0-9;]*m", "", out).strip()


def data_dir():
    out = subprocess.run(["docker", "inspect", CONTAINER, "--format",
                          '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}'],
                         capture_output=True, text=True).stdout.strip()
    return out


def rot(x, z, r):
    return {"NONE": (x, z), "CLOCKWISE_90": (-z, x), "CLOCKWISE_180": (-x, -z), "COUNTERCLOCKWISE_90": (z, -x)}[r]


def template_reader(data):
    jars = [zipfile.ZipFile(p) for p in glob.glob(os.path.join(data, "versions", "*", "server-*.jar"))]
    jars += [zipfile.ZipFile(p) for p in glob.glob(os.path.join(data, "mods", "*.jar"))]
    cache = {}

    def get(loc):
        if loc in cache:
            return cache[loc]
        ns, path = loc.split(":")
        name = f"data/{ns}/structure/{path}.nbt"
        t = None
        for j in jars:
            try:
                t = anvil.nbt(gzip.decompress(j.read(name)))
                break
            except KeyError:
                continue
        cache[loc] = t
        return t
    return get


def snbt(v):
    if isinstance(v, dict):
        return "{" + ",".join(f'"{k}":{snbt(x)}' for k, x in v.items()) + "}"
    if isinstance(v, list):
        return "[" + ",".join(snbt(x) for x in v) + "]"
    if isinstance(v, str):
        return json.dumps(v)
    return str(v)


def main():
    x0, z0 = int(float(sys.argv[1])), int(float(sys.argv[2]))
    dry = "--dry-run" in sys.argv
    data = data_dir()
    rc("save-all flush")
    time.sleep(6)
    w = anvil.World(os.path.join(data, "world/region"))
    best = None
    for cx in range((x0 - 300) >> 4, ((x0 + 300) >> 4) + 1):
        for cz in range((z0 - 300) >> 4, ((z0 + 300) >> 4) + 1):
            try:
                c = w.chunk(cx, cz)
            except Exception:
                continue
            for k, v in ((c or {}).get("structures") or {}).get("starts", {}).items():
                if "village" in k and v.get("id") != "INVALID":
                    d = math.dist((cx * 16, cz * 16), (x0, z0))
                    if not best or d < best[0]:
                        best = (d, k, v.get("Children", []))
    if not best:
        sys.exit("no village within 300 blocks")
    _, vid, pieces = best
    bx = [p["BB"] for p in pieces]
    lo = [min(b[i] for b in bx) for i in range(3)]
    hi = [max(b[i + 3] for b in bx) for i in range(3)]
    print("village", vid, len(pieces), "pieces, bounds", lo, hi, flush=True)

    rc(E + f"forceload add {lo[0]} {lo[2]} {hi[0]} {hi[2]}")
    time.sleep(8)
    fires = 0
    for x in range(lo[0] - 16, hi[0] + 17, 32):
        for z in range(lo[2] - 16, hi[2] + 17, 32):
            for y in range(lo[1] - 4, hi[1] + 12, 32):
                for b in ("fire", "soul_fire"):
                    m = re.search(r"filled (\d+)", rc(E + f"fill {x} {y} {z} {x + 31} {y + 31} {z + 31} minecraft:air "
                                                          f"replace minecraft:{b}"))
                    fires += int(m.group(1)) if m else 0
    print("fire removed:", fires, flush=True)

    get = template_reader(data)
    damaged = []
    for i, p in enumerate(pieces):
        loc = p["pool_element"].get("location", "")
        if not loc or any(s in loc for s in SKIP_POOLS) or p["pool_element"].get("element_type", "").endswith("feature_pool_element"):
            continue
        t = get(loc)
        if not t:
            continue
        pal = [b["Name"] for b in t["palette"]]
        wood = lost = 0
        for b in t["blocks"]:
            nm = pal[b["state"]]
            if not any(k in nm for k in WOODISH):
                continue
            x, y, z = b["pos"]
            dx, dz = rot(x, z, p["rotation"])
            wood += 1
            if (w.block(p["PosX"] + dx, p["PosY"] + y, p["PosZ"] + dz) or "") in ("minecraft:air", "minecraft:fire"):
                lost += 1
        if wood >= 10 and lost / wood > 0.15:
            damaged.append((i, loc, lost, wood))
    for d in damaged:
        print("damaged", d[1].split("/")[-1], f"{d[2]}/{d[3]} wood blocks gone", flush=True)
    if dry or not damaged:
        rc(E + f"forceload remove {lo[0]} {lo[2]} {hi[0]} {hi[2]}")
        return

    saved = []
    for i, _, _, _ in damaged:
        b = pieces[i]["BB"]
        for cx in range(b[0] >> 4, (b[3] >> 4) + 1):
            for cz in range(b[2] >> 4, (b[5] >> 4) + 1):
                for be in (w.chunk(cx, cz) or {}).get("block_entities", []):
                    if b[0] <= be["x"] <= b[3] and b[1] <= be["y"] <= b[4] and b[2] <= be["z"] <= b[5] \
                            and be.get("Items") and isinstance(be["Items"], list):
                        saved.append(be)
    players = []
    for n in re.sub(r"\[[^\]]*\]\s*", "", rc("list").split(":", 1)[-1]).split(","):
        m = re.findall(r"-?\d+\.\d+", rc(f"data get entity {n.strip()} Pos")) if n.strip() else []
        if len(m) == 3:
            players.append((n.strip(), *map(float, m)))
    for i, loc, _, _ in damaged:
        p = pieces[i]
        b = p["BB"]
        inside = [n for n, x, y, z in players if b[0] - 1 <= x <= b[3] + 1 and b[1] - 1 <= y <= b[4] + 2 and b[2] - 1 <= z <= b[5] + 1]
        if inside:
            print("skipped", loc.split("/")[-1], "because", ", ".join(inside), "is inside it", flush=True)
            continue
        print(i, rc(E + f"place template {loc} {p['PosX']} {p['PosY']} {p['PosZ']} {ROT[p['rotation']]}")[:70], flush=True)
        if (b[3] - b[0] + 1) * (b[4] - b[1] + 1) * (b[5] - b[2] + 1) <= 32768:
            rc(E + f"fill {b[0]} {b[1]} {b[2]} {b[3]} {b[4]} {b[5]} minecraft:air replace minecraft:jigsaw")
    ok = bad = 0
    for be in saved:
        for it in be["Items"]:
            if it["id"] == "minecraft:written_book":
                continue
            comp = ""
            if it.get("components"):
                comp = "[" + ",".join(f"{k.split(':')[-1] if k.startswith('minecraft:') else k}={snbt(v)}"
                                      for k, v in it["components"].items()) + "]"
            out = rc(E + f"item replace block {be['x']} {be['y']} {be['z']} container.{it['Slot']} with "
                         f"{it['id']}{comp} {it.get('count', 1)}")
            ok, bad = (ok + 1, bad) if "Replaced" in out else (ok, bad + 1)
    print(f"items restored {ok}, failed {bad}", flush=True)
    rc(E + f"forceload remove {lo[0]} {lo[2]} {hi[0]} {hi[2]}")


if __name__ == "__main__":
    main()
