"""One-shot generator for the initial RB-Controller_fix profile library.

Writes profiles under D:/RB-Controller_fix/profiles/<system>/.

Honesty levels:
  V = verified (tested live or sourced from confirmed RetroBat source code)
  K = known with high confidence (from manuals or widely-documented behavior)
  T = TBD / low confidence — included as scaffold for user to refine
"""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent
PROF = ROOT / "profiles"


def write(system: str, name: str, data: dict):
    out = PROF / system / f"{name}.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120),
                   encoding="utf-8")
    print(f"  wrote {out.relative_to(ROOT)}")


# ----------------------- system defaults -----------------------

write("c64", "_default", {
    "system": "c64",
    "title": "C64 system defaults",
    "confidence": "V",
    "notes": (
        "Cross-game defaults for all C64 (VICE x64 / x64sc) games.\n"
        "These core_options are NOT in RetroBat's Configurevice() bind list,\n"
        "so they survive launch-time config regeneration.\n"
        "\n"
        "  vice_mapper_y = RETROK_F1   — controller Y → F1 (standard C64 menu start key)\n"
        "  vice_physical_keyboard_pass_through = enabled — physical keys reach VICE\n"
        "  vice_analogmouse = disabled — left stick joins joystick instead of being mouse\n"
    ),
    "core_options": {
        "vice_mapper_y": "RETROK_F1",
        "vice_physical_keyboard_pass_through": "enabled",
        "vice_analogmouse": "disabled",
    },
})

write("amigacd32", "_default", {
    "system": "amigacd32",
    "title": "Amiga CD32 system defaults",
    "confidence": "V",
    "notes": (
        "CD32 games require the CD32 Pad device type (517) to expose all\n"
        "seven CD32 buttons distinctly:\n"
        "  Red   = RetroPad B    Blue  = RetroPad A\n"
        "  Yellow = RetroPad Y   Green = RetroPad X\n"
        "  Play   = Start        Reverse = Select\n"
        "  Forward = R           Rewind = L\n"
        "Without this, every face button produces 'fire' (RetroPad device 1)."
    ),
    "es_settings": {
        "puae_controller1": "517",
    },
})

write("amiga500", "_default", {
    "system": "amiga500",
    "title": "Amiga 500 system defaults",
    "confidence": "T",
    "notes": (
        "Amiga 500 base config currently uses RetroPad device (1) — the\n"
        "default 1-button joystick mode. Most Amiga games are 1-button.\n"
        "Per-game profiles override device type for specific titles\n"
        "(e.g. 2-button games or mouse-required adventures)."
    ),
})

# ----------------------- C64 per-game -----------------------

write("c64", "Boulder Dash.crt", {
    "system": "c64",
    "rom": "Boulder Dash.crt",
    "title": "Boulder Dash",
    "year": 1984,
    "confidence": "V",
    "notes": (
        "Uses unusual joystick port 1 (CIA-shared with keyboard). Most C64\n"
        "games default to port 2 — Boulder Dash is the well-known exception.\n"
        "F-keys handle menus; controller Y (→F1) cycles player count.\n"
        "Tested live on 2026-05-03."
    ),
    "es_settings": {
        "vice_joyport": "1",
        "GameFocus": "1",
        "c64_model": "C64 PAL auto",
    },
    "button_semantics": {
        "B": "joy fire — START game on selection screen",
        "A": "joy fire 2 (alt fire)",
        "X": "SPACE (selection screen confirm)",
        "Y": "F1 (cycles player count)",
    },
})

write("c64", "Spy Hunter.crt", {
    "system": "c64",
    "rom": "Spy Hunter.crt",
    "title": "Spy Hunter",
    "year": 1985,
    "confidence": "T",
    "notes": (
        "An old .keys file shipped with this ROM mapped L2→J and R2→N.\n"
        "Those are likely Spy Hunter's weapon-fire keys. pad2key is inert\n"
        "for libretro VICE — these can only be expressed via vice_mapper_l2\n"
        "/ vice_mapper_r2 globally, but those are currently RETROK_ESCAPE\n"
        "and RETROK_RETURN (used by other games). Per-game free remap not\n"
        "yet possible without additional plumbing.\n"
        "Action: profile is documentation-only for now."
    ),
    "es_settings": {
        "GameFocus": "1",
        "c64_model": "C64 PAL auto",
    },
    "button_semantics": {
        "L2": "(would be 'J' — weapon select if remap was wired)",
        "R2": "(would be 'N' — weapon select if remap was wired)",
        "B":  "joy fire (machine gun)",
    },
})

