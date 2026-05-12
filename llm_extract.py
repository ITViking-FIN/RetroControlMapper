"""
LLM-based binding extraction (v0.2 spike).

Reads OCR'd manual text + a system "passport" (allowed buttons, game
metadata) and uses a local LLM via Ollama HTTP API to extract
button-to-action bindings. Implements the contract specified in
``docs/LLM_PROTOCOL.md`` — that document is the source of truth; this
module must match it.

## Design tenets (mirror of LLM_PROTOCOL.md)

1. **Verbatim or nothing.** Each binding carries a ``source_quote``
   field that must appear verbatim in the input. The validator drops
   any binding whose quote isn't present — kills hallucinations.

2. **Closed-vocabulary buttons.** Each system has an explicit list of
   allowed canonical button names. The LLM cannot invent new ones.

3. **Section-scoped input.** Caller passes the controls SECTION text,
   not the whole manual.

4. **Strict JSON output.** ``format: "json"`` in Ollama's API
   constrains output. One retry on malformed JSON; abandon after that.

5. **Rejection log.** Every dropped binding writes a JSONL record to
   ``data/llm_rejections.jsonl`` for later analysis / prompt refinement.

## Usage

    from llm_extract import LLMExtractor, SystemPassport
    ex = LLMExtractor(endpoint="http://localhost:11434",
                       model="qwen2.5:3b")
    passport = SystemPassport.for_system("snes", "Super Mario World",
                                          era_hint="1991",
                                          genre_hint="platformer")
    result = ex.extract_bindings(controls_section_text, passport)
    for b in result["bindings"]:
        print(b)

## CLI

    py llm_extract.py ping              # check ollama reachable
    py llm_extract.py extract --pdf <path> --system snes --rom "<title>"
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
REJECTION_LOG = DATA_DIR / "llm_rejections.jsonl"
# Uncertain bindings — items the LLM flagged as ambiguous via the
# `uncertain` array in its response. Logged for human review; never
# enter the bindings DB on their own. A separate review CLI could
# later promote them to bindings or reject them.
UNCERTAIN_LOG = DATA_DIR / "llm_uncertain.jsonl"
# Per-call telemetry — one record per LLM extraction. Feeds the
# llm_visualize.py learning-curve chart (speed/yield trends over time).
CALL_LOG = DATA_DIR / "llm_calls.jsonl"

PROTOCOL_VERSION = "1.0"
# Default Ollama endpoint. Localhost is the safe public default; users
# point at a LAN box via the `RBCF_LLM_ENDPOINT` env var or the
# --endpoint CLI flag. The hybrid feed orchestrator and any future
# GUI integration honour the same env var.
DEFAULT_ENDPOINT = os.environ.get("RBCF_LLM_ENDPOINT",
                                  "http://localhost:11434")
DEFAULT_MODEL    = os.environ.get("RBCF_LLM_MODEL", "qwen2.5:3b")
DEFAULT_TIMEOUT  = 60   # seconds per call (warm)
DEFAULT_RETRIES  = 1    # one retry on malformed JSON


# ============================================================
# Per-system button passports — closed vocabularies
# ============================================================

# Each system_id maps to its allowed canonical button names. The LLM
# only ever sees the list relevant to one game. Anything outside this
# list during validation is rejected.
SYSTEM_BUTTONS: dict[str, list[str]] = {
    # Universal dpad fragment reused by many systems
    "_dpad": ["dpad_up", "dpad_down", "dpad_left", "dpad_right"],

    # Nintendo lineage
    "nes":      ["a", "b", "start", "select"],
    "snes":     ["a", "b", "x", "y", "l", "r", "start", "select"],
    "sfc":      ["a", "b", "x", "y", "l", "r", "start", "select"],
    "n64":      ["a", "b", "cup", "cdown", "cleft", "cright",
                 "z", "l", "r", "start"],
    "gamecube": ["a", "b", "x", "y", "z", "l", "r", "start",
                 "cstick_up", "cstick_down", "cstick_left", "cstick_right"],
    "gb":       ["a", "b", "start", "select"],
    "gbc":      ["a", "b", "start", "select"],
    "gba":      ["a", "b", "l", "r", "start", "select"],
    "nds":      ["a", "b", "x", "y", "l", "r", "start", "select"],
    "switch":   ["a", "b", "x", "y", "l", "r", "zl", "zr",
                 "plus", "minus"],
    "virtualboy": ["a", "b", "l", "r", "start", "select",
                    "ldpad_up", "ldpad_down", "ldpad_left", "ldpad_right",
                    "rdpad_up", "rdpad_down", "rdpad_left", "rdpad_right"],

    # Sega lineage
    "megadrive":    ["a", "b", "c", "x", "y", "z", "start", "mode"],
    "genesis":      ["a", "b", "c", "x", "y", "z", "start", "mode"],
    "mastersystem": ["1", "2", "start"],
    "gamegear":     ["1", "2", "start"],
    "sega32x":      ["a", "b", "c", "x", "y", "z", "start", "mode"],
    "saturn":       ["a", "b", "c", "x", "y", "z", "l", "r", "start"],
    "dreamcast":    ["a", "b", "x", "y", "l_trig", "r_trig", "start",
                     "stick_up", "stick_down", "stick_left", "stick_right"],

    # Sony lineage
    "psx": ["triangle", "circle", "cross", "square", "l1", "l2",
            "r1", "r2", "start", "select"],
    "ps2": ["triangle", "circle", "cross", "square", "l1", "l2",
            "r1", "r2", "l3", "r3", "start", "select",
            "lstick_up", "lstick_down", "lstick_left", "lstick_right",
            "rstick_up", "rstick_down", "rstick_left", "rstick_right"],
    "psp": ["triangle", "circle", "cross", "square", "l", "r",
            "start", "select"],

    # Microsoft
    "xbox":    ["a", "b", "x", "y", "l_trig", "r_trig", "white", "black",
                 "start", "back",
                 "lstick_up", "lstick_down", "lstick_left", "lstick_right",
                 "rstick_up", "rstick_down", "rstick_left", "rstick_right"],
    "xbox360": ["a", "b", "x", "y", "lb", "rb", "lt", "rt",
                 "start", "back",
                 "lstick_up", "lstick_down", "lstick_left", "lstick_right",
                 "rstick_up", "rstick_down", "rstick_left", "rstick_right"],

    # Atari
    "atari2600":    ["fire"],
    "atari5200":    ["fire", "side_button", "start", "pause", "reset",
                     "key:0", "key:1", "key:2", "key:3", "key:4",
                     "key:5", "key:6", "key:7", "key:8", "key:9",
                     "key:star", "key:hash"],
    "atari7800":    ["fire1", "fire2", "select", "pause", "reset"],
    "atarist":      ["fire"],
    "lynx":         ["a", "b", "option1", "option2", "pause"],
    "jaguar":       ["a", "b", "c", "pause", "option",
                     "key:0", "key:1", "key:2", "key:3", "key:4",
                     "key:5", "key:6", "key:7", "key:8", "key:9",
                     "key:star", "key:hash"],

    # Commodore family
    "c64":        ["fire"],
    "c20":        ["fire"],
    "amiga500":   ["fire", "button2"],
    "amiga1200":  ["fire", "button2"],
    "amiga4000":  ["fire", "button2"],
    "amigacd32":  ["red", "blue", "green", "yellow", "fwd", "rev",
                    "play", "pause"],

    # Sinclair / Amstrad family
    "zxspectrum":  ["fire"],
    "amstradcpc":  ["fire1", "fire2"],
    "gx4000":      ["1", "2", "pause"],
    "dragon32":    ["fire"],

    # MSX family
    "msx1":       ["a", "b"],
    "msx2":       ["a", "b"],

    # Misc retro / specialty
    "vectrex":       ["1", "2", "3", "4"],
    "intellivision": ["top", "left_action", "right_action",
                       "key:0", "key:1", "key:2", "key:3", "key:4",
                       "key:5", "key:6", "key:7", "key:8", "key:9",
                       "key:clear", "key:enter"],
    "colecovision":  ["lp", "rp", "key:0", "key:1", "key:2", "key:3",
                       "key:4", "key:5", "key:6", "key:7", "key:8",
                       "key:9", "key:star", "key:hash"],
    "channelf":      ["fwd", "rev", "twist_left", "twist_right",
                       "pull", "push"],
    "odyssey2":      ["fire"],
    "astrocade":     ["fire"],
    "vic20":         ["fire"],
    "ti99":          ["fire"],
    "apple2":        ["fire1", "fire2"],

    # Neo Geo / SNK pockets
    "neogeo":     ["a", "b", "c", "d", "start", "select"],
    "ngp":        ["a", "b", "option"],
    "ngpc":       ["a", "b", "option"],

    # Bandai / NEC etc.
    "pcengine":   ["1", "2", "run", "select"],
    "tg16":       ["1", "2", "run", "select"],
    "tg16cd":     ["1", "2", "run", "select"],

    # 3DO
    "3do":        ["a", "b", "c", "l", "r", "p", "x", "stop", "play"],

    # CD-i / Philips
    "cdi":        ["1", "2"],
}


# Common keyboard-key add-ons many systems share (we include relevant
# subsets in the passport when the controls section mentions them).
COMMON_KEYBOARD_KEYS = [
    "key:f1", "key:f2", "key:f3", "key:f4", "key:f5", "key:f6",
    "key:f7", "key:f8", "key:f9", "key:f10", "key:f11", "key:f12",
    "key:space", "key:enter", "key:esc", "key:tab", "key:shift",
    "key:ctrl", "key:alt",
]


def _resolve_buttons(system_id: str, include_dpad: bool = True,
                     include_kbd: bool = False) -> list[str]:
    """Return the canonical button list for a system, with optional
    extras. Always includes the system's primary buttons; optionally
    appends dpad_* and keyboard keys."""
    sys_buttons = list(SYSTEM_BUTTONS.get(system_id) or [])
    if include_dpad and not any(b.startswith("dpad_") for b in sys_buttons):
        sys_buttons.extend(SYSTEM_BUTTONS["_dpad"])
    if include_kbd:
        sys_buttons.extend(COMMON_KEYBOARD_KEYS)
    return sys_buttons


# ============================================================
# System passport — the context bundle passed to the LLM
# ============================================================

@dataclass
class SystemPassport:
    """Per-game context the LLM needs to interpret a controls section.
    Built once per extraction call by the orchestrator."""
    system_id:    str
    system_name:  str
    buttons:      list[str]
    game_title:   str
    era_hint:     str = ""           # e.g. "1991"
    genre_hint:   str = ""           # e.g. "platformer"

    @classmethod
    def for_system(cls, system_id: str, game_title: str, **hints) -> "SystemPassport":
        # Friendlier human names. Many fall through to a Title-cased id.
        SYSTEM_NAME_MAP = {
            "nes": "Nintendo Entertainment System",
            "snes": "Super Nintendo Entertainment System",
            "psx": "Sony PlayStation",
            "ps2": "Sony PlayStation 2",
            "psp": "Sony PlayStation Portable",
            "n64": "Nintendo 64",
            "gb": "Game Boy", "gbc": "Game Boy Color", "gba": "Game Boy Advance",
            "megadrive": "Sega Mega Drive / Genesis",
            "genesis":   "Sega Mega Drive / Genesis",
            "gamecube": "Nintendo GameCube",
            "saturn": "Sega Saturn", "dreamcast": "Sega Dreamcast",
            "c64": "Commodore 64", "amiga500": "Commodore Amiga 500",
            "amiga1200": "Commodore Amiga 1200", "amiga4000": "Commodore Amiga 4000",
            "amstradcpc": "Amstrad CPC", "zxspectrum": "Sinclair ZX Spectrum",
            "atari2600": "Atari 2600", "atarist": "Atari ST",
            "neogeo": "SNK Neo Geo", "pcengine": "NEC PC Engine / TurboGrafx-16",
            "xbox": "Microsoft Xbox", "xbox360": "Microsoft Xbox 360",
            "mastersystem": "Sega Master System",
            "intellivision": "Mattel Intellivision",
            "colecovision": "Coleco Vision",
        }
        return cls(
            system_id=system_id,
            system_name=SYSTEM_NAME_MAP.get(system_id, system_id.title()),
            buttons=_resolve_buttons(
                system_id,
                include_dpad=True,
                include_kbd=hints.get("include_kbd", False)),
            game_title=game_title,
            era_hint=hints.get("era_hint", ""),
            genre_hint=hints.get("genre_hint", ""),
        )


# ============================================================
# Ollama HTTP client — minimal stdlib-only
# ============================================================

class LLMError(RuntimeError):
    pass


class LLMClient:
    """Thin Ollama HTTP client. Stateless beyond config. The orchestrator
    creates one and reuses it across calls."""

    def __init__(self, endpoint: str = DEFAULT_ENDPOINT,
                 model: str = DEFAULT_MODEL,
                 timeout: int = DEFAULT_TIMEOUT):
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.timeout = timeout

    def ping(self) -> dict:
        """Probe ``/api/tags`` to confirm reachability + see which models
        are loaded. Raises LLMError on connect failure."""
        try:
            req = urllib.request.Request(f"{self.endpoint}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.loads(r.read())
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise LLMError(f"ollama unreachable at {self.endpoint}: {e}")

    def generate(self, prompt: str, *, json_mode: bool = True,
                 temperature: float = 0.1,
                 num_predict: int = 600) -> dict:
        """POST to ``/api/generate``. Returns the parsed JSON response
        dict including ``response`` (the text), ``eval_count`` (output
        tokens), ``prompt_eval_count`` (input tokens), etc."""
        body = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "format": "json" if json_mode else None,
            "stream": False,
            "options": {"temperature": temperature,
                        "num_predict": num_predict},
        }).encode("utf-8")
        try:
            req = urllib.request.Request(
                f"{self.endpoint}/api/generate", data=body,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read())
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise LLMError(f"ollama call failed: {e}")


# ============================================================
# Prompt builder — implements LLM_PROTOCOL.md exactly
# ============================================================

def build_prompt(section_text: str, passport: SystemPassport,
                 prior_examples: list = None) -> str:
    """Compose the user-facing prompt. Empirically refined for the
    Qwen2.5-3B model class: short and concrete, anchored by a one-shot
    example, rules near the example so the model treats them as
    instructions not abstract guidance.

    `prior_examples` (optional): list of llm_memory.Example records from
    the per-system pool. Injected AFTER the generic example block,
    BEFORE the new input. Strategically placed early in the prompt so
    Ollama's prompt-cache can reuse the system + examples prefix across
    same-system calls within a batch — meaningful latency reduction
    on long runs.

    Tested findings (v0.2 spike, 2026-05-12):
      - long rule lists confuse small models -> output empty/minimal
      - "verbatim or nothing" strict mode causes zero output -> relaxed
        to source_quote field which the orchestrator validates post-hoc
      - one-shot example dramatically improves action-verb selection
        (without it the model picks weak verbs like 'deliver' instead of
        the canonical move name)
      - the example MUST demonstrate the compound-direction rule
        explicitly or the model emits only one direction"""
    buttons_csv = ", ".join(passport.buttons)
    era = f", {passport.era_hint}" if passport.era_hint else ""
    genre = f", {passport.genre_hint}" if passport.genre_hint else ""

    # System-specific accumulated examples — injected just before the
    # new input. Format chosen for Ollama prompt-cache compatibility
    # (deterministic order, fixed-width fields).
    learned_block = ""
    if prior_examples:
        from llm_memory import format_examples_for_prompt
        learned_block = "\n" + format_examples_for_prompt(prior_examples)

    # Style-guide block — variations and pitfalls the LLM should know.
    # Filtered to the system family (joystick vs gamepad) so we don't
    # spend tokens explaining gamepad patterns to single-button-system
    # extractions and vice versa.
    from llm_style_guide import format_style_guide
    style_block = format_style_guide(passport.system_id)

    return f"""Extract video game button bindings from this manual section. The ACTION is the ALL-CAPS or capitalized verb at the start of each sentence (KICK, LEAP, JUMP, RUN, etc.) — that is the move name. Match each move to the physical input that triggers it.

