"""
Style guide for the LLM — manual-variation patterns and pitfalls.

Modern game manuals use a small number of recurring vocabulary patterns
to describe controls, but the small LLM doesn't know which is which.
This module teaches it explicitly through compact prompt fragments:

  1. **Variations** — six recognised styles ("Press X to Y", action-first
     prose, tabular columns, button-header blocks, etc.). The prompt
     includes 1-2 micro-examples per variation, system-family-filtered
     so joystick systems see joystick variations and gamepad systems
     see gamepad variations.

  2. **Pitfalls** — six common mistakes the LLM (or any naive parser)
     makes. Each pitfall has a bad-input example, the wrong output, and
     the correct response (usually "skip — that's not a binding").

  3. **Uncertainty channel** — instructions for the LLM to FLAG ambiguous
     bindings into an `uncertain` array instead of forcing them into
     `bindings`. The orchestrator routes uncertain items to a separate
     log for asynchronous human review rather than letting bad guesses
     pollute the bindings DB.

Designed for token efficiency. Total prompt cost for the guide is
~250-400 tokens depending on system family — well within the budget
that still benefits from Ollama prompt-caching.

## Public API

    from llm_style_guide import format_style_guide
    guide = format_style_guide(system_id="c64")   # joystick variations
    guide = format_style_guide(system_id="snes")  # gamepad variations
    # Pass into build_prompt as the `style_guide` parameter.

## Maintenance

When a new failure mode is discovered in `data/llm_rejections.jsonl`
or `data/llm_uncertain.jsonl`, add a PITFALL entry here with the
example + corrective instruction. Treat this file like a regression
test for the LLM's behaviour.
"""
from __future__ import annotations


# ============================================================
# System-family classification (which variations apply where)
# ============================================================

JOYSTICK_SYSTEMS = {
    "atari2600", "atari5200", "atari7800", "atari800", "atarist",
    "lynx", "jaguar", "jaguarcd",
    "c64", "c20", "amiga500", "amiga1200", "amiga4000",
    "amstradcpc", "gx4000", "dragon32", "atom",
    "zxspectrum", "msx1", "msx2", "msxturbor",
    "vectrex", "intellivision", "colecovision",
    "channelf", "advision", "creatiVision",
    "astrocade", "arcadia", "odyssey2",
    "ti99", "apple2", "vic20",
    "ngp", "ngpc",
}

GAMEPAD_SYSTEMS = {
    "nes", "snes", "sfc", "n64", "gamecube",
    "gb", "gbc", "gba", "nds", "switch",
    "megadrive", "genesis", "mastersystem", "gamegear",
    "sega32x", "saturn", "dreamcast",
    "psx", "ps2", "psp",
    "xbox", "xbox360",
    "neogeo", "pcengine", "tg16", "tg16cd", "3do", "cdi",
    "amigacd32",
}


def _family(system_id: str) -> str:
    if system_id in JOYSTICK_SYSTEMS: return "joystick"
    if system_id in GAMEPAD_SYSTEMS: return "gamepad"
    return "any"


# ============================================================
# VARIATIONS — recognised manual styles
# ============================================================

# Each variation: name, brief description, one tight example. Kept
# minimal so the LLM sees the SHAPE without reading paragraphs of
# explanation. The applies_to field gates which prompt families see it.
VARIATIONS = [
    {
        "name": "press-to-action",
        "applies_to": "any",
        "summary": "Press X to <action>",
        "example": '"Press A to jump." → {"button":"a","action":"Jump","source_quote":"Press A to jump"}',
    },
    {
        "name": "button-header",
        "applies_to": "gamepad",
        "summary": "Button name on its own line, action on following line(s)",
        "example": (
            '"A Button\\n  Spin Jump — Use while running" '
            '→ {"button":"a","action":"Spin Jump","source_quote":"Spin Jump"}'
        ),
    },
    {
        "name": "dash-mapping",
        "applies_to": "any",
        "summary": "Button - action (table cell style)",
        "example": '"L1 — Strafe left" → {"button":"l1","action":"Strafe left","source_quote":"L1 — Strafe left"}',
    },
    {
        "name": "action-first-prose",
        "applies_to": "joystick",
        "summary": "ACTION (all-caps verb) by VERB-ing the X",
        "example": (
            '"KICK by pressing the joystick button" '
            '→ {"button":"fire","action":"Kick","source_quote":"KICK by pressing the joystick button"}'
        ),
    },
    {
        "name": "compound-joystick",
        "applies_to": "joystick",
        "summary": "DE-9 joystick diagonal = TWO simultaneous cardinal bindings",
        "example": (
            '"LEAP by moving the joystick up and to the left" → '
            'TWO bindings sharing action "Leap": dpad_up + dpad_left'
        ),
    },
    {
        "name": "tabular",
        "applies_to": "any",
        "summary": "Columnar: <button>  <gap>  <action>",
        "example": (
            '"Up    Climb up vine\\nDown  Climb down" → '
            '{dpad_up:"Climb up vine"} + {dpad_down:"Climb down"}'
        ),
    },
]


