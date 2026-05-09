"""
Manual → bindings extractor (Stage 2 of the manual-research pipeline).

Takes a cached PDF (produced by `manual_local.extract_local_manual()` or
`manual_research_online.research_manual()`), pulls plain text from it,
finds the controls section, and runs line-level heuristics to produce
a structured list of {button, action} pairs the GUI can show as
suggestions.

This is **deliberately heuristic and noisy**. Game manuals from 30+
years across dozens of platforms have wildly inconsistent layouts.
Some are scanned bitmaps with garbage OCR. Some bury controls in the
middle of a paragraph. Some use pictograms that pypdf can't read at
all. The extractor's job isn't to be authoritative — it's to surface
candidates so the user has *something* to confirm, instead of mapping
buttons from scratch with no information.

Always present output to the user as suggestions, not facts. Confidence
levels are rough hints, not probabilities.

## Pipeline

```
PDF  →  pypdf text extract  →  section finder  →  line parser
                                     │                  │
                              "CONTROLS" / "HOW   "A Button - Jump"
                               TO PLAY" / etc.    "Press B to fire"
                                                  "FIRE: shoots"
                                                       │
                                                       v
                                            [{button, action, ...}]
```

## Public API

    from manual_extract import extract_bindings_from_pdf
    result = extract_bindings_from_pdf(Path("data/manuals/snes/foo.pdf"))
    if result["section_found"]:
        for b in result["bindings"]:
            print(f"{b['button']:>10}  →  {b['action']}  ({b['confidence']})")

## CLI

    py manual_extract.py path/to/manual.pdf
    py manual_extract.py --system snes --rom "Super Mario World"
        (resolves through manual_local.lookup_local_manual + extract)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent


# ============================================================
# Parser config — drives the multi-pass cascade
# ============================================================

@dataclass
class ParserConfig:
    """Tunable knobs for one pass over a PDF. Multi-pass extraction
    runs each named config in sequence over titles where the previous
    pass yielded zero bindings, climbing the yield curve from the
    high-precision default toward looser, broader heuristics."""
    name: str
    psm: int = 3                            # tesseract page-segmentation mode
    extra_section_headers: list[str] = field(default_factory=list)
    looser_action_filter: bool = False       # reduce letter_ratio / length thresholds
    extra_line_patterns: list[tuple] = field(default_factory=list)
    accept_global_scan: bool = True          # whether the no-section-found fallback runs
    max_section_lines: int = 80
    confidence_floor: str = "medium"         # passes 3+ tag results as "low" by default
    # Optional: limit this pass to specific RetroBat system ids. Used by
    # pass 5 (single-button systems) which would generate noise if run
    # against multi-button platforms. None = run on every system.
    system_filter: set[str] | None = None
    # Merge wrapped sentences before line parsing. Many manual control
    # descriptions span 2-3 lines ("LEAP to get from one ledge to another
    # by moving the joystick\nup and to the ieft or right."). Default
    # False — pass 1 relies on lines being separate. Pass 5 enables this
    # for prose-heavy joystick manuals.
    merge_wrapped_lines: bool = False

# ============================================================
# Section detection
# ============================================================

# Headers that introduce a controls section. Case-insensitive substring
# match; we normalise whitespace before checking. Order matters — the
# more specific phrases first so "GAME CONTROLS" wins over "CONTROLS".
SECTION_HEADERS = [
    "game controls",
    "controller buttons",
    "button configuration",
    "button layout",
    "controls",
    "how to play",
    "playing the game",
    "gameplay",
    "operation",
    "joystick",
    "gamepad",
    "key configuration",
    "names of controller parts",      # NES-era boilerplate header
    "controller parts",
    "your controller",
    "using the controller",
    "using the control pad",
    "taking control",
    "control pad",
    "directional pad",
    "command summary",
    "starting the game",              # often where button list begins
    "starting up",
]

# Headers that signal we've LEFT the controls section. When we find one
# inside the captured chunk, we stop expanding.
SECTION_TERMINATORS = [
    "story",
    "characters",
    "credits",
    "warranty",
    "limited warranty",
    "table of contents",
    "saving",
    "options menu",
    "items",
    "world map",
    "tips and tricks",
]

# How many lines to capture after a header before we hit a terminator.
MAX_SECTION_LINES = 80


# ============================================================
# Line parsers — ordered most-specific first
# ============================================================

# Aliases that recur across systems. Map raw matches to canonical keys.
# We keep the manual's original button text in `raw` so the GUI can
# show what the manual *actually* said.
BUTTON_TOKENS = {
    # Face buttons — letter style (NES/SNES/Saturn/etc.)
    "a button":  "a",      "b button":  "b",      "c button":  "c",
    "x button":  "x",      "y button":  "y",      "z button":  "z",
    "l button":  "l",      "r button":  "r",
    "a":         "a",      "b":         "b",
    "x":         "x",      "y":         "y",
    # PlayStation glyphs (Latin transcriptions; Unicode rare in old PDFs)
    "triangle":  "triangle",
    "circle":    "circle",
    "cross":     "cross",
    "x (cross)": "cross",
    "square":    "square",
    "l1":        "l1",     "l2":        "l2",
    "r1":        "r1",     "r2":        "r2",
    # Modern shoulders / triggers
    "lb":        "l1",     "rb":        "r1",
    "lt":        "l2",     "rt":        "r2",
    "select":    "select", "start":     "start",
    "options":   "start",  "share":     "select",
    # Generic
    "fire button":   "fire",
    "fire":          "fire",
    "button 1":      "btn1",
    "button 2":      "btn2",
    "button 3":      "btn3",
    "button 4":      "btn4",
    "button a":      "a",
    "button b":      "b",
    # D-pad / stick
    "d-pad":          "dpad",
    "directional pad": "dpad",
    "joystick":        "stick",
    "control pad":     "dpad",
    "left stick":      "lstick",
    "right stick":     "rstick",
    # Direction tokens — workhorses for single-button-joystick systems
    # (Atari 2600/ST, C64, Amiga, Amstrad, MSX, ZX Spectrum). Manuals
    # of that era describe controls as "Push joystick up to climb" /
    # "Up: Jump" rather than "A Button: Jump". Pass 5's patterns yield
    # these tokens and rely on the canonical mapping below.
    "up":             "dpad_up",
    "down":           "dpad_down",
    "left":           "dpad_left",
    "right":          "dpad_right",
    "joystick up":    "dpad_up",
    "joystick down":  "dpad_down",
    "joystick left":  "dpad_left",
    "joystick right": "dpad_right",
    "stick up":       "dpad_up",
    "stick down":     "dpad_down",
    "stick left":     "dpad_left",
    "stick right":    "dpad_right",
    # On single-button systems, "joystick button" alone (without
    # "fire") is the only action button — same target as fire.
    "joystick button": "fire",
    "the joystick":    "stick",
    "the fire button": "fire",
    "the joystick button": "fire",
}


# Patterns. Each yields (button_text, action_text) on match. Order =
# priority; first match wins.
LINE_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    # "A Button - Jump" / "A Button: Jump" / "A Button = Jump"
    ("button-dash",
     re.compile(r"^([A-Za-z][A-Za-z0-9 \-/()]{0,40}?(?:button|trigger|stick|pad))"
                r"\s*[-:=]\s*(.{2,80})$", re.I),
     "high"),
    # "A: Jump" / "X = Punch"
    ("letter-colon",
     re.compile(r"^([A-Za-z]{1,2}|L1|L2|R1|R2|LB|RB|LT|RT|Start|Select|"
                r"Triangle|Circle|Cross|Square|Fire)\s*[:=]\s*(.{2,80})$", re.I),
     "high"),
    # "Press A to jump" / "Push the A Button to fire"
    ("press-to",
     re.compile(r"^(?:by\s+)?(?:press(?:ing)?|hold(?:ing)?|tap(?:ping)?|push(?:ing)?)"
                r"\s+(?:the\s+)?"
                r"([A-Za-z][A-Za-z0-9 \-]{0,30}?(?:button|trigger|stick|pad)?)"
                r"\s+(?:to|will|you\s+can)\s+(.{2,80})$", re.I),
     "medium"),
    # "Button 1 - Punch"
    ("buttonN-dash",
     re.compile(r"^(button\s*\d+|fire\s*\d?)\s*[-:=]\s*(.{2,80})$", re.I),
     "high"),
    # "FIRE - Shoots"  (single-button systems)
    ("token-dash",
     re.compile(r"^(fire|jump|action|attack|select|start|pause)\s*[-:=]\s*(.{2,80})$", re.I),
     "medium"),
    # "The A Button [verb] [object]" — implicit prose
    ("the-button-verb",
     re.compile(r"^the\s+([A-Za-z][A-Za-z0-9 \-]{0,30}?(?:button|trigger|pad))"
                r"\s+(?:enables?|moves?|will|starts?|stops?|jumps?|fires?|pauses?"
                r"|resumes?|launches?|opens?|controls?|shoots?|attacks?|swaps?"
                r"|selects?|cancels?|does|makes?|gives?|switches?|toggles?)\s+(.{2,80})$",
                re.I),
     "medium"),
    # "Pushing this button [does]" + prior context — handled by
    # state machine, but match if we've already merged: "BUTTON A
    # Pushing this button starts the game" → A: Pushing this button starts
    ("X-pushing-this",
     re.compile(r"^([A-Za-z][A-Za-z0-9 \-]{0,30}?(?:button|trigger|pad))\s+"
                r"(?:pushing|pressing|holding)\s+this\s+button\s+(.{2,80})$", re.I),
     "medium"),
]


# Lines that ARE a button name and nothing else (or with leading OCR
# garbage like "* " / "- "). We coalesce these with the next 1-3
# content lines into a synthetic "button - action" string the main
# parser then sees.
HEADER_ONLY_RE = re.compile(
    r"^[\s*\-�•·e\.]*"          # leading bullets, garbage
    r"(button\s+[A-Za-z]"                  # "Button A", "BUTTON B"
    r"|[A-Za-z]\s+button"                  # "A Button"
    r"|select\s+button|start\s+button"
    r"|fire\s+button|control\s+pad"
    r"|d-?pad|joystick|gamepad"
    r"|triangle|circle|cross|square"
    r"|l1|l2|r1|r2|lb|rb|lt|rt)"
    r"\s*[*\-�•\.]*\s*$", re.I)


def _canonical_button(raw: str) -> str | list[str] | None:
    """Map raw button text from the manual to a canonical key.

    Returns:
      - str         single canonical button ("fire", "a", "dpad_up", ...)
      - list[str]   multiple canonical buttons (compound directions on
                    a DE-9 joystick — pushing "up and left" closes the
                    Up switch AND the Left switch simultaneously, so
                    one manual phrase produces two bindings sharing
                    the same action)
      - None        no canonical mapping

    Caller (_parse_line) detects the list form and emits one binding
    per element. The same action is duplicated across each direction —
    matches how a DE-9 joystick actually wires (two cardinal switches
    closed at once = diagonal input).

    Robust to prose-style input phrases from action-first patterns:
      "the joystick button while you are running"
            → "fire"
      "the joystick up and to the left or right"
            → ["dpad_up", "dpad_left", "dpad_right"]
      "yourself under it, moving the joystick up"
            → "dpad_up"
    """
    norm = raw.strip().lower()
    norm = re.sub(r"\s+", " ", norm)
    norm = re.sub(r"^(?:the\s+|your\s+|a\s+|an\s+)", "", norm)
    norm = re.sub(r"[.!,;:]+$", "", norm).strip()

    # Tier 1: exact match
    if norm in BUTTON_TOKENS:
        return BUTTON_TOKENS[norm]

    # Per-token punctuation stripping so "up," still resolves
    raw_parts = norm.split()
    parts = [p.rstrip(",.;:!?") for p in raw_parts]
    DIRECTIONS = ("up", "down", "left", "right")
    has_joystick = "joystick" in parts or "stick" in parts

    # Tier 2: COMPOUND-DIRECTION detection (must run BEFORE the prefix
    # shrink, since "joystick up and to the left" should produce both
    # dpad_up AND dpad_left, not just resolve "joystick up" via tier 3).
    #
    # Compound: "joystick up and to the left or right"
    #   → ["dpad_up", "dpad_left", "dpad_right"]
    # Reflects how a DE-9 joystick actually wires: pushing diagonally
    # closes TWO cardinal switches simultaneously, so each cardinal
    # is its own binding sharing the same action. NOT a separate
    # "diagonal" input.
    if has_joystick:
        found = []
        for token in parts:
            if token in DIRECTIONS and token not in found:
                found.append(token)
        if len(found) > 1:
            return [f"dpad_{d}" for d in found]
        # Fall through if only one direction (or none) — let tier 3
        # progressive prefix shrink handle "joystick button while running"

    # Bare direction at start (OCR dropped "joystick"). Same compound
    # logic — an OCR-mangled "up and to the left" still means both Up
    # and Left switches close simultaneously.
    if parts and parts[0] in DIRECTIONS:
        found = [parts[0]]
        for token in parts[1:]:
            if token in DIRECTIONS and token not in found:
                found.append(token)
        if len(found) > 1:
            return [f"dpad_{d}" for d in found]
        return f"dpad_{found[0]}"

    # Tier 3: progressive prefix shrink. "joystick button while running"
    # → try "joystick button while", "joystick button" → match. Used
    # for prose-style trailing modifiers.
    for end in range(min(len(parts), 4), 0, -1):
        prefix = " ".join(parts[:end])
        if prefix in BUTTON_TOKENS:
            return BUTTON_TOKENS[prefix]

    # Tier 4: single-direction in joystick context (compound check
    # above didn't fire — there's only one direction in the phrase).
    if has_joystick:
        for token in parts:
            if token in DIRECTIONS:
                return f"dpad_{token}"

    # Tier 4: strip trailing 'button' and re-try
    no_button = re.sub(r"\s+button$", "", norm).strip()
    if no_button in BUTTON_TOKENS:
        return BUTTON_TOKENS[no_button]

    # Tier 5: bare single-letter / shoulder-button fallbacks
    if re.fullmatch(r"[abcxyz]", norm):
        return norm
    if re.fullmatch(r"l[12rt]|r[12lt]", norm):
        return norm
    return None


# ============================================================
# Core extraction
# ============================================================

def _resplit_words(text: str) -> str:
    """Some PDFs place glyphs by absolute position and never emit a
    space token. The result from pypdf is "TheFIREBUTTONstartsthegame".
    This heuristic re-splits by case and digit boundaries — imperfect
    but usually enough to make the line patterns match.

    Rules:
      - lowercase → uppercase: insert space  (TheFIRE → The FIRE)
      - uppercase → uppercase+lowercase: insert space  (FIREBUTTON → FIRE BUTTON, but keep BUTTONLayout → BUTTON Layout)
      - letter → digit: insert space  (F3 stays glued — exception via
        single-letter-then-digit list)
      - digit → letter: insert space
      - keep common letter-digit shortcodes intact: F1-F12, R1, R2, L1,
        L2, X1, X2, P1, P2.
    """
    if not text or " " in text and len(text) < 30:
        return text   # short tokens that already have spaces — leave alone
    # Don't molest already-well-spaced text. If the text has plenty of
    # spaces relative to length, skip re-splitting.
    spaces = text.count(" ")
    if spaces >= len(text) * 0.10:
        return text

    # 1. lowercase → uppercase
    out = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    # 2. UPPER → Upper-then-lower (FIREBUTTON → FIRE BUTTON, but
    #    don't break "USB" or "PDF" — only when followed by lowercase
    #    AND preceded by another uppercase: FIREBu → FIRE Bu)
    out = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", out)
    # 3. letter → digit (Press5 → Press 5; but preserve F1-F12, R1, etc.)
    out = re.sub(r"([a-zA-Z])(\d)",
                 lambda m: m.group(0) if m.group(1) in "FfRrLlXxPpAaBb"
                 and len(m.group(2)) <= 2 else f"{m.group(1)} {m.group(2)}",
                 out)
    # 4. digit → letter
    out = re.sub(r"(\d)([A-Za-z])", r"\1 \2", out)
    # 5. Punctuation stuck to the next word: "...game.Press" → ". Press"
    out = re.sub(r"([.!?,:;])([A-Z])", r"\1 \2", out)
    # Collapse runs of multiple spaces
    out = re.sub(r" {2,}", " ", out).strip()
    return out


def _read_pdf_text(pdf_path: Path,
                   ocr: bool = False,
                   psm: int = 3) -> tuple[list[str], int, str]:
    """Return (lines, page_count, source). Source is one of:
      - "pdfplumber"   — extracted clean text (best path)
      - "pypdf"        — extracted text + heuristic resplit fallback
      - "ocr"          — image-only PDF, lines come from tesseract OCR
      - "empty"        — neither path produced anything

    With `ocr=False` (default; safe for end-user runtime path), we only
    do pdfplumber + pypdf. With `ocr=True` (build-time path on the dev
    box), we additionally run tesseract OCR if the text extractors come
    up dry — turning scanned bitmap manuals into usable text.

    `psm` chooses tesseract's page-segmentation mode for the OCR fallback.
    Different PSMs read different layouts well: 3 (auto) handles
    multi-column NES manuals; 6 (single block) handles dense mid-90s
    booklets; 4 (column) handles rigid two-column layouts.
    """
    # Try pdfplumber first — it preserves word boundaries that pypdf
    # drops on positionally-encoded PDFs.
    pdfplumber_lines: list[str] = []
    page_count = 0
    try:
        import pdfplumber
        with pdfplumber.open(str(pdf_path)) as pdf:
            page_count = len(pdf.pages)
            for page in pdf.pages:
                try:
                    txt = page.extract_text() or ""
                except Exception:
                    continue
                for ln in txt.splitlines():
                    ln = ln.strip()
                    if ln:
                        pdfplumber_lines.append(ln)
        if pdfplumber_lines:
            return pdfplumber_lines, page_count, "pdfplumber"
    except ImportError:
        pass   # fall through to pypdf

    pypdf_lines: list[str] = []
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
        page_count = page_count or len(reader.pages)
        for page in reader.pages:
            try:
                txt = page.extract_text() or ""
            except Exception:
                continue
            for ln in txt.splitlines():
                ln = ln.strip()
                if not ln: continue
                pypdf_lines.append(_resplit_words(ln))
        if pypdf_lines:
            return pypdf_lines, page_count, "pypdf"
    except ImportError:
        if not ocr:
            raise RuntimeError(
                "Need a PDF library. Install one:\n"
                "  pip install pdfplumber   (preferred)\n"
                "  pip install pypdf        (lighter)"
            )
    except Exception:
        pass

    # Both text extractors empty. If OCR is enabled (build-time path),
    # rasterise + tesseract.
    if ocr:
        try:
            from manual_ocr import ocr_pdf_pages, is_available
        except ImportError:
            return [], page_count, "empty"
        if not is_available():
            return [], page_count, "empty"
        try:
            ocr_lines, info = ocr_pdf_pages(pdf_path, psm=psm)
            if not page_count:
                page_count = info.get("pages_total", 0)
            return ocr_lines, page_count, "ocr"
        except RuntimeError:
            return [], page_count, "empty"

    return [], page_count, "empty"


def _find_section(lines: list[str],
                  extra_headers: list[str] | None = None,
                  max_section_lines: int = 80) -> tuple[int, int] | None:
    """Locate the controls section in the line list. Returns
    (start_idx, end_idx) inclusive, or None if no header matched.

    Two-tier detection: prefer a clean isolated header line
    ("CONTROLS" alone), but fall back to a header phrase appearing
    inside a longer line (common in OCR-ed PDFs where headers get
    glued to neighbouring content).

    `extra_headers` adds to the base SECTION_HEADERS — used by pass 3
    to surface genre-specific headings (BATTLE COMMANDS, OFFENSE,
    SPECIAL MOVES, etc.) that don't belong in the default set."""
    n = len(lines)
    headers = SECTION_HEADERS + (extra_headers or [])
    # Tier 1: header is the entire line (or close to it). This is the
    # high-confidence match and stops the search early.
    for i, ln in enumerate(lines):
        norm = re.sub(r"\s+", " ", ln.strip().lower())
        if len(norm) > 60: continue
        for hdr in headers:
            if hdr in norm and len(hdr) >= len(norm) - 8:
                return (i, _section_end(lines, i, n, max_section_lines))
    # Tier 2: header phrase appears anywhere in a line. Lower confidence;
    # only triggers if Tier 1 found nothing. We require a match on one
    # of the more specific phrases (skip generic "controls" alone), and
    # bias toward the FIRST match in the document.
    specific_headers = [h for h in headers
                        if h not in ("controls", "operation")]
    for i, ln in enumerate(lines):
        norm = re.sub(r"\s+", " ", ln.strip().lower())
        if len(norm) < 6 or len(norm) > 200: continue
        for hdr in specific_headers:
            if hdr in norm:
                return (i, _section_end(lines, i, n, max_section_lines))
    return None