GAME: {passport.game_title}
SYSTEM: {passport.system_name}{era}{genre}

Available inputs (use ONLY these names — no others):
{buttons_csv}

RULES:
- "joystick button" or "fire button" = `fire` on single-button systems.
- DE-9 joysticks have NO diagonal switches. "up and to the left or right" means THREE separate bindings: dpad_up, dpad_left, dpad_right — all mapping to the same action.
- If a sentence mentions an input NOT in the Available list (e.g. ENTER key, RESET button), SKIP that binding.
- Combos like "Down, Down-Forward, Forward + Punch" are GAME MECHANICS, not bindings. Skip them.
- Each binding must have a `source_quote` field with a verbatim substring of the input text. The orchestrator validates this.

EXAMPLE input:
"KICK by pressing the joystick button while running.
WALK left and right by moving the joystick.
JUMP by pressing the fire button.
PAUSE the game by pressing the SPACE key."

EXAMPLE output:
{{"bindings": [
  {{"button":"fire", "action":"Kick", "confidence":"high",
    "source_quote":"KICK by pressing the joystick button while running"}},
  {{"button":"dpad_left", "action":"Walk", "confidence":"high",
    "source_quote":"WALK left and right by moving the joystick"}},
  {{"button":"dpad_right", "action":"Walk", "confidence":"high",
    "source_quote":"WALK left and right by moving the joystick"}},
  {{"button":"fire", "action":"Jump", "confidence":"high",
    "source_quote":"JUMP by pressing the fire button"}}
], "uncertain": [], "notes": ""}}

