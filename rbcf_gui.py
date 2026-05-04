"""
RB-Controller_fix GUI — local web app.

Usage:
    py rbcf_gui.py [--port 8765] [--no-open]

Endpoints:
    GET  /                              index.html
    GET  /static-files (any)            served from gui/
    GET  /api/systems                   list of supported systems
    GET  /api/games?system=X            list of ROMs in roms/<system>/
    GET  /api/profile?system&rom        existing profile YAML (or {})
    GET  /api/retrobat-root             RetroBat install probe result (onboarding)
    GET  /api/scan                      per-system rom/profile counts (onboarding).
                                        Includes top-level `bezels_with_cutoffs`
                                        count (number of <system>.png bezels whose
                                        alpha-235 auto-detect would cut off the
                                        play area, vs the strict alpha-32 detect).
    GET  /api/scaffold-all[?apply]      preview/write T-confidence scaffolds
    GET  /api/scaffold-defaults[?apply] preview/write _default.yaml scaffolds
    GET  /api/bezel-cutoffs[?apply]     preview/write bezel <system>.info sidecars
                                        for bezels with alpha-235 cutoff.
    POST /api/save                      write a profile YAML
    POST /api/apply                     invoke rbcf.py apply as subprocess
    GET  /api/backup/list               two-tier snapshot inventory + factory
                                        existence flag (DECISIONS.md #5).
    POST /api/backup/factory            capture the one-shot factory snapshot.
    POST /api/backup/snapshot           capture a working (tier-2) snapshot;
                                        body: {description}.
    POST /api/backup/restore            preview by default; body {id, apply}
                                        — apply:true actually writes back.
"""
from __future__ import annotations

import argparse
import http.server
import json
import re
import socketserver
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import yaml

from config import (
    RETROBAT_ROOT, ROMS_ROOT, ES_SYSTEMS_CFG, BEZELS_DIR, RBCFRC_PATH,
    write_rbcfrc, clear_rbcfrc, _probed_locations_summary,
)
from rbcf import load_profiles

ROOT = Path(__file__).resolve().parent
GUI_DIR = ROOT / "gui"
PROFILES_DIR = ROOT / "profiles"
RBCF_PY = ROOT / "rbcf.py"
SYNC_PY = ROOT / "controller_sync.py"
CATALOG_YAML = ROOT / "controller_catalog.yaml"
SYNC_MANIFEST = ROOT / "sync_manifest.json"
KNOWN_IMG_DIR = GUI_DIR / "img" / "known"

# Each system declares which "target controller" we render on the right side.
# Adding a new system here is the main extension point.
SYSTEMS = [
    {"id": "c64",       "name": "Commodore 64",   "target_controller": "joystick_1btn",
     "fixed_mapping_note": "VICE: D-pad/stick → joy direction · B → fire · A → fire2 · X → SPACE"},
    {"id": "amiga500",  "name": "Amiga 500",      "target_controller": "joystick_1btn",
     "fixed_mapping_note": "puae default RetroPad mode: D-pad/stick → joy · B → fire"},
    {"id": "amiga1200", "name": "Amiga 1200",     "target_controller": "joystick_1btn",
     "fixed_mapping_note": "puae default RetroPad mode: D-pad/stick → joy · B → fire"},
    {"id": "amigacd32", "name": "Amiga CD32",     "target_controller": "cd32_pad",
     "fixed_mapping_note": "CD32 Pad (device 517): B=Red · A=Blue · Y=Yellow · X=Green · L=Forward · R=Rewind · Start=Play · Select=Reverse"},
]

# Some per-system options surfaced in the UI. Keys must match what RetroBat's
# Configurevice() / ConfigurePuae() bind from SystemConfig.
SYSTEM_OPTIONS = {
    "c64": [
        {"key": "GameFocus",   "label": "Game Focus (capture keyboard)", "type": "bool"},
        {"key": "c64_model",   "label": "C64 model",       "type": "select",
         "choices": ["C64 PAL auto", "C64 NTSC auto", "C64C PAL auto", "C64C NTSC auto", "C64 PAL", "C64 NTSC"]},
        {"key": "vice_joyport","label": "Joystick port",   "type": "select", "choices": ["2", "1"]},
        {"key": "vice_retropad_options", "label": "Pad button layout", "type": "select",
         "choices": ["disabled", "jump", "rotate", "rotate_jump"]},
    ],
    "amiga500": [
        {"key": "GameFocus", "label": "Game Focus (capture keyboard)", "type": "bool"},
        {"key": "puae_controller1", "label": "Player 1 controller type", "type": "select",
         "choices": ["257 (RetroPad)", "517 (CD32 Pad)", "773 (Analog)", "260 (Phaser Lightgun)", "261 (Joystick)", "259 (Keyboard)"]},
    ],
    "amiga1200": [
        {"key": "GameFocus", "label": "Game Focus", "type": "bool"},
        {"key": "puae_controller1", "label": "Player 1 controller type", "type": "select",
         "choices": ["257 (RetroPad)", "517 (CD32 Pad)", "773 (Analog)", "260 (Phaser Lightgun)", "261 (Joystick)", "259 (Keyboard)"]},
    ],
    "amigacd32": [
        {"key": "GameFocus", "label": "Game Focus", "type": "bool"},
        {"key": "puae_controller1", "label": "Player 1 controller type", "type": "select",
         "choices": ["517 (CD32 Pad)", "257 (RetroPad)", "773 (Analog)", "261 (Joystick)"]},
    ],
}

# Map of system → libretro core's mapper-key prefix (for keystroke remapping).
CORE_MAPPER_PREFIX = {
    "c64": "vice_mapper_",
    "amiga500": "puae_mapper_",
    "amiga1200": "puae_mapper_",
    "amigacd32": "puae_mapper_",
}

# RetroPad button names that show in the UI ("a" → vice_mapper_a, etc.)
PAD_BUTTONS = ["a", "b", "x", "y", "l", "r", "l2", "r2", "l3", "r3",
               "select", "start", "up", "down", "left", "right"]

