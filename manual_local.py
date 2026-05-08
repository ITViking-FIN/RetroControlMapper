"""
Local game-manual archive — indexer, lookup, on-demand extraction.

Wraps the user's `Manual_Package.7z` (a ~29 GB archive of 10,917 manuals
across 63 retro systems, organised as `data/<System Name>/<title>.pdf`).
We never fully extract — that would consume ~32 GB of disk. Instead:

  1. **Index pass** (cheap): parse the archive's listing into a JSON
     keyed by (RetroBat system id, normalised ROM name) → archive path.
  2. **On-demand extract** (per-game): when the GUI looks up a ROM and
     finds a hit, we call 7z.exe to extract that single PDF into a
     local cache `data/manuals/<system>/<rom>.pdf`.
  3. **PDF text extraction** (Stage 2 — see TODO at end of this file)
     turns the cached PDF into plain text we can scan for control
     descriptions ("Press X to jump", "L1 = punch", etc.).

This module covers steps 1 and 2. Step 3 (text mining) and the online
manual fetcher live elsewhere — see `manual_research_online.py`.

## Pointing at the archive

The archive's location is *not* hardcoded. Resolved in this order:

  1. `--archive PATH` CLI flag
  2. `RBCF_MANUAL_ARCHIVE` env var
  3. `data/manual_archive_path.txt` (one absolute path; gitignored)

Run `py manual_local.py config` to see what's currently resolved.

## Usage

    py manual_local.py config
    py manual_local.py --archive E:/path/to/Manual_Package.7z reindex
    py manual_local.py reindex --from-raw-only       # if you already have the dump
    py manual_local.py lookup snes "Super Mario World"
    py manual_local.py extract snes "Super Mario World"

## Programmatic

    from manual_local import (
        ensure_index, lookup_local_manual, extract_local_manual,
        resolve_archive_path,
    )
    hit = lookup_local_manual("snes", "Super Mario World")
    if hit:
        pdf_path = extract_local_manual(hit)
        # → data/manuals/snes/super_mario_world.pdf
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    from config import RBCFRC_PATH  # type: ignore
except Exception:
    RBCFRC_PATH = None  # graceful fallback if config import fails

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
INDEX_RAW = DATA_DIR / "manual_archive_index.raw.txt"
INDEX_JSON = DATA_DIR / "manual_archive_index.json"
CACHE_DIR = DATA_DIR / "manuals"

# Where to find the user's manual archive. NOT hardcoded — every user
# stores it in a different place. Resolved in this order:
#
#   1. `--archive PATH` CLI arg
#   2. `RBCF_MANUAL_ARCHIVE` environment variable
#   3. `data/manual_archive_path.txt` (one line, absolute path; gitignored)
#   4. give up with an error pointing at the above
ARCHIVE_PATH_CONFIG = DATA_DIR / "manual_archive_path.txt"
ARCHIVE_ENV_VAR = "RBCF_MANUAL_ARCHIVE"
SEVEN_ZIP_EXE = Path(r"C:/Program Files/7-Zip/7z.exe")


def resolve_archive_path(cli_override: str | None = None) -> Path | None:
    """Locate the Manual_Package.7z archive without baking a path into source.
    Returns None if no configured location exists; callers should print a
    helpful message in that case."""
    if cli_override:
        return Path(cli_override).expanduser()
    env_val = os.environ.get(ARCHIVE_ENV_VAR)
    if env_val:
        return Path(env_val).expanduser()
    if ARCHIVE_PATH_CONFIG.exists():
        try:
            line = ARCHIVE_PATH_CONFIG.read_text(encoding="utf-8").strip()
            if line and not line.startswith("#"):
                return Path(line).expanduser()
        except OSError:
            pass
    return None

# The archive uses verbose system folder names like "Nintendo SNES".
# RetroBat uses short ids like "snes". Map between them so a GUI lookup
# by system-id resolves to the right archive folder.
ARCHIVE_TO_RETROBAT = {
    "Acorn Atom":                 "atom",
    "Amstrad CPC":                "amstradcpc",
    "Amstrad GX4000":             "gx4000",
    "Apple II":                   "apple2",
    "Arcade":                     "mame",       # also matches fbneo/hbmame at lookup time
    "Atari 2600":                 "atari2600",
    "Atari 5200":                 "atari5200",
    "Atari 7800":                 "atari7800",
    "Atari 8-bit":                "atari800",
    "Atari Jaguar":               "jaguar",
    "Atari Jaguar CD":            "jaguarcd",
    "Atari Lynx":                 "lynx",
    "Atari ST":                   "atarist",
    "Bally Astrocade":            "astrocade",
    "Coleco Vision":              "colecovision",
    "Commodore 64":               "c64",
    "Commodore Amiga":            "amiga500",   # also amiga1200 at lookup time
    "Commodore Amiga CD32":       "amigacd32",
    "Commodore VIC-20":           "c20",        # RetroBat id is c20 not vic20
    "Dragon 32-64":               "dragon32",
    "Emerson Arcadia 2001":       "arcadia",
    "Entex Adventure Vision":     "advision",
    "Fairchild Channel F":        "channelf",
    "GCE Vectrex":                "vectrex",
    "Laserdisc":                  "daphne",
    "MSX Laserdisc":              "msx1",       # closest fit
    "Magnavox Odyssey 2":         "odyssey2",
    "Mattel Intellivision":       "intellivision",
    "Microsoft Xbox":             "xbox",
    "Microsoft Xbox 360":         "xbox360",
    "NEC PC Engine":              "pcengine",
    "NEC TurboGrafx CD":          "tg16cd",
    "NEC TurboGrafx-16":          "tg16",
    "Nintendo Arcade Systems":    "nes3d",      # rough match
    "Nintendo DS":                "nds",
    "Nintendo Game Boy":          "gb",
    "Nintendo Game Boy Color":    "gbc",
    "Nintendo GameCube":          "gamecube",
    "Nintendo N64":               "n64",
    "Nintendo NES":               "nes",
    "Nintendo SNES":              "snes",
    "Nintendo Switch":            "switch",
    "Nintendo Virtual Boy":       "virtualboy",
    "Panasonic 3DO":              "3do",
    "Philips CD-i":               "cdi",
    "SNK Neo-Geo MVS":            "neogeo",
    "SNK Neo-Geo Pocket":         "ngp",
    "SNK Neo-Geo Pocket Color":   "ngpc",
    "Sega 32X":                   "sega32x",
    "Sega CD":                    "segacd",
    "Sega Dreamcast":             "dreamcast",
    "Sega Game Gear":             "gamegear",
    "Sega Genesis":               "megadrive",  # also "genesis"; GUI accepts either
    "Sega Master System":         "mastersystem",
    "Sega Nomad":                 "megadrive",  # Nomad ran Genesis carts
    "Sega SG-1000":               "sg1000",
    "Sega Saturn":                "saturn",
    "Sinclair ZX Spectrum":       "zxspectrum",
    "Sony PSP":                   "psp",
    "Sony Playstation":           "psx",
    "Sony Playstation 2":         "ps2",
    "Texas Instruments TI 99":    "ti99",
    "VTech CreatiVision":         "creatiVision",  # actual RetroBat id casing
}

# Inverse with multi-mapping support (one RetroBat id can match multiple
# archive folders, e.g. amiga500 + amiga1200 + amiga4000 all share
# "Commodore Amiga"). Built lazily.
_RETROBAT_TO_ARCHIVE: dict[str, list[str]] | None = None


def retrobat_to_archive(rb_id: str) -> list[str]:
    global _RETROBAT_TO_ARCHIVE
    if _RETROBAT_TO_ARCHIVE is None:
        m: dict[str, list[str]] = {}
        for arc, rb in ARCHIVE_TO_RETROBAT.items():
            m.setdefault(rb, []).append(arc)
        # Manual extras — same archive folder serves multiple RetroBat ids
        for extra_rb in ("amiga1200", "amiga4000"):
            m.setdefault(extra_rb, []).extend(["Commodore Amiga"])
        m.setdefault("genesis", []).append("Sega Genesis")
        m.setdefault("fbneo", []).append("Arcade")
        m.setdefault("hbmame", []).append("Arcade")
        m.setdefault("cps1", []).append("Arcade")
        m.setdefault("cps2", []).append("Arcade")
        m.setdefault("cps3", []).append("Arcade")
        m.setdefault("neogeo", []).append("Arcade")
        _RETROBAT_TO_ARCHIVE = m
    return _RETROBAT_TO_ARCHIVE.get(rb_id, [])


# ============================================================
# Indexing
# ============================================================

def normalise_title(s: str) -> str:
    """Aggressive normalisation so 'Street Fighter II (USA)' and
    'StreetFighterII' and 'street_fighter_ii.zip' all collide."""
    s = Path(s).stem.lower()
    s = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", s)   # strip () [] tags
    s = re.sub(r"[\s_\-:.,!&'+]+", " ", s)            # collapse separators
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_raw_index(raw_path: Path = INDEX_RAW) -> dict:
    """Read the verbose 7z listing dump and produce
    {system_id: {normalised_title: {archive_path, archive_system, file_size}}}.
    Multiple RetroBat ids may receive the same archive path (e.g. amiga500
    and amiga1200 both pointing at "Commodore Amiga").
    """
    if not raw_path.exists():
        raise FileNotFoundError(
            f"raw index not found: {raw_path}. Generate it first with:\n"
            f"  \"{SEVEN_ZIP_EXE}\" l <archive> -slt > {raw_path}"
        )

    out: dict = {}
    cur: dict = {}
    with raw_path.open("r", encoding="cp1252", errors="replace") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line:
                _process_entry(cur, out)
                cur = {}
                continue
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            cur[k.strip()] = v.strip()
    _process_entry(cur, out)
    return out


def _process_entry(entry: dict, out: dict):
    if not entry: return
    path = entry.get("Path") or ""
    attr = entry.get("Attributes") or ""
    if not path.startswith("data\\"):
        return
    if "D" in attr:   # directory
        return
    if not path.lower().endswith(".pdf"):
        return
    parts = path.split("\\")
    if len(parts) < 3: return
    arc_system = parts[1]
    title_file = parts[-1]   # may be nested deeper
    norm = normalise_title(title_file)
    if not norm: return
    rb_ids = [ARCHIVE_TO_RETROBAT.get(arc_system)]
    # Manual extras for shared folders
    if arc_system == "Commodore Amiga":
        rb_ids = ["amiga500", "amiga1200", "amiga4000"]
    elif arc_system == "Sega Genesis" or arc_system == "Sega Nomad":
        rb_ids = ["megadrive", "genesis"]
    elif arc_system == "Arcade":
        rb_ids = ["mame", "fbneo", "hbmame", "neogeo",
                  "cps1", "cps2", "cps3"]
    rb_ids = [r for r in rb_ids if r]
    if not rb_ids: return

    record = {
        "archive_path": path,
        "archive_system": arc_system,
        "filename": title_file,
        "size": int(entry.get("Size") or 0),
    }
    for rb in rb_ids:
        out.setdefault(rb, {})[norm] = record


def build_index(raw_path: Path = INDEX_RAW,
                json_path: Path = INDEX_JSON) -> dict:
    """Parse the raw 7z listing and write a structured JSON index."""
    idx = parse_raw_index(raw_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(idx, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    counts = {sys: len(games) for sys, games in idx.items()}
    print(f"Wrote {json_path}")
    print(f"  systems indexed:  {len(idx)}")
    print(f"  total entries:    {sum(counts.values())}")
    print("  top by count:")
    for s, n in sorted(counts.items(), key=lambda x: -x[1])[:8]:
        print(f"    {s:<24} {n:>5}")
    return idx


def ensure_index() -> dict:
    """Load (and build if missing) the manual archive index."""
    if INDEX_JSON.exists():
        try:
            return json.loads(INDEX_JSON.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    if INDEX_RAW.exists():
        return build_index()
    return {}


# ============================================================
# Lookup
# ============================================================

def lookup_local_manual(system_id: str, rom_name: str,
                        index: dict | None = None) -> dict | None:
    """Find a manual for (system, ROM) in the local archive index.
    Returns {archive_path, archive_system, filename, size} or None.

    Tries multiple normalisations of the ROM name to handle different
    naming conventions (USA/Europe tags, underscores, etc.)."""
    if index is None:
        index = ensure_index()
    games = index.get(system_id) or {}
    if not games:
        return None
    candidates = _candidate_keys(rom_name)
    for c in candidates:
        if c in games:
            return games[c]
    # Fuzzy fallback: substring match on the longest-prefix candidate
    base = candidates[0] if candidates else ""
    if len(base) >= 4:
        for k in games:
            if k.startswith(base) or base.startswith(k):
                return games[k]
    return None


def _candidate_keys(rom_name: str) -> list[str]:
    base = normalise_title(rom_name)
    out = [base]
    # Try replacing common roman numeral / number variants
    if " ii" in base:  out.append(base.replace(" ii", " 2"))
    if " 2" in base:   out.append(base.replace(" 2", " ii"))
    if " iii" in base: out.append(base.replace(" iii", " 3"))
    if " 3" in base:   out.append(base.replace(" 3", " iii"))
    return out


# ============================================================
# On-demand extraction
# ============================================================

def extract_local_manual(hit: dict, dest_dir: Path = CACHE_DIR,
                         archive: Path | None = None) -> Path | None:
    """Extract a single PDF from the archive into the cache.
    `hit` is the dict returned by lookup_local_manual().
    `archive` overrides the resolved archive path (CLI/env/config).
    Returns the path of the extracted PDF, or None on failure."""
    if not SEVEN_ZIP_EXE.exists():
        print(f"[fatal] 7z.exe not found: {SEVEN_ZIP_EXE}", file=sys.stderr)
        return None
    if archive is None:
        archive = resolve_archive_path()
    if archive is None or not archive.exists():
        print(
            f"[fatal] manual archive not found.\n"
            f"  Set the {ARCHIVE_ENV_VAR} env var, write the path into\n"
            f"  {ARCHIVE_PATH_CONFIG}, or pass --archive PATH on the CLI.",
            file=sys.stderr)
        return None

    archive_path = hit.get("archive_path")
    if not archive_path:
        return None
    rb_systems = retrobat_to_archive_inverse(hit.get("archive_system"))
    rb_system = rb_systems[0] if rb_systems else "unknown"
    safe_name = re.sub(r"[^A-Za-z0-9._\-]+", "_",
                       Path(hit["filename"]).stem)[:120]
    out_dir = dest_dir / rb_system
    out_dir.mkdir(parents=True, exist_ok=True)
    out_pdf = out_dir / f"{safe_name}.pdf"
    if out_pdf.exists() and out_pdf.stat().st_size > 0:
        return out_pdf

    # 7z extracts with original folder structure unless `e` (extract,
    # flat). We use `x -o<dest>` and then move the output file.
    tmp_dir = dest_dir / "_extract_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(SEVEN_ZIP_EXE), "x", str(archive),
           f"-o{tmp_dir}", "-y", archive_path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=120)
    except subprocess.TimeoutExpired:
        print(f"[error] 7z extract timed out", file=sys.stderr)
        return None
    if result.returncode != 0:
        print(f"[error] 7z exit {result.returncode}: {result.stderr[:300]}",
              file=sys.stderr)
        return None
    extracted = tmp_dir / archive_path
    if not extracted.exists():
        print(f"[error] extracted file not found at {extracted}",
              file=sys.stderr)
        return None
    extracted.replace(out_pdf)
    # Clean up the now-empty tmp tree
    try:
        for p in sorted(tmp_dir.rglob("*"), reverse=True):
            if p.is_dir(): p.rmdir()
    except OSError: pass
    return out_pdf


def retrobat_to_archive_inverse(arc_system: str | None) -> list[str]:
    """Given an archive folder name, return the RetroBat ids that consume it."""
    if not arc_system: return []
    out = []
    for arc, rb in ARCHIVE_TO_RETROBAT.items():
        if arc == arc_system: out.append(rb)
    return out


# ============================================================
# Entry point
# ============================================================

def _gen_raw_listing(archive: Path) -> bool:
    """Run `7z l <archive> -slt` and capture stdout to INDEX_RAW. Slow
    (multi-minute on a 29 GB archive) but only needed once per archive
    revision."""
    if not SEVEN_ZIP_EXE.exists():
        print(f"[fatal] 7z.exe not found: {SEVEN_ZIP_EXE}", file=sys.stderr)
        return False
    if not archive.exists():
        print(f"[fatal] archive missing: {archive}", file=sys.stderr)
        return False
    INDEX_RAW.parent.mkdir(parents=True, exist_ok=True)
    print(f"Running: 7z l {archive} -slt   (this may take a few minutes)")
    with INDEX_RAW.open("wb") as f:
        result = subprocess.run(
            [str(SEVEN_ZIP_EXE), "l", str(archive), "-slt"],
            stdout=f, stderr=subprocess.PIPE)
    if result.returncode != 0:
        print(f"[error] 7z exit {result.returncode}: "
              f"{result.stderr.decode('cp1252', 'replace')[:300]}",
              file=sys.stderr)
        return False
    print(f"  wrote {INDEX_RAW} ({INDEX_RAW.stat().st_size:,} bytes)")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archive", help="Override Manual_Package.7z path "
                    f"(else reads {ARCHIVE_ENV_VAR} env var or "
                    f"{ARCHIVE_PATH_CONFIG.name}).")
    sub = ap.add_subparsers(dest="cmd", required=False)
    R = sub.add_parser("reindex", help="Re-list the archive and rebuild the JSON index.")
    R.add_argument("--from-raw-only", action="store_true",
                   help="Skip the 7z listing step; reuse the existing raw dump.")
    L = sub.add_parser("lookup", help="Find a manual in the local index.")
    L.add_argument("system_id")
    L.add_argument("rom")
    X = sub.add_parser("extract", help="Extract one manual from the archive into the local cache.")
    X.add_argument("system_id")
    X.add_argument("rom")
    sub.add_parser("stats", help="Print index statistics.")
    sub.add_parser("config", help="Show resolved archive path and config sources.")
    args = ap.parse_args()

    if args.cmd is None:
        ap.print_help(); return

    if args.cmd == "config":
        archive = resolve_archive_path(getattr(args, "archive", None))
        print(f"Archive path:    {archive or '(unresolved)'}")
        print(f"  exists:        {archive.exists() if archive else False}")
        print(f"  env var:       {ARCHIVE_ENV_VAR}={os.environ.get(ARCHIVE_ENV_VAR, '(unset)')}")
        print(f"  config file:   {ARCHIVE_PATH_CONFIG}")
        print(f"    exists:      {ARCHIVE_PATH_CONFIG.exists()}")
        print(f"  7z.exe:        {SEVEN_ZIP_EXE} (exists={SEVEN_ZIP_EXE.exists()})")
        print(f"  index:         {INDEX_JSON} (exists={INDEX_JSON.exists()})")
        return

    if args.cmd == "reindex":
        archive = resolve_archive_path(args.archive)
        if not args.from_raw_only:
            if archive is None:
                print(
                    f"[fatal] manual archive not found.\n"
                    f"  Set {ARCHIVE_ENV_VAR}, write a path into "
                    f"{ARCHIVE_PATH_CONFIG.name}, or pass --archive PATH.",
                    file=sys.stderr)
                sys.exit(1)
            if not _gen_raw_listing(archive):
                sys.exit(1)
        build_index()
        return
    if args.cmd == "lookup":
        idx = ensure_index()
        hit = lookup_local_manual(args.system_id, args.rom, index=idx)
        if hit:
            print(json.dumps(hit, indent=2))
        else:
            print(f"[miss] no local manual for {args.system_id}/{args.rom}")
            sys.exit(2)
        return
    if args.cmd == "extract":
        idx = ensure_index()
        hit = lookup_local_manual(args.system_id, args.rom, index=idx)
        if not hit:
            print(f"[miss] no local manual for {args.system_id}/{args.rom}")
            sys.exit(2)
        archive = resolve_archive_path(args.archive)
        out = extract_local_manual(hit, archive=archive)
        if out:
            print(f"Extracted: {out}")
        else:
            print("[error] extract failed"); sys.exit(1)
        return
    if args.cmd == "stats":
        idx = ensure_index()
        if not idx:
            print("(no index — run `reindex` first)")
            sys.exit(2)
        total = sum(len(g) for g in idx.values())
        print(f"Systems: {len(idx)}   Total entries: {total}")
        for s, games in sorted(idx.items(), key=lambda x: -len(x[1]))[:15]:
            print(f"  {s:<20} {len(games):>5}")
        return


if __name__ == "__main__":
    main()
