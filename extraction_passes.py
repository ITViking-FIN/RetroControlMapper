"""
Extraction pass definitions — the cascade of parser configs.

Multi-pass extraction climbs the yield curve: each subsequent pass runs
ONLY on titles where the previous yielded zero bindings, picking up
manuals the earlier passes couldn't crack. The four passes get
progressively broader (and lower-precision):

    pass1_default          high-precision, tight heuristics, PSM 3 OCR
    pass2_extra_headers    pass1 + genre-specific section headings
                           (sports/fighter/RPG/menu boilerplate)
    pass3_psm_sweep        re-OCR with PSM 6 (single block) and PSM 4
                           (column) and pick whichever yields more
    pass4_loose            looser regex thresholds, action validation,
                           low-confidence flag — last-resort scoop

Each binding records `pass_name` so the GUI can show "extracted by
pass 3 — confidence: low; please double-check" if useful.
"""
from __future__ import annotations

from manual_extract import ParserConfig

# Single source of truth for extractor version. Bumped whenever heuristics
# change in a way that would meaningfully alter outputs — so a future
# `--upgrade-below-version <V>` run can selectively re-extract just the
# titles that were processed under older logic.
#
# Versioning convention: "<release>-<heuristic-tag>" (sortable as strings).
# Tags so far:
#   0.1.4-baseline             initial OCR + 5-pass cascade
#   0.1.4-multidirection       compound joystick directions emit one
#                               binding per cardinal; OCR vocab fixes
#                               (ieft→left etc.); lazy quantifiers in
#                               action-by-verb fix LEAP-class clipping
EXTRACTOR_VERSION = "0.1.4-multidirection"

# Headers that signal a controls section in genre-specific contexts
# the default list misses. Real-world examples observed in manuals:
#   "OFFENSE" / "DEFENSE"           — sports manuals (10-Yard Fight, NHL)
#   "MOVES" / "SPECIAL MOVES"        — fighting games (SF2, Mortal Kombat)
#   "BATTLE COMMANDS" / "MAGIC"      — RPGs (Final Fantasy, Phantasy Star)
#   "PUNCH" / "KICK" / "BLOCK"       — beat-em-ups
#   "SHOOT" / "BOMB"                 — shmups
#   "FIELD CONTROLS"                 — sports/sims
EXTRA_HEADERS_PASS_2 = [
    "offense", "defense",
    "moves", "special moves",
    "battle commands", "magic", "spells",
    "fighting techniques", "techniques",
    "punch", "kick", "block",
    "shoot", "bomb", "weapons",
    "field controls", "in-game controls",
    "running the game", "playing",
    "menu controls", "menu screens",
    "starting and playing",
    "command summary", "command reference",
    "joypad", "joypads",
    "control summary", "key summary",
    "input", "inputs",
]

# Pass 4 adds a few looser regex shapes that are too noisy for
# pass 1 but pull useful bindings from prose-heavy descriptions:
#   "X Button. <verb>"     — period-separator style (Saturn manuals)
#   "<verb> with the X"    — postfix style (some PSX manuals)
#   "X = <verb>"           — terse table cells
import re
EXTRA_LINE_PATTERNS_PASS_4 = [
    # "A Button. Jumps."
    ("button-period",
     re.compile(r"^([A-Za-z][A-Za-z0-9 \-/()]{0,40}?(?:button|trigger|stick|pad))"
                r"\s*[.]\s+(.{2,80})$", re.I),
     "low"),
    # "<verb> with the X button"
    ("verb-with-button",
     re.compile(r"^([A-Z][a-z]{1,30})\s+with\s+(?:the\s+)?"
                r"([A-Za-z][A-Za-z0-9 \-]{0,30}?(?:button|trigger|pad))\s*[.]?\s*$", re.I),
     "low"),
]


# ============================================================
# Pass definitions
# ============================================================

PASS_1_DEFAULT = ParserConfig(
    name="pass1_default",
    psm=3,
    looser_action_filter=False,
    confidence_floor="high",
)

PASS_2_EXTRA_HEADERS = ParserConfig(
    name="pass2_extra_headers",
    psm=3,
    extra_section_headers=EXTRA_HEADERS_PASS_2,
    looser_action_filter=False,
    confidence_floor="medium",
)