def load_catalog() -> dict:
    """Read controller_catalog.yaml and produce a VID:PID → metadata map.

    Image URLs prefer the local cache (gui/img/known/<vid>_<pid>.<ext>) when
    a synced copy exists; otherwise fall back to a Wikimedia thumbnail URL.
    """
    out = {}
    if not CATALOG_YAML.exists():
        return out
    try:
        data = yaml.safe_load(CATALOG_YAML.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return out
    for entry in data.get("controllers", []):
        vid = (entry.get("vid") or "").upper()
        pid = (entry.get("pid") or "").upper()
        if not vid or not pid:
            continue
        key = f"{vid}:{pid}"
        # Prefer locally-synced image
        local = None
        if KNOWN_IMG_DIR.exists():
            for ext in (".jpg", ".png", ".webp", ".svg"):
                p = KNOWN_IMG_DIR / f"{vid}_{pid}{ext}"
                if p.exists():
                    local = f"/img/known/{p.name}"
                    break
        out[key] = {
            "name": entry.get("name") or key,
            "image": local or "",
            "wiki_file": entry.get("wiki_file") or "",
        }
    return out


def load_sync_status() -> dict:
    if not SYNC_MANIFEST.exists():
        return {"last_sync": None, "entry_count": 0}
    try:
        m = json.loads(SYNC_MANIFEST.read_text(encoding="utf-8"))
        return {
            "last_sync": m.get("last_sync"),
            "entry_count": len(m.get("entries", {})),
        }
    except (OSError, json.JSONDecodeError):
        return {"last_sync": None, "entry_count": 0}


def run_sync_now(dry: bool = False) -> dict:
    if not SYNC_PY.exists():
        return {"ok": False, "error": "controller_sync.py not found"}
    args = [sys.executable, str(SYNC_PY)]
    if dry:
        args.append("--dry-run")
    try:
        result = subprocess.run(args, capture_output=True, text=True,
                                timeout=120, cwd=str(ROOT))
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "sync timed out (120s)"}


# Module-level cache of catalog data, refreshable via /api/sync.
KNOWN_CONTROLLERS = load_catalog()


def refresh_catalog():
    global KNOWN_CONTROLLERS
    KNOWN_CONTROLLERS = load_catalog()


# Negative friendly-name hints — exclude even strong matches
EXCLUDE_NAME_HINTS = (
    "mouse", "keyboard", "audio", "headset", "headphone", "microphone",
    "camera", "webcam", "scanner", "printer", "tablet", "touch screen",
    "touchpad", "fingerprint", "card reader", "smart card",
    # HID consumer / system collections — not gamepads even if attached
    # to a gamepad device parent
    "consumer control", "system control",
    # Logitech G HUB virtual devices
    "virtual keyboard", "virtual mouse",
)

# Strong positive hints in friendly_name. Windows tags real gamepads as
# "HID-compliant game controller" — that's the gold-standard signal.
GAMEPAD_NAME_HINTS = (
    "game controller", "gamepad", "joystick", "joypad",
    "wireless controller", "wired controller", "xbox",
    "playstation", "dualshock", "dualsense", "8bitdo",
    "switch pro", "thrustmaster", "logitech g", "fanatec",
    "wheel", "flight stick",
)