def _section_end(lines: list[str], start: int, n: int,
                 max_section_lines: int = 80) -> int:
    """Walk forward from a found header until a terminator or the
    section length cap."""
    end = min(start + max_section_lines, n - 1)
    for j in range(start + 1, end + 1):
        jnorm = re.sub(r"\s+", " ", lines[j].strip().lower())
        if any(t in jnorm and len(jnorm) < 40
               for t in SECTION_TERMINATORS):
            return j - 1
    return end


# Move-sequence noise indicators — patterns that signal a fighter-game
# combo description rather than a button binding. Reject these BEFORE
# pattern matching so we don't accidentally extract "Sweep Kick: Down +
# Heavy Kick" or "Hadouken: ↓ ↘ → + Punch" as bindings. Combos aren't
# bindings: the game internally recognises input sequences, RetroBat
# only handles physical-button → emulated-button mapping.
_ARROW_CHARS = "↑↓←→↗↘↙↖"
MOVE_SEQUENCE_INDICATORS = (
    # Two unicode arrows within 30 chars of each other — combo notation
    # ("↓ ↘ → + Punch"). Single arrow is fine ("↑ Up: Move forward")
    # since some manual headers use one as a glyph.
    re.compile(rf"[{_ARROW_CHARS}].{{0,30}}[{_ARROW_CHARS}]"),
    # An arrow followed by '+' or 'and' within 20 chars — combo
    # ("↓ + Punch", "→ and HP").
    re.compile(rf"[{_ARROW_CHARS}].{{0,20}}(?:\+|\band\b)", re.I),
    # 3+ chained "+ X" tokens — combo ingredient list (HP+LK+MP).
    re.compile(r"(?:\+\s*\w+){3,}"),
    # ASCII arrow chains — OCR often turns ↓↘→ into ">>>" or "vvv"
    re.compile(r"[<>^v]{3,}"),
    # Charge moves — "Charge ← for 2 sec, → + Punch"
    re.compile(r"\bcharge\b.{0,40}\b(?:back|forward|down|up|left|right)\b", re.I),
    # Multi-char fighter token combinations — "HP+LK", "MP+MK"
    re.compile(r"\b[HLMhlm][PKpk]\s*\+\s*[HLMhlm][PKpk]\b"),
)


