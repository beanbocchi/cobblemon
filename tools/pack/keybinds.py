"""Write the pack's default keybindings (Default Options keybindings.txt) from Cobbleverse's file plus our layout.

Usage: python3 -I keybinds.py <cobbleverse keybindings.txt> <out keybindings.txt>
"""
import sys

OFF = "key.keyboard.unknown"
K = "key.keyboard."

LAYOUT = {
    # Pokémon, left hand
    "key.cobblemon.throwpartypokemon": K + "r",
    "key.cobblemon.upshiftparty": K + "z",
    "key.cobblemon.downshiftparty": K + "x",
    "key.cobblemon.summary": K + "c",
    "key.cobblemon.pokenavigator": K + "n",
    "key.fightorflight.startbattle": K + "g",
    "key.lumymon.access_pc": K + "p",
    "key.lumymon.dismount": K + "v",
    "key.cobblemon.ridingfreelook": K + "left.alt",
    "key.mega_showdown.mega_evo": K + "y",
    "key.mega_showdown.ultra_key": OFF,
    # Mouse side buttons
    "zoomify.key.zoom": "key.mouse.4",
    "key.pingwheel.ping_location": "key.mouse.5",
    # Inventory and world
    "keybind.sophisticatedbackpacks.open_backpack": K + "b",
    "accessories.key.open_accessories_screen": K + "h",
    "gui.xaero_open_map": K + "m",
    "gui.xaero_waypoints_key": K + "u",
    "iris.keybind.toggleShaders": K + "k",
    # Raids
    "key.cobblemonraiddens.accept": K + "f6",
    "key.cobblemonraiddens.deny": K + "f7",
    "key.cobblemonraiddens.mouse": K + "right.control",
    # Unbound: debug, config screens, rarely used toggles
    "key.cobblemon.hideparty": OFF,
    "key.cobblemon.printmodelsettings": OFF,
    "key.cobblemon.scaleportraitdown": OFF,
    "key.cobblemon.scaleportraitup": OFF,
    "key.cobblemon.translateportraitdown": OFF,
    "key.cobblemon.translateportraitleft": OFF,
    "key.cobblemon.translateportraitright": OFF,
    "key.cobblemon.translateportraitup": OFF,
    "key.cobblemon.toggleridingstatsgui": OFF,
    "key.cobblemon-battle-extras.controller_config": OFF,
    "key.fightorflight.should_display_notification_bar": OFF,
    "key.fightorflight.cmdmode.auto_battle": OFF,
    "key.catchrate.show_comparison": OFF,
    "key.more_cobblemon_tweaks.open_config": OFF,
    "key.musicnotification.open_screen": OFF,
    "key.modernfix.config": OFF,
    "key.toms_storage.open_terminal": OFF,
    "gui.xaero_minimap_settings": OFF,
    "gui.xaero_enlarge_map": OFF,
    "gui.xaero_open_settings": OFF,
    "zoomify.key.zoom.secondary": OFF,
}


def main(src, out):
    lines, seen = [], set()
    for line in open(src, encoding="utf-8"):
        line = line.rstrip("\n")
        if not line.startswith("key_"):
            continue
        name = line.split(":", 1)[0].removeprefix("key_")
        seen.add(name)
        lines.append(f"key_{name}:{LAYOUT.get(name, line.split(':', 1)[1])}")
    lines += [f"key_{name}:{key}" for name, key in LAYOUT.items() if name not in seen]

    bound = {}
    for line in lines:
        name, key = line.removeprefix("key_").split(":", 1)
        if key != OFF:
            bound.setdefault(key, []).append(name)
    # GUI-only binds share keys with world binds on purpose (sort on middle click).
    gui_only = {"keybind.sophisticatedbackpacks.sort", "keybind.sophisticatedstorage.sort", "gui.xaero_quick_confirm"}
    clashes = {k: v for k, v in bound.items() if len([n for n in v if n not in gui_only]) > 1}
    for k, v in clashes.items():
        print(f"CLASH {k}: {v}")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"wrote {len(lines)} bindings, {sum(k != OFF for k in bound)} keys in use, {len(clashes)} clashes")


if __name__ == "__main__":
    main(*sys.argv[1:])
