"""Print every mixin class a Fabric jar declares (all configs, all sides). Usage: python3 -I mixins.py <jar>"""
import json, sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
mod = json.loads(z.read("fabric.mod.json").decode("utf-8-sig"), strict=False)
for cfg in mod.get("mixins", []):
    name = cfg if isinstance(cfg, str) else cfg["config"]
    try:
        d = json.loads(z.read(name).decode("utf-8-sig"), strict=False)
    except KeyError:
        continue
    pkg = d.get("package", "")
    for side in ("mixins", "client", "server"):
        for m in d.get(side) or []:
            print(f"{side}:{pkg}.{m}")
