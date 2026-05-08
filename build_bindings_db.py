"""
Build the per-game bindings database — the shippable artifact.

Walks the local manual archive (`manual_local`'s index), extracts each
PDF on-demand, runs the heuristic extractor (`manual_extract`), and
accumulates the results into per-system JSON files under
`data/bindings_db/<system_id>.json`.

The output is what we ship in the installer (or as a release asset).
The PDFs themselves never leave the user's machine. The output is
small (~few MB total) and contains only **functional button-to-action
mappings** — facts that aren't copyrightable — never any PDF prose.

## Resumable

The orchestrator writes progress incrementally — every N games it
checkpoints the per-system JSON. Re-running with the same args picks
up where it left off, only processing games not yet recorded.

## Usage

    py build_bindings_db.py --system nes --limit 50
        # quick yield recon: first 50 NES games
    py build_bindings_db.py --system nes
        # full pass over NES (~668 games, ~10 min)
    py build_bindings_db.py
        # full pass over EVERY non-arcade system. Hours.
    py build_bindings_db.py --system nes --rebuild
        # discard existing results, start fresh

## Output schema (per system file)

    {
      "system_id": "nes",
      "schema_version": 1,
      "extracted_at": "ISO8601",
      "extractor_version": "0.1.4",
      "stats": {
        "total_games_in_index": 668,
        "attempted":            668,
        "section_found":        420,
        "with_bindings":        310,
        "skipped_already_done": 0,
        "errors":               12
      },
      "games": {
        "<normalised_rom_name>": {
          "title":           "Super Mario Bros.",
          "filename":        "Super Mario Bros. - 1985 - Nintendo.pdf",
          "section_found":   true,
          "pages_scanned":   18,
          "bindings":        [{button, action, confidence, raw, matched_by}, ...],
          "note":            "..."  (optional; present when extraction degraded)
        }
      }
    }
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
BINDINGS_DB_DIR = DATA_DIR / "bindings_db"

EXTRACTOR_VERSION = "0.1.4"
SCHEMA_VERSION = 1

# Arcade systems are served better by controls.dat (Task 1) so we skip
# them here. They're also massively duplicated in the archive index due
# to the Arcade-folder cross-mapping (mame/fbneo/hbmame/cps1/2/3 all
# point at the same 1,520 PDFs).
SKIP_SYSTEMS = {
    "mame", "fbneo", "hbmame", "neogeo",
    "cps1", "cps2", "cps3",
}


# ============================================================
# Per-system database I/O
# ============================================================

def _db_path(system_id: str) -> Path:
    return BINDINGS_DB_DIR / f"{system_id}.json"


def load_system_db(system_id: str) -> dict:
    """Load existing per-system DB or return a fresh skeleton."""
    p = _db_path(system_id)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {
        "system_id":         system_id,
        "schema_version":    SCHEMA_VERSION,
        "extracted_at":      None,
        "extractor_version": EXTRACTOR_VERSION,
        "stats":             {},
        "games":             {},
    }


def save_system_db(db: dict):
    BINDINGS_DB_DIR.mkdir(parents=True, exist_ok=True)
    db["extracted_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    p = _db_path(db["system_id"])
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(db, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(p)


# ============================================================
# Per-game extraction
# ============================================================

def process_game(system_id: str, normalised_name: str, hit: dict,
                 ocr: bool = True) -> dict | None:
    """Extract + analyse one game's manual. Returns the per-game record
    for the DB, or None on hard error.

    `ocr=True` (default for build-time) enables the tesseract fallback
    on image-only PDFs. Set False for a fast text-PDF-only pass."""
    from manual_local import extract_local_manual
    from manual_extract import extract_bindings_from_pdf

    pdf_path = extract_local_manual(hit)
    if pdf_path is None:
        return {
            "title":         hit.get("filename", normalised_name),
            "filename":      hit.get("filename"),
            "section_found": False,
            "pages_scanned": 0,
            "bindings":      [],
            "text_source":   "empty",
            "note":          "extraction failed (could not unpack PDF from archive)",
        }

    result = extract_bindings_from_pdf(pdf_path, ocr=ocr)
    if "error" in result:
        return {
            "title":         hit.get("filename", normalised_name),
            "filename":      hit.get("filename"),
            "section_found": False,
            "pages_scanned": result.get("pages_scanned", 0),
            "bindings":      [],
            "text_source":   result.get("text_source", "empty"),
            "note":          result["error"],
        }

    record = {
        "title":         hit.get("filename", normalised_name),
        "filename":      hit.get("filename"),
        "section_found": bool(result.get("section_found")),
        "pages_scanned": int(result.get("pages_scanned") or 0),
        "text_source":   result.get("text_source", "empty"),
        "bindings":      result.get("bindings") or [],
    }
    if result.get("note"):
        record["note"] = result["note"]
    return record


# ============================================================
# Orchestration
# ============================================================

def process_system(system_id: str,
                   index: dict,
                   limit: int | None = None,
                   rebuild: bool = False,
                   checkpoint_every: int = 10,
                   ocr: bool = True,
                   verbose: bool = True) -> dict:
    games_index = index.get(system_id) or {}
    if not games_index:
        if verbose:
            print(f"[{system_id}] not in index")
        return {}

    db = load_system_db(system_id) if not rebuild else {
        "system_id":         system_id,
        "schema_version":    SCHEMA_VERSION,
        "extracted_at":      None,
        "extractor_version": EXTRACTOR_VERSION,
        "stats":             {},
        "games":             {},
    }
    done_keys = set(db.get("games", {}).keys())

    todo = [(k, v) for k, v in games_index.items() if k not in done_keys]
    if limit:
        todo = todo[:limit]

    if verbose:
        print(f"[{system_id}] index: {len(games_index)}  "
              f"already done: {len(done_keys)}  "
              f"to process now: {len(todo)}")

    stats = {
        "total_games_in_index":  len(games_index),
        "attempted":             0,
        "section_found":         0,
        "with_bindings":         0,
        "skipped_already_done":  len(done_keys),
        "errors":                0,
        "ocr_required":          0,    # legacy field; same as text_source==ocr
        "by_text_source":        {"pdfplumber": 0, "pypdf": 0,
                                  "ocr": 0, "empty": 0},
    }

    t0 = time.time()
    for i, (key, hit) in enumerate(todo):
        try:
            record = process_game(system_id, key, hit, ocr=ocr)
        except Exception:
            if verbose:
                print(f"  [error] {key}: {traceback.format_exc(limit=1).strip().splitlines()[-1]}",
                      file=sys.stderr)
            record = None
            stats["errors"] += 1

        stats["attempted"] += 1
        if record is None:
            db["games"][key] = {
                "title":         key,
                "section_found": False,
                "pages_scanned": 0,
                "bindings":      [],
                "note":          "exception during processing",
            }
        else:
            db["games"][key] = record
            if record.get("section_found"):
                stats["section_found"] += 1
            if record.get("bindings"):
                stats["with_bindings"] += 1
            ts = record.get("text_source", "empty")
            if ts in stats["by_text_source"]:
                stats["by_text_source"][ts] += 1
            if ts == "ocr" or "scanned/image-only" in (record.get("note") or ""):
                stats["ocr_required"] += 1

        if verbose and (i + 1) % 5 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            print(f"  [{i + 1}/{len(todo)}] "
                  f"section_found={stats['section_found']}  "
                  f"with_bindings={stats['with_bindings']}  "
                  f"ocr={stats['ocr_required']}  "
                  f"err={stats['errors']}  "
                  f"({rate:.1f}/s)")

        if (i + 1) % checkpoint_every == 0:
            db["stats"] = stats
            save_system_db(db)

    db["stats"] = {**db.get("stats", {}), **stats}
    save_system_db(db)
    if verbose:
        print(f"[{system_id}] DONE — "
              f"{stats['attempted']} processed, "
              f"{stats['with_bindings']} with bindings "
              f"({100 * stats['with_bindings'] // max(1, stats['attempted'])}% yield), "
              f"{stats['ocr_required']} need OCR, "
              f"{stats['errors']} errors. "
              f"Wrote {_db_path(system_id)}")
    return stats


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--system", help="Limit to one RetroBat system id "
                    "(default: every non-arcade system in the index).")
    ap.add_argument("--limit", type=int,
                    help="Process at most N games (useful for yield recon).")
    ap.add_argument("--rebuild", action="store_true",
                    help="Discard existing per-system DB and start over.")
    ap.add_argument("--checkpoint-every", type=int, default=10,
                    help="Save the per-system DB every N games (default 10).")
    ap.add_argument("--no-ocr", action="store_true",
                    help="Skip the OCR fallback for image-only PDFs. Faster "
                         "but yields ~1%% on most retro systems where manuals "
                         "are scanned. Default: OCR enabled.")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    from manual_local import ensure_index
    index = ensure_index()
    if not index:
        print("[fatal] no manual archive index found. Run "
              "`py manual_local.py reindex` first.", file=sys.stderr)
        sys.exit(1)

    if args.system:
        systems = [args.system]
    else:
        systems = [s for s in index.keys() if s not in SKIP_SYSTEMS]
        # Process biggest first so checkpoints land early
        systems.sort(key=lambda s: -len(index.get(s, {})))

    grand = {"attempted": 0, "with_bindings": 0,
             "section_found": 0, "ocr_required": 0, "errors": 0}
    for sys_id in systems:
        stats = process_system(sys_id, index,
                               limit=args.limit,
                               rebuild=args.rebuild,
                               checkpoint_every=args.checkpoint_every,
                               ocr=not args.no_ocr,
                               verbose=not args.quiet)
        for k in grand:
            grand[k] += stats.get(k, 0)
        if not args.quiet:
            print()

    if not args.quiet and len(systems) > 1:
        print("=" * 60)
        print(f"GRAND TOTALS across {len(systems)} systems:")
        print(f"  attempted:       {grand['attempted']}")
        print(f"  section_found:   {grand['section_found']}")
        print(f"  with bindings:   {grand['with_bindings']} "
              f"({100 * grand['with_bindings'] // max(1, grand['attempted'])}%)")
        print(f"  need OCR:        {grand['ocr_required']}")
        print(f"  errors:          {grand['errors']}")


if __name__ == "__main__":
    main()