def _is_move_sequence_noise(line: str) -> bool:
    """True when the line is clearly a fighter-game move-sequence
    description (Hadouken, Fatality, special move tables) rather than
    a button binding. Filtered out before pattern matching to keep
    the bindings DB clean of game-internal combo data."""
    if not line: return False
    for pat in MOVE_SEQUENCE_INDICATORS:
        if pat.search(line):
            return True
    return False


def _clean_ocr_line(line: str) -> str:
    """Strip leading OCR junk and normalise whitespace. Examples:
       "* Button A �"           → "Button A"
       "e Pushing this button"  → "Pushing this button"
       "  - SELECT BUTTON  "    → "SELECT BUTTON"
    """
    # Strip leading garbage characters often produced by OCR for bullets,
    # asterisks, em-dashes, and stray single letters.
    s = re.sub(r"^[\s*\-—–•·�\.]+", "", line)
    # Drop trailing OCR bits like "*", "—" and stray punctuation
    s = re.sub(r"[\s*\-—–•·�]+$", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _coalesce_header_followed_by_action(lines: list[str]) -> list[str]:
    """Walk the line list. Whenever a line IS just a button name (e.g.
    "BUTTON A" or "Select Button"), merge it with the next 1-2 content
    lines as a synthetic "{button} - {merged action}" line. Original
    lines are still kept so the existing patterns can match them too.

    This is the workhorse for OCR'd manuals, where layout puts the
    button name on a heading line and the action on the next line(s)."""
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        cur = _clean_ocr_line(lines[i])
        out.append(lines[i])

        if cur and HEADER_ONLY_RE.match(cur):
            # Look ahead up to 3 lines for action prose. Stop at empty
            # line, another header, or after capturing two non-empty.
            captured: list[str] = []
            j = i + 1
            while j < n and j < i + 4 and len(captured) < 2:
                nxt = _clean_ocr_line(lines[j])
                if not nxt:
                    j += 1; continue
                if HEADER_ONLY_RE.match(nxt):
                    break
                # Drop "Pushing this button" / "Pressing this button"
                # boilerplate prefix — the description is what follows.
                action = re.sub(
                    r"^(?:by\s+)?(?:pushing|pressing|holding|tapping)\s+(?:the\s+)?this\s+(?:button|trigger|pad)\s+",
                    "", nxt, flags=re.I)
                # Lowercase first char if it was capitalized for a sentence
                if action and action[0].isupper():
                    # only lowercase if not a known abbreviation/proper noun
                    pass
                captured.append(action)
                j += 1
            if captured:
                merged = f"{cur} - " + " ".join(captured)
                out.append(merged)
        i += 1
    return out


def _merge_wrapped_lines(lines: list[str]) -> list[str]:
    """Join lines that look like they're continuations of the previous
    sentence. Heuristic: a line is a continuation when:
      - the previous line doesn't end with terminating punctuation (.!?)
      - the current line starts with a lowercase letter, OR a connector
        word (and/or/but/up/down/left/right/the/a/while)
      - neither line is a section header (all-caps short line)

    Returns a NEW list — original input untouched."""
    if not lines: return []
    out: list[str] = []
    SENTENCE_END = re.compile(r"[.!?:;]\s*$")
    HEADER_LIKE = re.compile(r"^[\s*\-—]*[A-Z][A-Z0-9 \-]{2,40}\s*$")
    # NB: no re.I here — `[a-z]` must mean lowercase only. With re.I,
    # uppercase headers like "KICK" / "PAUSE" would be wrongly considered
    # continuations of the previous line.
    CONTINUER  = re.compile(
        r"^(?:[a-z]|And\s|Or\s|But\s|The\s+|A\s+|While\s+|Until\s+"
        r"|Up\s|Down\s|Left\s|Right\s|To\s+\w"
        r"|and\s|or\s|but\s|the\s+|a\s+|while\s+|until\s+"
        r"|up\s|down\s|left\s|right\s|to\s+\w)")

    i = 0
    n = len(lines)
    while i < n:
        cur = lines[i].strip()
        if not cur:
            i += 1; continue

        # Try to absorb continuation lines.
        merged = cur
        j = i + 1
        merge_count = 0
        while j < n and merge_count < 2:    # cap at 2 continuation lines
            nxt = lines[j].strip()
            if not nxt: break
            if SENTENCE_END.search(merged): break
            if HEADER_LIKE.match(nxt): break
            if not CONTINUER.match(nxt): break
            merged = merged + " " + nxt
            merge_count += 1
            j += 1
        out.append(merged)
        i = j if merge_count > 0 else i + 1
    return out


def _parse_line(line: str,
                extra_patterns: list[tuple] | None = None,
                looser: bool = False,
                confidence_floor: str = "medium") -> list[dict]:
    """Try each line pattern against the cleaned line. Return a list of
    binding dicts (typically 0 or 1; CAN be 2-4 for compound-direction
    cases like "the joystick up and to the left or right" which closes
    multiple DE-9 cardinal switches simultaneously).

    `extra_patterns` are appended to LINE_PATTERNS (a pass can add new
    shapes without editing the global list).

    `looser=True` relaxes the noise-rejection thresholds — more
    bindings get through, more noise too. Pass 4 uses this and tags
    everything as "low" confidence so the GUI can colour them
    differently.

    `confidence_floor` caps the confidence: passes 3+ shouldn't claim
    "high" even if the regex would, since the broader heuristics are
    by definition lower-precision than pass 1's tight match."""
    cleaned = _clean_ocr_line(line)
    if not cleaned: return []

    # Reject fighter-game move-sequence lines before pattern matching.
    # "Hadouken: ↓ ↘ → + Punch" superficially looks like a binding
    # ("Hadouken" left of colon, action right of colon) but it's a
    # game-internal combo description we don't want in the DB.
    if _is_move_sequence_noise(cleaned):
        return []

    patterns = LINE_PATTERNS + list(extra_patterns or [])

    # Threshold parameters: stricter by default, relaxed under looser=True
    if looser:
        min_action_len, letter_ratio_floor, upper_cap, button_token_cap = 3, 0.40, 0.60, 3
    else:
        min_action_len, letter_ratio_floor, upper_cap, button_token_cap = 4, 0.55, 0.50, 2

    rank = {"high": 2, "medium": 1, "low": 0}

    for entry in patterns:
        # Support both 3-tuple (legacy) and 4-tuple (action-first prose).
        # 4-tuple's 4th element is `swap=True` — group 1 is the ACTION
        # text, group 2 is the BUTTON / input phrase. The Bruce Lee
        # manual's "KICK by pressing the joystick button" is the
        # canonical example: action ("KICK") comes first in the source.
        if len(entry) == 4:
            pname, pat, conf, swap = entry
        else:
            pname, pat, conf = entry
            swap = False
        m = pat.match(cleaned)
        if not m: continue
        if swap:
            btn_raw, action = m.group(2), m.group(1)
            # Action is typically all-caps in this prose shape ("KICK")
            # — title-case it so the all-caps validator below doesn't
            # reject and so the GUI displays it pleasantly.
            if action.isupper():
                action = action.title()
        else:
            btn_raw, action = m.group(1), m.group(2)
        btn = _canonical_button(btn_raw)
        if not btn: continue
        action = re.sub(r"\s+", " ", action).strip().rstrip(".,;")
        action = re.sub(r"[\s*\-—–•·�]+$", "", action).strip()
        if not action or len(action) > 80 or len(action) < min_action_len:
            continue
        letter_ratio = sum(1 for c in action if c.isalpha()) / len(action)
        if letter_ratio < letter_ratio_floor: continue
        if not re.search(r"\b[a-z]{3,}\b", action.lower()):
            continue
        upper_count = sum(1 for c in action if c.isupper())
        if upper_count > len(action) * upper_cap: continue
        action_lower = action.lower()
        button_token_count = sum(1 for tok in
            ("button", "trigger", "buttor", "buttn", "button.")
            if tok in action_lower)
        if button_token_count >= button_token_cap: continue
        if re.match(r"^\d+[\)\.\s]+[A-Z]", action): continue

        # Cap confidence at the floor (e.g. pass 3 floors at "low")
        if rank.get(conf, 0) > rank.get(confidence_floor, 1):
            conf = confidence_floor

        # Compound-direction case: _canonical_button returned a list.
        # Emit one binding per cardinal direction, all sharing the
        # same action ("LEAP" with up+left+right → 3 bindings).
        # This matches DE-9 joystick electrical reality — diagonals
        # are TWO simultaneous cardinal switch closures, not a
        # separate "diagonal" input.
        if isinstance(btn, list):
            return [
                {"button":     b,
                 "action":     action,
                 "confidence": conf,
                 "raw":        line,
                 "matched_by": pname}
                for b in btn
            ]
        return [{
            "button":     btn,
            "action":     action,
            "confidence": conf,
            "raw":        line,
            "matched_by": pname,
        }]
    return []


DEFAULT_CONFIG = ParserConfig(name="pass1_default", psm=3,
                              looser_action_filter=False,
                              confidence_floor="high")


def extract_with_config(pdf_path: Path, config: ParserConfig,
                        ocr: bool = False) -> dict:
    """Run one extraction pass with the given parser config. Returns
    the same result schema as extract_bindings_from_pdf, plus a
    `pass_name` field for telemetry."""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return {"pdf_path": str(pdf_path), "error": "PDF not found",
                "section_found": False, "bindings": [],
                "text_source": "empty", "pass_name": config.name}

    lines, page_count, source = _read_pdf_text(pdf_path, ocr=ocr,
                                                psm=config.psm)
    if not lines:
        return {"pdf_path":     str(pdf_path),
                "pages_scanned": page_count,
                "text_source":   source,
                "pass_name":     config.name,
                "error":         ("scanned/image-only manual — needs OCR"
                                  if not ocr else
                                  "OCR ran but produced no usable text"),
                "section_found": False, "bindings": []}

    # Optional pre-pass: merge wrapped sentences. Many manual control
    # descriptions span 2-3 OCR lines, breaking line-by-line parsers.
    if config.merge_wrapped_lines:
        lines = _merge_wrapped_lines(lines)

    span = _find_section(lines,
                         extra_headers=config.extra_section_headers,
                         max_section_lines=config.max_section_lines)
    if span is None:
        if not config.accept_global_scan:
            return {
                "pdf_path":      str(pdf_path),
                "pages_scanned": page_count,
                "text_source":   source,
                "pass_name":     config.name,
                "section_found": False,
                "bindings":      [],
                "note":          "no section header found "
                                 "(global-scan disabled for this pass)",
            }
        scan_lines = _coalesce_header_followed_by_action(lines[:300])
        bindings = []
        for ln in scan_lines:
            bindings.extend(_parse_line(ln,
                            extra_patterns=config.extra_line_patterns,
                            looser=config.looser_action_filter,
                            confidence_floor=config.confidence_floor))
        return {
            "pdf_path":      str(pdf_path),
            "pages_scanned": page_count,
            "text_source":   source,
            "pass_name":     config.name,
            "section_found": False,
            "section_text":  None,
            "section_lines": None,
            "bindings":      _dedupe(bindings),
            "note":          "no explicit controls section header found; "
                             "scanned first 300 lines globally",
        }

    start, end = span
    section_lines = _coalesce_header_followed_by_action(lines[start:end + 1])
    bindings = []
    for ln in section_lines:
        bindings.extend(_parse_line(ln,
                        extra_patterns=config.extra_line_patterns,
                        looser=config.looser_action_filter,
                        confidence_floor=config.confidence_floor))

    return {
        "pdf_path":      str(pdf_path),
        "pages_scanned": page_count,
        "text_source":   source,
        "pass_name":     config.name,
        "section_found": True,
        "section_text":  "\n".join(section_lines),
        "section_lines": [start, end],
        "bindings":      _dedupe(bindings),
    }


def extract_bindings_from_pdf(pdf_path: Path, ocr: bool = False) -> dict:
    """Backwards-compatible legacy entry point — runs the default pass
    config. New callers should use extract_with_config or the multi-pass
    orchestrator in build_bindings_db_passes.
    """
    return extract_with_config(pdf_path, DEFAULT_CONFIG, ocr=ocr)


def _dedupe(bindings: list[dict]) -> list[dict]:
    """Drop duplicate (button, action) pairs, keeping the highest-confidence
    version. Preserve original order otherwise."""
    seen: dict[tuple[str, str], dict] = {}
    rank = {"high": 2, "medium": 1, "low": 0}
    for b in bindings:
        key = (b["button"], b["action"].lower())
        cur = seen.get(key)
        if cur is None or rank.get(b["confidence"], 0) > rank.get(cur["confidence"], 0):
            seen[key] = b
    # Order by appearance in the original list
    out = []
    seen_keys = set()
    for b in bindings:
        key = (b["button"], b["action"].lower())
        if key in seen_keys: continue
        seen_keys.add(key)
        out.append(seen[key])
    return out


# ============================================================
# CLI
# ============================================================

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", nargs="?", help="Path to a PDF to analyse.")
    ap.add_argument("--system", help="RetroBat system id (with --rom).")
    ap.add_argument("--rom", help="ROM name (with --system); "
                    "resolves via manual_local.")
    ap.add_argument("--show-section", action="store_true",
                    help="Also print the captured section text.")
    ap.add_argument("--ocr", action="store_true",
                    help="Enable OCR fallback for image-only PDFs "
                         "(requires tesseract — slow). Build-time path.")
    args = ap.parse_args()

    if args.system and args.rom:
        from manual_local import (
            ensure_index, lookup_local_manual, extract_local_manual)
        idx = ensure_index()
        hit = lookup_local_manual(args.system, args.rom, index=idx)
        if not hit:
            print(f"[miss] no manual found for {args.system}/{args.rom}",
                  file=sys.stderr); sys.exit(2)
        pdf_path = extract_local_manual(hit)
        if pdf_path is None:
            print("[error] could not extract PDF from archive",
                  file=sys.stderr); sys.exit(1)
    elif args.pdf:
        pdf_path = Path(args.pdf)
    else:
        ap.print_help(); sys.exit(1)

    result = extract_bindings_from_pdf(pdf_path, ocr=args.ocr)
    if "error" in result:
        print(f"[error] {result['error']}", file=sys.stderr)
        sys.exit(1)

    print(f"PDF:           {result['pdf_path']}")
    print(f"Pages scanned: {result['pages_scanned']}")
    print(f"Text source:   {result.get('text_source', '?')}")
    print(f"Section found: {result['section_found']}")
    if result.get("note"):
        print(f"Note:          {result['note']}")
    print(f"Bindings:      {len(result['bindings'])}")
    print()
    for b in result["bindings"]:
        print(f"  {b['button']:>10}  →  {b['action']:<30}  "
              f"[{b['confidence']:>6}]  ({b['matched_by']})")

    if args.show_section and result.get("section_text"):
        print("\n" + "=" * 60 + "\nSECTION TEXT:\n" + "=" * 60)
        print(result["section_text"])


if __name__ == "__main__":
    main()
