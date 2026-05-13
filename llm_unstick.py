"""
Reset `llm_attempted` on records that were stranded by Ollama failures.

When the hybrid feed runs against an unreachable Ollama box, the older
version of llm_hybrid_feed.py pre-stamped `llm_attempted=true` on every
record BEFORE actually calling the LLM. Connection failures then left
those records permanently skipped on future runs — even after Ollama
comes back online.

This utility walks data/bindings_db/*.json and reverses that for
records with the failure signature:
  - llm_attempted: true
  - bindings: empty (or missing)
  - no llm_skip_reason          (would be present on real skips like
                                  "no PDF available" / "OCR yielded
                                  no text" / "exception:")
  - no llm_uncertain_count      (real LLM calls leave this even on
                                  zero-binding outcomes)

If both fields are absent it strongly implies the call never reached
the LLM at all — pure network failure. Those get llm_attempted
cleared so the next hybrid-feed run will retry them.

## Usage

    py llm_unstick.py --dry-run            # show what would be reset
    py llm_unstick.py                      # actually do it
    py llm_unstick.py --system nes         # one system only
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BINDINGS_DB_DIR = ROOT / "data" / "bindings_db"


def _load(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save(p: Path, db: dict):
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(db, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(p)


def _looks_stranded(rec: dict) -> bool:
    """A record was stranded by a network failure if:
       - llm_attempted is truthy
       - no bindings were produced
       - llm_skip_reason is absent (real skips leave this)
       - llm_uncertain_count is absent (real LLM calls would set this)
    """
    if not rec.get("llm_attempted"): return False
    if rec.get("bindings"): return False
    if rec.get("llm_skip_reason"): return False
    if rec.get("llm_uncertain_count") is not None: return False
    # Also leave alone titles that have an llm_attempted_at recent enough
    # that we're confident it was real. Heuristic: if llm_attempted_at
    # is missing the record was definitely stranded.
    # (Older buggy runs DID stamp llm_attempted_at, so we can't use
    # presence as a real-vs-stranded discriminator alone. The two prior
    # fields are sufficient.)
    return True


def unstick(system_id: str | None = None, dry_run: bool = False) -> dict:
    if not BINDINGS_DB_DIR.exists():
        print("[fatal] no bindings_db dir", file=sys.stderr)
        sys.exit(1)

    targets = []
    if system_id:
        p = BINDINGS_DB_DIR / f"{system_id}.json"
        if p.exists(): targets = [p]
    else:
        targets = sorted(BINDINGS_DB_DIR.glob("*.json"))

    totals = {"systems": 0, "scanned": 0, "stranded": 0, "unstuck": 0}

    for p in targets:
        db = _load(p)
        if db is None: continue
        games = db.get("games") or {}
        if not games: continue
        totals["systems"] += 1

        stranded_keys = []
        for k, rec in games.items():
            totals["scanned"] += 1
            if _looks_stranded(rec):
                stranded_keys.append(k)

        if not stranded_keys:
            continue

        totals["stranded"] += len(stranded_keys)
        print(f"[{p.stem}] {len(stranded_keys)} stranded records "
              f"(of {len(games)} total)")

        if dry_run: continue

        for k in stranded_keys:
            rec = games[k]
            # Drop the stale fields so the hybrid feed considers it fresh
            rec.pop("llm_attempted", None)
            rec.pop("llm_attempted_at", None)
            # Keep any preserved bindings (there shouldn't be any but
            # be defensive).
        totals["unstuck"] += len(stranded_keys)
        _save(p, db)

    print()
    print(f"Systems scanned:     {totals['systems']}")
    print(f"Records scanned:     {totals['scanned']}")
    print(f"Stranded detected:   {totals['stranded']}")
    if dry_run:
        print(f"(dry-run — no changes written)")
    else:
        print(f"Unstuck (cleared):   {totals['unstuck']}")
    return totals


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--system", help="Limit to one system id.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would be reset, don't write.")
    args = ap.parse_args()
    unstick(system_id=args.system, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
