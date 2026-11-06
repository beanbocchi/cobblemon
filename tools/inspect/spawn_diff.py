"""Three-way look at spawn_pool_world: Cobblemon 1.7.3 (base), Cobblemon 1.8.4 (upstream), Cobbleverse (fork).

Usage: python3 -I spawn_diff.py <1.7.3 dir> <1.8.4 dir> <cobbleverse dir>
"""
import collections
import json
import os
import sys


def load(d, f):
    p = os.path.join(d, f)
    if not os.path.exists(p):
        return None
    return json.load(open(p, encoding="utf-8-sig"), strict=False)


def by_id(doc):
    return {s.get("id"): s for s in (doc or {}).get("spawns", [])}


def strip_weight(s):
    return {k: v for k, v in s.items() if k != "weight"}


def main(base_dir, up_dir, fork_dir):
    files = sorted(set(os.listdir(fork_dir)) & set(os.listdir(up_dir)))
    ratios = collections.Counter()
    up_changes = collections.Counter()   # what upstream changed besides weight
    fork_changed_files = 0
    both_changed = []
    for f in files:
        base, up, fork = by_id(load(base_dir, f)), by_id(load(up_dir, f)), by_id(load(fork_dir, f))
        up_other = False
        for sid, u in up.items():
            b = base.get(sid)
            if b is None:
                up_changes["new spawn entry"] += 1
                up_other = True
                continue
            if b.get("weight") and u.get("weight"):
                ratios[round(u["weight"] / b["weight"], 3)] += 1
            if strip_weight(b) != strip_weight(u):
                for k in set(b) | set(u):
                    if k != "weight" and b.get(k) != u.get(k):
                        up_changes[k] += 1
                up_other = True
        if set(base) - set(up):
            up_changes["removed spawn entry"] += 1
            up_other = True
        fork_changed = base != fork
        fork_changed_files += fork_changed
        if fork_changed and up_other:
            both_changed.append(f)
    print(f"overlapping files: {len(files)}")
    print(f"weight ratio 1.8.4/1.7.3: {ratios.most_common(8)}")
    print(f"upstream non-weight changes by key: {dict(up_changes)}")
    print(f"files Cobbleverse changed vs 1.7.3: {fork_changed_files}")
    print(f"files changed on both sides (need merge): {len(both_changed)}")
    print("  e.g.", both_changed[:15])
    only_fork = sorted(set(os.listdir(fork_dir)) - set(os.listdir(up_dir)))
    only_up = sorted(set(os.listdir(up_dir)) - set(os.listdir(fork_dir)))
    print(f"only in Cobbleverse: {len(only_fork)}; only in 1.8.4: {len(only_up)} {only_up}")
    fw = collections.Counter(round(s.get("weight", 0), 1) for f in only_fork for s in by_id(load(fork_dir, f)).values())
    print(f"weights in Cobbleverse-only files: {fw.most_common(8)}")


if __name__ == "__main__":
    main(*sys.argv[1:])
