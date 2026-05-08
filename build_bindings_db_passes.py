"""
Multi-pass bindings DB extraction — climbs the yield curve.

Pass 1 (the existing build_bindings_db.py) handles the easy wins —
~43% of NES at last measure. This script picks up where that left off:
runs pass 2/3/4 only on titles where the previous pass yielded zero
bindings, and records which pass finally caught each title.

## Why pass-by-pass instead of one big tuned parser

Each pass is its own honest hypothesis. Pass 2 says "maybe the section
header was just unusual"; pass 3 says "maybe the OCR was wrong"; pass 4
says "let's try every loose pattern that produces noise but might
actually catch something". By keeping them separate we can tell from
the per-game `pass_succeeded` field what kind of manual it was, and
later passes are honest about their lower confidence (the GUI can
colour low-confidence bindings differently).

## Usage

    py build_bindings_db_passes.py --start-pass 2
        # Run passes 2, 3, 4 over every prior miss
    py build_bindings_db_passes.py --start-pass 3 --end-pass 3 --system nes
        # Just pass 3, just NES
    py build_bindings_db_passes.py --start-pass 4 --limit 50
        # First 50 misses only (for quick sanity-check)
    py build_bindings_db_passes.py --stats
        # Just print the per-pass yield breakdown, no work

## Resumable

Each pass writes its progress back into the per-system bindings DB.
Re-running the same pass is a no-op for titles that already have
bindings. The orchestrator only operates on entries where
`bindings == []` AND `pass_succeeded` is None or earlier than the
current pass.

## How pass 3 works (PSM sweep, special-cased)

Pass 3 needs to try multiple tesseract PSMs since each layout style
benefits from different segmentation. The orchestrator runs PSM 6,
PSM 4, and PSM 11 in turn (PSM 3 already cached from pass 1) and
keeps whichever produced the most bindings — so a single "pass 3 hit"
is actually the best of three OCR re-runs, all cached for future use.
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


def _load_db(system_id: str) -> dict | None:
    p = BINDINGS_DB_DIR / f"{system_id}.json"
    if not p.exists(): return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save_db(db: dict):
    BINDINGS_DB_DIR.mkdir(parents=True, exist_ok=True)
    db["extracted_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    p = BINDINGS_DB_DIR / f"{db['system_id']}.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(db, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(p)


def _games_to_retry(db: dict, current_pass: str,
                    pass_order: list[str]) -> list[str]:
    """Which games (normalised keys) should this pass try?
    Rule: bindings is empty AND no later pass already succeeded.
    A pass that already 'succeeded' for this game (even if it found
    zero) is not re-run — that's what passes_after is for."""
    games = db.get("games") or {}
    cur_idx = pass_order.index(current_pass)
    out = []
    for k, rec in games.items():
        # Skip if already has bindings.
        if rec.get("bindings"): continue
        # Skip if a same-or-later pass already attempted (recorded
        # by `passes_attempted` list — earlier passes get listed even
        # if they yielded zero).
        attempted = rec.get("passes_attempted") or []
        attempt_idxs = [pass_order.index(p) for p in attempted
                        if p in pass_order]
        if any(idx >= cur_idx for idx in attempt_idxs): continue
        # Skip if this PDF is image-only and we don't have OCR (legacy
        # records from pre-OCR runs). Re-attempts with OCR happen
        # naturally because text_source==empty triggers OCR.
        out.append(k)
    return out


def _resolve_archive_hit(system_id: str, normalised_key: str,
                         index: dict) -> dict | None:
    """Re-locate the archive hit for a game key. The DB stores the
    filename and the bindings, but extraction needs the archive_path."""
    games = index.get(system_id) or {}
    return games.get(normalised_key)


