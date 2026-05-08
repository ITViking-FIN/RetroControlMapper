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

ORDERED_PASSES: list[ParserConfig] = [
    PASS_1_DEFAULT,
    PASS_2_EXTRA_HEADERS,
    PASS_3_PSM_SWEEP,
    PASS_4_LOOSE,
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
