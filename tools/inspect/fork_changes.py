"""Classify what Cobbleverse changed in each spawn file it took from Cobblemon 1.7.3.

Usage: python3 -I fork_changes.py <1.7.3 dir> <cobbleverse dir> [file ...]
"""
import collections
import json
import os
import sys


def load(d, f):
    return json.load(open(os.path.join(d, f), encoding="utf-8-sig"), strict=False)


def classify(base, fork):
    kinds = set()
    if base.get("enabled", True) and not fork.get("enabled", True):
        kinds.add("file disabled")
    b = {s["id"]: s for s in base.get("spawns", [])}
    k = {s["id"]: s for s in fork.get("spawns", [])}
    if set(k) - set(b):
        kinds.add("added entries")
    if set(b) - set(k):
        kinds.add("removed entries")
    for sid in set(b) & set(k):
        for key in set(b[sid]) | set(k[sid]):
            if b[sid].get(key) != k[sid].get(key):
                if key == "weight" and not k[sid].get("weight"):
                    kinds.add("weight -> 0")
                else:
                    kinds.add(f"changed {key}")
    for key in set(base) | set(fork):
        if key not in ("spawns", "enabled") and base.get(key) != fork.get(key):
            kinds.add(f"top-level {key}")
    return kinds


def main(base_dir, fork_dir, *only):
    files = only or sorted(set(os.listdir(base_dir)) & set(os.listdir(fork_dir)))
    tally = collections.Counter()
    examples = collections.defaultdict(list)
    for f in files:
        base, fork = load(base_dir, f), load(fork_dir, f)
        if base == fork:
            continue
        kinds = classify(base, fork)
        tally[" + ".join(sorted(kinds))] += 1
        examples[" + ".join(sorted(kinds))].append(f)
    for kind, n in tally.most_common():
        print(f"{n:4} {kind}\n      {examples[kind][:6]}")


if __name__ == "__main__":
    main(*sys.argv[1:])
