"""List keybinding names each mod jar registers, by reading string constants in classes that use KeyMapping.

Matches strings against the jar's own en_us.json so only translated binding names survive. Nested jars
(META-INF/jars) are scanned too.

Usage: python3 -I keyscan.py <out.json> <jar> [jar ...]
"""
import io
import json
import re
import struct
import sys
import zipfile

KEYMAPPING = ("net/minecraft/class_304", "com/mojang/blaze3d/platform/InputConstants", "net/minecraft/class_3675")
NAME = re.compile(r"^(key|keys|keybind|keybinds|keybinding|gui\.xaero)[._].+")


def strings_if_keymapping(data):
    count = struct.unpack_from(">H", data, 8)[0]
    pos, i, utf, strings, classes = 10, 1, {}, [], set()
    while i < count:
        tag = data[pos]
        if tag == 1:
            n = struct.unpack_from(">H", data, pos + 1)[0]
            utf[i] = data[pos + 3:pos + 3 + n].decode("utf-8", "replace")
            pos += 3 + n
        elif tag in (3, 4):
            pos += 5
        elif tag in (5, 6):
            pos += 9
            i += 1
        elif tag == 7:
            classes.add(struct.unpack_from(">H", data, pos + 1)[0])
            pos += 3
        elif tag == 8:
            strings.append(struct.unpack_from(">H", data, pos + 1)[0])
            pos += 3
        elif tag in (16, 19, 20):
            pos += 3
        elif tag in (9, 10, 11, 12, 17, 18):
            pos += 5
        elif tag == 15:
            pos += 4
        else:
            return []
        i += 1
    if not any(utf.get(c, "").startswith(KEYMAPPING) for c in classes) and "class_304" not in "".join(utf.values()):
        return []
    return [utf[s] for s in strings if s in utf]


def scan(z, name, out):
    lang = {}
    for n in z.namelist():
        if n.endswith("lang/en_us.json"):
            try:
                lang.update(json.loads(z.read(n).decode("utf-8-sig"), strict=False))
            except Exception:
                pass
    found = set()
    for n in z.namelist():
        if n.endswith(".class"):
            for s in strings_if_keymapping(z.read(n)):
                if NAME.match(s) and (s in lang or s.startswith("gui.xaero")):
                    found.add(s)
        elif n.startswith("META-INF/jars/") and n.endswith(".jar"):
            scan(zipfile.ZipFile(io.BytesIO(z.read(n))), n.rsplit("/", 1)[-1], out)
    if found:
        out[name] = {k: lang.get(k, "") for k in sorted(found)}


def main(out_path, *jars):
    out = {}
    for j in jars:
        try:
            scan(zipfile.ZipFile(j), j.rsplit("/", 1)[-1], out)
        except zipfile.BadZipFile:
            pass
    json.dump(out, open(out_path, "w"), indent=1, ensure_ascii=False)
    print(sum(len(v) for v in out.values()), "bindings in", len(out), "jars")


if __name__ == "__main__":
    main(*sys.argv[1:])