def probe_devices() -> list[dict]:
    """Enumerate connected gamepads via Windows PowerShell.

    Fast single-pass enumeration. Filters out non-gamepad HID devices via:
      - exclude list of obvious negatives (mouse / keyboard / audio / …)
      - positive list including "HID-compliant game controller" (Windows's
        own classification — strongest signal we have)
      - XInput marker (`&IG_`) — always a gamepad
      - VID:PID catalog match
    """
    if sys.platform != "win32":
        return []
    cmd = (
        "Get-PnpDevice -PresentOnly -Class HIDClass | "
        "Where-Object { $_.Status -eq 'OK' -and $_.InstanceId -match 'VID_[0-9A-Fa-f]{4}' } | "
        "Select-Object FriendlyName, InstanceId | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, text=True, timeout=8,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return [{"error": f"probe failed: {e}"}]
    out = (result.stdout or "").strip()
    if not out:
        return []
    try:
        items = json.loads(out)
    except json.JSONDecodeError:
        return []
    if isinstance(items, dict):
        items = [items]

    pat = re.compile(r"VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})")
    # First pass: gather all entries per VID:PID, picking the "best" one
    # (strongest positive reason) since each physical device shows up under
    # multiple HID interface entries (one per IG_NN / MI_NN / COL_NN).
    candidates: dict[str, dict] = {}
    for it in items:
        inst = (it.get("InstanceId") or "").strip()
        m = pat.search(inst)
        if not m:
            continue
        vid = m.group(1).upper()
        pid = m.group(2).upper()
        key = f"{vid}:{pid}"

        friendly = (it.get("FriendlyName") or "").strip()
        friendly_lc = friendly.lower()
        is_xinput = "&IG_" in inst.upper()

        # Determine if this entry is a gamepad signal
        if any(hint in friendly_lc for hint in EXCLUDE_NAME_HINTS):
            continue
        reason = ""
        if is_xinput:
            reason = "xinput"
        elif "game controller" in friendly_lc:
            reason = "hid-game-controller"
        elif key in KNOWN_CONTROLLERS:
            reason = "catalog-match"
        elif any(hint in friendly_lc for hint in GAMEPAD_NAME_HINTS):
            reason = "name-hint"
        if not reason:
            continue

        # Promote stronger reasons over weaker ones if a candidate already exists
        rank = {"xinput": 4, "hid-game-controller": 3,
                "catalog-match": 2, "name-hint": 1}
        existing = candidates.get(key)
        new_rank = rank[reason]
        if existing and rank[existing["match_reason"]] >= new_rank:
            # Keep the existing stronger entry, but record additional names
            existing.setdefault("aliases", set()).add(friendly)
            if is_xinput:
                existing["xinput"] = True
            continue
        entry = {
            "vid": vid,
            "pid": pid,
            "key": key,
            "friendly_name": friendly,
            "xinput": is_xinput,
            "instance_id": inst,
            "match_reason": reason,
            "aliases": (existing or {}).get("aliases", set()),
        }
        if existing:
            entry["aliases"] = existing.get("aliases", set())
            entry["xinput"] = entry["xinput"] or existing.get("xinput", False)
        candidates[key] = entry

    out_list = []
    for entry in candidates.values():
        # Drop the alias set (not JSON-serialisable) — keep as a comma list
        aliases = entry.pop("aliases", set())
        if aliases:
            entry["aliases"] = sorted(a for a in aliases if a and a != entry["friendly_name"])
        else:
            entry["aliases"] = []
        known = KNOWN_CONTROLLERS.get(entry["key"])
        if known:
            entry["name"] = known["name"]
            entry["image"] = known["image"]
            entry["wiki_file"] = known.get("wiki_file", "")
        out_list.append(entry)
    out_list.sort(key=lambda e: (not e["xinput"], not e.get("name"), e["key"]))
    return out_list


def system_extensions(system: str) -> set[str]:
    """Read es_systems.cfg and return the file extensions for this system."""
    if not ES_SYSTEMS_CFG.exists():
        return set()
    try:
        tree = ET.parse(ES_SYSTEMS_CFG)
    except ET.ParseError:
        return set()
    for node in tree.getroot().findall("system"):
        if (node.findtext("name") or "").strip() == system:
            ext_raw = (node.findtext("extension") or "").strip()
            return {e.lower() for e in ext_raw.split() if e.startswith(".")}
    return set()


def list_roms(system: str) -> list[dict]:
    sys_dir = ROMS_ROOT / system
    if not sys_dir.exists():
        return []
    exts = system_extensions(system)
    out = []
    reserved = {"images", "videos", "manuals", "marquees", "screenshots", "media"}
    for entry in sorted(sys_dir.iterdir(), key=lambda p: p.name.lower()):
        if entry.is_dir() and entry.name.lower() not in reserved:
            # multi-file ROM folder (rare)
            continue
        if not entry.is_file():
            continue
        ext = entry.suffix.lower()
        if exts and ext not in exts:
            continue
        if not exts and ext in {".cfg", ".xml", ".txt", ".jpg", ".png", ".bak", ".ini",
                                ".log", ".keys", ".pdf", ".dat"}:
            continue
        # Has a profile? Mark it.
        profile_path = PROFILES_DIR / system / f"{entry.name}.yaml"
        out.append({
            "filename": entry.name,
            "title": entry.stem,
            "has_profile": profile_path.exists(),
        })
    return out


def profile_path(system: str, rom: str) -> Path:
    return PROFILES_DIR / system / f"{rom}.yaml"


def load_profile(system: str, rom: str) -> dict:
    p = profile_path(system, rom)
    if not p.exists():
        return {}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        return {"_error": f"YAML parse error: {e}"}


def save_profile(data: dict) -> dict:
    system = data.get("system")
    rom = data.get("rom")
    if not system or not rom:
        return {"ok": False, "error": "missing system or rom"}
    out = profile_path(system, rom)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Normalize: keep YAML clean
    normalized = {"system": system, "rom": rom}
    if data.get("title"):
        normalized["title"] = data["title"]
    if data.get("year"):
        normalized["year"] = data["year"]
    if data.get("confidence"):
        normalized["confidence"] = data["confidence"]
    if data.get("notes"):
        normalized["notes"] = data["notes"]
    if data.get("es_settings"):
        normalized["es_settings"] = {k: str(v) for k, v in data["es_settings"].items() if v not in (None, "")}
    if data.get("core_options"):
        normalized["core_options"] = {k: str(v) for k, v in data["core_options"].items() if v not in (None, "")}
    if data.get("button_semantics"):
        normalized["button_semantics"] = {k: v for k, v in data["button_semantics"].items() if v}
    out.write_text(
        yaml.safe_dump(normalized, sort_keys=False, allow_unicode=True, width=120),
        encoding="utf-8",
    )
    return {"ok": True, "path": str(out)}


def run_apply() -> dict:
    if not RBCF_PY.exists():
        return {"ok": False, "error": "rbcf.py not found"}
    py = sys.executable
    try:
        result = subprocess.run(
            [py, str(RBCF_PY), "apply"],
            capture_output=True, text=True, timeout=30, cwd=str(ROOT),
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "apply timed out"}


# ------------------------------ onboarding helpers ------------------------------

# Mirror of audit_media.py RESERVED_DIRS — folder names that are media/asset
# subfolders inside roms/<system>/, never ROMs themselves.
ONBOARD_RESERVED_DIRS = {"images", "videos", "manuals", "marquees", "maps",
                         "screenshots", "media", "boxart", "wheels", "mixrbv",
                         "mixrbv1", "mixrbv2", "support", "downloaded_media"}


def _retrobat_root_payload() -> dict:
    """Build the response for GET /api/retrobat-root."""
    if RETROBAT_ROOT is None:
        return {
            "root": None,
            "found": False,
            "probed": _probed_locations_summary(),
        }
    return {
        "root": str(RETROBAT_ROOT).replace("\\", "/"),
        "found": True,
        "probed": _probed_locations_summary(),
    }


def _count_roms_in_system(system_dir: Path) -> int:
    """Count ROM files recursively under a system folder, skipping reserved
    asset subdirs and hidden / dotfiles. Used by /api/scan only — list_roms()
    above is the canonical per-system enumerator for the editor flow.
    """
    if not system_dir.exists() or not system_dir.is_dir():
        return 0
    total = 0
    try:
        for entry in system_dir.iterdir():
            name = entry.name
            if name.startswith("."):
                continue
            if entry.is_dir():
                if name.lower() in ONBOARD_RESERVED_DIRS:
                    continue
                # Recurse into non-reserved subdir (rare: multi-disk folders, etc.)
                total += _count_roms_in_system(entry)
                continue
            if entry.is_file():
                total += 1
    except OSError:
        return total
    return total


def _iter_rom_files(system_dir: Path):
    """Yield Path objects for every ROM file under a system dir, skipping
    reserved asset subdirs, hidden entries, and dotfiles."""
    if not system_dir.exists() or not system_dir.is_dir():
        return
    try:
        entries = list(system_dir.iterdir())
    except OSError:
        return
    for entry in entries:
        name = entry.name
        if name.startswith("."):
            continue
        if entry.is_dir():
            if name.lower() in ONBOARD_RESERVED_DIRS:
                continue
            # Recurse for any other subdir.
            yield from _iter_rom_files(entry)
            continue
        if entry.is_file():
            yield entry


def _scan_systems() -> dict:
    """Build the response for GET /api/scan."""
    empty = {"systems": [], "totals": {"systems": 0, "roms": 0, "profiles": 0, "missing": 0}}
    if RETROBAT_ROOT is None or not ROMS_ROOT.exists():
        # No live RetroBat, but we may still have profiles. Still return empty
        # per spec ("If RETROBAT_ROOT is None / ROMS_ROOT doesn't exist, return
        # empty systems and zero totals; do not error.").
        return empty

    # Profile counts per system (excluding _default.yaml from rom_count).
    profiles = load_profiles()
    by_system_profiles: dict[str, list] = {}
    has_default: dict[str, bool] = {}
    for p in profiles:
        if p.is_system_default:
            has_default[p.system] = True
        else:
            by_system_profiles.setdefault(p.system, []).append(p)
        # Make sure system appears even if it only has a _default.
        by_system_profiles.setdefault(p.system, by_system_profiles.get(p.system, []))

    # ROM systems: every direct subdir of ROMS_ROOT that isn't a reserved
    # media folder.
    roms_by_system: dict[str, int] = {}
    try:
        for entry in ROMS_ROOT.iterdir():
            if not entry.is_dir():
                continue
            name = entry.name
            if name.startswith("."):
                continue
            if name.lower() in ONBOARD_RESERVED_DIRS:
                continue
            roms_by_system[name] = _count_roms_in_system(entry)
    except OSError:
        pass

    # Union of both sets.
    all_systems = sorted(set(roms_by_system) | set(by_system_profiles))
    out_systems = []
    total_roms = 0
    total_profiles = 0
    total_missing = 0
    for sys_name in all_systems:
        rom_count = roms_by_system.get(sys_name, 0)
        profiles_count = len(by_system_profiles.get(sys_name, []))
        missing = rom_count - profiles_count
        if missing < 0:
            missing = 0
        entry = {
            "name": sys_name,
            "rom_count": rom_count,
            "profiles_count": profiles_count,
            "missing": missing,
            "has_default": bool(has_default.get(sys_name, False)),
        }
        out_systems.append(entry)
        total_roms += rom_count
        total_profiles += profiles_count
        total_missing += missing

    return {
        "systems": out_systems,
        "totals": {
            "systems": len(out_systems),
            "roms": total_roms,
            "profiles": total_profiles,
            "missing": total_missing,
        },
    }


def _scaffold_all(apply: bool) -> dict:
    """Build the response for GET /api/scaffold-all (preview or apply).

    Per decision #9 in DECISIONS.md, scaffold-all also includes missing
    `_default.yaml` files alongside per-game stubs. Defaults appear first
    in the preview list (so they get written first if applied).
    """
    if RETROBAT_ROOT is None or not ROMS_ROOT.exists():
        return {"preview": [], "applied": False, "count": 0}

    # Set of (system, rom_filename) that already have a per-game profile.
    existing: set[tuple[str, str]] = set()
    existing_defaults: set[str] = set()
    for p in load_profiles():
        if p.rom:
            existing.add((p.system, p.rom))
        if p.is_system_default:
            existing_defaults.add(p.system)

    today = date.today().isoformat()
    preview: list[dict] = []
    write_targets: list[tuple[Path, dict]] = []

    try:
        sys_dirs = list(ROMS_ROOT.iterdir())
    except OSError:
        sys_dirs = []

    # First pass: scaffold missing _default.yaml entries so they appear at
    # the top of the preview and get written before per-game stubs.
    for sys_dir in sys_dirs:
        if not sys_dir.is_dir():
            continue
        sys_name = sys_dir.name
        if sys_name.startswith(".") or sys_name.lower() in ONBOARD_RESERVED_DIRS:
            continue
        if sys_name in existing_defaults:
            continue
        rom_count = _count_roms_in_system(sys_dir)
        if rom_count == 0:
            continue
        target = PROFILES_DIR / sys_name / "_default.yaml"
        rel_display = f"profiles/{sys_name}/_default.yaml"
        scaffold = {
            "system": sys_name,
            "title": f"{sys_name} (system default)",
            "confidence": "T",
            "notes": (
                f"Auto-scaffolded by /api/scaffold-all on {today}.\n"
                f"Empty placeholder — fill in es_settings / core_options as you "
                f"verify which keys survive RetroBat regeneration. See CLAUDE.md "
                f"and docs/GUID_DRIFT_DESIGN.md for the rules.\n"
            ),
            "es_settings": {},
            "core_options": {},
        }
        preview.append({
            "system": sys_name,
            "path": rel_display,
            "rom_count": rom_count,
        })
        write_targets.append((target, scaffold))

    # Second pass: per-game stubs.
    for sys_dir in sys_dirs:
        if not sys_dir.is_dir():
            continue
        sys_name = sys_dir.name
        if sys_name.startswith("."):
            continue
        if sys_name.lower() in ONBOARD_RESERVED_DIRS:
            continue
        for rom_path in _iter_rom_files(sys_dir):
            rom_name = rom_path.name
            if (sys_name, rom_name) in existing:
                continue
            yaml_name = f"{rom_name}.yaml"
            target = PROFILES_DIR / sys_name / yaml_name
            rel_display = f"profiles/{sys_name}/{yaml_name}"
            scaffold = {
                "system": sys_name,
                "rom": rom_name,
                "title": rom_path.stem,
                "confidence": "T",
                "notes": (
                    f"Auto-scaffolded by /api/scaffold-all on {today}.\n"
                    f"Inherits from {sys_name}/_default.yaml. Promote to V or K once verified.\n"
                ),
                "es_settings": {},
                "core_options": {},
            }
            preview.append({
                "system": sys_name,
                "rom": rom_name,
                "path": rel_display,
            })
            write_targets.append((target, scaffold))

    result = {"preview": preview, "applied": False, "count": len(preview)}
    if not apply:
        return result

    written: list[str] = []
    profiles_root = PROFILES_DIR.resolve()
    for target, scaffold in write_targets:
        try:
            resolved_parent = target.parent.resolve()
        except OSError:
            continue
        # Safety: target path must be inside PROFILES_DIR.
        try:
            resolved_parent.relative_to(profiles_root)
        except ValueError:
            print(f"[scaffold-all] refusing path outside profiles/: {target}",
                  file=sys.stderr)
            continue
        if target.exists():
            # Never overwrite.
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                yaml.safe_dump(scaffold, sort_keys=False, allow_unicode=True, width=120),
                encoding="utf-8",
            )
        except OSError as e:
            print(f"[scaffold-all] failed to write {target}: {e}", file=sys.stderr)
            continue
        written.append(f"profiles/{target.parent.name}/{target.name}")

    result["applied"] = bool(written)
    result["written"] = written
    return result


