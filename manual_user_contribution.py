"""
End-user manual contribution — drop-PDF flow for unknown games.

When a user opens a profile for a game we don't have bindings for,
the GUI offers: "Got the manual? Drop the PDF here and we'll extract
suggestions." This module is the data-layer side of that flow.

## Why this is OCR-free

The build-time bindings DB (`build_bindings_db.py`) runs OCR on the
dev box where tesseract is installed. End users running this
contribution flow do NOT have tesseract — they get the pre-built DB
free instead.

So this module's `extract_user_pdf` calls `extract_bindings_from_pdf`
with `ocr=False`. If the user's PDF is image-only (a scan), the
extractor returns an honest "needs OCR" error and the GUI surfaces a
"This appears to be a scanned manual; we can't auto-extract from it
without server-side OCR" message.

For native-text PDFs (a lot of modern manuals, web-archive re-typesets,
homebrew docs, etc.), the same heuristic engine produces useful
suggestions.

## Optional submission

Once the user confirms their bindings, the GUI can offer "Submit to
the community DB" — a future hook (probably a GitHub PR via the
existing pull-community / submit-controller plumbing). Stubbed here
so the flow has a clear target.

## Public API

    from manual_user_contribution import (
        extract_user_pdf, save_and_optionally_submit,
    )

    result = extract_user_pdf(Path("user_provided.pdf"),
                              system_id="snes",
                              rom_name="Some Obscure Game")
    if result["bindings"]:
        # GUI shows them, user edits/confirms
        save_and_optionally_submit(result, submit=False)
"""
from __future__ import annotations

from pathlib import Path

from bindings_lookup import save_user_bindings


def extract_user_pdf(pdf_path: Path,
                     system_id: str,
                     rom_name: str) -> dict:
    """Run the end-user-safe extraction (no OCR) on a user-supplied PDF.

    Returns a dict shaped like bindings_lookup's lookup() result, so
    the GUI can use the same display code. Includes diagnostic info
    when extraction degrades.

      {
        source:        "user_pdf",
        system_id:     ...,
        rom_name:      ...,
        title:         (PDF stem),
        bindings:      [...],
        extra: {
          pdf_path:        ...,
          section_found:   bool,
          text_source:     "pdfplumber" | "pypdf" | "empty",
          pages_scanned:   int,
          warning:         str | None,
        }
      }
    """
    from manual_extract import extract_bindings_from_pdf

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return {
            "source":    "user_pdf",
            "system_id": system_id,
            "rom_name":  rom_name,
            "title":     rom_name,
            "bindings":  [],
            "extra":     {"error": "PDF file not found",
                          "pdf_path": str(pdf_path)},
        }

    # OCR explicitly disabled — end-user environment doesn't have
    # tesseract installed.
    result = extract_bindings_from_pdf(pdf_path, ocr=False)

    warning = None
    if "error" in result:
        # Most common case: scanned bitmap manual with no extractable text.
        # Surface a friendly explanation the GUI can show.
        warning = (
            "This PDF appears to contain only scanned images, not selectable "
            "text. Auto-extraction can't read scanned manuals on your machine "
            "(it would require installing OCR software). The PDF may still be "
            "useful as reference — please map controls manually."
        )

    return {
        "source":    "user_pdf",
        "system_id": system_id,
        "rom_name":  rom_name,
        "title":     rom_name,
        "bindings":  result.get("bindings") or [],
        "extra": {
            "pdf_path":      str(pdf_path),
            "section_found": result.get("section_found"),
            "text_source":   result.get("text_source", "empty"),
            "pages_scanned": result.get("pages_scanned", 0),
            "warning":       warning,
            "error":         result.get("error"),
            "note":          result.get("note"),
        },
    }


def save_and_optionally_submit(result: dict, submit: bool = False,
                               edited_bindings: list[dict] | None = None
                               ) -> dict:
    """Persist confirmed bindings to the user DB. If `submit=True`,
    also queues for community submission.

    `edited_bindings` lets the GUI override the auto-extracted list
    (the user typically edits before saving). If None, saves what
    `extract_user_pdf` produced as-is.
    """
    bindings = (edited_bindings if edited_bindings is not None
                else result.get("bindings") or [])
    if not bindings:
        return {"saved": False, "reason": "no bindings to save"}

    saved_path = save_user_bindings(
        result["system_id"], result["rom_name"], bindings,
        title=result.get("title"),
        source_note=f"user_pdf:{result.get('extra', {}).get('pdf_path', '?')}")

    submission_status = None
    if submit:
        submission_status = _queue_submission(result["system_id"],
                                              result["rom_name"], bindings)

    return {
        "saved":         True,
        "saved_path":    str(saved_path),
        "submission":    submission_status,
    }


def _queue_submission(system_id: str, rom_name: str,
                      bindings: list[dict]) -> dict:
    """Stub for the community-submission path. The real implementation
    will piggy-back on the existing submit-controller flow (GitHub PR
    against a community/bindings repo). For now: write a queue file
    the user can review/clear later, with a clear note that no actual
    network submission has occurred."""
    from datetime import datetime, timezone
    from pathlib import Path
    import json

    queue_dir = Path(__file__).resolve().parent / "data" / "bindings_user_submission_queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    fn = queue_dir / f"{ts}_{system_id}_{_safe(rom_name)}.json"
    fn.write_text(json.dumps({
        "system_id":  system_id,
        "rom_name":   rom_name,
        "bindings":   bindings,
        "queued_at":  datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status":     "queued",
        "_note":      ("Submission API not yet wired. File saved locally; "
                       "user can review and submit via future "
                       "`pull-community` / `submit-controller` flow."),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"status": "queued_local", "path": str(fn)}


def _safe(s: str, maxlen: int = 60) -> str:
    import re
    s = re.sub(r"[^A-Za-z0-9._\-]+", "_", s).strip("_")
    return s[:maxlen] or "unnamed"


# ============================================================
# CLI (for end-user driving from a script if no GUI)
# ============================================================

def main():
    import argparse, json, sys
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", help="Path to the PDF the user provided.")
    ap.add_argument("system_id")
    ap.add_argument("rom")
    ap.add_argument("--save", action="store_true",
                    help="Persist auto-extracted bindings to the user DB "
                         "(no editing — typically the GUI edits first).")
    ap.add_argument("--submit", action="store_true",
                    help="Also queue a community submission "
                         "(no network call yet — local queue only).")
    args = ap.parse_args()

    result = extract_user_pdf(Path(args.pdf), args.system_id, args.rom)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    if args.save:
        outcome = save_and_optionally_submit(result, submit=args.submit)
        print("\n--- save outcome ---")
        print(json.dumps(outcome, indent=2, ensure_ascii=False))

    sys.exit(0 if result.get("bindings") else 1)


if __name__ == "__main__":
    main()
