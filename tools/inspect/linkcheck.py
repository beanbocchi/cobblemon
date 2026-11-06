"""Find references from addon jars to Cobblemon classes, methods and fields that a given Cobblemon jar lacks.

Reads class-file constant pools directly; no JVM needed. A reference counts as resolved when the owner class
(or one of its Cobblemon supertypes) declares the member, or when the lookup walks out of Cobblemon into
Minecraft/JDK classes, which this script can't see.

Usage: python3 -I linkcheck.py <cobblemon.jar> <addon.jar> [addon.jar ...]
"""
import struct
import sys
import zipfile

PREFIX = "com/cobblemon/mod/"


def parse(data):
    """Return (this, super, interfaces, members, refs) for one class file."""
    pos = 10
    count = struct.unpack_from(">H", data, 8)[0]
    cp = [None] * count
    i = 1
    while i < count:
        tag = data[pos]
        if tag == 1:
            n = struct.unpack_from(">H", data, pos + 1)[0]
            cp[i] = ("utf8", data[pos + 3:pos + 3 + n].decode("utf-8", "replace"))
            pos += 3 + n
        elif tag in (3, 4):
            pos += 5
        elif tag in (5, 6):
            pos += 9
            i += 1
        elif tag in (7, 8, 16, 19, 20):
            cp[i] = (tag, struct.unpack_from(">H", data, pos + 1)[0])
            pos += 3
        elif tag in (9, 10, 11, 12, 17, 18):
            cp[i] = (tag,) + struct.unpack_from(">HH", data, pos + 1)
            pos += 5
        elif tag == 15:
            pos += 4
        else:
            raise ValueError(f"bad constant tag {tag}")
        i += 1

    def utf(idx):
        return cp[idx][1]

    def cls(idx):
        return utf(cp[idx][1])

    access, this_i, super_i, n_if = struct.unpack_from(">HHHH", data, pos)
    pos += 8
    interfaces = [cls(struct.unpack_from(">H", data, pos + 2 * k)[0]) for k in range(n_if)]
    pos += 2 * n_if
    members = set()
    for _ in range(2):  # fields, then methods
        n = struct.unpack_from(">H", data, pos)[0]
        pos += 2
        for _ in range(n):
            _, name_i, desc_i, n_attr = struct.unpack_from(">HHHH", data, pos)
            pos += 8
            members.add((utf(name_i), utf(desc_i)))
            for _ in range(n_attr):
                pos += 6 + struct.unpack_from(">I", data, pos + 2)[0]

    refs = set()
    for entry in cp:
        if entry and entry[0] == 7:
            name = utf(entry[1]).lstrip("[").removeprefix("L").removesuffix(";")
            if name.startswith(PREFIX):
                refs.add(("class", name, None, None))
        elif entry and entry[0] in (9, 10, 11):
            owner = cls(entry[1]).lstrip("[").removeprefix("L").removesuffix(";")
            nt = cp[entry[2]]
            if owner.startswith(PREFIX):
                kind = "field" if entry[0] == 9 else "method"
                refs.add((kind, owner, utf(nt[1]), utf(nt[2])))
    this = cls(this_i)
    sup = cls(super_i) if super_i else None
    return this, sup, interfaces, members, refs


def classes(jar):
    with zipfile.ZipFile(jar) as z:
        for n in z.namelist():
            if n.endswith(".class") and not n.startswith("META-INF/versions/"):
                yield parse(z.read(n))


def index(jar):
    return {this: (sup, ifs, members) for this, sup, ifs, members, _ in classes(jar)}


def resolves(idx, owner, name, desc, seen=None):
    seen = seen or set()
    if owner in seen:
        return False
    seen.add(owner)
    if owner not in idx:
        return not owner.startswith(PREFIX)  # walked out of Cobblemon: can't tell, assume fine
    sup, ifs, members = idx[owner]
    if (name, desc) in members:
        return True
    return any(resolves(idx, t, name, desc, seen) for t in [sup, *ifs] if t)


def main(cobblemon_jar, *addons):
    idx = index(cobblemon_jar)
    for jar in addons:
        missing = set()
        for this, _, _, _, refs in classes(jar):
            for kind, owner, name, desc in refs:
                if kind == "class":
                    if owner not in idx:
                        missing.add(f"class  {owner}")
                elif owner in idx or owner.startswith(PREFIX):
                    if not resolves(idx, owner, name, desc):
                        missing.add(f"{kind:6} {owner}.{name}{desc}")
        print(f"== {jar.rsplit('/', 1)[-1]}: {len(missing)} missing")
        for m in sorted(missing)[:25]:
            print("   ", m)
        if len(missing) > 25:
            print(f"    ... {len(missing) - 25} more")
        sys.stdout.flush()


if __name__ == "__main__":
    main(*sys.argv[1:])
