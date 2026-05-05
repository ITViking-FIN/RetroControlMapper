"""
Retrobat ROM media + duplicate audit.

For each system under E:/RetroBat/roms/<system>/:
  - Lists ROMs (file extensions per system pulled from es_systems.cfg).
  - Cross-references gamelist.xml.
  - Flags ROMs that have NO scraped media (no <image>/<video>/<marquee>/<thumbnail>/<fanart>).
  - Flags duplicates by normalized name.

Output: a markdown report.
"""
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

from config import ROMS_ROOT, ES_SYSTEMS_CFG as ES_SYSTEMS
import xml_safe

# Audit finding LOW: hardcoded "D:/RB-Controller_fix/" path. Replace with
# Path(__file__).parent so the report lands next to the script regardless
# of where the project tree lives.
REPORT = Path(__file__).resolve().parent / "scrape_audit_report.md"

RESERVED_DIRS = {"images", "videos", "manuals", "marquees", "maps",
                 "screenshots", "media", "boxart", "wheels", "mixrbv",
                 "mixrbv1", "mixrbv2", "support", "downloaded_media"}

MEDIA_TAGS = ("image", "video", "marquee", "thumbnail", "fanart",
              "boxart", "boxback", "titleshot", "wheel", "mix", "cartridge",
              "screenshot", "manual", "map", "bezel")


def load_system_extensions():
    """Return {system_name: set(extensions_lowercase_with_dot)}."""
    if not ES_SYSTEMS.exists():
        return {}
    out = {}
    try:
        tree = xml_safe.safe_parse(ES_SYSTEMS)
    except ET.ParseError as e:
        print(f"[warn] could not parse es_systems.cfg: {e}", file=sys.stderr)
        return out
    except xml_safe.XMLSecurityError as e:
        print(f"[warn] {e}", file=sys.stderr)
        return out
    for sys_node in tree.getroot().findall("system"):
        name = (sys_node.findtext("name") or "").strip()
        ext_raw = (sys_node.findtext("extension") or "").strip()
        if not name or not ext_raw:
            continue
        exts = set()
        for tok in ext_raw.split():
            tok = tok.strip().lower()
            if tok and tok.startswith("."):
                exts.add(tok)
        out[name] = exts
    return out


def normalize_name(stem: str) -> str:
    """Strip parenthetical tags, brackets, trailing variant markers, lowercase."""
    s = stem.lower()
    # Strip () and [] groups (region codes, dump tags, version markers)
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"\[[^\]]*\]", "", s)
    # Strip trailing "side X", "disk X", "tape X", "part X", "vol X", "rev X"
    s = re.sub(r"[\s\-_]*(side|disk|disc|tape|part|vol|volume|rev|v)[\s_\-]*\d+\s*$", "", s)
    # Normalize separators and punctuation
    s = re.sub(r"[\s\-_:.,!&'+]+", " ", s)
    s = s.strip()
    return s


def parse_gamelist(path: Path):
    """Return {rom_basename_lowercase: media_count}.

    media_count = number of populated media tags pointing at existing files.
    Missing entries → ROM not in gamelist.
    """
    if not path.exists():
        return {}
    try:
        root = xml_safe.safe_parse(path).getroot()
    except ET.ParseError as e:
        print(f"[warn] gamelist parse error in {path}: {e}", file=sys.stderr)
        return {}
    except xml_safe.XMLSecurityError as e:
        print(f"[warn] {e}", file=sys.stderr)
        return {}
    out = {}
    base = path.parent
    for game in root.findall("game"):
        rel = (game.findtext("path") or "").strip()
        if not rel:
            continue
        # rel typically "./Foo.crt"
        rel_clean = rel.lstrip("./").lstrip("\\")
        rom_key = rel_clean.lower().replace("\\", "/")
        media_count = 0
        for tag in MEDIA_TAGS:
            v = game.findtext(tag)
            if not v:
                continue
            v_clean = v.strip().lstrip("./").lstrip("\\")
            full = base / v_clean.replace("/", os.sep)
            if full.exists():
                media_count += 1
        out[rom_key] = media_count
    return out


