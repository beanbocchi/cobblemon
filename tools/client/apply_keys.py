"""Force a profile's options.txt keybinds to match the pack layout, keeping every other setting.

Default Options only seeds keys missing from options.txt, so a launcher-created options.txt keeps
vanilla defaults such as socialInteractions on P. This rewrites each key the layout knows about.

Usage: python3 -I apply_keys.py <keybindings.txt> <options.txt>
"""
import shutil
import sys


def main(layout_path, options_path):
    layout = dict(l.rstrip("\n").split(":", 1) for l in open(layout_path, encoding="utf-8") if l.startswith("key_"))
    lines = open(options_path, encoding="utf-8").read().splitlines()
    shutil.copyfile(options_path, options_path + ".bak")
    changed, seen = 0, set()
    for i, line in enumerate(lines):
        name, _, value = line.partition(":")
        if name in layout:
            seen.add(name)
            if value != layout[name]:
                print(f"{name}: {value} -> {layout[name]}")
                lines[i] = f"{name}:{layout[name]}"
                changed += 1
    for name in layout.keys() - seen:
        lines.append(f"{name}:{layout[name]}")
        changed += 1
    open(options_path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print(f"{changed} keybinds updated; backup at {options_path}.bak")


if __name__ == "__main__":
    main(*sys.argv[1:])
