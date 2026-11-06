"""Write hidden_abilities.json: species -> hidden ability, for the Hidden Grotto in cvlife.py.

Usage: python3 -I build_grotto.py <Cobblemon jar> <out.json>

Reads data/cobblemon/species/*/*.json and keeps implemented species whose ability list has an "h:" entry.
"""
import json
import sys
import zipfile


def main(jar, out):
    z = zipfile.ZipFile(jar)
    rows = {}
    for n in z.namelist():
        if n.startswith("data/cobblemon/species/") and n.endswith(".json"):
            d = json.loads(z.read(n))
            if not d.get("implemented"):
                continue
            hidden = [a[2:] for a in d.get("abilities", []) if isinstance(a, str) and a.startswith("h:")]
            if hidden:
                rows[n.rsplit("/", 1)[1][:-5]] = hidden[0]
    json.dump(dict(sorted(rows.items())), open(out, "w"), indent=0)
    print(len(rows), "species")


if __name__ == "__main__":
    main(*sys.argv[1:])
