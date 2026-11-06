"""Download the old and new jars of every Cobblemon-related mod and write the merge plan.

merge.py needs both sides of each file a datapack overrides: the old jars are the base, the new ones upstream.

Usage: python3 -I fetch_jars.py <port.json> <analysis.json> <jar cache dir> <out plan.json>
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import modrinth  # noqa: E402

RELATED = re.compile(r"cobbl|poke|mega|rct|raid|lumy|legendary|capture|catch|fightorflight|tmcraft|timcore|pasture|bottle|zamega|badge", re.I)


def fetch(v, prefix, jar_dir):
    pf = modrinth.primary_file(v)
    return modrinth.download(pf["url"], os.path.join(jar_dir, prefix + pf["filename"]), pf["hashes"]["sha512"])


def main(port_path, analysis_path, jar_dir, out):
    port = json.load(open(port_path))
    base, up = [], []
    for e in json.load(open(analysis_path)):
        # Only loaded mod jars count; the pack also lists inactive "credits only" zips that carry data folders.
        if not (e["path"].startswith("mods/") and e["path"].endswith(".jar")):
            continue
        if not (e["needs_cobblemon"] or RELATED.search(e["slug"] + e["title"])):
            continue
        cur = fetch(modrinth.version(e["version"]), "cur-", jar_dir)
        base.append(cur)
        if e["slug"] in port["drop"]:
            continue
        up.append(fetch(modrinth.version(port["update"][e["slug"]][1]), "new-", jar_dir) if e["slug"] in port["update"] else cur)
    # Mods in port["add"] stay out: they are not a newer version of anything in base, and a three-way merge
    # against an unrelated mod that happens to share a path (ATM x MSD vs Mega Showdown) drops real data.
    first = lambda p: (0 if "Cobblemon-fabric" in os.path.basename(p) else 1, os.path.basename(p))
    plan = {"base_jars": sorted(base, key=first), "up_jars": sorted(up, key=first),
            "bucket_scale": {"ultra-rare": 8, "default": 10}}
    json.dump(plan, open(out, "w"), indent=1)
    print(f"{len(plan['base_jars'])} base jars, {len(plan['up_jars'])} upstream jars")


if __name__ == "__main__":
    main(*sys.argv[1:])
