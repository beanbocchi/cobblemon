"""Check every Modrinth file in a Cobbleverse mrpack against the newest Fabric 1.21.1 release.

Usage: python3 -I analyze.py <modrinth.index.json> <out.json>
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import modrinth  # noqa: E402

COBBLEMON = "MdwFAVRL"
get = modrinth.get


def main(index_path, out_path):
    index = json.load(open(index_path))
    entries = []
    for f in index["files"]:
        parts = f["downloads"][0].split("/")
        entries.append({"path": f["path"], "project": parts[4], "version": parts[6]})

    pids = sorted({e["project"] for e in entries})
    projects = {p["id"]: p for p in get("/projects", ids=pids)}
    current = {}
    vids = [e["version"] for e in entries]
    for i in range(0, len(vids), 100):
        for v in get("/versions", ids=vids[i:i + 100]):
            current[v["id"]] = v

    for e in entries:
        p = projects[e["project"]]
        cur = current[e["version"]]
        e["title"] = p["title"]
        e["slug"] = p["slug"]
        e["type"] = p["project_type"]
        e["current"] = cur["version_number"]
        e["current_date"] = cur["date_published"][:10]
        e["needs_cobblemon"] = any(d.get("project_id") == COBBLEMON for d in cur["dependencies"])
        loaders = ["fabric"] if e["type"] == "mod" else None
        params = {"game_versions": ["1.21.1"]}
        if loaders:
            params["loaders"] = loaders
        versions = get(f"/project/{e['project']}/version", **params)
        e["latest"] = None
        if versions:
            v = versions[0]
            e["latest"] = {
                "id": v["id"],
                "number": v["version_number"],
                "name": v["name"],
                "date": v["date_published"][:10],
                "file": next((f for f in v["files"] if f["primary"]), v["files"][0])["filename"],
            }
        print(f"{e['title'][:40]:40} {e['current']:>28} -> {e['latest']['number'] if e['latest'] else '-'}",
              file=sys.stderr)

    json.dump(entries, open(out_path, "w"), indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:])