def _scaffold_defaults(apply: bool) -> dict:
    """Build the response for GET /api/scaffold-defaults (preview or apply).

    Per-system safe scaffold: creates `<system>/_default.yaml` for every
    system that has ≥1 ROM but no existing default. Bounded by the number
    of systems (~258 max), unlike scaffold-all which is bounded by the
    total ROM count (285k+ for the user's library). Empty es_settings /
    core_options — user fills them in incrementally via `rbcf` or the GUI.
    """
    if RETROBAT_ROOT is None or not ROMS_ROOT.exists():
        return {"preview": [], "applied": False, "count": 0}

    existing_defaults: set[str] = set()
    for p in load_profiles():
        if p.is_system_default:
            existing_defaults.add(p.system)

    today = date.today().isoformat()
    preview: list[dict] = []
    write_targets: list[tuple[Path, dict]] = []

    try:
        sys_dirs = list(ROMS_ROOT.iterdir())
    except OSError:
        sys_dirs = []

    for sys_dir in sys_dirs:
        if not sys_dir.is_dir():
            continue
        sys_name = sys_dir.name
        if sys_name.startswith(".") or sys_name.lower() in ONBOARD_RESERVED_DIRS:
            continue
        if sys_name in existing_defaults:
            continue
        # Only scaffold defaults for systems that actually contain ROMs.
        rom_count = _count_roms_in_system(sys_dir)
        if rom_count == 0:
            continue
        target = PROFILES_DIR / sys_name / "_default.yaml"
        rel_display = f"profiles/{sys_name}/_default.yaml"
        scaffold = {
            "system": sys_name,
            "title": f"{sys_name} (system default)",
            "confidence": "T",
            "notes": (
                f"Auto-scaffolded by /api/scaffold-defaults on {today}.\n"
                f"Empty placeholder — fill in es_settings / core_options as you "
                f"verify which keys survive RetroBat regeneration. See CLAUDE.md "
                f"and docs/GUID_DRIFT_DESIGN.md for the rules.\n"
            ),
            "es_settings": {},
            "core_options": {},
        }
        preview.append({
            "system": sys_name,
            "path": rel_display,
            "rom_count": rom_count,
        })
        write_targets.append((target, scaffold))

    result = {"preview": preview, "applied": False, "count": len(preview)}
    if not apply:
        return result

    written: list[str] = []
    profiles_root = PROFILES_DIR.resolve()
    for target, scaffold in write_targets:
        try:
            resolved_parent = target.parent.resolve()
        except OSError:
            continue
        try:
            resolved_parent.relative_to(profiles_root)
        except ValueError:
            print(f"[scaffold-defaults] refusing path outside profiles/: {target}",
                  file=sys.stderr)
            continue
        if target.exists():
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                yaml.safe_dump(scaffold, sort_keys=False, allow_unicode=True, width=120),
                encoding="utf-8",
            )
        except OSError as e:
            print(f"[scaffold-defaults] failed to write {target}: {e}", file=sys.stderr)
            continue
        written.append(f"profiles/{target.parent.name}/{target.name}")

    result["applied"] = bool(written)
    result["written"] = written
    return result


