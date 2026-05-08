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
    # "Press A to jump"
    ("press-to",
     re.compile(r"^(?:press|hold|tap)\s+(?:the\s+)?"
                r"([A-Za-z][A-Za-z0-9 \-]{0,30}?(?:button|trigger|stick|pad)?)"
                r"\s+to\s+(.{2,80})$", re.I),
     "medium"),
    # "Button 1 - Punch"
    ("buttonN-dash",
     re.compile(r"^(button\s*\d+|fire\s*\d?)\s*[-:=]\s*(.{2,80})$", re.I),
     "high"),
    # "FIRE - Shoots"  (single-button systems)
    ("token-dash",
     re.compile(r"^(fire|jump|action|attack|select|start|pause)\s*[-:=]\s*(.{2,80})$", re.I),
     "medium"),
]


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


def _read_pdf_text(pdf_path: Path) -> tuple[list[str], int]:
    """Return (lines, page_count). Tries pdfplumber first (handles
    glyph-positioned PDFs that omit space tokens, common in 1980s-90s
    manuals). Falls back to pypdf + heuristic word resplit if pdfplumber
    isn't installed.

    Pages with no text (typically scanned bitmaps that the user would
    need OCR to read) contribute nothing."""
    # Try pdfplumber first — it preserves word boundaries that pypdf
    # drops on positionally-encoded PDFs.
    try:
        import pdfplumber
        with pdfplumber.open(str(pdf_path)) as pdf:
            page_count = len(pdf.pages)
            lines: list[str] = []
            for page in pdf.pages:
                try:
                    txt = page.extract_text() or ""
                except Exception:
                    continue
                for ln in txt.splitlines():
                    ln = ln.strip()
                    if ln:
                        lines.append(ln)
        return lines, page_count
    except ImportError:
        pass   # fall through to pypdf

    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError(
            "Need a PDF library for Stage 2 extraction. Install one:\n"
            "  pip install pdfplumber   (preferred — better word boundaries)\n"
            "  pip install pypdf        (lighter; needs the resplit heuristic)"
        )
    try:
        reader = PdfReader(str(pdf_path))
    except Exception as e:
        raise RuntimeError(f"Could not open PDF {pdf_path}: {e}")

    lines: list[str] = []
    page_count = len(reader.pages)
    for page in reader.pages:
        try:
            txt = page.extract_text() or ""
        except Exception:
            continue
        for ln in txt.splitlines():
            ln = ln.strip()
            if not ln: continue
            lines.append(_resplit_words(ln))
    return lines, page_count


def _find_section(lines: list[str]) -> tuple[int, int] | None:
    """Locate the controls section in the line list. Returns
    (start_idx, end_idx) inclusive, or None if no header matched."""
    n = len(lines)
    for i, ln in enumerate(lines):
        norm = re.sub(r"\s+", " ", ln.strip().lower())
        # Heuristic: header lines are short (< 60 chars) and don't end
        # with a sentence-period, and the header phrase is the bulk of
        # the line — not buried in a long sentence.
        if len(norm) > 60: continue
        for hdr in SECTION_HEADERS:
            if hdr in norm and len(hdr) >= len(norm) - 8:
                # Found a header. Walk forward until terminator or limit.
                end = min(i + MAX_SECTION_LINES, n - 1)
                for j in range(i + 1, end + 1):
                    jnorm = re.sub(r"\s+", " ", lines[j].strip().lower())
                    if any(t in jnorm and len(jnorm) < 40
                           for t in SECTION_TERMINATORS):
                        end = j - 1; break
                return (i, end)
    return None


def _parse_line(line: str) -> dict | None:
    """Try each line pattern against the line. Return a binding dict or None."""
    for pname, pat, conf in LINE_PATTERNS:
        m = pat.match(line)
        if not m: continue
        btn_raw, action = m.group(1), m.group(2)
        btn = _canonical_button(btn_raw)
        if not btn: continue
        action = re.sub(r"\s+", " ", action).strip().rstrip(".,;")
        if not action or len(action) > 80: continue
        return {
            "button":     btn,
            "action":     action,
            "confidence": conf,
            "raw":        line,
            "matched_by": pname,
        }
    return None


def extract_bindings_from_pdf(pdf_path: Path) -> dict:
    """Top-level entry point. Returns:
    {
      pdf_path:        str,
      pages_scanned:   int,
      section_found:   bool,
      section_text:    str | None,
      section_lines:   [int, int] | None,    # start, end indices in raw line list
      bindings:        [{button, action, confidence, raw, matched_by}, ...],
    }"""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return {"pdf_path": str(pdf_path), "error": "PDF not found",
                "section_found": False, "bindings": []}

    lines, page_count = _read_pdf_text(pdf_path)
    if not lines:
        return {"pdf_path": str(pdf_path), "pages_scanned": page_count,
                "error": "PDF yielded no extractable text "
                         "(scanned/image-only manual?)",
                "section_found": False, "bindings": []}

    span = _find_section(lines)
    if span is None:
        # Fallback: scan ALL lines, but cap output. Many small old
        # manuals don't have an explicit "CONTROLS" header — controls
        # are sprinkled through the gameplay description.
        bindings = []
        for ln in lines[:200]:
            b = _parse_line(ln)
            if b: bindings.append(b)
        return {
            "pdf_path":      str(pdf_path),
            "pages_scanned": page_count,
            "section_found": False,
            "section_text":  None,
            "section_lines": None,
            "bindings":      _dedupe(bindings),
            "note":          "no explicit controls section header found; "
                             "scanned first 200 lines globally",
        }

    start, end = span
    section_lines = lines[start:end + 1]
    bindings = []
    for ln in section_lines:
        b = _parse_line(ln)
        if b: bindings.append(b)

    return {
        "pdf_path":      str(pdf_path),
        "pages_scanned": page_count,
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

    result = extract_bindings_from_pdf(pdf_path)
    if "error" in result:
        print(f"[error] {result['error']}", file=sys.stderr)
        sys.exit(1)

    print(f"PDF:           {result['pdf_path']}")
    print(f"Pages scanned: {result['pages_scanned']}")
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
