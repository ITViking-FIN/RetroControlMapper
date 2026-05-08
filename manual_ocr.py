"""
OCR fallback for image-only PDFs (Stage 2.5 of the manual pipeline).

Most retro game manuals (especially NES, SNES, Genesis, PSX-era) ship
as scanned bitmap PDFs — pypdf and pdfplumber both return empty text.
This module rasterises each page via pypdfium2 and runs tesseract OCR
to recover text the heuristic line parser can chew on.

## Why this exists at build-time, not runtime

The bindings DB is **extracted ONCE on the dev box** (where tesseract is
installed and the Manual_Package archive lives) and shipped to end
users as a small JSON artifact in the installer. End users never run
OCR — they get the pre-extracted bindings for free.

The user-contribution flow (drop-PDF-here in the GUI for a game we
don't yet cover) intentionally uses the pypdf-only path with no OCR,
so end users don't need tesseract installed.

## Pipeline

```
PDF  ->  pypdfium2 render @ 300 DPI  ->  PIL Image  ->  tesseract eng  ->  text
                                                                            |
                                                                            v
                                                                  manual_extract line parser
```

## Tesseract install

This module shells out to `tesseract.exe`. Install the binary first:

    winget install --id UB-Mannheim.TesseractOCR

Default install path on Windows is `C:\\Program Files\\Tesseract-OCR\\`.
Set `RBCF_TESSERACT_EXE` env var if your install lives elsewhere.

## Public API

    from manual_ocr import is_available, ocr_pdf_pages
    if is_available():
        text = ocr_pdf_pages(Path("scan.pdf"), max_pages=20)

`text` is a list of lines (one PDF flattened across pages, like
manual_extract._read_pdf_text returns), ready to feed back into the
line parser.

## CLI

    py manual_ocr.py status                          # check tesseract availability
    py manual_ocr.py ocr path/to/scan.pdf            # OCR + dump text
    py manual_ocr.py ocr path/to/scan.pdf --pages 5  # cap pages (faster)
"""
from __future__ import annotations

import argparse
import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"

TESSERACT_ENV = "RBCF_TESSERACT_EXE"
DEFAULT_TESSERACT = Path(r"C:/Program Files/Tesseract-OCR/tesseract.exe")

# Render DPI for OCR. 300 DPI is the tesseract sweet spot — higher
# rarely helps and dramatically slows things; lower hurts accuracy on
# small body text in old game manuals.
RENDER_DPI = 300

# Soft cap on pages OCR'd per PDF. Bigger numbers = better coverage,
# slower. 30 pages covers any retro-game manual; longer manuals are
# vanishingly rare and the controls section is typically near the front.
DEFAULT_MAX_PAGES = 30


# ============================================================
# Tesseract location + availability
# ============================================================

def find_tesseract() -> Path | None:
    """Locate tesseract.exe. Order: env var, default install path,
    PATH lookup."""
    env_val = os.environ.get(TESSERACT_ENV)
    if env_val:
        p = Path(env_val).expanduser()
        if p.exists(): return p
    if DEFAULT_TESSERACT.exists():
        return DEFAULT_TESSERACT
    which = shutil.which("tesseract")
    if which:
        return Path(which)
    return None


def is_available() -> bool:
    return find_tesseract() is not None


def tesseract_version() -> str | None:
    exe = find_tesseract()
    if exe is None: return None
    try:
        r = subprocess.run([str(exe), "--version"],
                           capture_output=True, text=True, timeout=10)
        first = r.stderr.splitlines()[0] if r.stderr else r.stdout.splitlines()[0]
        return first.strip()
    except (subprocess.TimeoutExpired, OSError, IndexError):
        return None


# ============================================================
# Per-page OCR
# ============================================================

def _render_page(pdf, page_index: int, dpi: int = RENDER_DPI):
    """Return a PIL.Image for one page of a pypdfium2-opened PDF.
    Caller owns closing the page."""
    page = pdf[page_index]
    try:
        # scale = dpi / 72 (PDF native is 72 DPI)
        bitmap = page.render(scale=dpi / 72)
        return bitmap.to_pil()
    finally:
        page.close()