# ============================================================
# PITFALLS — explicit don'ts
# ============================================================

# Each pitfall: name, bad input, the wrong output a naive parser would
# produce, the correct response (usually "skip"). Phrased as short
# prohibitions the LLM can scan quickly.
PITFALLS = [
    {
        "name": "cross-reference",
        "bad_input": '"See the Options section for joystick configuration."',
        "wrong":     '{button:"dpad_left", action:"OPTIONS", source_quote:"...Options..."}',
        "correct":   'Skip. "See the X section" is a pointer to documentation, not a binding.',
    },
    {
        "name": "combo-as-binding",
        "bad_input": '"Hadouken: Down, Down-Forward, Forward + Punch"',
        "wrong":     'Any binding for "Hadouken"',
        "correct":   'Skip. Move-sequence combos are game mechanics; the game recognises the input pattern internally.',
    },
    {
        "name": "legal-or-warning",
        "bad_input": '"Copyright 1991 Nintendo. All rights reserved."',
        "wrong":     'Anything extracted from copyright / warning / safety text',
        "correct":   'Skip. Legal and warning boilerplate is not gameplay.',
    },
    {
        "name": "menu-navigation-flavor",
        "bad_input": '"Use the joystick to navigate the title screen menu."',
        "wrong":     'A separate binding for "navigate title screen"',
        "correct":   'Skip — generic UI navigation is implicit on every system; do not pollute bindings with it.',
    },
    {
        "name": "story-description",
        "bad_input": '"Bruce Lee fights his way past the Green Yamo and the Ninja."',
        "wrong":     'A binding for "fight" or "Green Yamo"',
        "correct":   'Skip. Story / lore text is not control documentation.',
    },
    {
        "name": "missing-button-or-action",
        "bad_input": '"The fire button is on top of the joystick."',
        "wrong":     'A binding with empty/garbage action',
        "correct":   'Skip when ONLY a button is mentioned without a paired action verb. A binding needs BOTH.',
    },
    {
        "name": "ocr-garbled",
        "bad_input": '"i by pres8ing the j0ystick buttor"',
        "wrong":     'Hallucinated "Punch" binding based on context guess',
        "correct":   'If OCR is too garbled to read confidently, route the candidate to the "uncertain" array instead of "bindings". Better to flag than to guess.',
    },
]


# ============================================================
# UNCERTAINTY CHANNEL
# ============================================================

UNCERTAINTY_INSTRUCTIONS = """
If a candidate binding is AMBIGUOUS — you can read it but you're not
sure if it's actually a control binding, or which interpretation is
correct — DO NOT put it in "bindings". Put it in the "uncertain"
array instead with a brief reason. The orchestrator routes uncertain
items to human review rather than letting guesses contaminate the DB.

Trigger uncertainty when:
- The action word could be a verb OR a noun (e.g. "Magic" — cast spell or magic menu?)
- The OCR text is degraded; you're filling in gaps
- The same button appears mapped to two different actions and you can't tell which is the canonical binding
- A button name in the manual doesn't exactly match the Available inputs

Uncertain item shape:
{"tentative_button": "<name>", "tentative_action": "<best-guess phrase>",
 "source_quote": "<verbatim from input>", "reason": "<why unsure, one line>"}
"""


# ============================================================
# Formatter
# ============================================================

def format_style_guide(system_id: str) -> str:
    """Render the system-family-filtered style guide as a prompt
    fragment. Kept compact for prompt-cache friendliness."""
    fam = _family(system_id)

    # Filter variations: include "any" + family-matching ones
    relevant_variations = [
        v for v in VARIATIONS
        if v["applies_to"] == "any" or v["applies_to"] == fam
    ]

    parts = ["\nRECOGNISED MANUAL STYLES (extract via any of these patterns):"]
    for v in relevant_variations:
        parts.append(f"- {v['summary']}: {v['example']}")

    parts.append("\nCOMMON MISTAKES TO AVOID:")
    for p in PITFALLS:
        parts.append(f"- {p['name']}: {p['correct']}")

    parts.append(UNCERTAINTY_INSTRUCTIONS.strip())

    return "\n".join(parts) + "\n"


if __name__ == "__main__":
    # Quick sanity check
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    for sid in ["c64", "snes", "saturn"]:
        guide = format_style_guide(sid)
        print(f"\n{'=' * 60}\nSystem: {sid}  ({_family(sid)} family)\n{'=' * 60}")
        print(guide)
        print(f"[length: {len(guide)} chars]")