# ----- bezel cutoff detection -----

# Strict and lenient alpha thresholds — see calibrate_bezels.py docstring.
# 32 = strict (excludes anti-aliased edges and glass effects from the play area).
# 235 = RetroBat's own auto-detect default (too lenient — the cause of the cutoff bug).
_BEZEL_STRICT_ALPHA = 32
_BEZEL_LENIENT_ALPHA = 235
# A bezel is reported as "cutoff" if the strict play-area is materially smaller
# than the lenient one. 5% of either dimension is the threshold below which we
# consider the difference negligible (anti-aliasing only, not real cutoff).
_BEZEL_CUTOFF_PCT_THRESHOLD = 5.0


def _scan_bezels() -> list[dict]:
    """Walk BEZELS_DIR and detect bezels whose RetroBat auto-detect would
    let the game image render past the bezel frame.

    For each <system>.png:
      - compute the bounding box of pixels with alpha <= 32 (strict / correct)
      - compute the bounding box of pixels with alpha <= 235 (lenient ≈ RetroBat
        default; close enough that anti-aliased + glass-effect pixels get
        wrongly counted as play area, which is the bug we're detecting)
      - if the strict box is materially smaller (> 5% of either dimension),
        report it as a cutoff candidate

    Returns a list of dicts:
        [{system, bezel_path, current_info_exists, cutoff_pct: {x, y},
          viewport: {l, t, r, b}, image_size: {w, h}}, ...]

    Empty list if BEZELS_DIR doesn't exist or RetroBat isn't found.
    Reuses calibrate_bezels.find_play_area — no reimplementation.
    """
    if RETROBAT_ROOT is None or not BEZELS_DIR.exists():
        return []

    try:
        # Lazy import: keeps cold-start fast and avoids loading PIL until used.
        from PIL import Image  # type: ignore
        from calibrate_bezels import find_play_area
    except ImportError as e:
        print(f"[bezel-scan] missing dependency: {e}", file=sys.stderr)
        return []

    out: list[dict] = []
    try:
        pngs = sorted(BEZELS_DIR.glob("*.png"))
    except OSError:
        return []

    for png in pngs:
        try:
            with Image.open(png) as im:
                w, h = im.size
                strict_bbox = find_play_area(im, _BEZEL_STRICT_ALPHA)
                lenient_bbox = find_play_area(im, _BEZEL_LENIENT_ALPHA)
        except (OSError, ValueError) as e:
            print(f"[bezel-scan] {png.name}: {e}", file=sys.stderr)
            continue

        if strict_bbox is None or lenient_bbox is None:
            # Either no transparency at all (skip — not a bezel-shaped image)
            # or the strict pass found nothing while the lenient one did,
            # which means the image has only soft edges — not a cutoff.
            continue

        s_l, s_t, s_r, s_b = strict_bbox
        l_l, l_t, l_r, l_b = lenient_bbox
        s_w, s_h = max(s_r - s_l, 0), max(s_b - s_t, 0)
        l_w, l_h = max(l_r - l_l, 0), max(l_b - l_t, 0)
        if s_w == 0 or s_h == 0 or l_w == 0 or l_h == 0:
            continue

        # Cutoff = how much MORE area the lenient bbox claims vs the strict one,
        # as a percentage of the lenient size. If lenient is much bigger, the
        # game image will render past the bezel frame using RetroBat's defaults.
        x_pct = ((l_w - s_w) / l_w) * 100.0 if l_w > s_w else 0.0
        y_pct = ((l_h - s_h) / l_h) * 100.0 if l_h > s_h else 0.0
        if x_pct <= _BEZEL_CUTOFF_PCT_THRESHOLD and y_pct <= _BEZEL_CUTOFF_PCT_THRESHOLD:
            continue

        info_path = png.with_suffix(".info")
        out.append({
            "system": png.stem,
            "bezel_path": str(png).replace("\\", "/"),
            "current_info_exists": info_path.exists(),
            "cutoff_pct": {
                "x": round(x_pct, 2),
                "y": round(y_pct, 2),
            },
            "viewport": {
                "l": int(s_l),
                "t": int(s_t),
                "r": int(s_r),
                "b": int(s_b),
            },
            "image_size": {"w": int(w), "h": int(h)},
        })

    return out


