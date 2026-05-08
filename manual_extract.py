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
from pathlib import Path

ROOT = Path(__file__).resolve().parent

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


def _canonical_button(raw: str) -> str | None:
    """Map raw button text from the manual to a canonical key."""
    norm = raw.strip().lower()
    norm = re.sub(r"\s+", " ", norm)
    if norm in BUTTON_TOKENS:
        return BUTTON_TOKENS[norm]
    # Strip trailing 'button' and try again
    no_button = re.sub(r"\s+button$", "", norm).strip()
    if no_button in BUTTON_TOKENS:
        return BUTTON_TOKENS[no_button]
    # Direct single-letter A/B/C/X/Y/Z fallback
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
                   ocr: bool = False) -> tuple[list[str], int, str]:
    """Return (lines, page_count, source). Source is one of:
      - "pdfplumber"   — extracted clean text (best path)
      - "pypdf"        — extracted text + heuristic resplit fallback
      - "ocr"          — image-only PDF, lines come from tesseract OCR
      - "empty"        — neither path produced anything

    With `ocr=False` (default; safe for end-user runtime path), we only
    do pdfplumber + pypdf. With `ocr=True` (build-time path on the dev
    box), we additionally run tesseract OCR if the text extractors come
    up dry — turning scanned bitmap manuals into usable text.
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
            ocr_lines, info = ocr_pdf_pages(pdf_path)
            if not page_count:
                page_count = info.get("pages_total", 0)
            return ocr_lines, page_count, "ocr"
        except RuntimeError:
            return [], page_count, "empty"

    return [], page_count, "empty"


def _find_section(lines: list[str]) -> tuple[int, int] | None:
    """Locate the controls section in the line list. Returns
    (start_idx, end_idx) inclusive, or None if no header matched.

    Two-tier detection: prefer a clean isolated header line
    ("CONTROLS" alone), but fall back to a header phrase appearing
    inside a longer line (common in OCR-ed PDFs where headers get
    glued to neighbouring content)."""
    n = len(lines)
    # Tier 1: header is the entire line (or close to it). This is the
    # high-confidence match and stops the search early.
    for i, ln in enumerate(lines):
        norm = re.sub(r"\s+", " ", ln.strip().lower())
        if len(norm) > 60: continue
        for hdr in SECTION_HEADERS:
            if hdr in norm and len(hdr) >= len(norm) - 8:
                return (i, _section_end(lines, i, n))
    # Tier 2: header phrase appears anywhere in a line. Lower confidence;
    # only triggers if Tier 1 found nothing. We require a match on one
    # of the more specific phrases (skip generic "controls" alone), and
    # bias toward the FIRST match in the document.
    SPECIFIC_HEADERS = [h for h in SECTION_HEADERS
                        if h not in ("controls", "operation")]
    for i, ln in enumerate(lines):
        norm = re.sub(r"\s+", " ", ln.strip().lower())
        if len(norm) < 6 or len(norm) > 200: continue
        for hdr in SPECIFIC_HEADERS:
            if hdr in norm:
                return (i, _section_end(lines, i, n))
    return None


def _section_end(lines: list[str], start: int, n: int) -> int:
    """Walk forward from a found header until a terminator or the
    section length cap."""
    end = min(start + MAX_SECTION_LINES, n - 1)
    for j in range(start + 1, end + 1):
        jnorm = re.sub(r"\s+", " ", lines[j].strip().lower())
        if any(t in jnorm and len(jnorm) < 40
               for t in SECTION_TERMINATORS):
            return j - 1
    return end


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


def _parse_line(line: str) -> dict | None:
    """Try each line pattern against the cleaned line. Return a binding
    dict or None. Pre-cleans OCR garbage prefixes/suffixes."""
    cleaned = _clean_ocr_line(line)
    if not cleaned: return None
    for pname, pat, conf in LINE_PATTERNS:
        m = pat.match(cleaned)
        if not m: continue
        btn_raw, action = m.group(1), m.group(2)
        btn = _canonical_button(btn_raw)
        if not btn: continue
        action = re.sub(r"\s+", " ", action).strip().rstrip(".,;")
        # Strip trailing OCR noise like asterisks
        action = re.sub(r"[\s*\-—–•·�]+$", "", action).strip()
        if not action or len(action) > 80 or len(action) < 4: continue
        # Reject pure-noise actions (mostly non-letter chars from OCR)
        letter_ratio = sum(1 for c in action if c.isalpha()) / len(action)
        if letter_ratio < 0.55: continue
        # Require at least one common English-y word of 3+ lowercase
        # letters — this cheaply rules out OCR-garbage actions like
        # "EEE +i a" or "i� ee Sl".
        if not re.search(r"\b[a-z]{3,}\b", action.lower()):
            continue
        # Reject if the action is mostly UPPERCASE — that's almost
        # always OCR misreading bullet glyphs as letters or section
        # headers leaking through.
        upper_count = sum(1 for c in action if c.isupper())
        if upper_count > len(action) * 0.5: continue
        # Reject when the "action" itself is a button-name fragment —
        # cross-contamination from columnar OCR where two adjacent
        # button blocks merge. Examples we DON'T want to keep:
        #   start -> "Press B button to..." → maps to B not start
        #   dpad -> "START buttor"          → noise
        action_lower = action.lower()
        button_token_count = sum(1 for tok in
            ("button", "trigger", "buttor", "buttn", "button.")
            if tok in action_lower)
        if button_token_count >= 2: continue
        # Reject if the action begins with a numbered list marker —
        # almost always a table of contents bleeding in.
        if re.match(r"^\d+[\)\.\s]+[A-Z]", action): continue
        return {
            "button":     btn,
            "action":     action,
            "confidence": conf,
            "raw":        line,
            "matched_by": pname,
        }
    return None


def extract_bindings_from_pdf(pdf_path: Path, ocr: bool = False) -> dict:
    """Top-level entry point.

    `ocr=True` enables the OCR fallback for image-only PDFs. Use this
    on the dev box where tesseract is installed and you're building
    the shippable bindings DB. End-user runtime path leaves it False.

    Returns:
    {
      pdf_path:        str,
      pages_scanned:   int,
      text_source:     "pdfplumber" | "pypdf" | "ocr" | "empty",
      section_found:   bool,
      section_text:    str | None,
      section_lines:   [int, int] | None,
      bindings:        [{button, action, confidence, raw, matched_by}, ...],
      note:            str (optional; explains degraded extraction)
    }"""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return {"pdf_path": str(pdf_path), "error": "PDF not found",
                "section_found": False, "bindings": [],
                "text_source": "empty"}

    lines, page_count, source = _read_pdf_text(pdf_path, ocr=ocr)
    if not lines:
        return {"pdf_path":     str(pdf_path),
                "pages_scanned": page_count,
                "text_source":   source,
                "error":         ("scanned/image-only manual — needs OCR"
                                  if not ocr else
                                  "OCR ran but produced no usable text"),
                "section_found": False, "bindings": []}

    span = _find_section(lines)
    if span is None:
        # Fallback: scan ALL lines (capped). Many old manuals don't
        # have an explicit "CONTROLS" header — controls are sprinkled
        # through the gameplay description. Apply the header-coalescer
        # so multi-line "BUTTON A\nstarts game" gets seen as one binding.
        scan_lines = _coalesce_header_followed_by_action(lines[:300])
        bindings = []
        for ln in scan_lines:
            b = _parse_line(ln)
            if b: bindings.append(b)
        return {
            "pdf_path":      str(pdf_path),
            "pages_scanned": page_count,
            "text_source":   source,
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
        b = _parse_line(ln)
        if b: bindings.append(b)

    return {
        "pdf_path":      str(pdf_path),
        "pages_scanned": page_count,
        "text_source":   source,
        "section_found": True,
        "section_text":  "\n".join(section_lines),
        "section_lines": [start, end],
        "bindings":      _dedupe(bindings),
    }


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