def _run_pass3_psm_sweep(pdf_path: Path, base_config) -> dict:
    """Pass 3: try multiple PSMs, keep the best. Cached so subsequent
    runs that hit the same PSM are free."""
    from manual_extract import extract_with_config, ParserConfig
    from extraction_passes import PASS_3_PSM_OPTIONS

    best = None
    for psm in PASS_3_PSM_OPTIONS:
        cfg = ParserConfig(
            name=f"pass3_psm_sweep_psm{psm}",
            psm=psm,
            extra_section_headers=base_config.extra_section_headers,
            extra_line_patterns=base_config.extra_line_patterns,
            looser_action_filter=base_config.looser_action_filter,
            confidence_floor=base_config.confidence_floor,
            max_section_lines=base_config.max_section_lines,
        )
        try:
            result = extract_with_config(pdf_path, cfg, ocr=True)
        except Exception:
            continue
        nb = len(result.get("bindings") or [])
        if best is None or nb > len(best.get("bindings") or []):
            best = result
        # Short-circuit if a PSM finds bindings — don't waste cycles.
        if nb >= 3: break
    if best is None:
        # All PSMs errored; return a synthetic empty record.
        return {"pdf_path": str(pdf_path), "bindings": [],
                "section_found": False, "pass_name": "pass3_psm_sweep",
                "text_source": "empty"}
    # Re-tag with the umbrella pass name for telemetry consistency.
    best["pass_name"] = "pass3_psm_sweep"
    return best


def run_pass(pass_name: str, system_id: str | None = None,
             limit: int | None = None,
             checkpoint_every: int = 10,
             verbose: bool = True) -> dict:
    """Run one named pass over all systems (or one system)."""
    from extraction_passes import (ORDERED_PASSES, get_pass, PASS_3_PSM_SWEEP)
    from manual_extract import extract_with_config
    from manual_local import ensure_index, extract_local_manual

    cfg = get_pass(pass_name)
    if cfg is None:
        raise ValueError(f"Unknown pass: {pass_name}")

    pass_order = [c.name for c in ORDERED_PASSES]
    index = ensure_index()
    if not index:
        raise RuntimeError(
            "no manual archive index found — run `py manual_local.py reindex`")

    if system_id:
        systems = [system_id]
    else:
        systems = sorted([p.stem for p in BINDINGS_DB_DIR.glob("*.json")
                          if p.stem in index])
        # biggest first
        systems.sort(key=lambda s: -len(index.get(s, {})))

    grand = {"attempted": 0, "found": 0, "errors": 0}

    for sys_id in systems:
        db = _load_db(sys_id)
        if db is None:
            if verbose: print(f"[{sys_id}] no DB file (skip)")
            continue

        retry_keys = _games_to_retry(db, pass_name, pass_order)
        if limit:
            retry_keys = retry_keys[:limit]
        if not retry_keys:
            if verbose: print(f"[{sys_id}] nothing to retry for {pass_name}")
            continue

        if verbose:
            print(f"[{sys_id}] pass={pass_name} retrying {len(retry_keys)} titles")

        stats = {"attempted": 0, "found": 0, "errors": 0,
                 "by_pass": db.get("stats", {}).get("by_pass", {})}
        stats["by_pass"].setdefault(pass_name, 0)
        t0 = time.time()

        for i, key in enumerate(retry_keys):
            hit = _resolve_archive_hit(sys_id, key, index)
            if hit is None:
                # Archive entry vanished — possibly an encoding-issue
                # filename. Skip with a note.
                rec = db["games"].get(key) or {}
                rec.setdefault("passes_attempted", [])
                if pass_name not in rec["passes_attempted"]:
                    rec["passes_attempted"].append(pass_name)
                rec["note"] = (rec.get("note") or "") + \
                              f" | {pass_name}: archive entry missing"
                db["games"][key] = rec
                stats["attempted"] += 1
                continue
            try:
                pdf_path = extract_local_manual(hit)
            except Exception:
                stats["errors"] += 1
                continue
            if pdf_path is None:
                stats["errors"] += 1
                continue

            try:
                if pass_name == "pass3_psm_sweep":
                    result = _run_pass3_psm_sweep(pdf_path, PASS_3_PSM_SWEEP)
                else:
                    result = extract_with_config(pdf_path, cfg, ocr=True)
            except Exception:
                if verbose:
                    print(f"  [error] {key}: "
                          f"{traceback.format_exc(limit=1).strip().splitlines()[-1]}",
                          file=sys.stderr)
                stats["errors"] += 1
                continue

            stats["attempted"] += 1
            rec = db["games"].get(key) or {}
            rec.setdefault("passes_attempted", [])
            if pass_name not in rec["passes_attempted"]:
                rec["passes_attempted"].append(pass_name)

            new_bindings = result.get("bindings") or []
            if new_bindings:
                rec["bindings"]      = new_bindings
                rec["section_found"] = bool(result.get("section_found"))
                rec["pages_scanned"] = result.get("pages_scanned",
                                                  rec.get("pages_scanned", 0))
                rec["text_source"]   = result.get("text_source",
                                                  rec.get("text_source", "empty"))
                rec["pass_succeeded"] = pass_name
                if "note" in rec and "needs OCR" in (rec.get("note") or ""):
                    del rec["note"]
                stats["found"] += 1
                stats["by_pass"][pass_name] += 1

            db["games"][key] = rec

            if verbose and (i + 1) % 5 == 0:
                rate = (i + 1) / max(0.01, time.time() - t0)
                print(f"  [{i + 1}/{len(retry_keys)}] "
                      f"new_found={stats['found']}  "
                      f"err={stats['errors']}  ({rate:.1f}/s)")

            if (i + 1) % checkpoint_every == 0:
                # merge stats and save
                db["stats"] = {**db.get("stats", {}),
                               "by_pass": stats["by_pass"]}
                _save_db(db)

        # Final save
        db["stats"] = {**db.get("stats", {}),
                       "by_pass": stats["by_pass"]}
        # Recompute with_bindings
        with_b = sum(1 for r in db["games"].values() if r.get("bindings"))
        db["stats"]["with_bindings"] = with_b
        _save_db(db)

        if verbose:
            print(f"[{sys_id}] pass={pass_name} DONE — "
                  f"new_found={stats['found']}, "
                  f"now total with_bindings={with_b}, "
                  f"err={stats['errors']}")
        grand["attempted"] += stats["attempted"]
        grand["found"]     += stats["found"]
        grand["errors"]    += stats["errors"]
    return grand


