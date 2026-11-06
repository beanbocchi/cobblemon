"""Port Cobbleverse's datapacks onto newer mod jars with a three-way JSON merge.

For every JSON file a datapack overrides, base is that path in the old jars, upstream is the same path in the new
jars, and the fork is the datapack copy. The merge keeps upstream's edits wherever Cobbleverse left the base alone,
keeps Cobbleverse's edits elsewhere, and logs the spots both sides changed (Cobbleverse wins those).

A datapack file that is only a verbatim copy of the base is dropped so upstream's file shows through. Spawn files
(.../spawn_pool_world/...) merge their "spawns" list by id, and Cobbleverse's weights are rescaled to 1.8's scale.

Usage: python3 -I merge.py <plan.json> <datapack dir> [...] --out <dir> --log <file>
plan.json: {"base_jars": [...], "up_jars": [...], "bucket_scale": {"ultra-rare": 8, ...}}
"""
import json
import os
import shutil
import statistics
import sys
import zipfile

MISSING = object()

# Files Cobblemon 1.8 moved. Cobbleverse's edits to the old file are merged onto the new one.
MOVED = {
    "data/cobblemon/advancement/craft_pokedex.json": "data/cobblemon/advancement/catching/craft_pokedex.json",
    "data/cobblemon/advancement/craft_poke_ball.json": "data/cobblemon/advancement/catching/craft_basic_balls.json",
    "data/cobblemon/advancement/obtain_berry.json": "data/cobblemon/advancement/agriculture/obtain_berry.json",
}
# Files Cobblemon 1.8 removed with no replacement; Cobbleverse's copy would fail to load.
REMOVED = {"data/cobblemon/advancement/any_plant.json"}


def read_json(raw):
    return json.loads(raw.decode("utf-8-sig"), strict=False)


class Jars:
    """Path -> bytes over a list of jars, first jar wins (pack mod order doesn't matter for data paths here)."""

    def __init__(self, paths):
        self.files = {}
        for p in paths:
            with zipfile.ZipFile(p) as z:
                for n in z.namelist():
                    if n.startswith("data/") and not n.endswith("/"):
                        self.files.setdefault(n, (p, n))

    def get(self, path):
        hit = self.files.get(path)
        if not hit:
            return None
        with zipfile.ZipFile(hit[0]) as z:
            return z.read(hit[1])


class Merger:
    def __init__(self, bucket_scale):
        self.bucket_scale = bucket_scale
        self.conflicts = []

    def merge(self, base, up, fork, where):
        if fork == base:
            return up
        if up == base or up is MISSING:
            return fork
        if fork == up:
            return fork
        if isinstance(base, dict) and isinstance(up, dict) and isinstance(fork, dict):
            out = {}
            for k in list(up) + [k for k in fork if k not in up]:
                v = self.merge(base.get(k, MISSING), up.get(k, MISSING), fork.get(k, MISSING), f"{where}.{k}")
                if v is not MISSING:
                    out[k] = v
            return out
        self.conflicts.append((where, base, up, fork))
        return fork

    def scale_for(self, entry, base_entry, up_entry):
        bw = (base_entry or {}).get("weight")
        uw = (up_entry or {}).get("weight")
        if bw and uw and (base_entry or {}).get("bucket") == (up_entry or {}).get("bucket"):
            return uw / bw
        return self.bucket_scale.get(entry.get("bucket"), self.bucket_scale["default"])

    def rescale(self, entry, base_entry, up_entry):
        if isinstance(entry.get("weight"), (int, float)):
            entry = dict(entry)
            entry["weight"] = round(entry["weight"] * self.scale_for(entry, base_entry, up_entry), 4)
        return entry

    def merge_spawn_file(self, base, up, fork, where):
        """Spawn files: merge top-level keys normally, the spawns list by id."""
        if base is None:  # no 1.7 original: Cobbleverse's own spawn file, just rescale
            out = dict(fork)
            out["spawns"] = [self.rescale(s, None, None) for s in fork.get("spawns", [])]
            return out
        b = {s["id"]: s for s in base.get("spawns", [])}
        u = {s["id"]: s for s in (up or {}).get("spawns", [])}
        f = {s["id"]: s for s in fork.get("spawns", [])}
        top = self.merge({k: v for k, v in base.items() if k != "spawns"},
                         {k: v for k, v in (up or base).items() if k != "spawns"},
                         {k: v for k, v in fork.items() if k != "spawns"}, where)
        spawns = []
        for sid in list(u) + [s for s in f if s not in u]:
            be, ue, fe = b.get(sid), u.get(sid), f.get(sid)
            if be is not None and fe is None:
                continue  # Cobbleverse removed this spawn
            if fe is not None and be is None:
                spawns.append(self.rescale(fe, None, ue))  # Cobbleverse added it
                continue
            if fe is None:
                spawns.append(ue)  # new in upstream
                continue
            if ue is None:
                continue  # upstream removed it
            # Put Cobbleverse's weight on the new scale before merging, so an untouched weight compares equal.
            fe_scaled = dict(fe)
            if fe.get("weight") != be.get("weight") and isinstance(fe.get("weight"), (int, float)):
                fe_scaled["weight"] = round(fe["weight"] * self.scale_for(fe, be, ue), 4)
            elif "weight" in fe:
                fe_scaled["weight"] = ue.get("weight", fe["weight"])
            be_cmp = dict(be)
            if "weight" in be:
                be_cmp["weight"] = ue.get("weight", be["weight"])
            spawns.append(self.merge(be_cmp, ue, fe_scaled, f"{where}#{sid}"))
        top["spawns"] = spawns
        return top