def _bezel_cutoffs(apply: bool) -> dict:
    """Build the response for GET /api/bezel-cutoffs (preview or apply).

    Preview: returns {cutoffs: [...], applied: false, count: N}.
    Apply: writes <system>.info sidecars for each cutoff bezel using
    calibrate_bezels' margin/info schema. Returns the preview list, plus
    `applied: true` and `written: [paths]`.

    Existing .info files are NEVER overwritten — they're skipped (and
    excluded from `written`). Path-traversal: every write target must
    resolve under BEZELS_DIR; refuse otherwise.
    """
    cutoffs = _scan_bezels()
    result: dict = {
        "cutoffs": cutoffs,
        "applied": False,
        "count": len(cutoffs),
    }
    if not apply:
        return result
    if not cutoffs:
        result["applied"] = True
        result["written"] = []
        return result

    # Lazy import again; we only get here on apply.
    try:
        from PIL import Image  # type: ignore
        from calibrate_bezels import (
            find_play_area, margins_from_bbox, write_info,
        )
    except ImportError as e:
        result["error"] = f"missing dependency: {e}"
        return result

    bezels_root: Path
    try:
        bezels_root = BEZELS_DIR.resolve()
    except OSError as e:
        result["error"] = f"could not resolve BEZELS_DIR: {e}"
        return result

    written: list[str] = []
    skipped_existing: list[str] = []
    for c in cutoffs:
        png = Path(c["bezel_path"])
        info_target = png.with_suffix(".info")
        try:
            resolved_target = info_target.resolve()
        except OSError:
            continue
        # Path-traversal guard: target must live inside BEZELS_DIR.
        try:
            resolved_target.relative_to(bezels_root)
        except ValueError:
            print(f"[bezel-cutoffs] refusing path outside bezels dir: {info_target}",
                  file=sys.stderr)
            continue
        if info_target.exists():
            # Never overwrite existing .info — user can delete to force re-write.
            skipped_existing.append(str(info_target).replace("\\", "/"))
            continue
        try:
            with Image.open(png) as im:
                w, h = im.size
                bbox = find_play_area(im, _BEZEL_STRICT_ALPHA)
                if bbox is None:
                    continue
                m = margins_from_bbox(bbox, w, h)
                if write_info(png, w, h, m, dry_run=False):
                    written.append(str(info_target).replace("\\", "/"))
        except (OSError, ValueError) as e:
            print(f"[bezel-cutoffs] failed to write {info_target}: {e}", file=sys.stderr)
            continue

    result["applied"] = True
    result["written"] = written
    if skipped_existing:
        result["skipped_existing"] = skipped_existing
    return result


def _set_retrobat_root(data: dict) -> dict:
    """Persist a user-supplied RetroBat root path to .rbcfrc.

    Body: {"root": "<path>"}  or  {"root": null}  to clear.

    Returns: { ok, root, found, message, path_to_rbcfrc, restart_required }.
    Validates the candidate path before writing — does not write if the
    marker file (es_settings.cfg) is missing under the candidate. The
    server must be restarted for the new root to take effect (RETROBAT_ROOT
    is computed at module import time).
    """
    raw = data.get("root")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        cleared = clear_rbcfrc()
        return {
            "ok": True,
            "root": None,
            "found": False,
            "cleared": cleared,
            "message": (
                ".rbcfrc cleared. Restart the server for the change to take effect."
                if cleared else
                "No .rbcfrc was set."
            ),
            "path_to_rbcfrc": str(RBCFRC_PATH),
            "restart_required": cleared,
        }
    if not isinstance(raw, str):
        return {"ok": False, "error": "root must be a string or null"}

    candidate = Path(raw.strip().strip('"').strip("'"))
    marker = candidate / "emulationstation" / ".emulationstation" / "es_settings.cfg"
    if not marker.is_file():
        return {
            "ok": False,
            "root": str(candidate),
            "found": False,
            "error": (
                f"That path doesn't look like a RetroBat install — "
                f"{marker} is missing. Nothing was written."
            ),
            "path_to_rbcfrc": str(RBCFRC_PATH),
            "restart_required": False,
        }

    try:
        write_rbcfrc(candidate)
    except OSError as e:
        return {
            "ok": False,
            "error": f"Could not write {RBCFRC_PATH}: {e}",
        }
    return {
        "ok": True,
        "root": str(candidate).replace("\\", "/"),
        "found": True,
        "message": (
            f"Saved RetroBat root to {RBCFRC_PATH}. "
            f"Restart the server for the change to take effect."
        ),
        "path_to_rbcfrc": str(RBCFRC_PATH),
        "restart_required": True,
    }


