"""Write tower_trainers.json: RCT trainers the Battle Tower may summon.

Usage: python3 -I build_tower.py <rctmod jar> <COBBLEVERSE-RCT-DP dir> <out.json>

Keeps trainers of type "normal" (by their group or single mob config, falling back to default.json) with no
required defeats or series, so beating one in the tower never moves gym or league progress. cvlife checks each
pick again with `rctmod trainer get` before summoning it. Each row is [id, name, top level, team size].
"""
import json
import os
import re
import sys
import zipfile

SKIP = re.compile(r"leader|elite|champion|rival|boss|commander|admin|grunt|title_defense|battleground|executive|"
                  r"gym_|league|frontier|brain|professor|team_", re.I)


def main(jar, dp, out):
    files = {}
    z = zipfile.ZipFile(jar)
    for n in z.namelist():
        if n.startswith("data/rctmod/") and n.endswith(".json"):
            files[n[len("data/rctmod/"):]] = z.read(n)
    root = os.path.join(dp, "data", "rctmod")
    for d, _, names in os.walk(root):
        for n in names:
            if n.endswith(".json"):
                p = os.path.join(d, n)
                files[os.path.relpath(p, root).replace(os.sep, "/")] = open(p, "rb").read()
    default = json.loads(files["mobs/trainers/default.json"])
    groups = {k.split("/")[-1][:-5]: json.loads(v) for k, v in files.items() if k.startswith("mobs/trainers/groups/")}
    single = {k.split("/")[-1][:-5]: json.loads(v) for k, v in files.items() if k.startswith("mobs/trainers/single/")}
    rows = []
    for k, v in files.items():
        if not k.startswith("trainers/"):
            continue
        tid = k.split("/")[-1][:-5]
        if SKIP.search(tid):
            continue
        cfg = single.get(tid) or next((g for name, g in sorted(groups.items(), key=lambda kv: -len(kv[0]))
                                       if tid.startswith(name + "_")), default)
        if cfg.get("type") != "normal" or cfg.get("requiredDefeats") or cfg.get("series"):
            continue
        d = json.loads(v)
        team = [p.get("level", 0) for p in d.get("team", [])]
        if len(team) < 2:
            continue
        rows.append([tid, d.get("name", tid), max(team), len(team)])
    rows.sort(key=lambda r: (r[2], r[0]))
    json.dump(rows, open(out, "w"), ensure_ascii=False)
    print(len(rows), "trainers, levels", rows[0][2], "-", rows[-1][2])


if __name__ == "__main__":
    main(*sys.argv[1:])