def main(argv):
    out_dir = argv[argv.index("--out") + 1]
    log_path = argv[argv.index("--log") + 1]
    plan = json.load(open(argv[0]))
    packs = [a for a in argv[1:] if a not in ("--out", "--log", out_dir, log_path)]
    base, up = Jars(plan["base_jars"]), Jars(plan["up_jars"])
    m = Merger(plan["bucket_scale"])
    stats = {"copied": 0, "dropped_as_base_copy": 0, "merged": 0, "fork_only_spawn_rescaled": 0, "upstream_removed": 0}
    notes = []
    for pack in packs:
        dest_pack = os.path.join(out_dir, os.path.basename(pack.rstrip("/")))
        for root, _, names in os.walk(pack):
            for name in names:
                src = os.path.join(root, name)
                rel = os.path.relpath(src, pack).replace(os.sep, "/")
                dst = os.path.join(dest_pack, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                b_raw, u_raw = base.get(rel), up.get(rel)
                is_spawn = "/spawn_pool_world/" in rel and rel.endswith(".json")
                if not rel.endswith(".json") or (b_raw is None and u_raw is None and not is_spawn):
                    shutil.copyfile(src, dst)
                    stats["copied"] += 1
                    continue
                fork = read_json(open(src, "rb").read())
                b = read_json(b_raw) if b_raw is not None else None
                u = read_json(u_raw) if u_raw is not None else None
                if b is not None and fork == b and u is not None:
                    stats["dropped_as_base_copy"] += 1
                    continue
                if is_spawn and b is None and u is not None:
                    # Species Cobblemon implemented after 1.7: Cobbleverse's spawns were a stopgap, use the official ones.
                    notes.append(f"spawn file new in upstream, replaced Cobbleverse's stopgap: {rel}")
                    stats["dropped_for_new_upstream_spawn"] = stats.get("dropped_for_new_upstream_spawn", 0) + 1
                    continue
                if is_spawn:
                    result = m.merge_spawn_file(b, u, fork, rel)
                    stats["fork_only_spawn_rescaled" if b is None else "merged"] += 1
                elif b is None:
                    result = fork
                    notes.append(f"new upstream file overridden by Cobbleverse (kept Cobbleverse): {rel}")
                    stats["merged"] += 1
                elif rel in REMOVED:
                    notes.append(f"removed in upstream, dropped Cobbleverse copy: {rel}")
                    continue
                elif rel in MOVED:
                    new_rel = MOVED[rel]
                    result = m.merge(b, read_json(up.get(new_rel)), fork, f"{rel} -> {new_rel}")
                    if "parent" in result and result["parent"] == fork.get("parent"):
                        result["parent"] = read_json(up.get(new_rel))["parent"]  # old parent no longer exists
                    dst = os.path.join(dest_pack, new_rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    notes.append(f"moved in upstream, merged Cobbleverse edits onto: {new_rel}")
                    stats["merged"] += 1
                elif u is None:
                    result = fork
                    stats["upstream_removed"] += 1
                    notes.append(f"upstream deleted this file, kept Cobbleverse copy: {rel}")
                else:
                    result = m.merge(b, u, fork, rel)
                    stats["merged"] += 1
                with open(dst, "w", encoding="utf-8") as fh:
                    json.dump(result, fh, indent=2, ensure_ascii=False)
    with open(log_path, "w", encoding="utf-8") as log:
        log.write(json.dumps(stats, indent=1) + "\n\n")
        log.write("\n".join(notes) + "\n\n")
        log.write(f"{len(m.conflicts)} conflicts (both sides changed; Cobbleverse kept):\n")
        for where, b, u, f in m.conflicts:
            short = lambda v: "MISSING" if v is MISSING else json.dumps(v, ensure_ascii=False)[:160]
            log.write(f"- {where}\n    base: {short(b)}\n    1.8 : {short(u)}\n    CV  : {short(f)}\n")
    print(json.dumps(stats), f"conflicts={len(m.conflicts)} notes={len(notes)}")


if __name__ == "__main__":
    main(sys.argv[1:])