# ------------------------------ backup endpoints ------------------------------
#
# Two-tier backup subsystem (DECISIONS.md #5). Implementation lives in
# backups.py — these helpers just adapt module calls to JSON-friendly
# dicts and surface refusal modes (factory-already-taken, snapshot-not-
# found, etc.) as 200 responses with ``ok: False`` so the front-end can
# render them as error banners without dealing with HTTP status codes.

def _snapshot_to_dict(snap) -> dict:
    """backups.Snapshot → JSON-serializable dict."""
    return {
        "id": snap.id,
        "kind": snap.kind,
        "created_at": snap.created_at,
        "description": snap.description,
        "files": list(snap.files),
        "retrobat_root": snap.retrobat_root,
    }


def _backup_list() -> dict:
    """GET /api/backup/list — return all snapshots + factory_exists flag."""
    try:
        from backups import list_snapshots, factory_exists
        snaps = list_snapshots()
        return {
            "ok": True,
            "snapshots": [_snapshot_to_dict(s) for s in snaps],
            "factory_exists": factory_exists(),
        }
    except Exception as e:
        return {"ok": False, "error": f"backup list failed: {e}",
                "snapshots": [], "factory_exists": False}


def _backup_factory() -> dict:
    """POST /api/backup/factory — capture the one-shot tier-1 snapshot."""
    try:
        from backups import snapshot as _snapshot, factory_exists, _read_manifest
        if factory_exists():
            existing = _read_manifest("factory")
            return {
                "ok": False,
                "error": "factory snapshot already exists",
                "existing": _snapshot_to_dict(existing) if existing else None,
            }
        snap = _snapshot("factory", description="pre-install factory snapshot")
        if snap is None:
            return {"ok": False, "error": "factory snapshot failed (see server log)"}
        return {"ok": True, "snapshot": _snapshot_to_dict(snap)}
    except Exception as e:
        return {"ok": False, "error": f"factory snapshot failed: {e}"}


def _backup_snapshot(data: dict) -> dict:
    """POST /api/backup/snapshot — capture a tier-2 working snapshot."""
    try:
        from backups import snapshot as _snapshot
        description = str(data.get("description") or "manual snapshot")
        snap = _snapshot("working", description=description)
        if snap is None:
            return {"ok": False, "error": "snapshot failed (see server log)"}
        return {"ok": True, "snapshot": _snapshot_to_dict(snap)}
    except Exception as e:
        return {"ok": False, "error": f"snapshot failed: {e}"}


def _backup_restore(data: dict) -> dict:
    """POST /api/backup/restore — preview by default; ``apply: true`` writes.

    Always reports the auto-snapshot id that was taken (or would be
    taken, in dry mode) so the caller can show "we just made a safety
    snapshot at X" in the UI.
    """
    try:
        from backups import (
            list_snapshots, restore as _restore, _read_manifest,
        )
        snap_id = (data.get("id") or "").strip()
        do_apply = bool(data.get("apply"))
        if not snap_id:
            return {"ok": False, "error": "missing snapshot id"}

        snap = _read_manifest(snap_id)
        if snap is None:
            return {"ok": False, "error": f"no such snapshot: {snap_id}"}

        # Snapshot ids before/after restore so caller can identify the
        # auto-created safety snapshot. We need to compare lists, since
        # restore() takes the auto-snap internally and doesn't return it.
        existing_ids = {s.id for s in list_snapshots()}
        restored, skipped = _restore(snap_id, dry=not do_apply)
        auto_snap_id: str | None = None
        if do_apply:
            new_ids = [s.id for s in list_snapshots()]
            for nid in new_ids:
                if nid not in existing_ids:
                    auto_snap_id = nid
                    break

        return {
            "ok": True,
            "dry_run": not do_apply,
            "snapshot": _snapshot_to_dict(snap),
            "restored": list(restored),
            "skipped": [{"path": p, "reason": r} for p, r in skipped],
            "auto_snapshot_id": auto_snap_id,
        }
    except Exception as e:
        return {"ok": False, "error": f"restore failed: {e}"}


