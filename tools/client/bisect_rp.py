"""Binary-search the resource pack that leaves the port profile stuck on the splash screen.

Each round keeps one half of the candidate packs in resourcepacks/, parks the rest, launches the game with
trylaunch.sh and compares the F2 screenshot against a known stuck frame.

Usage: python3 -I bisect_rp.py <stuck reference png>
"""
import os
import shutil
import subprocess
import sys

PROFILE = os.path.expanduser("~/.local/share/ModrinthApp/profiles/COBBLEVERSE-1.7.42-cm1.8.4")
RP = os.path.join(PROFILE, "resourcepacks")
PARK = os.path.join(PROFILE, "rp-parked")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "build", "client-tests")
LAUNCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trylaunch.sh")


def stuck(png, ref):
    def small(p):
        return subprocess.run(["magick", p, "-resize", "160x90!", "png:-"], capture_output=True, check=True).stdout
    a, b = os.path.join(OUT, "_a.png"), os.path.join(OUT, "_b.png")
    open(a, "wb").write(small(png))
    open(b, "wb").write(small(ref))
    r = subprocess.run(["magick", "compare", "-metric", "RMSE", a, b, "null:"], capture_output=True, text=True)
    score = float(r.stderr.split("(")[1].split(")")[0])
    return score < 0.1, score


def run(tag, ref):
    res = subprocess.run([LAUNCH, tag], capture_output=True, text=True).stdout
    png = os.path.join(OUT, f"{tag}-f2.png")
    if "F2 screenshot" not in res or not os.path.exists(png):
        print(f"[{tag}] launch problem:\n{res}", flush=True)
        return None
    s, score = stuck(png, ref)
    print(f"[{tag}] {'STUCK' if s else 'OK'} (rmse {score:.3f})", flush=True)
    return s


def place(keep, all_packs):
    os.makedirs(PARK, exist_ok=True)
    for p in all_packs:
        src_rp, src_park = os.path.join(RP, p), os.path.join(PARK, p)
        if p in keep and os.path.exists(src_park):
            shutil.move(src_park, src_rp)
        elif p not in keep and os.path.exists(src_rp):
            shutil.move(src_rp, src_park)


def main(ref):
    packs = sorted(p for p in os.listdir(RP) if not p.endswith(".rpo"))
    cand = list(packs)
    rnd = 0
    while len(cand) > 1:
        rnd += 1
        half = cand[: len(cand) // 2]
        rest = [p for p in packs if p not in cand]  # already cleared: keep them in, they're innocent
        place(set(half) | set(rest), packs)
        print(f"round {rnd}: testing {len(half)} of {len(cand)} candidates: {half}", flush=True)
        s = run(f"rp{rnd}", ref)
        if s is None:
            break
        cand = half if s else cand[len(cand) // 2:]
    print(f"CANDIDATE: {cand}", flush=True)
    place(set(packs), packs)  # restore everything
    if len(cand) == 1:
        place(set(packs) - set(cand), packs)
        s = run("rp-verify-without", ref)
        print(f"verify: without {cand[0]} -> {'STUCK' if s else 'OK'}", flush=True)
        place(set(packs), packs)


if __name__ == "__main__":
    main(*sys.argv[1:])