write("c64", "IK+.crt", {
    "system": "c64",
    "rom": "IK+.crt",
    "title": "International Karate +",
    "year": 1987,
    "confidence": "K",
    "notes": (
        "Multi-fighter karate. C64 IK+ uses joystick + 1 fire button with\n"
        "8 directional moves; the fire button alone handles most attacks.\n"
        "F-keys configure number of players in pre-game menu."
    ),
    "es_settings": {
        "GameFocus": "1",
        "c64_model": "C64 PAL auto",
    },
})

write("c64", "Bruce Lee.crt", {
    "system": "c64",
    "rom": "Bruce Lee.crt",
    "title": "Bruce Lee",
    "year": 1984,
    "confidence": "K",
    "notes": "Joystick + 1 fire button. F1 starts game. RUN/STOP pauses.",
    "es_settings": {
        "GameFocus": "1",
        "c64_model": "C64 PAL auto",
    },
})

write("c64", "Bubble Bobble.crt", {
    "system": "c64",
    "rom": "Bubble Bobble.crt",
    "title": "Bubble Bobble",
    "year": 1987,
    "confidence": "K",
    "notes": "2-player co-op. F1 = 1P, F3 = 2P, F5 = options, F7 = start.",
    "es_settings": {
        "GameFocus": "1",
        "c64_model": "C64 PAL auto",
    },
})

write("c64", "Last Ninja, The.crt", {
    "system": "c64",
    "rom": "Last Ninja, The.crt",
    "title": "The Last Ninja",
    "year": 1987,
    "confidence": "K",
    "notes": (
        "Joystick + fire. Inventory is via keyboard:\n"
        "  RUN/STOP = inventory toggle\n"
        "  Number keys = item select\n"
        "GameFocus required so physical keyboard reaches the game."
    ),
    "es_settings": {
        "GameFocus": "1",
        "c64_model": "C64 PAL auto",
    },
})

write("c64", "Impossible Mission.crt", {
    "system": "c64",
    "rom": "Impossible Mission.crt",
    "title": "Impossible Mission",
    "year": 1984,
    "confidence": "K",
    "notes": "Joystick + fire. Hold fire to search furniture.",
    "es_settings": {
        "GameFocus": "1",
        "c64_model": "C64 PAL auto",
    },
})

write("c64", "Maniac Mansion Mercury.crt", {
    "system": "c64",
    "rom": "Maniac Mansion Mercury.crt",
    "title": "Maniac Mansion (Mercury)",
    "year": 1987,
    "confidence": "K",
    "notes": (
        "Point-and-click adventure. C64 version is keyboard/joystick hybrid.\n"
        "GameFocus essential for verb selection via keyboard."
    ),
    "es_settings": {
        "GameFocus": "1",
        "c64_model": "C64 PAL auto",
    },
})

write("c64", "Commando.crt", {
    "system": "c64",
    "rom": "Commando.crt",
    "title": "Commando",
    "year": 1985,
    "confidence": "K",
    "notes": "Joystick + fire (gun). Hold fire to lob grenades.",
    "es_settings": {
        "GameFocus": "1",
        "c64_model": "C64 PAL auto",
    },
})

# ----------------------- Amiga CD32 per-game -----------------------

write("amigacd32", "Pirates! Gold (Europe) (En,De).chd", {
    "system": "amigacd32",
    "rom": "Pirates! Gold (Europe) (En,De).chd",
    "title": "Pirates! Gold",
    "year": 1994,
    "confidence": "V",
    "notes": (
        "CD32 7-button pad. System-default puae_controller1=517 covers it.\n"
        "Tested live on 2026-05-03."
    ),
    "button_semantics": {
        "B (Red)":    "Action / select / fire cannon",
        "A (Blue)":   "Cancel / back / exit map screen",
        "Y (Yellow)": "(in-game function — TBD by play)",
        "X (Green)":  "(in-game function — TBD by play)",
        "Start (Play)": "Pause / menu",
    },
})