def print_stats():
    """Per-pass yield breakdown across all per-system DBs."""
    if not BINDINGS_DB_DIR.exists():
        print("(no bindings_db directory)")
        return
    grand = {"attempted": 0, "with_bindings": 0,
             "by_pass": {}}
    print(f"{'system':<14} {'attempted':>9} {'with_bindings':>14}  by_pass")
    for p in sorted(BINDINGS_DB_DIR.glob("*.json")):
        try:
            db = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        s = db.get("stats", {})
        att = s.get("attempted", 0)
        wb  = s.get("with_bindings", 0)
        by_pass = s.get("by_pass", {})
        # Compute pass1 inferred (any with_bindings whose pass_succeeded
        # field is missing or "pass1_default")
        if "pass1_default" not in by_pass:
            p1 = sum(1 for r in db.get("games", {}).values()
                     if r.get("bindings") and
                     r.get("pass_succeeded", "pass1_default") == "pass1_default")
            by_pass["pass1_default"] = p1
        bp_str = ", ".join(f"{k}={v}" for k, v in sorted(by_pass.items()) if v)
        print(f"{p.stem:<14} {att:>9} {wb:>14}  {bp_str}")
        grand["attempted"] += att
        grand["with_bindings"] += wb
        for k, v in by_pass.items():
            grand["by_pass"][k] = grand["by_pass"].get(k, 0) + v
    print()
    print(f"GRAND  attempted={grand['attempted']}  "
          f"with_bindings={grand['with_bindings']}  "
          f"({100 * grand['with_bindings'] // max(1, grand['attempted'])}%)")
    print("  Per-pass yield:")
    for k, v in sorted(grand["by_pass"].items()):
        print(f"    {k:<22} {v}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start-pass", default="pass2_extra_headers",
                    help="First pass to run (default: pass2_extra_headers).")
    ap.add_argument("--end-pass", default="pass4_loose",
                    help="Last pass to run.")
    ap.add_argument("--system", help="Limit to one system.")
    ap.add_argument("--limit", type=int, help="At most N retries per system.")
    ap.add_argument("--checkpoint-every", type=int, default=10)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--stats", action="store_true",
                    help="Just print per-pass stats and exit.")
    args = ap.parse_args()

    if args.stats:
        print_stats()
        return

    from extraction_passes import ORDERED_PASSES
    pass_order = [c.name for c in ORDERED_PASSES]
    try:
        start = pass_order.index(args.start_pass)
        end   = pass_order.index(args.end_pass)
    except ValueError as e:
        print(f"[fatal] {e}", file=sys.stderr); sys.exit(1)

    for cfg in ORDERED_PASSES[start:end + 1]:
        if not args.quiet:
            print(f"\n{'=' * 60}\n  RUNNING {cfg.name}\n{'=' * 60}")
        run_pass(cfg.name, system_id=args.system, limit=args.limit,
                 checkpoint_every=args.checkpoint_every,
                 verbose=not args.quiet)

    if not args.quiet:
        print()
        print_stats()


if __name__ == "__main__":
    main()