# ------------------------------ HTTP layer ------------------------------

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(GUI_DIR), **kwargs)

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        msg = fmt % args
        if " 200 " in msg or " 304 " in msg:
            return
        sys.stderr.write(f"[{self.log_date_time_string()}] {msg}\n")

    def _query(self):
        return urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/systems":
            return self._json({
                "systems": SYSTEMS,
                "system_options": SYSTEM_OPTIONS,
                "core_mapper_prefix": CORE_MAPPER_PREFIX,
                "pad_buttons": PAD_BUTTONS,
            })
        if u.path == "/api/devices":
            return self._json({"devices": probe_devices()})
        if u.path == "/api/sync-status":
            return self._json(load_sync_status())
        if u.path == "/api/games":
            q = self._query()
            sys_id = (q.get("system", [""])[0] or "").strip()
            return self._json({"system": sys_id, "games": list_roms(sys_id)})
        if u.path == "/api/profile":
            q = self._query()
            sys_id = (q.get("system", [""])[0] or "").strip()
            rom = (q.get("rom", [""])[0] or "").strip()
            return self._json({"system": sys_id, "rom": rom, "profile": load_profile(sys_id, rom)})
        if u.path == "/api/retrobat-root":
            return self._json(_retrobat_root_payload())
        if u.path == "/api/scan":
            payload = _scan_systems()
            # Cheap-ish supplement so the UI can surface a "fix N bezels"
            # callout in step 2 without a second round-trip. _scan_bezels is
            # bounded by the number of system PNGs in BEZELS_DIR (~100s, not
            # 100Ks like ROMs) so it's safe to inline here.
            try:
                payload["bezels_with_cutoffs"] = len(_scan_bezels())
            except Exception as e:  # belt-and-braces: never block /api/scan
                print(f"[scan] bezel sub-scan failed: {e}", file=sys.stderr)
                payload["bezels_with_cutoffs"] = 0
            return self._json(payload)
        if u.path == "/api/scaffold-all":
            q = self._query()
            apply_flag = (q.get("apply", ["false"])[0] or "").strip().lower() in ("1", "true", "yes")
            return self._json(_scaffold_all(apply=apply_flag))
        if u.path == "/api/scaffold-defaults":
            q = self._query()
            apply_flag = (q.get("apply", ["false"])[0] or "").strip().lower() in ("1", "true", "yes")
            return self._json(_scaffold_defaults(apply=apply_flag))
        if u.path == "/api/bezel-cutoffs":
            q = self._query()
            apply_flag = (q.get("apply", ["false"])[0] or "").strip().lower() in ("1", "true", "yes")
            return self._json(_bezel_cutoffs(apply=apply_flag))
        if u.path == "/api/backup/list":
            return self._json(_backup_list())
        if u.path in ("", "/"):
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8") if length else ""
            data = json.loads(body) if body else {}
        except (ValueError, json.JSONDecodeError) as e:
            return self._json({"ok": False, "error": f"bad request: {e}"}, status=400)

        if u.path == "/api/save":
            result = save_profile(data)
            if result.get("ok") and data.get("apply"):
                result["apply"] = run_apply()
            return self._json(result)
        if u.path == "/api/apply":
            return self._json(run_apply())
        if u.path == "/api/sync":
            result = run_sync_now(dry=bool(data.get("dry_run")))
            refresh_catalog()
            result["status"] = load_sync_status()
            return self._json(result)
        if u.path == "/api/retrobat-root":
            return self._json(_set_retrobat_root(data))
        if u.path == "/api/backup/factory":
            return self._json(_backup_factory())
        if u.path == "/api/backup/snapshot":
            return self._json(_backup_snapshot(data))
        if u.path == "/api/backup/restore":
            return self._json(_backup_restore(data))
        return self._json({"ok": False, "error": "unknown endpoint"}, status=404)


class ReuseTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


def serve_http(host: str = "127.0.0.1",
               port: int = 8765,
               no_open: bool = False,
               ready_event: threading.Event | None = None,
               shutdown_event: threading.Event | None = None) -> None:
    """Run the local HTTP server.

    Used by both the tray-resident main loop (server-in-daemon-thread) and
    the legacy --no-tray foreground entry point.

    Args:
        host: bind address. Default 127.0.0.1.
        port: bind port. Default 8765.
        no_open: skip auto-opening the browser. Tray mode passes True
            because it opens the browser itself once ready_event fires.
        ready_event: if provided, set() once the server is listening so a
            caller (e.g. tray) can open the browser without racing the
            socket bind.
        shutdown_event: if provided, server_forever()'s shutdown is gated
            on this event; a watcher thread polls it and calls
            srv.shutdown() when set. This is how the tray's Quit handler
            terminates the server cleanly.
    """
    if not GUI_DIR.exists():
        print(f"[fatal] gui directory missing: {GUI_DIR}", file=sys.stderr)
        sys.exit(1)

    url = f"http://localhost:{port}/"
    print(f"RB-Controller_fix GUI -> {url}")
    print(f"  ROMs root:    {ROMS_ROOT}")
    print(f"  Profiles dir: {PROFILES_DIR}")
    print("Ctrl-C to stop (or use the tray menu's Quit item).\n")

    if not no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    with ReuseTCPServer((host, port), Handler) as srv:
        if ready_event is not None:
            ready_event.set()

        # If a shutdown_event was supplied, run a tiny watcher thread that
        # converts it into srv.shutdown(). serve_forever() doesn't take an
        # external cancellation token, so this is the standard pattern.
        watcher: threading.Thread | None = None
        if shutdown_event is not None:
            def _watch_shutdown() -> None:
                shutdown_event.wait()
                # shutdown() is safe to call from any thread except the one
                # currently inside serve_forever(); it blocks until the
                # serve loop exits.
                try:
                    srv.shutdown()
                except OSError:
                    pass
            watcher = threading.Thread(
                target=_watch_shutdown,
                name="rbcf-http-shutdown-watcher",
                daemon=True,
            )
            watcher.start()

        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped.")
            if shutdown_event is not None:
                shutdown_event.set()
        finally:
            # Make sure the watcher thread can exit if it's still parked.
            if shutdown_event is not None and not shutdown_event.is_set():
                shutdown_event.set()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-open", action="store_true",
                    help="don't auto-open the default browser on start.")
    ap.add_argument("--no-tray", action="store_true",
                    help="run the server in the foreground (legacy "
                         "behaviour). Useful for headless / CI / dev. "
                         "Without this flag, rbcf_gui runs as a "
                         "tray-resident app.")
    args = ap.parse_args()

    if args.no_tray:
        # Legacy foreground mode — exactly the pre-refactor behaviour.
        serve_http(
            host="127.0.0.1",
            port=args.port,
            no_open=args.no_open,
            ready_event=None,
            shutdown_event=None,
        )
        return

    # Default: tray-resident app. tray.start_tray_app() handles its own
    # graceful fallback to foreground mode if pystray isn't installed.
    try:
        from tray import start_tray_app
    except ImportError as e:
        print(
            f"[rbcf_gui] could not import tray module ({e}); "
            f"falling back to foreground server.",
            file=sys.stderr,
        )
        serve_http(
            host="127.0.0.1",
            port=args.port,
            no_open=args.no_open,
            ready_event=None,
            shutdown_event=None,
        )
        return

    start_tray_app(open_browser_on_start=not args.no_open,
                   host="127.0.0.1",
                   port=args.port)


if __name__ == "__main__":
    main()