# Pass 3 needs special handling: it actually runs the same parser but
# multiple PSMs. The orchestrator special-cases it. We define a base
# config here for the params that don't change.
PASS_3_PSM_SWEEP = ParserConfig(
    name="pass3_psm_sweep",
    psm=6,    # primary PSM for this pass; orchestrator may also try 4
    extra_section_headers=EXTRA_HEADERS_PASS_2,  # carry pass 2's headers
    looser_action_filter=False,
    confidence_floor="medium",
)

PASS_4_LOOSE = ParserConfig(
    name="pass4_loose",
    psm=3,
    extra_section_headers=EXTRA_HEADERS_PASS_2,
    extra_line_patterns=EXTRA_LINE_PATTERNS_PASS_4,
    looser_action_filter=True,
    confidence_floor="low",
)


# ============================================================
# Pass 5 — single-button-joystick specialist
# ============================================================
#
# Manuals for Atari 2600/ST, C64, Amiga, Amstrad CPC, MSX, ZX Spectrum
# describe controls fundamentally differently from the Nintendo /
# PlayStation lineage that pass 1 was tuned for. Examples real-world
# observed in the archive:
#
#   "Push the joystick up to climb"
#   "Pull joystick down to crouch"
#   "Press fire to shoot"
#   "Joystick left - Walk left"
#   "Up = Jump, Down = Duck, Fire = Attack"
#
# Pass 5 narrows scope to systems known to use this paradigm and adds
# patterns specifically for direction-based and fire-only vocab.

# RetroBat system ids known to use joystick + 1-2 fire button(s) only.
# Manuals for these tend to spell controls as "joystick up = climb"
# rather than "A Button: Jump". Pass 5 only fires for these systems.
SINGLE_BUTTON_SYSTEMS = {
    # Atari
    "atari2600", "atari5200", "atari7800", "atari800", "atarist",
    "lynx", "jaguar", "jaguarcd",
    # Commodore
    "c64", "c20", "amiga500", "amiga1200", "amiga4000", "amigacd32",
    # Sinclair / Amstrad / dragon
    "zxspectrum", "amstradcpc", "gx4000", "dragon32", "atom",
    # MSX family
    "msx1", "msx2", "msxturbor",
    # Misc retro
    "vectrex", "intellivision", "colecovision",
    "channelf", "advision", "creatiVision",
    "astrocade", "arcadia", "odyssey2",
    "ti99", "apple2",
    # SNK pocket / minor handhelds
    "ngp", "ngpc", "wonderswan", "wonderswancolor",
}

PASS_5_HEADERS = [
    "joystick controls",
    "your joystick",
    "playing with the joystick",
    "the joystick",
    "the fire button",
    "moving",
    "movement",
    "loading and playing",
    "loading the game",
    "instructions",
    "joystick or keyboard",
    "keyboard controls",
    "keys",
    "key controls",
]

