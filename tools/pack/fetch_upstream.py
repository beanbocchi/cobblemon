"""Download the upstream Cobbleverse mrpack named in port.json and print its path.

Usage: python3 -I fetch_upstream.py <port.json> <cache dir>
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import modrinth  # noqa: E402


def main(port_path, cache_dir):
    up = json.load(open(port_path))["upstream"]
    v = modrinth.version(up["version_id"])
    assert v["version_number"] == up["version"], f"{up['version_id']} is {v['version_number']}, port.json says {up['version']}"
    pf = modrinth.primary_file(v)
    print(modrinth.download(pf["url"], os.path.join(cache_dir, f"{up['project']}-{up['version']}.mrpack"), pf["hashes"]["sha512"]))


if __name__ == "__main__":
    main(*sys.argv[1:])