(PAUSE skipped because SPACE key is not in Available inputs.)
{style_block}{learned_block}
NOW EXTRACT FROM:
\"\"\"
{section_text}
\"\"\"

Output JSON only:"""


# ============================================================
# Validation — enforces protocol on LLM output
# ============================================================

@dataclass
class ValidationResult:
    bindings:   list[dict] = field(default_factory=list)
    rejected:   list[dict] = field(default_factory=list)
    uncertain:  list[dict] = field(default_factory=list)
    notes:      str = ""
    raw_call_info: dict = field(default_factory=dict)


def _is_valid_action(action: str) -> bool:
    if not action: return False
    if len(action) < 2 or len(action) > 80: return False
    letter_ratio = sum(1 for c in action if c.isalpha()) / len(action)
    return letter_ratio >= 0.5


def _quote_in_text(quote: str, text: str) -> bool:
    """Verbatim check, case-insensitive, whitespace-normalised. The LLM
    sometimes reflows the quote slightly (extra spaces); be lenient on
    whitespace but strict on word content."""
    if not quote or not text: return False
    norm_quote = re.sub(r"\s+", " ", quote).strip().lower()
    norm_text  = re.sub(r"\s+", " ", text).strip().lower()
    return norm_quote in norm_text


def validate(raw_response: str, section_text: str,
             passport: SystemPassport) -> ValidationResult:
    """Parse + validate the LLM's JSON response per the protocol. Drops
    invalid bindings; survivors get returned in ``bindings``. Rejected
    bindings get returned with reasons for the rejection log."""
    out = ValidationResult()
    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError as e:
        out.rejected.append({"reason": "invalid_json", "error": str(e),
                             "raw": raw_response[:500]})
        return out

    if not isinstance(parsed, dict) or "bindings" not in parsed:
        out.rejected.append({"reason": "missing_bindings_array",
                             "raw": raw_response[:500]})
        return out

    out.notes = (parsed.get("notes") or "").strip()
    bindings_raw = parsed.get("bindings") or []
    if not isinstance(bindings_raw, list):
        out.rejected.append({"reason": "bindings_not_array",
                             "raw": raw_response[:500]})
        return out

    seen = set()
    allowed = set(passport.buttons)
    for b in bindings_raw:
        if not isinstance(b, dict):
            out.rejected.append({"reason": "binding_not_object", "binding": b})
            continue
        btn   = (b.get("button") or "").strip()
        act   = (b.get("action") or "").strip()
        conf  = (b.get("confidence") or "medium").strip().lower()
        quote = (b.get("source_quote") or "").strip()

        if btn not in allowed:
            out.rejected.append({"reason": "button_not_in_passport",
                                 "binding": b}); continue
        if not _is_valid_action(act):
            out.rejected.append({"reason": "action_invalid",
                                 "binding": b}); continue
        if conf not in ("high", "medium", "low"):
            conf = "medium"
        if not _quote_in_text(quote, section_text):
            out.rejected.append({"reason": "source_quote_not_found",
                                 "binding": b}); continue
        key = (btn, act.lower())
        if key in seen:
            out.rejected.append({"reason": "duplicate", "binding": b}); continue
        seen.add(key)

        out.bindings.append({
            "button":       btn,
            "action":       act.rstrip(".,;"),
            "confidence":   conf,
            "source_quote": quote,
            "matched_by":   "llm",
            "extractor":    "llm-qwen2.5-3b",
        })

    # Uncertain items: the LLM flagged these as ambiguous. Don't enter
    # the bindings DB but route to llm_uncertain.jsonl for async human
    # review. Schema is more permissive than bindings — tentative
    # button might not even be in passport (the LLM is asking).
    for u in (parsed.get("uncertain") or []):
        if not isinstance(u, dict): continue
        # Must at least have a source_quote present in input to be
        # diagnostic. Otherwise it's just noise.
        u_quote = (u.get("source_quote") or "").strip()
        if not u_quote or not _quote_in_text(u_quote, section_text):
            continue
        out.uncertain.append({
            "tentative_button": (u.get("tentative_button") or "").strip(),
            "tentative_action": (u.get("tentative_action") or "").strip(),
            "source_quote":     u_quote,
            "reason":           (u.get("reason") or "").strip(),
        })
    return out


# ============================================================
# Rejection log
# ============================================================

def _section_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def log_rejections(rejections: list[dict], passport: SystemPassport,
                   section_text: str):
    """Append rejection records to data/llm_rejections.jsonl. Best-effort;
    silent on I/O errors (rejection log is diagnostic only)."""
    if not rejections: return
    REJECTION_LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    section_h = _section_hash(section_text)
    try:
        with REJECTION_LOG.open("a", encoding="utf-8") as f:
            for r in rejections:
                rec = {
                    "timestamp":         ts,
                    "system_id":         passport.system_id,
                    "game_title":        passport.game_title,
                    "section_text_hash": section_h,
                    "protocol_version":  PROTOCOL_VERSION,
                    **r,
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def log_call(passport: SystemPassport, section_text: str,
             bindings: list[dict], uncertain: list[dict],
             rejected: list[dict], call_info: dict,
             used_examples: int, memory_outcome: dict | None,
             pool_size_after: int | None):
    """One-line JSONL telemetry record per LLM call. Schema matches
    llm_visualize.py's reader."""
    CALL_LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "timestamp":         time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "system_id":         passport.system_id,
        "game_title":        passport.game_title,
        "section_len":       len(section_text or ""),
        "elapsed_s":         call_info.get("elapsed_s"),
        "prompt_eval_count": call_info.get("prompt_eval_count"),
        "eval_count":        call_info.get("eval_count"),
        "bindings_count":    len(bindings or []),
        "rejected_count":    len(rejected or []),
        "uncertain_count":   len(uncertain or []),
        "used_examples":     used_examples,
        "memory_added":      bool(memory_outcome and memory_outcome.get("added_to_memory")),
        "pool_size_after":   pool_size_after,
        "model":             call_info.get("model"),
        "protocol_version":  PROTOCOL_VERSION,
    }
    try:
        with CALL_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def log_uncertain(uncertain: list[dict], passport: SystemPassport,
                  section_text: str):
    """Append the LLM-flagged-as-uncertain items to llm_uncertain.jsonl
    for later human review. The protocol allows the LLM to ask 'I see
    a candidate but I'm not sure' rather than forcing a guess into the
    bindings DB."""
    if not uncertain: return
    UNCERTAIN_LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    section_h = _section_hash(section_text)
    try:
        with UNCERTAIN_LOG.open("a", encoding="utf-8") as f:
            for u in uncertain:
                rec = {
                    "timestamp":         ts,
                    "system_id":         passport.system_id,
                    "game_title":        passport.game_title,
                    "section_text_hash": section_h,
                    "protocol_version":  PROTOCOL_VERSION,
                    **u,
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


# ============================================================
# Top-level extractor
# ============================================================

class LLMExtractor:
    """Orchestrates: build_prompt -> call LLM -> validate -> log.

    Optional `memory` parameter enables few-shot learning: examples
    from the per-system pool get injected into prompts, and successful
    extractions get offered back to the pool. Over a batch run, the
    pool grows and prompts get richer for the same compute budget —
    the LLM "learns" via prompt engineering rather than weight
    updates, exploiting Ollama's prompt-cache for free latency wins."""

    def __init__(self, endpoint: str = DEFAULT_ENDPOINT,
                 model: str = DEFAULT_MODEL,
                 retries: int = DEFAULT_RETRIES,
                 timeout: int = DEFAULT_TIMEOUT,
                 memory: "LLMMemory | None" = None,
                 examples_per_prompt: int = 2,
                 auto_save_memory: bool = True):
        self.client = LLMClient(endpoint=endpoint, model=model, timeout=timeout)
        self.retries = retries
        self.model = model
        self.memory = memory
        self.examples_per_prompt = examples_per_prompt
        self.auto_save_memory = auto_save_memory

    def extract_bindings(self, section_text: str,
                         passport: SystemPassport) -> dict:
        """Run extraction. Returns a dict with bindings, rejections,
        notes, and call metadata (token counts, latency)."""
        if not section_text or not section_text.strip():
            return {"bindings": [], "rejected": [],
                    "notes": "empty section text",
                    "call_info": {}}

        # Pull system-specific examples from memory if available
        prior_examples = None
        if self.memory is not None and self.examples_per_prompt > 0:
            prior_examples = self.memory.get_examples(
                passport.system_id, n=self.examples_per_prompt)

        prompt = build_prompt(section_text, passport,
                              prior_examples=prior_examples)
        last_err = None
        last_resp = None
        last_call_info: dict = {}

        for attempt in range(self.retries + 1):
            t0 = time.time()
            try:
                resp = self.client.generate(prompt, json_mode=True)
            except LLMError as e:
                last_err = str(e); break
            elapsed = time.time() - t0
            last_call_info = {
                "elapsed_s":         round(elapsed, 2),
                "eval_count":        resp.get("eval_count", 0),
                "prompt_eval_count": resp.get("prompt_eval_count", 0),
                "model":             self.model,
                "attempt":           attempt + 1,
            }
            last_resp = resp.get("response", "")
            val = validate(last_resp, section_text, passport)
            # Retry if JSON outright invalid; otherwise accept
            invalid_json = any(r.get("reason") == "invalid_json"
                              for r in val.rejected)
            if not invalid_json or attempt >= self.retries:
                log_rejections(val.rejected, passport, section_text)
                log_uncertain(val.uncertain, passport, section_text)
                # Offer the extraction to memory if quality is good
                memory_outcome = None
                if self.memory is not None and val.bindings:
                    output_for_memory = {"bindings": val.bindings,
                                         "notes": val.notes}
                    added, reason = self.memory.consider(
                        passport.system_id, section_text,
                        output_for_memory,
                        validator_rejected=len(val.rejected))
                    memory_outcome = {"added_to_memory": added,
                                      "reason": reason}
                    if added and self.auto_save_memory:
                        self.memory.save()
                # Capture post-call pool size for learning-curve telemetry
                pool_size_after = None
                if self.memory is not None:
                    pool_size_after = self.memory.stats().get(
                        passport.system_id, {}).get("pool_size", 0)
                # Per-call telemetry record
                log_call(passport, section_text, val.bindings,
                         val.uncertain, val.rejected, last_call_info,
                         len(prior_examples or []), memory_outcome,
                         pool_size_after)
                return {
                    "bindings":      val.bindings,
                    "uncertain":     val.uncertain,
                    "rejected":      val.rejected,
                    "notes":         val.notes,
                    "call_info":     last_call_info,
                    "memory":        memory_outcome,
                    "used_examples": len(prior_examples or []),
                }
            # Strict-retry prompt prefix
            prompt = ("YOUR PREVIOUS RESPONSE WAS NOT VALID JSON. "
                      "OUTPUT MUST BE A JSON OBJECT, NOTHING ELSE.\n\n"
                      + prompt)

        return {
            "bindings": [], "rejected": [
                {"reason": "persistent_failure",
                 "error": last_err or "no response",
                 "last_raw": (last_resp or "")[:500]}
            ],
            "notes": "all retries failed",
            "call_info": last_call_info,
        }


# ============================================================
# CLI
# ============================================================

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=False)
    sub.add_parser("ping", help="Confirm ollama reachable + list models.")
    E = sub.add_parser("extract", help="End-to-end extraction on one PDF.")
    E.add_argument("--pdf", required=True)
    E.add_argument("--system", required=True)
    E.add_argument("--rom", required=True, help="Game title.")
    E.add_argument("--era", default="")
    E.add_argument("--genre", default="")
    E.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    E.add_argument("--model", default=DEFAULT_MODEL)
    E.add_argument("--show-section", action="store_true")
    E.add_argument("--no-memory", action="store_true",
                   help="Skip the few-shot memory store entirely.")
    E.add_argument("--examples", type=int, default=2,
                   help="How many memory examples to inject into the prompt "
                        "(default 2). Set to 0 to disable.")
    args = ap.parse_args()

    if args.cmd is None:
        ap.print_help(); return

    if args.cmd == "ping":
        cli = LLMClient()
        try:
            info = cli.ping()
            print(f"Endpoint: {cli.endpoint}")
            print(f"Reachable: yes")
            for m in info.get("models", []):
                size_mb = m.get("size", 0) / (1024 * 1024)
                print(f"  {m.get('name'):<24} {size_mb:>7.0f} MB  "
                      f"params={m.get('details', {}).get('parameter_size')}")
        except LLMError as e:
            print(f"[error] {e}", file=sys.stderr); sys.exit(1)
        return

    if args.cmd == "extract":
        # Read OCR + section detection via existing pipeline
        from manual_extract import (
            _read_pdf_text, _find_section, _coalesce_header_followed_by_action,
            _merge_wrapped_lines, _expand_tabular_rows)

        lines, page_count, source = _read_pdf_text(Path(args.pdf), ocr=True)
        if not lines:
            print(f"[error] could not OCR PDF (source={source})",
                  file=sys.stderr); sys.exit(2)

        # Same section finder used by regex passes — keeps the
        # LLM's input identical to what regex sees
        lines = _expand_tabular_rows(lines)
        span = _find_section(lines)
        if span is not None:
            start, end = span
            section_lines = _coalesce_header_followed_by_action(
                lines[start:end + 1])
            section_text = "\n".join(section_lines)
        else:
            section_text = "\n".join(lines[:200])
            print(f"[note] no controls section header detected; "
                  f"feeding LLM the first 200 lines", file=sys.stderr)

        if args.show_section:
            print("--- SECTION TEXT ---")
            print(section_text)
            print("--- END SECTION ---\n")

        passport = SystemPassport.for_system(
            args.system, args.rom,
            era_hint=args.era, genre_hint=args.genre)
        print(f"System:   {passport.system_name}")
        print(f"Game:     {passport.game_title}")
        print(f"Buttons:  {len(passport.buttons)} allowed "
              f"({', '.join(passport.buttons[:6])}{'...' if len(passport.buttons) > 6 else ''})")
        print(f"Section:  {len(section_text)} chars\n")

        memory = None
        if not args.no_memory:
            from llm_memory import LLMMemory
            memory = LLMMemory()
        ex = LLMExtractor(endpoint=args.endpoint, model=args.model,
                          memory=memory, examples_per_prompt=args.examples)
        result = ex.extract_bindings(section_text, passport)
        ci = result.get("call_info", {})
        print(f"LLM call: {ci.get('elapsed_s', 0)}s  "
              f"in={ci.get('prompt_eval_count', 0)} tok, "
              f"out={ci.get('eval_count', 0)} tok  "
              f"(used {result.get('used_examples', 0)} prior examples)")
        print(f"Bindings: {len(result['bindings'])} accepted, "
              f"{len(result['rejected'])} rejected")
        if result.get("memory"):
            m = result["memory"]
            tag = "ADDED to memory" if m["added_to_memory"] else "not added"
            print(f"Memory:   {tag} - {m['reason']}\n")
        else:
            print()
        for b in result["bindings"]:
            print(f"  {b['button']:>12} -> {b['action']:<30} "
                  f"[{b['confidence']}]")
            print(f"               quote: {b['source_quote'][:60]!r}")
        if result["rejected"]:
            print("\nRejections:")
            for r in result["rejected"][:5]:
                print(f"  {r.get('reason'):<30} {str(r.get('binding', ''))[:80]}")
        uncertain = result.get("uncertain") or []
        if uncertain:
            print(f"\nUncertain (flagged for review — {len(uncertain)} items):")
            for u in uncertain[:5]:
                print(f"  ?  {u.get('tentative_button', '?'):>10} -> "
                      f"{u.get('tentative_action', '?')[:30]}")
                print(f"     reason: {u.get('reason', '')[:80]}")
                print(f"     quote:  {u.get('source_quote', '')[:60]!r}")
        if result.get("notes"):
            print(f"\nLLM notes: {result['notes']}")


if __name__ == "__main__":
    main()