import re
PASS_5_PATTERNS = [
    # "Push joystick up to climb" / "Pull joystick down to crouch" /
    # "Move joystick left to walk" / "Tilt joystick right to turn"
    ("joystick-direction-to",
     re.compile(r"^(?:push|pull|move|tilt|hold)\s+(?:the\s+)?joystick\s+"
                r"(up|down|left|right|north|south|east|west)\s+(?:to|will|you\s+can)\s+(.{2,80})$",
                re.I),
     "high"),
    # "Joystick up - Climb" / "Joystick LEFT: Walk left"
    ("joystick-direction-dash",
     re.compile(r"^joystick\s+(up|down|left|right|north|south|east|west)"
                r"\s*[-:=]\s*(.{2,80})$", re.I),
     "high"),
    # Bare directional shorthand in tabular form: "Up - Jump", "Down: Crouch"
    ("direction-shorthand",
     re.compile(r"^(up|down|left|right)\s*[-:=]\s*(.{2,80})$", re.I),
     "medium"),
    # "Press fire to shoot" — already in default but here we tighten
    # to require fire as the literal token (no false positives).
    ("fire-to-action",
     re.compile(r"^(?:press|hold|tap|push)\s+(?:the\s+)?(fire(?:\s+button)?)"
                r"\s+(?:to|will)\s+(.{2,80})$", re.I),
     "high"),
    # "Fire - Shoot" / "FIRE: Punch"
    ("fire-dash",
     re.compile(r"^(fire(?:\s+button)?)\s*[-:=]\s*(.{2,80})$", re.I),
     "high"),
    # "Fire + Up = Special move" / "Fire + Direction → Throw"
    ("fire-plus-direction",
     re.compile(r"^fire(?:\s+button)?\s*\+\s*(up|down|left|right|"
                r"diagonal|any\s+direction)\s*[-:=→]\s*(.{2,80})$", re.I),
     "medium"),
    # ACTION-FIRST PROSE: "KICK by pressing the joystick button".
    # 4-tuple form with swap=True flips the regex groups: group 1 (the
    # action verb) becomes the binding's action, group 2 (the input
    # phrase) becomes the button. Real C64/Amiga manual samples this
    # rescues:
    #   "KICK by pressing the joystick button while you are running"
    #   "PUNCH by pressing the joystick button while you are standing"
    #   "LEAP by moving the joystick up and to the left or right"
    #   "CLIMB up a vine by ... moving the joystick up"
    # Group 1 = ALL-CAPS verb (3-15 chars). The action verb may be
    # followed by short lowercase qualifiers ("CLIMB up a vine") — we
    # allow up to ~30 chars of object phrase before "by VERBING".
    # Group 2 = input phrase, captured greedily through end-of-line.
    # _canonical_button's tier-2 prefix-shrink + tier-3 direction
    # detection handles trailing prose like "while you are running" or
    # "and to the left or right".
    ("action-by-verb",
     re.compile(r"^([A-Z]{3,15})"
                # Both optional middle groups are LAZY (`??`) — the engine
                # tries empty first so the trailing alternation can capture
                # the FULL "the joystick ..." phrase. With greedy `?`, the
                # middle would happily eat "the joystick up and to" and leave
                # only "the left or right" for the input phrase, losing the
                # primary direction (dpad_up) on multi-direction sentences.
                r"(?:\s+[a-z][a-z\s,]{0,50}?)??"               # optional short object
                r"\s+by\s+"
                r"(?:pressing|holding|tapping|moving|using|"
                r"positioning|tilting)"
                r"(?:\s+[a-z][a-z\s,.\-]{0,60}?)??"             # "yourself under it,"
                r"\s+(the\s+joystick(?:\s+(?:button|up|down|left|right))?\b.*"
                r"|the\s+fire\s+button\b.*"
                r"|the\s+(?:up|down|left|right)\b.*)"          # OCR may drop 'joystick'
                r"$", re.I),
     "medium",
     True),                       # swap=True
    # Tabular layouts (Up    Climb / Down    Jump) need to be detected
    # BEFORE _clean_ocr_line collapses multi-space into single — that's
    # a separate concern from line-pattern matching. Skipped here;
    # could be a future addition with a pre-clean tabular detector.
]

PASS_5_SINGLE_BUTTON = ParserConfig(
    name="pass5_single_button",
    psm=3,
    extra_section_headers=PASS_5_HEADERS,
    extra_line_patterns=PASS_5_PATTERNS,
    looser_action_filter=True,
    confidence_floor="medium",
    system_filter=SINGLE_BUTTON_SYSTEMS,
    # Single-button-system manuals describe controls in flowing prose
    # that wraps across 2-3 lines. The action-by-verb pattern would
    # otherwise miss "LEAP ... by moving the joystick\nup and to the
    # left" because line 1 ends without 'up' and line 2 doesn't have
    # the action verb.
    merge_wrapped_lines=True,
)

ORDERED_PASSES: list[ParserConfig] = [
    PASS_1_DEFAULT,
    PASS_2_EXTRA_HEADERS,
    PASS_3_PSM_SWEEP,
    PASS_4_LOOSE,
    PASS_5_SINGLE_BUTTON,
]


# Special-case alternate PSMs for pass 3. The orchestrator runs each
# in turn for a single title and keeps whichever yielded the most
# bindings. Cached, so PSM 3 already-OCR'd from pass 1 is free.
PASS_3_PSM_OPTIONS = [6, 4, 11]


def get_pass(name: str) -> ParserConfig | None:
    """Lookup helper — pass name → config object."""
    for cfg in ORDERED_PASSES:
        if cfg.name == name: return cfg
    return None


def passes_after(name: str) -> list[ParserConfig]:
    """All passes that come AFTER `name` in the cascade. Used to resume
    from a partial multi-pass run."""
    seen = False
    out = []
    for cfg in ORDERED_PASSES:
        if seen:
            out.append(cfg)
        if cfg.name == name:
            seen = True
    return out
