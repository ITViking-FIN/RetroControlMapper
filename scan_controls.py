"""
Scan all gamelist.xml files under E:/RetroBat/roms/<system>/ for controls-
related fields contributed by ScreenScraper or other scrapers.

ScreenScraper exposes a 'controles' field per game in its API. RetroBat may
or may not be persisting it locally — this script tells us how much we
already have.
"""
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

ROMS_ROOT = Path(r"E:/RetroBat/roms")
CONTROL_TAGS = ("controls", "control", "controles", "controle",
                "buttons", "controlscheme", "input", "inputs",
                "controller", "scheme", "controlsdat")

per_system = defaultdict(lambda: {"games": 0, "with_controls": 0, "samples": []})
all_tags_seen = set()


def scan_gamelist(path):
    sys_name = path.parent.name
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        print(f"[warn] {path}: parse error {e}", file=sys.stderr)
        return
    for g in root.findall("game"):
        per_system[sys_name]["games"] += 1
        # Catalogue every child tag we see
        for child in g:
            all_tags_seen.add(child.tag.lower())
        # Look for any control-related field
        for tag in CONTROL_TAGS:
            v = g.findtext(tag)
            if v and v.strip():
                per_system[sys_name]["with_controls"] += 1
                if len(per_system[sys_name]["samples"]) < 3:
                    name = g.findtext("name") or g.findtext("path") or "?"
                    per_system[sys_name]["samples"].append((tag, name, v.strip()[:200]))
                break


def main():
    if not ROMS_ROOT.exists():
        print(f"[fatal] {ROMS_ROOT} not found", file=sys.stderr)
        sys.exit(1)

    gamelists = sorted(ROMS_ROOT.glob("*/gamelist.xml"))
    print(f"Scanning {len(gamelists)} gamelist.xml files...\n")

    for gl in gamelists:
        scan_gamelist(gl)

    # Summary
    print(f"{'System':<20} {'Games':>6} {'With controls':>15}")
    print("-" * 50)
    grand_games = 0
    grand_controls = 0
    for sys_name in sorted(per_system):
        s = per_system[sys_name]
        if s["with_controls"] == 0:
            continue
        print(f"{sys_name:<20} {s['games']:>6} {s['with_controls']:>15}")
        grand_games += s["games"]
        grand_controls += s["with_controls"]

    print("-" * 50)
    print(f"{'TOTAL':<20} {grand_games:>6} {grand_controls:>15}")
    print()

    # Show some samples
    print("Sample entries with controls data:\n")
    sample_count = 0
    for sys_name in sorted(per_system):
        s = per_system[sys_name]
        if not s["samples"]:
            continue
        print(f"--- {sys_name} ---")
        for tag, name, val in s["samples"]:
            print(f"  [{tag}] {name}")
            print(f"    {val}")
        sample_count += len(s["samples"])
        if sample_count >= 12:
            break
    print()

    # All tags seen — helps spot anything we missed
    print("All distinct child tags across <game> entries:")
    tags = sorted(all_tags_seen)
    for i in range(0, len(tags), 6):
        print("  " + ", ".join(tags[i:i+6]))


if __name__ == "__main__":
    main()