def _ocr_image(image, tess_exe: Path, lang: str = "eng",
               psm: int = 3, timeout: int = 120) -> str:
    """Pipe a PIL.Image through tesseract via subprocess and return
    the recognised text. PSM=3 is "Fully automatic page segmentation
    with OSD" — handles the multi-column layouts that 80s/90s game
    manuals love (where PSM=6 linearises columns and ruins the
    button-name-followed-by-description structure)."""
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    cmd = [str(tess_exe),
           "-l", lang,
           "--psm", str(psm),
           "-",          # stdin
           "-"]          # stdout
    try:
        r = subprocess.run(cmd, input=png_bytes,
                           capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return ""
    if r.returncode != 0:
        return ""
    try:
        return r.stdout.decode("utf-8", errors="replace")
    except Exception:
        return ""


def ocr_pdf_pages(pdf_path: Path,
                  max_pages: int = DEFAULT_MAX_PAGES,
                  dpi: int = RENDER_DPI,
                  lang: str = "eng",
                  early_stop: bool = True,
                  verbose: bool = False) -> tuple[list[str], dict]:
    """OCR a PDF page-by-page, returning (lines, info_dict).

    `lines` is a flat list across pages, ready for the heuristic line
    parser in manual_extract.

    `info_dict` reports {pages_total, pages_ocrd, characters, time_s,
    early_stopped} for telemetry.

    early_stop=True: once we've found a controls-section header on a
    page, stop OCR'ing further pages — saves a lot of time on long
    multi-language manuals where the controls live in the first 5-10
    pages and the rest is just other-language repeats / story.
    """
    import time
    info = {
        "pages_total":   0,
        "pages_ocrd":    0,
        "characters":    0,
        "time_s":        0.0,
        "early_stopped": False,
    }
    tess_exe = find_tesseract()
    if tess_exe is None:
        raise RuntimeError(
            "tesseract.exe not found. Install with:\n"
            "  winget install --id UB-Mannheim.TesseractOCR\n"
            f"or set {TESSERACT_ENV} env var.")

    try:
        import pypdfium2 as pdfium
    except ImportError:
        raise RuntimeError("pypdfium2 not installed. pip install pypdfium2")

    t0 = time.time()
    lines: list[str] = []
    found_section_marker = False

    pdf = None
    try:
        pdf = pdfium.PdfDocument(str(pdf_path))
        info["pages_total"] = len(pdf)
        cap = min(len(pdf), max_pages)
        for i in range(cap):
            try:
                img = _render_page(pdf, i, dpi=dpi)
            except Exception:
                continue
            text = _ocr_image(img, tess_exe, lang=lang)
            info["pages_ocrd"] += 1
            info["characters"] += len(text)

            page_lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            lines.extend(page_lines)
            if verbose:
                print(f"  page {i + 1}/{cap}: {len(text)} chars, "
                      f"{len(page_lines)} non-empty lines")

            # Early-stop check: have we seen a controls header AND
            # already collected a few pages of content past it? The
            # heuristic is intentionally lenient — section finder will
            # do the precise work.
            if early_stop and not found_section_marker:
                joined = "\n".join(page_lines).lower()
                if any(h in joined for h in ("controls", "how to play",
                                             "button", "joystick",
                                             "gamepad", "control pad")):
                    found_section_marker = True
                    early_cap = min(cap, i + 4)   # +3 more pages of context
                    if i + 1 >= early_cap:
                        info["early_stopped"] = True
                        break
                    cap = early_cap   # downsize the loop
    finally:
        if pdf is not None:
            try: pdf.close()
            except Exception: pass

    info["time_s"] = round(time.time() - t0, 2)
    return lines, info


# ============================================================
# CLI
# ============================================================

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=False)
    sub.add_parser("status", help="Check tesseract availability + version.")
    O = sub.add_parser("ocr", help="OCR a PDF and dump the recognised text.")
    O.add_argument("pdf")
    O.add_argument("--pages", type=int, default=DEFAULT_MAX_PAGES,
                   help=f"max pages to OCR (default {DEFAULT_MAX_PAGES})")
    O.add_argument("--dpi", type=int, default=RENDER_DPI,
                   help=f"render DPI (default {RENDER_DPI})")
    O.add_argument("--no-early-stop", action="store_true",
                   help="OCR all pages even after a controls header is found")
    O.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if args.cmd is None:
        ap.print_help(); return

    if args.cmd == "status":
        exe = find_tesseract()
        print(f"tesseract.exe:   {exe or '(not found)'}")
        if exe:
            print(f"  version:       {tesseract_version() or '(unknown)'}")
            print(f"  exists:        {exe.exists()}")
        print(f"  env override:  {TESSERACT_ENV}={os.environ.get(TESSERACT_ENV, '(unset)')}")
        try:
            import pypdfium2 as pdfium
            print(f"  pypdfium2:     installed ({pdfium.__name__})")
        except ImportError:
            print(f"  pypdfium2:     MISSING — pip install pypdfium2")
        sys.exit(0 if exe else 1)
        return

    if args.cmd == "ocr":
        try:
            lines, info = ocr_pdf_pages(
                Path(args.pdf),
                max_pages=args.pages,
                dpi=args.dpi,
                early_stop=not args.no_early_stop,
                verbose=args.verbose)
        except RuntimeError as e:
            print(f"[error] {e}", file=sys.stderr); sys.exit(1)
        print(f"--- info ---")
        for k, v in info.items():
            print(f"  {k}: {v}")
        print(f"--- text ({len(lines)} lines) ---")
        for ln in lines:
            print(ln)


if __name__ == "__main__":
    main()
