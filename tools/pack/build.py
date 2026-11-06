"""Build the ported mrpack from the unpacked upstream pack, port.json, merged datapacks and overrides/.

Usage: python3 -I build.py <port.json> <unpacked upstream dir> <analysis.json> <merged datapack dir> <overrides dir> <out.mrpack>

The index swaps, drops and adds mods as port.json says. Overrides come from upstream, minus its datapack zips
(replaced by the merged ones) and minus port.json's drop_overrides, with port.json's patches applied; files in
<overrides dir> are layered on top.
"""
import json
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import modrinth  # noqa: E402

EXTRA_PACKS = {"COBBLEVERSE-Hoenn-DP", "COBBLEVERSE-Johto-DP", "COBBLEVERSE-Sinnoh-DP", "Terralith-DP"}
STAMP = (2026, 10, 30, 0, 0, 0)  # some unpacked files carry timestamps zip can't encode


def add_bytes(z, data, arcname):
    info = zipfile.ZipInfo(arcname, STAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    z.writestr(info, data)


def zip_dir(src, dest):
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, names in os.walk(src):
            for n in sorted(names):
                p = os.path.join(root, n)
                add_bytes(z, open(p, "rb").read(), os.path.relpath(p, src).replace(os.sep, "/"))


def drop_pack(text, path, pack):
    if path.endswith(".json"):
        def clean(o):
            if isinstance(o, dict):
                return {k: clean(v) for k, v in o.items() if k != pack}
            if isinstance(o, list):
                return [clean(v) for v in o if v != pack]
            return o
        return json.dumps(clean(json.loads(text)), indent=2, ensure_ascii=False) + "\n"
    q = re.escape(json.dumps(pack))
    return re.sub(rf"{q}\s*,\s*|,\s*{q}", "", text)


def patched(rel, data, patches):
    for p in patches:
        if rel not in p["files"]:
            continue
        text = data.decode("utf-8")
        if "drop_pack" in p:
            new = drop_pack(text, rel, p["drop_pack"])
        else:
            new = text.replace(p["find"], p["replace"])
        if new == text:
            raise SystemExit(f"patch had no effect on {rel}: {p}")
        data = new.encode("utf-8")
    return data


def main(port_path, pack_dir, analysis_path, merged_dir, extra_dir, out):
    port = json.load(open(port_path))
    index = json.load(open(os.path.join(pack_dir, "modrinth.index.json")))
    analysis = {e["path"]: e for e in json.load(open(analysis_path))}
    files, changes = [], []
    for f in index["files"]:
        e = analysis[f["path"]]
        if e["slug"] in port["drop"]:
            changes.append(f"- removed {e['title']} {e['current']} ({port['drop'][e['slug']]})")
            continue
        if e["slug"] in port["update"]:
            number, vid = port["update"][e["slug"]]
            v = modrinth.version(vid)
            assert v["version_number"] == number, f"{e['slug']}: {vid} is {v['version_number']}, port.json says {number}"
            changes.append(f"- {e['title']}: {e['current']} -> {number}")
            f = modrinth.index_entry(v, f.get("env"))
        files.append(f)
    for slug, (number, vid) in port["add"].items():
        v = modrinth.version(vid)
        assert v["version_number"] == number, f"{slug}: {vid} is {v['version_number']}, port.json says {number}"
        changes.append(f"- added {v['name']}")
        files.append(modrinth.index_entry(v))
    index["files"] = files
    index["name"] = port["name"]
    index["versionId"] += port["version_suffix"]
    index["summary"] = f"Unofficial: COBBLEVERSE {port['upstream']['version']} moved to Cobblemon 1.8 for a private server."

    patch_files = {f for p in port["patches"] for f in p["files"]}
    applied = set()
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        add_bytes(z, json.dumps(index, indent=1).encode(), "modrinth.index.json")
        overrides = os.path.join(pack_dir, "overrides")
        for root, _, names in os.walk(overrides):
            for n in sorted(names):
                p = os.path.join(root, n)
                rel = os.path.relpath(p, overrides).replace(os.sep, "/")
                if rel.startswith("datapacks/") and n.endswith(".zip"):
                    continue
                if rel in port["drop_overrides"] or os.path.exists(os.path.join(extra_dir, rel)):
                    continue
                data = open(p, "rb").read()
                if rel in patch_files:
                    data = patched(rel, data, port["patches"])
                    applied.add(rel)
                add_bytes(z, data, "overrides/" + rel)
        for root, _, names in os.walk(extra_dir):
            for n in sorted(names):
                p = os.path.join(root, n)
                add_bytes(z, open(p, "rb").read(), "overrides/" + os.path.relpath(p, extra_dir).replace(os.sep, "/"))
        tmp = out + ".dp.zip"
        for name in sorted(os.listdir(merged_dir)):
            zip_dir(os.path.join(merged_dir, name), tmp)
            sub = "extra/" if name in EXTRA_PACKS else ""
            add_bytes(z, open(tmp, "rb").read(), f"overrides/datapacks/{sub}{name}.zip")
        os.remove(tmp)
    if patch_files - applied:
        raise SystemExit(f"patched files missing from upstream: {sorted(patch_files - applied)}")
    print("\n".join(changes))
    print(f"wrote {out}: {len(files)} files in index")


if __name__ == "__main__":
    main(*sys.argv[1:])
