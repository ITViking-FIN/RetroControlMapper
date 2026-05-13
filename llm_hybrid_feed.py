"""
Hybrid LLM feeder — runs Qwen 2.5 3B on regex-zero titles only.

Strategy: don't disturb regex-extracted bindings; only attack the
games where regex returned nothing. This maximises LLM signal-to-noise:
the hardest manuals are where it gets to prove its value, and the
memory pool grows fastest because every successful call gets
considered for the pool.

## Resumability

- A title's record gets a new field ``llm_attempted: true`` after
  any LLM call (success or failure) — re-running the script skips
  these unless ``--force`` is passed.
- Memory pool persists between runs (data/llm_few_shot.json).
- Per-system checkpoints written every N games.
- Interrupting (Ctrl-C, machine reboot) loses at most N games of work.

## Selection criteria for "regex-zero"

A title qualifies for LLM feeding when:
  - record['bindings'] is empty array OR missing
  - record['llm_attempted'] is falsy (not yet tried by LLM)
  - the PDF exists in data/manuals/<system>/

## Usage

    py llm_hybrid_feed.py --dry-run          # show what would be done
    py llm_hybrid_feed.py --system c64       # feed one system only
    py llm_hybrid_feed.py --limit 50         # cap titles processed
    py llm_hybrid_feed.py                    # full hybrid run

## Output

- Updates per-system DBs in data/bindings_db/<system>.json
  - LLM-extracted bindings get ``extractor: "llm-qwen2.5-3b"``
  - ``pass_succeeded: "llm_hybrid"`` for telemetry
- Memory pool grows in data/llm_few_shot.json
- Uncertain items append to data/llm_uncertain.jsonl
- Rejections append to data/llm_rejections.jsonl
- Run-summary printed at end + appended to data/llm_hybrid_feed.log
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
BINDINGS_DB_DIR = DATA_DIR / "bindings_db"
FEED_LOG = DATA_DIR / "llm_hybrid_feed.log"


def _load_db(system_id: str) -> dict | None:
    p = BINDINGS_DB_DIR / f"{system_id}.json"
    if not p.exists(): return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_db(db: dict):
    p = BINDINGS_DB_DIR / f"{db['system_id']}.json"
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(db, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(p)


def _qualifies_for_llm(rec: dict, force: bool) -> bool:
    """Regex-zero AND not yet LLM-attempted (unless --force)."""
    if rec.get("bindings"): return False           # has regex bindings already
    if not force and rec.get("llm_attempted"):     # already tried
        return False
    return True


def _resolve_pdf_path(system_id: str, normalised_name: str,
                       index: dict) -> Path | None:
    """Get the cached PDF path for a title. Returns None if not yet
    extracted from the archive (caller should extract first)."""
    games_index = index.get(system_id) or {}
    hit = games_index.get(normalised_name)
    if not hit:
        return None
    from manual_local import extract_local_manual
    try:
        return extract_local_manual(hit)
    except Exception:
        return None


def _get_section_text(pdf_path: Path) -> str | None:
    """Run OCR + section detection, return just the controls section
    text. Same pipeline regex uses, so the LLM sees identical input."""
    from manual_extract import (
        _read_pdf_text, _find_section, _coalesce_header_followed_by_action,
        _expand_tabular_rows)
    lines, _, source = _read_pdf_text(pdf_path, ocr=True)
    if not lines: return None
    lines = _expand_tabular_rows(lines)
    span = _find_section(lines)
    if span is None:
        # Fall back to first 200 lines — same as regex global-scan path
        return "\n".join(lines[:200])
    start, end = span
    section_lines = _coalesce_header_followed_by_action(lines[start:end + 1])
    return "\n".join(section_lines)


def _process_title(extractor, system_id: str, normalised_name: str,
                   rec: dict, index: dict, verbose: bool = True) -> dict:
    """Run LLM on one title. Returns the updated record (caller writes
    to DB). Does NOT mutate input — returns a copy.

    Important: `llm_attempted=true` only gets stamped on REAL outcomes
    (success, skip-with-reason, exception). Connection failures /
    Ollama-unreachable get NO mutation — _games_to_retry will pick up
    the same title on next run when the box is back online.
    """
    from llm_extract import SystemPassport, LLMError

    out = dict(rec)
    # Note: we no longer pre-stamp llm_attempted here. It gets set ONLY
    # after we know the LLM call actually executed (success or hard
    # failure that the LLM itself rejected). See bottom of function.

    pdf_path = _resolve_pdf_path(system_id, normalised_name, index)
    if pdf_path is None:
        out["llm_attempted"] = True
        out["llm_attempted_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                 time.gmtime())
        out["llm_skip_reason"] = "no PDF available (archive miss?)"
        return out
    section_text = _get_section_text(pdf_path)
    if not section_text:
        out["llm_attempted"] = True
        out["llm_attempted_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                 time.gmtime())
        out["llm_skip_reason"] = "OCR yielded no text"
        return out
    # Section sanity guard: if it's massive (>4000 chars), probably the
    # detector grabbed too much. Cap at 4000 chars.
    if len(section_text) > 4000:
        section_text = section_text[:4000]

    game_title = (rec.get("title") or normalised_name).rstrip(".pdf")
    passport = SystemPassport.for_system(
        system_id, game_title,
        era_hint="", genre_hint="")

    try:
        result = extractor.extract_bindings(section_text, passport)
    except LLMError as e:
        # Ollama unreachable / connection failed — do NOT mark
        # llm_attempted. Next run picks this title up again. Surfacing
        # the error so the caller can bail the whole run if Ollama is
        # down (no point in churning 3000 titles all with the same
        # network failure).
        raise
    except Exception:
        out["llm_attempted"] = True
        out["llm_attempted_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                 time.gmtime())
        out["llm_skip_reason"] = (f"exception: "
            f"{traceback.format_exc(limit=1).strip().splitlines()[-1]}")
        return out

    bindings = result.get("bindings") or []
    uncertain = result.get("uncertain") or []
    ci = result.get("call_info") or {}

    # Real outcome (success OR LLM-returned-nothing-but-call-completed)
    # — safe to mark attempted.
    out["llm_attempted"] = True
    out["llm_attempted_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                             time.gmtime())

    if bindings:
        out["bindings"]       = bindings
        out["section_found"]  = True
        out["text_source"]    = "ocr"
        out["pass_succeeded"] = "llm_hybrid"
        out["extractor_version"] = "0.2-llm-hybrid"
        # Append to passes_attempted history
        attempts = list(out.get("passes_attempted") or [])
        if "llm_hybrid" not in attempts:
            attempts.append("llm_hybrid")
        out["passes_attempted"] = attempts
    if uncertain:
        out["llm_uncertain_count"] = len(uncertain)

    if verbose:
        print(f"  {normalised_name[:40]:<42} "
              f"bind={len(bindings):>2}  unc={len(uncertain):>2}  "
              f"{ci.get('elapsed_s', 0):>5.1f}s  "
              f"(in={ci.get('prompt_eval_count', 0)} out={ci.get('eval_count', 0)})")
    return out


def _list_targets(system_id: str, force: bool = False) -> list[str]:
    db = _load_db(system_id)
    if db is None: return []
    return [k for k, r in (db.get("games") or {}).items()
            if _qualifies_for_llm(r, force)]


def run_feed(system_id: str | None = None, limit: int | None = None,
             checkpoint_every: int = 10, force: bool = False,
             dry_run: bool = False, verbose: bool = True,
             endpoint: str | None = None, model: str | None = None,
             examples_per_prompt: int = 2,
             skip_single_button: bool = False) -> dict:
    """The full hybrid feed loop.

    `skip_single_button=True` excludes systems in
    llm_style_guide.JOYSTICK_SYSTEMS so this can run in parallel with
    the regex pass-5 (single-button specialist) without race-condition
    risk on shared per-system DBs.
    """
    from manual_local import ensure_index
    from llm_extract import LLMExtractor, DEFAULT_ENDPOINT, DEFAULT_MODEL
    from llm_memory import LLMMemory

    index = ensure_index()
    if not index:
        print("[fatal] no manual archive index — run `py manual_local.py reindex`",
              file=sys.stderr); sys.exit(1)

    # Choose systems
    if system_id:
        systems = [system_id]
    else:
        systems = sorted([p.stem for p in BINDINGS_DB_DIR.glob("*.json")
                          if p.stem in index])
        systems.sort(key=lambda s: -len(index.get(s, {})))

    # Optional: drop joystick (single-button) systems. Lets the hybrid
    # feed run safely alongside the regex pass-5 cascade.
    if skip_single_button:
        from llm_style_guide import JOYSTICK_SYSTEMS
        before = len(systems)
        systems = [s for s in systems if s not in JOYSTICK_SYSTEMS]
        if verbose:
            print(f"--skip-single-button: dropped {before - len(systems)} "
                  f"joystick systems; processing {len(systems)} multi-button.")

    memory = LLMMemory()
    extractor = LLMExtractor(
        endpoint=endpoint or DEFAULT_ENDPOINT,
        model=model or DEFAULT_MODEL,
        memory=memory,
        examples_per_prompt=examples_per_prompt)

    # Ping ollama first — bail early if unreachable
    try:
        info = extractor.client.ping()
        if verbose:
            ms = info.get("models", [])
            print(f"Ollama: {extractor.client.endpoint} reachable "
                  f"({len(ms)} model(s))")
    except Exception as e:
        print(f"[fatal] ollama unreachable: {e}", file=sys.stderr)
        sys.exit(1)

    grand = {"systems": 0, "attempted": 0, "with_bindings": 0,
             "uncertain": 0, "skipped": 0, "errors": 0,
             "memory_added": 0,
             "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    for sys_id in systems:
        targets = _list_targets(sys_id, force=force)
        if not targets:
            if verbose: print(f"[{sys_id}] no targets (all titles either have "
                              f"bindings or already LLM-attempted)")
            continue
        if limit:
            targets = targets[:limit]
        grand["systems"] += 1

        if dry_run:
            if verbose:
                print(f"[{sys_id}] would process {len(targets)} titles")
            grand["attempted"] += len(targets)
            continue

        db = _load_db(sys_id)
        if db is None: continue
        if verbose:
            print(f"\n[{sys_id}] processing {len(targets)} regex-zero titles")

        t0 = time.time()
        sys_stats = {"with_bindings": 0, "uncertain": 0, "memory_added": 0,
                     "skipped": 0}

        for i, key in enumerate(targets):
            rec = db["games"].get(key, {})
            try:
                updated = _process_title(extractor, sys_id, key, rec,
                                          index, verbose=verbose)
            except KeyboardInterrupt:
                print("\n[interrupted] saving checkpoint and stopping...")
                _save_db(db); memory.save(); return grand
            except Exception as e:
                # LLMError from _process_title means Ollama is unreachable
                # — bail the whole run, don't waste cycles. Caller can
                # resume when the box is back online; no titles get
                # falsely marked llm_attempted in the meantime.
                from llm_extract import LLMError
                if isinstance(e, LLMError):
                    print(f"\n[fatal] Ollama unreachable mid-run: {e}",
                          file=sys.stderr)
                    print("  Saving partial progress and aborting. "
                          "Re-run when Ollama is back — already-attempted "
                          "titles will be skipped, in-flight title will "
                          "be retried.", file=sys.stderr)
                    _save_db(db); memory.save()
                    grand["errors"] += 1
                    grand["aborted_at"] = key
                    grand["abort_reason"] = "ollama_unreachable"
                    return grand
                grand["errors"] += 1
                if verbose:
                    print(f"  [error] {key}: {e}", file=sys.stderr)
                continue

            db["games"][key] = updated
            grand["attempted"] += 1

            if updated.get("bindings"):
                sys_stats["with_bindings"] += 1
                grand["with_bindings"] += 1
            if updated.get("llm_uncertain_count"):
                sys_stats["uncertain"] += updated["llm_uncertain_count"]
                grand["uncertain"] += updated["llm_uncertain_count"]
            if updated.get("llm_skip_reason"):
                sys_stats["skipped"] += 1
                grand["skipped"] += 1

            if (i + 1) % checkpoint_every == 0:
                _save_db(db); memory.save()
                if verbose:
                    rate = (i + 1) / max(0.01, time.time() - t0)
                    pool = memory.stats().get(sys_id, {}).get("pool_size", 0)
                    print(f"  -- checkpoint @ {i + 1}/{len(targets)}: "
                          f"+{sys_stats['with_bindings']} bindings, "
                          f"pool now {pool}, {rate:.2f}/s")

        # Final save for this system
        _save_db(db); memory.save()
        if verbose:
            elapsed = time.time() - t0
            print(f"[{sys_id}] DONE  attempted={len(targets)} "
                  f"new_bindings={sys_stats['with_bindings']} "
                  f"uncertain={sys_stats['uncertain']} "
                  f"skipped={sys_stats['skipped']}  ({elapsed:.0f}s)")

    grand["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    grand["memory_pool"] = memory.stats()
    return grand


def _append_log(summary: dict):
    """Append a one-line summary entry to data/llm_hybrid_feed.log."""
    try:
        FEED_LOG.parent.mkdir(parents=True, exist_ok=True)
        with FEED_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(summary, ensure_ascii=False) + "\n")
    except OSError:
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--system", help="Limit to one system.")
    ap.add_argument("--limit", type=int, help="Cap titles per system.")
    ap.add_argument("--checkpoint-every", type=int, default=10)
    ap.add_argument("--force", action="store_true",
                    help="Re-attempt titles even if llm_attempted=true.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Just print what would happen, don't call LLM.")
    ap.add_argument("--endpoint", help="Ollama endpoint override.")
    ap.add_argument("--model", help="Ollama model override.")
    ap.add_argument("--examples", type=int, default=2,
                    help="Few-shot examples per prompt.")
    ap.add_argument("--skip-single-button", action="store_true",
                    help="Exclude joystick (single-button) systems. Use "
                         "when running in parallel with pass 5 to avoid "
                         "per-system DB race conditions.")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    summary = run_feed(
        system_id=args.system,
        limit=args.limit,
        checkpoint_every=args.checkpoint_every,
        force=args.force,
        dry_run=args.dry_run,
        verbose=not args.quiet,
        endpoint=args.endpoint,
        model=args.model,
        examples_per_prompt=args.examples,
        skip_single_button=args.skip_single_button,
    )

    if not args.quiet:
        print("\n" + "=" * 60)
        print(f"  HYBRID FEED SUMMARY")
        print("=" * 60)
        print(f"  systems processed:    {summary['systems']}")
        print(f"  titles attempted:     {summary['attempted']}")
        print(f"  new bindings found:   {summary['with_bindings']}")
        print(f"  uncertain items:      {summary['uncertain']}")
        print(f"  skipped (no PDF/OCR): {summary['skipped']}")
        print(f"  errors:               {summary['errors']}")
        print(f"\n  Memory pool growth:")
        for sid, info in sorted(summary.get("memory_pool", {}).items()):
            print(f"    {sid:<14} {info['pool_size']:>3} examples  "
                  f"avg-score {info['avg_score']}")
    if not args.dry_run:
        _append_log(summary)


if __name__ == "__main__":
    main()