write("amigacd32", "Cannon Fodder (Europe).chd", {
    "system": "amigacd32",
    "rom": "Cannon Fodder (Europe).chd",
    "title": "Cannon Fodder",
    "year": 1993,
    "confidence": "K",
    "notes": (
        "Mouse-driven action-strategy. CD32 version supports CD32 Pad as\n"
        "mouse-emulation: stick = pointer, Red = left-click (move), Blue =\n"
        "right-click (shoot/grenade). System default device 517 sufficient."
    ),
    "button_semantics": {
        "B (Red)":  "Left mouse click — move squad",
        "A (Blue)": "Right mouse click — fire / lob grenade",
    },
})

write("amigacd32", "Beneath a Steel Sky (Europe) (En,Fr,De,It).chd", {
    "system": "amigacd32",
    "rom": "Beneath a Steel Sky (Europe) (En,Fr,De,It).chd",
    "title": "Beneath a Steel Sky",
    "year": 1994,
    "confidence": "K",
    "notes": (
        "Point-and-click adventure (Revolution Software). CD32 controls\n"
        "use stick for cursor, Red/Blue for verb cycling and interaction."
    ),
    "button_semantics": {
        "Stick":    "Move cursor",
        "B (Red)":  "Interact / use",
        "A (Blue)": "Examine / cycle verb",
    },
})

write("amigacd32", "Battle Chess (Europe).chd", {
    "system": "amigacd32",
    "rom": "Battle Chess (Europe).chd",
    "title": "Battle Chess",
    "year": 1994,
    "confidence": "T",
    "notes": "Chess. CD32 pad → cursor + select/cancel.",
})

write("amigacd32", "Chaos Engine, The (Europe) (En,Fr,De,It).chd", {
    "system": "amigacd32",
    "rom": "Chaos Engine, The (Europe) (En,Fr,De,It).chd",
    "title": "The Chaos Engine",
    "year": 1993,
    "confidence": "K",
    "notes": (
        "Bitmap Brothers run-and-gun. Multi-button: shoot, special weapon,\n"
        "switch character. CD32 pad maps these distinctly when device=517."
    ),
    "button_semantics": {
        "B (Red)":    "Shoot",
        "A (Blue)":   "Special weapon",
        "Y (Yellow)": "Switch character",
        "X (Green)":  "Use item",
    },
})

# ----------------------- Amiga 500 per-game -----------------------

write("amiga500", "Lotus2_v1.12_0497.lha", {
    "system": "amiga500",
    "rom": "Lotus2_v1.12_0497.lha",
    "title": "Lotus Esprit Turbo Challenge II",
    "year": 1991,
    "confidence": "T",
    "notes": (
        "Racing game with stick-shift gear change. Original Amiga supports\n"
        "2-button via 'Up = button 2' style or proper 2-button pad. CD32 Pad\n"
        "device type (517) gives full button distinction. May want to set\n"
        "puae_controller1=517 for this title."
    ),
})

write("amiga500", "CannonFodder_v2.0_0860.lha", {
    "system": "amiga500",
    "rom": "CannonFodder_v2.0_0860.lha",
    "title": "Cannon Fodder",
    "year": 1993,
    "confidence": "K",
    "notes": "Mouse-driven. Need mouse on port 1 (or analog stick → mouse mode).",
})

write("amiga500", "IK+_v1.9_2063.lha", {
    "system": "amiga500",
    "rom": "IK+_v1.9_2063.lha",
    "title": "International Karate +",
    "year": 1987,
    "confidence": "K",
    "notes": "Joystick + fire. Same as C64 version — multi-fighter karate.",
})

write("amiga500", "Gods_v3.2_0666.lha", {
    "system": "amiga500",
    "rom": "Gods_v3.2_0666.lha",
    "title": "Gods",
    "year": 1991,
    "confidence": "K",
    "notes": (
        "Bitmap Brothers platformer. Single-button original; with 'rotate'\n"
        "preset, Up replaces Jump and fire becomes shoot. Consider:\n"
        "  puae_retropad_options = jump  — for single-button + jump-on-up"
    ),
})

write("amiga500", "Barbarian_v2.0_Psygnosis_1011.lha", {
    "system": "amiga500",
    "rom": "Barbarian_v2.0_Psygnosis_1011.lha",
    "title": "Barbarian (Psygnosis)",
    "year": 1987,
    "confidence": "T",
    "notes": "Joystick + fire fighting game. Held-fire + direction = combos.",
})

print("\nDone.")
