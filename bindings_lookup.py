"""
Unified bindings lookup — the API the GUI calls.

Given (system_id, rom_name), find the best-available button bindings
across all the tiers we can pull from. Returns a list of suggested
bindings the GUI shows as a "We think these are the controls — confirm
or change them" panel.

## Cascade order (highest priority first)

  1. **User contribution**     — bindings the end user previously
                                 confirmed for this exact game on this
                                 machine, saved to bindings_user/.
                                 Always wins if present.
  2. **Bundled bindings DB**   — the shippable artifact the installer
                                 dropped in data/bindings_db/<sys>.json.
                                 Pre-extracted from manuals on the dev
                                 box, ~thousands of titles.
  3. **Arcade controls.dat**   — for arcade systems (mame/fbneo/cps*/
                                 neogeo), the canonical controls.dat
                                 (already loaded via data_arcade_controls).
  4. **Online research**       — Vimm's Lair etc. via Flaresolverr,
                                 if available. Network-bound; only run
                                 when explicitly requested by the GUI
                                 (not from auto-load) so it doesn't
                                 stall every profile open.

The first tier that returns something stops the cascade; lower tiers
aren't queried.

## Public API

    from bindings_lookup import lookup, online_lookup, save_user_bindings

    result = lookup("nes", "Super Mario Bros.")
    # → {"source": "bundled", "bindings": [...], "title": "...", ...}
    # or None if no tier has a hit

    # Optional explicit online query (slow, asks Flaresolverr):
    result = online_lookup("nes", "Some Obscure Game")

    # User confirmed/edited bindings — save for next time:
    save_user_bindings("nes", "Super Mario Bros.", [...])

## Schema returned

    {
      "source":     "user" | "bundled" | "arcade" | "online" | "user_pdf",
      "system_id":  "nes",
      "rom_name":   "Super Mario Bros.",
      "title":      "Super Mario Bros.",     # human-readable
      "bindings":   [{button, action, confidence, raw, matched_by}, ...],
      "extra":      { ...source-specific telemetry... }
    }
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
BUNDLED_DB_DIR = DATA_DIR / "bindings_db"

# v0.1.5: user-writable data lives under %APPDATA%/RB-Controller_fix/data/
# when running as a frozen PyInstaller exe; under the source tree's
# data/ when running from source. The bundled DB stays read-only at
# the frozen-bundle path (or the source tree's data/bindings_db/ in
# dev). Matches the same pattern used for profiles/ and the controller
# sync log (see rbcf.spec header comment for the architecture).
def _user_data_dir() -> Path:
    if getattr(sys, "frozen", False):
        appdata = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if appdata:
            return Path(appdata) / "RB-Controller_fix" / "data"
    return DATA_DIR

USER_DATA_DIR = _user_data_dir()
USER_DB_DIR = USER_DATA_DIR / "bindings_user"

# Arcade systems (controls.dat handles these)
ARCADE_SYSTEMS = {
    "mame", "fbneo", "hbmame", "neogeo", "neogeocd",
    "cps1", "cps2", "cps3", "naomi", "naomi2",
    "atomiswave", "model2", "model3", "raine", "fbalpha",
}


# ============================================================
# Normalisation (must match build_bindings_db's keys)
# ============================================================

def _normalise(s: str) -> str:
    s = Path(s).stem.lower()
    s = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", s)
    s = re.sub(r"[\s_\-:.,!&'+]+", " ", s).strip()
    return s


def _candidate_keys(rom_name: str) -> list[str]:
    """Multiple normalised keys to try, handling roman numerals etc."""
    base = _normalise(rom_name)
    out = [base]
    if " ii" in base:  out.append(base.replace(" ii", " 2"))
    if " 2" in base:   out.append(base.replace(" 2", " ii"))
    if " iii" in base: out.append(base.replace(" iii", " 3"))
    if " 3" in base:   out.append(base.replace(" 3", " iii"))
    return out


# ============================================================
# Per-tier lookups
# ============================================================

def _lookup_user(system_id: str, rom_name: str) -> dict | None:
    """Tier 1: user-confirmed bindings on this machine."""
    p = USER_DB_DIR / f"{system_id}.json"
    if not p.exists(): return None
    try:
        db = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    games = db.get("games") or {}
    for k in _candidate_keys(rom_name):
        if k in games:
            rec = games[k]
            return {
                "source":    "user",
                "system_id": system_id,
                "rom_name":  rom_name,
                "title":     rec.get("title", rom_name),
                "bindings":  rec.get("bindings") or [],
                "extra":     {"saved_at": rec.get("saved_at")},
            }
    return None


def _lookup_bundled(system_id: str, rom_name: str) -> dict | None:
    """Tier 2: bindings DB shipped with the installer."""
    p = BUNDLED_DB_DIR / f"{system_id}.json"
    if not p.exists(): return None
    try:
        db = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    games = db.get("games") or {}
    for k in _candidate_keys(rom_name):
        if k in games:
            rec = games[k]
            if not rec.get("bindings"):
                continue   # entry exists but extraction failed; try next
            return {
                "source":    "bundled",
                "system_id": system_id,
                "rom_name":  rom_name,
                "title":     rec.get("title", rom_name),
                "bindings":  rec.get("bindings") or [],
                "extra":     {
                    "section_found":  rec.get("section_found"),
                    "text_source":    rec.get("text_source"),
                    "pages_scanned":  rec.get("pages_scanned"),
                    "extracted_from": "manual_pdf",
                },
            }
    return None


def _lookup_arcade(system_id: str, rom_name: str) -> dict | None:
    """Tier 3: controls.dat for arcade systems."""
    if system_id not in ARCADE_SYSTEMS:
        return None
    try:
        from data_arcade_controls import lookup_arcade
    except ImportError:
        return None
    try:
        rec = lookup_arcade(rom_name)
    except Exception:
        return None
    if not rec:
        return None

    # data_arcade_controls returns a different schema (joystick + button
    # labels). Translate to the unified shape.
    bindings = []
    buttons = rec.get("buttons") or {}
    for retropad_idx, action in buttons.items():
        bindings.append({
            "button":     str(retropad_idx),     # e.g. "P1_BUTTON1"
            "action":     str(action),
            "confidence": "high",
            "raw":        f"{retropad_idx}: {action}",
            "matched_by": "controls.dat",
        })
    if not bindings:
        return None
    return {
        "source":    "arcade",
        "system_id": system_id,
        "rom_name":  rom_name,
        "title":     rec.get("title") or rom_name,
        "bindings":  bindings,
        "extra":     {"controls_dat_record": rec},
    }


def _lookup_online_via_research(system_id: str, rom_name: str) -> dict | None:
    """Tier 4: live online research (slow). Fetches a PDF via
    manual_research_online and runs extraction on it. NOT called from
    `lookup()` automatically — invoke `online_lookup()` explicitly."""
    try:
        from manual_research_online import research_manual
        from manual_extract import extract_bindings_from_pdf
    except ImportError:
        return None

    hit = research_manual(system_id, rom_name)
    if not hit or not hit.get("pdf_path"):
        return None

    try:
        # Online PDFs are usually clean native — pypdf path, no OCR
        # (OCR is build-time only on the dev box).
        result = extract_bindings_from_pdf(Path(hit["pdf_path"]), ocr=False)
    except Exception:
        return None

    if not result.get("bindings"):
        return None

    return {
        "source":    "online",
        "system_id": system_id,
        "rom_name":  rom_name,
        "title":     hit.get("title") or rom_name,
        "bindings":  result["bindings"],
        "extra":     {
            "site":          hit.get("site"),
            "page_url":      hit.get("page_url"),
            "pdf_path":      hit.get("pdf_path"),
            "section_found": result.get("section_found"),
            "text_source":   result.get("text_source"),
        },
    }


# ============================================================
# Top-level cascade
# ============================================================

def lookup(system_id: str, rom_name: str,
           include_online: bool = False) -> dict | None:
    """Try each tier in priority order. Returns the first hit.

    `include_online=False` (default): never makes a network call. Safe
    for auto-load on profile open; latency = filesystem reads.

    `include_online=True`: also tries Vimm via Flaresolverr if all
    local tiers miss. Slow (multi-second). Use only on explicit user
    request like a "Search online" button."""
    for fn in (_lookup_user, _lookup_bundled, _lookup_arcade):
        result = fn(system_id, rom_name)
        if result:
            return result
    if include_online:
        return _lookup_online_via_research(system_id, rom_name)
    return None


def online_lookup(system_id: str, rom_name: str) -> dict | None:
    """Force the slow online tier — use behind an explicit GUI button."""
    return _lookup_online_via_research(system_id, rom_name)


# ============================================================
# User contribution — save / clear
# ============================================================

def save_user_bindings(system_id: str, rom_name: str,
                       bindings: list[dict],
                       title: str | None = None,
                       source_note: str | None = None) -> Path:
    """Persist user-confirmed/edited bindings to the per-machine user
    DB. The next call to lookup() for the same (system, rom) will
    return these instead of any bundled DB entry."""
    USER_DB_DIR.mkdir(parents=True, exist_ok=True)
    p = USER_DB_DIR / f"{system_id}.json"

    if p.exists():
        try:
            db = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            db = {}
    else:
        db = {}

    db.setdefault("system_id", system_id)
    db.setdefault("schema_version", 1)
    db.setdefault("games", {})

    key = _candidate_keys(rom_name)[0]
    db["games"][key] = {
        "title":       title or rom_name,
        "bindings":    bindings,
        "saved_at":    datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_note": source_note,
    }

    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(db, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(p)
    return p


def clear_user_bindings(system_id: str, rom_name: str) -> bool:
    """Forget user-customised bindings, reverting to the cascade.
    Returns True if an entry was removed."""
    p = USER_DB_DIR / f"{system_id}.json"
    if not p.exists(): return False
    try:
        db = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    games = db.get("games") or {}
    removed = False
    for k in _candidate_keys(rom_name):
        if k in games:
            del games[k]
            removed = True
    if removed:
        db["games"] = games
        p.write_text(json.dumps(db, indent=2, ensure_ascii=False),
                     encoding="utf-8")
    return removed


# ============================================================
# CLI (for testing the cascade outside the GUI)
# ============================================================

def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=False)
    L = sub.add_parser("lookup", help="Run the cascade (no online).")
    L.add_argument("system_id"); L.add_argument("rom")
    L.add_argument("--online", action="store_true",
                   help="Also try the online tier (slow).")
    sub.add_parser("status", help="Show which DBs exist on this install.")
    args = ap.parse_args()

    if args.cmd is None:
        ap.print_help(); return

    if args.cmd == "status":
        print(f"User DB dir:    {USER_DB_DIR}  exists={USER_DB_DIR.exists()}")
        if USER_DB_DIR.exists():
            for p in sorted(USER_DB_DIR.glob("*.json")):
                try:
                    db = json.loads(p.read_text(encoding="utf-8"))
                    print(f"  {p.name:<25} {len(db.get('games', {}))} games")
                except Exception:
                    print(f"  {p.name:<25} (unreadable)")
        print(f"Bundled DB dir: {BUNDLED_DB_DIR}  exists={BUNDLED_DB_DIR.exists()}")
        if BUNDLED_DB_DIR.exists():
            for p in sorted(BUNDLED_DB_DIR.glob("*.json")):
                try:
                    db = json.loads(p.read_text(encoding="utf-8"))
                    s = db.get("stats", {})
                    print(f"  {p.name:<25} {len(db.get('games', {}))} games, "
                          f"{s.get('with_bindings', 0)} with bindings")
                except Exception:
                    print(f"  {p.name:<25} (unreadable)")
        return

    if args.cmd == "lookup":
        result = lookup(args.system_id, args.rom, include_online=args.online)
        if not result:
            print(f"[miss] no bindings found for {args.system_id}/{args.rom}")
            import sys; sys.exit(2)
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
