"""Print a java command line that launches a Modrinth profile offline, from Modrinth's meta files.

Usage: python3 -I launch_cmd.py <profile dir> [extra jvm args...]
"""
import json
import os
import shlex
import sys

META = os.path.expanduser("~/.local/share/ModrinthApp/meta")
VERSION = "1.21.1-0.18.4"


def allowed(rules):
    if not rules:
        return True
    ok = False
    for r in rules:
        os_rule = r.get("os", {})
        match = (os_rule.get("name") in (None, "linux")) and (os_rule.get("arch") in (None, "x86_64", "amd64"))
        if match:
            ok = r["action"] == "allow"
    return ok


def lib_path(lib):
    art = (lib.get("downloads") or {}).get("artifact") or {}
    if art.get("path"):
        return os.path.join(META, "libraries", art["path"])
    group, name, ver, *cls = lib["name"].split(":")
    fname = f"{name}-{ver}" + (f"-{cls[0]}" if cls else "") + ".jar"
    return os.path.join(META, "libraries", *group.split("."), name, ver, fname)


def main(profile, *extra):
    v = json.load(open(os.path.join(META, "versions", VERSION, f"{VERSION}.json")))
    cp = []
    for lib in v["libraries"]:
        if allowed(lib.get("rules")):
            p = lib_path(lib)
            if os.path.exists(p) and p not in cp and "arm" not in os.path.basename(p):
                cp.append(p)
    cp.append(os.path.join(META, "versions", VERSION, f"{VERSION}.jar"))
    java = next(os.path.join(META, "java_versions", d, "bin", "java") for d in sorted(os.listdir(os.path.join(META, "java_versions"))) if "21" in d)
    cmd = [java, "-Xmx6144M", f"-Djava.library.path={os.path.join(META, 'natives', VERSION)}", *extra,
           "-cp", ":".join(cp), v["mainClass"],
           "--username", "BisectBot", "--version", "1.21.1", "--gameDir", profile,
           "--assetsDir", os.path.join(META, "assets"), "--assetIndex", v["assetIndex"]["id"],
           "--uuid", "00000000000000000000000000000001", "--accessToken", "0", "--userType", "legacy",
           "--versionType", "release", "--width", "1280", "--height", "720"] + (["--fullscreen"] if os.environ.get("FULLSCREEN") else []) \
        + (["--quickPlaySingleplayer", os.environ["QUICKPLAY"]] if os.environ.get("QUICKPLAY") else [])
    print(shlex.join(cmd))


if __name__ == "__main__":
    main(*sys.argv[1:])