def collect_roms(system_dir: Path, exts: set[str]):
    """Return list of (rom_key_lowercase_relative_path, display_name, is_dir)."""
    roms = []
    for entry in system_dir.iterdir():
        nm = entry.name
        if entry.is_dir():
            if nm.lower() in RESERVED_DIRS:
                continue
            # Folder-as-ROM: e.g. windows .pc folders, DOS games
            if "." in nm and nm.split(".")[-1].lower() in {"pc", "neogeo", "exe"}:
                roms.append((nm.lower(), nm, True))
            # else: skip generic subfolder
            continue
        if nm.startswith("."):
            continue
        ext = entry.suffix.lower()
        if not exts:
            # Unknown system extension list — fall through with broad heuristic
            if ext in {".xml", ".txt", ".cfg", ".jpg", ".png", ".db", ".dat",
                       ".bak", ".log", ".ini", ".lst"}:
                continue
            roms.append((nm.lower(), nm, False))
            continue
        if ext in exts:
            roms.append((nm.lower(), nm, False))
    return roms


def audit():
    sys_exts = load_system_extensions()
    if not ROMS_ROOT.exists():
        print(f"[fatal] ROMs root not found: {ROMS_ROOT}", file=sys.stderr)
        sys.exit(1)

    per_system = []
    grand_total = 0
    grand_missing = 0
    grand_dups = 0

    for system_dir in sorted(ROMS_ROOT.iterdir()):
        if not system_dir.is_dir():
            continue
        sys_name = system_dir.name
        exts = sys_exts.get(sys_name, set())
        roms = collect_roms(system_dir, exts)
        if not roms:
            continue
        gamelist = parse_gamelist(system_dir / "gamelist.xml")

        unmediated = []  # (display, status)
        for key, display, is_dir in roms:
            if key in gamelist:
                if gamelist[key] == 0:
                    unmediated.append((display, "scraped, no media"))
            else:
                unmediated.append((display, "not in gamelist"))

        # Duplicate detection by normalized name (excluding the extension)
        groups = defaultdict(list)
        for _, display, _ in roms:
            stem = Path(display).stem
            norm = normalize_name(stem)
            if norm:
                groups[norm].append(display)
        dups = {k: v for k, v in groups.items() if len(v) > 1}

        grand_total += len(roms)
        grand_missing += len(unmediated)
        grand_dups += sum(len(v) for v in dups.values())

        per_system.append({
            "system": sys_name,
            "total": len(roms),
            "unmediated": unmediated,
            "dups": dups,
        })

    write_report(per_system, grand_total, grand_missing, grand_dups)


def write_report(per_system, total, missing, dups):
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    lines.append("# Retrobat ROM audit\n")
    lines.append(f"- Total ROMs scanned: **{total}**")
    lines.append(f"- ROMs without media (no image/video/etc.): **{missing}**")
    lines.append(f"- ROMs caught in duplicate groups: **{dups}**\n")

    # Summary table
    lines.append("## Per-system summary\n")
    lines.append("| System | Total | No media | In dup groups |")
    lines.append("|---|---:|---:|---:|")
    for s in per_system:
        dup_count = sum(len(v) for v in s["dups"].values())
        lines.append(f"| {s['system']} | {s['total']} | {len(s['unmediated'])} | {dup_count} |")
    lines.append("")

    # Detailed unmediated lists
    lines.append("## ROMs without media (per system)\n")
    for s in per_system:
        if not s["unmediated"]:
            continue
        lines.append(f"### {s['system']} — {len(s['unmediated'])} ROM(s)\n")
        for display, status in sorted(s["unmediated"]):
            lines.append(f"- `{display}`  *({status})*")
        lines.append("")

    # Duplicate groups
    lines.append("## Duplicate groups (per system)\n")
    any_dups = False
    for s in per_system:
        if not s["dups"]:
            continue
        any_dups = True
        lines.append(f"### {s['system']}\n")
        for norm, items in sorted(s["dups"].items()):
            lines.append(f"**{norm}** — {len(items)} files")
            for it in sorted(items):
                lines.append(f"  - `{it}`")
            lines.append("")
    if not any_dups:
        lines.append("_No duplicates detected._\n")

    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written: {REPORT}")
    print(f"Summary: {total} ROMs, {missing} unmediated, {dups} caught in dup groups.")


if __name__ == "__main__":
    audit()
