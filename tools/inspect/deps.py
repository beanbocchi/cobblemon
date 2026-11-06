"""Download the Cobblemon-related jars (current and newest) and print what each declares in fabric.mod.json.

Usage: python3 -I deps.py <analysis.json> <jar dir>
"""
import json
import os
import re
import sys
import urllib.request
import zipfile

UA = {"User-Agent": "cobbleverse-1.8-port (personal use)"}
ADDON = re.compile(r"cobbl|poke|mega|rct|raid|lumy|legendary|capture|catch|fightorflight|tmcraft|timcore|pasture|bottle|zamega|badge", re.I)
WATCH = ("cobblemon", "minecraft", "fabricloader", "fabric-api", "fabric", "fabric-language-kotlin", "java")


def fetch(url, dest):
    if not os.path.exists(dest):
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r, open(dest, "wb") as f:
            f.write(r.read())
    return dest


def mod_json(jar):
    with zipfile.ZipFile(jar) as z:
        return json.loads(z.read("fabric.mod.json").decode("utf-8-sig"), strict=False)


def describe(jar):
    try:
        m = mod_json(jar)
    except Exception as e:
        return f"  (no fabric.mod.json: {e})"
    out = []
    for key in ("depends", "breaks", "recommends"):
        d = {k: v for k, v in (m.get(key) or {}).items() if k in WATCH or "cobble" in k or "mega" in k}
        if d:
            out.append(f"  {key}: {json.dumps(d)}")
    return "\n".join(out) or "  (no relevant constraints)"


def main(analysis, jar_dir):
    os.makedirs(jar_dir, exist_ok=True)
    entries = json.load(open(analysis))
    for e in entries:
        if e["type"] != "mod" or not (e["needs_cobblemon"] or ADDON.search(e["slug"] + e["title"])):
            continue
        cur = urllib.request.urlopen(urllib.request.Request(
            f"https://api.modrinth.com/v2/version/{e['version']}", headers=UA)).read()
        cur = json.loads(cur)
        cur_file = next((f for f in cur["files"] if f["primary"]), cur["files"][0])
        print(f"== {e['title']}  [{e['slug']}]")
        jar = fetch(cur_file["url"], os.path.join(jar_dir, "cur-" + cur_file["filename"]))
        print(f" current {e['current']}:\n{describe(jar)}")
        if e["latest"] and e["latest"]["id"] != e["version"]:
            lv = json.loads(urllib.request.urlopen(urllib.request.Request(
                f"https://api.modrinth.com/v2/version/{e['latest']['id']}", headers=UA)).read())
            lf = next((f for f in lv["files"] if f["primary"]), lv["files"][0])
            jar = fetch(lf["url"], os.path.join(jar_dir, "new-" + lf["filename"]))
            print(f" latest {e['latest']['number']}:\n{describe(jar)}")
        sys.stdout.flush()


if __name__ == "__main__":
    main(*sys.argv[1:])
