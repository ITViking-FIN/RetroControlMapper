"""
RB-Controller_fix GUI — local web app.

Usage:
    py rbcf_gui.py [--port 8765] [--no-open]

Endpoints:
    GET  /                              index.html
    GET  /static-files (any)            served from gui/
    GET  /api/systems                   list of supported systems
    GET  /api/games?system=X            list of ROMs in roms/<system>/
    GET  /api/profile?system&rom        existing profile YAML (or {});
                                        response also includes the loaded
                                        system_default for the inheritance
                                        overlay (Flow 4).
    GET  /api/profile-default?system    system _default.yaml content (or {})
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
    POST /api/system-lookup             best-effort online lookup of controller
                                        info for a system that has no curated
                                        metadata; gated behind explicit user
                                        consent. Body: {system, allow_online,
                                        force_refresh}. See system_lookup.py.
    GET  /api/update-check              cached-only check; never hits the net.
                                        Returns {ok, has_cache, ...UpdateInfo}.
                                        Used by the frontend on page load to
                                        decide whether to render the header
                                        update badge.
    POST /api/update-check              compare local __version__ against the
                                        latest GitHub release of the project
                                        repo (ITViking-FIN/RetroControlMapper).
                                        Body: {allow_online, force}. Cache TTL
                                        24h (errors 1h). See update_check.py.
    GET  /api/guid/watcher              GUID watcher state + last 50 events.
                                        Surfaces guid_watcher.get_state() +
                                        read_log() over HTTP for a future GUI
                                        panel. v0.1.0 surface is the tray menu.
    POST /api/guid/watcher              Body: {mode: 'off'|'detect'|'auto-fold'}.
                                        Persists the new mode; live thread
                                        picks it up on its next tick.
    POST /api/guid/fold-pending         Body: {vid, pid}. Manually triggers a
                                        fold for a specific alias group — used
                                        when the watcher is in 'detect' mode
                                        and the user clicks "fold this" in the
                                        GUI.
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import re
import socketserver
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
import xml.etree.ElementTree as ET
from datetime import date
from email.parser import BytesParser
from email.policy import default as email_default_policy
from pathlib import Path

import yaml

from config import (
    RETROBAT_ROOT, ROMS_ROOT, ES_SYSTEMS_CFG, BEZELS_DIR, RBCFRC_PATH,
    write_rbcfrc, clear_rbcfrc, _probed_locations_summary,
    __version__ as RBCF_VERSION,
)
from rbcf import load_profiles
import system_lookup
import update_check
import xml_safe

ROOT = Path(__file__).resolve().parent
GUI_DIR = ROOT / "gui"
PROFILES_DIR = ROOT / "profiles"
TEMPLATES_DIR = ROOT / "profile_templates"
RBCF_PY = ROOT / "rbcf.py"
SYNC_PY = ROOT / "controller_sync.py"
CATALOG_YAML = ROOT / "controller_catalog.yaml"
SYNC_MANIFEST = ROOT / "sync_manifest.json"
KNOWN_IMG_DIR = GUI_DIR / "img" / "known"
CONTRIB_IMG_DIR = GUI_DIR / "img" / "contrib"

# Order of preferred extensions when looking up an existing image for a
# VID:PID. Mirrored on the write path (with .jpeg canonicalised to .jpg).
IMG_EXT_PREF = (".png", ".jpg", ".jpeg", ".webp", ".svg")
# Allowed canonical save extensions for user-uploaded images.
ALLOWED_UPLOAD_EXTS = (".png", ".jpg", ".webp", ".svg")
# Hard cap on uploaded contrib images.
MAX_CONTRIB_IMG_BYTES = 2_000_000
# VID/PID format guard.
HEX4_RE = re.compile(r"^[0-9A-Fa-f]{4}$")

# Curated metadata for the systems we have full target-side support for.
# These get rich `target_controller` SVGs and `fixed_mapping_note` blurbs.
# Other systems discovered in es_systems.cfg are merged in at import time
# with `target_controller`/`fixed_mapping_note` set to None — the frontend
# already handles those gracefully ("no target controller diagram for this
# system yet"). See `_merge_systems()` below.
HARDCODED_SYSTEMS = [
    # --- Existing curated 4 (Commodore family — byte-identical, do not edit) ---
    {"id": "c64",       "name": "Commodore 64",   "target_controller": "joystick_1btn",
     "fixed_mapping_note": "VICE: D-pad/stick → joy direction · B → fire · A → fire2 · X → SPACE"},
    {"id": "amiga500",  "name": "Amiga 500",      "target_controller": "joystick_1btn",
     "fixed_mapping_note": "puae default RetroPad mode: D-pad/stick → joy · B → fire"},
    {"id": "amiga1200", "name": "Amiga 1200",     "target_controller": "joystick_1btn",
     "fixed_mapping_note": "puae default RetroPad mode: D-pad/stick → joy · B → fire"},
    {"id": "amigacd32", "name": "Amiga CD32",     "target_controller": "cd32_pad",
     "fixed_mapping_note": "CD32 Pad (device 517): B=Red · A=Blue · Y=Yellow · X=Green · L=Forward · R=Rewind · Start=Play · Select=Reverse"},

    # --- Tier 1: major consoles ---
    # `target_controller` left as None for everything below — only cd32_pad
    # and joystick_1btn target SVGs exist today (see TARGET_MAPPINGS in
    # gui/controllers.js). New per-system SVG art is a separate stream's
    # job; the frontend handles None as a graceful empty state.
    # Bindings sourced from libretro core defaults + RetroBat wiki +
    # community-confirmed conventions. RetroPad is the canonical "PS3 with
    # SNES face buttons" layout (B=south, A=east, Y=west, X=north).
    {"id": "nes",          "name": "Nintendo Entertainment System", "target_controller": None,
     "target_layout": {"face": {"layout": "row", "count": 2, "labels": ["B", "A"], "colors": ["red", "red"]},
                       "dpad": True, "sticks": 0, "shoulders": 0, "start": True, "select": True,
                       "label": "NES — D-pad + 2 buttons"},
     "fixed_mapping_note": "RetroPad → NES: B=B · A=A (south=B, east=A — matches NES face order) · Select=Select · Start=Start · D-pad=D-pad"},
    {"id": "snes",         "name": "Super Nintendo Entertainment System", "target_controller": None,
     "target_layout": {"face": {"layout": "diamond", "count": 4, "labels": ["X", "A", "B", "Y"],
                                 "colors": ["blue", "red", "yellow", "green"]},
                       "dpad": True, "sticks": 0, "shoulders": 2, "start": True, "select": True,
                       "label": "SNES — D-pad + 4 face + L/R"},
     "fixed_mapping_note": "RetroPad → SNES: B=B · A=A · Y=Y · X=X · L=L · R=R · Select=Select · Start=Start (RetroPad layout matches SNES diamond — no swap)"},
    {"id": "megadrive",    "name": "Sega Mega Drive / Genesis", "target_controller": None,
     "target_layout": {"face": {"layout": "grid", "count": 6, "labels": ["X", "Y", "Z", "A", "B", "C"]},
                       "dpad": True, "sticks": 0, "shoulders": 0, "start": True, "select": False,
                       "label": "Mega Drive — D-pad + 6 face (3-btn ignores X/Y/Z)"},
     "fixed_mapping_note": "RetroPad → Genesis 3-button: B=A · A=B · Y=C · Start=Start · Select=Mode. 6-button adds: X=Y · L=X · R=Z (genesis_plus_gx default)"},
    {"id": "genesis",      "name": "Sega Genesis", "target_controller": None,
     "target_layout": {"face": {"layout": "grid", "count": 6, "labels": ["X", "Y", "Z", "A", "B", "C"]},
                       "dpad": True, "sticks": 0, "shoulders": 0, "start": True, "select": False,
                       "label": "Genesis — D-pad + 6 face"},
     "fixed_mapping_note": "RetroPad → Genesis 3-button: B=A · A=B · Y=C · Start=Start · Select=Mode. 6-button adds: X=Y · L=X · R=Z"},
    {"id": "mastersystem", "name": "Sega Master System", "target_controller": None,
     "target_layout": {"face": {"layout": "row", "count": 2, "labels": ["1", "2"]},
                       "dpad": True, "sticks": 0, "shoulders": 0, "start": True, "select": False,
                       "label": "Master System — D-pad + 2 buttons"},
     "fixed_mapping_note": "RetroPad → SMS: B=Button 1 · A=Button 2 · Start=Pause/Start · D-pad=D-pad (genesis_plus_gx)"},
    {"id": "gamegear",     "name": "Sega Game Gear", "target_controller": None,
     "target_layout": {"face": {"layout": "row", "count": 2, "labels": ["1", "2"]},
                       "dpad": True, "sticks": 0, "shoulders": 0, "start": True, "select": False,
                       "label": "Game Gear — D-pad + 2 buttons"},
     "fixed_mapping_note": "RetroPad → Game Gear: B=Button 1 · A=Button 2 · Start=Start · D-pad=D-pad (genesis_plus_gx)"},
    {"id": "gb",           "name": "Nintendo Game Boy", "target_controller": None,
     "target_layout": {"face": {"layout": "row", "count": 2, "labels": ["B", "A"]},
                       "dpad": True, "sticks": 0, "shoulders": 0, "start": True, "select": True,
                       "label": "Game Boy — D-pad + 2 buttons"},
     "fixed_mapping_note": "RetroPad → GB: B=B · A=A · Select=Select · Start=Start · D-pad=D-pad (gambatte/sameboy)"},
    {"id": "gbc",          "name": "Nintendo Game Boy Color", "target_controller": None,
     "target_layout": {"face": {"layout": "row", "count": 2, "labels": ["B", "A"]},
                       "dpad": True, "sticks": 0, "shoulders": 0, "start": True, "select": True,
                       "label": "Game Boy Color — D-pad + 2 buttons"},
     "fixed_mapping_note": "RetroPad → GBC: B=B · A=A · Select=Select · Start=Start · D-pad=D-pad (gambatte/sameboy)"},
    {"id": "gba",          "name": "Nintendo Game Boy Advance", "target_controller": None,
     "target_layout": {"face": {"layout": "row", "count": 2, "labels": ["B", "A"]},
                       "dpad": True, "sticks": 0, "shoulders": 2, "start": True, "select": True,
                       "label": "GBA — D-pad + 2 face + L/R"},
     "fixed_mapping_note": "RetroPad → GBA: B=B · A=A · L=L · R=R · Select=Select · Start=Start (mGBA)"},
    {"id": "nds",          "name": "Nintendo DS", "target_controller": None,
     "target_layout": {"face": {"layout": "diamond", "count": 4, "labels": ["X", "A", "B", "Y"]},
                       "dpad": True, "sticks": 0, "shoulders": 2, "start": True, "select": True,
                       "label": "NDS — D-pad + 4 face + L/R + touch (R-stick)"},
     "fixed_mapping_note": "RetroPad → NDS: B=B · A=A · Y=Y · X=X · L=L · R=R · Select=Select · Start=Start · R-stick=touch pointer (desmume default; melonDS similar)"},
    {"id": "n64",          "name": "Nintendo 64", "target_controller": None,
     "target_layout": {"face": {"layout": "row", "count": 3, "labels": ["B", "A", "Z"]},
                       "dpad": True, "sticks": 1, "shoulders": 4, "start": True, "select": False,
                       "label": "N64 — Stick + D-pad + 3 face + L/R/Z (C via R-stick)"},
     "fixed_mapping_note": "RetroPad → N64: B=A (south=N64-A) · Y=B · R2=Z · L=L · R=R · Start=Start · R-stick=C-buttons (mupen64plus_next default; HOLD R2 to access C via face buttons)"},
    {"id": "psx",          "name": "Sony PlayStation", "target_controller": None,
     "target_layout": {"face": {"layout": "diamond", "count": 4, "labels": ["△", "○", "✕", "□"],
                                 "colors": ["green", "red", "blue", "yellow"]},
                       "dpad": True, "sticks": 2, "shoulders": 4, "start": True, "select": True,
                       "label": "PlayStation — DualShock layout"},
     "fixed_mapping_note": "RetroPad → PSX: B=Cross · A=Circle · Y=Square · X=Triangle · L/R/L2/R2 same · Select=Select · Start=Start (Beetle PSX / DuckStation / SwanStation — matches PS3 layout natively)"},
    {"id": "dreamcast",    "name": "Sega Dreamcast", "target_controller": None,
     "target_layout": {"face": {"layout": "diamond", "count": 4, "labels": ["Y", "X", "A", "B"]},
                       "dpad": True, "sticks": 1, "shoulders": 2, "start": True, "select": False,
                       "label": "Dreamcast — Stick + D-pad + 4 face + L/R triggers"},
     "fixed_mapping_note": "RetroPad → DC: B=A · A=B · Y=X · X=Y (note swap — DC face uses opposite cardinal positions to RetroPad) · L2=L-trigger · R2=R-trigger · Start=Start (Flycast default)"},
    {"id": "saturn",       "name": "Sega Saturn", "target_controller": None,
     "target_layout": {"face": {"layout": "grid", "count": 6, "labels": ["X", "Y", "Z", "A", "B", "C"]},
                       "dpad": True, "sticks": 0, "shoulders": 2, "start": True, "select": False,
                       "label": "Saturn — D-pad + 6 face + L/R"},
     "fixed_mapping_note": "RetroPad → Saturn: B=A · A=B · Y=X · X=Y · L=L · R=R · L2=Z · R2=C · Start=Start (Beetle Saturn / Kronos / YabaSanshiro — RetroPad mapped onto Saturn's 6-button face)"},
    {"id": "pcengine",     "name": "PC Engine / TurboGrafx-16", "target_controller": None,
     "target_layout": {"face": {"layout": "row", "count": 2, "labels": ["II", "I"]},
                       "dpad": True, "sticks": 0, "shoulders": 0, "start": True, "select": True,
                       "label": "PC Engine — D-pad + 2 (Run/Sel)"},
     "fixed_mapping_note": "RetroPad → PCE: B=II · Y=I (BY-style — Beetle PCE default, NOT BA) · Start=Run · Select=Select. 6-button adds: A=III · X=IV · L=V · R=VI"},

    # --- Tier 2: popular arcade / specialty ---
    {"id": "mame",         "name": "MAME", "target_controller": None,
     "fixed_mapping_note": "RetroPad → MAME: B=Button 1 · A=Button 2 · Y=Button 3 · X=Button 4 · L=Button 5 · R=Button 6 · L2=Button 7 · R2=Button 8 · Select=Coin · Start=Start (per-game ROMs may override; mame2003-plus / mame_libretro default)"},
    {"id": "fbneo",        "name": "FinalBurn Neo", "target_controller": None,
     "fixed_mapping_note": "RetroPad → FBNeo: B=Button 1 · A=Button 2 · Y=Button 3 · X=Button 4 · L=Button 5 · R=Button 6 · Select=Coin · Start=Start (per-driver overrides apply for fighting games)"},
    {"id": "neogeo",       "name": "SNK Neo Geo", "target_controller": None,
     "fixed_mapping_note": "RetroPad → Neo Geo: B=A · A=B · Y=C · X=D · Select=Coin · Start=Start (FBNeo / NeoGeo standard 4-button)"},
    {"id": "neogeocd",     "name": "SNK Neo Geo CD", "target_controller": None,
     "fixed_mapping_note": "RetroPad → Neo Geo CD: B=A · A=B · Y=C · X=D · Select=Select · Start=Start (NeoCD / FBNeo)"},
    {"id": "cps1",         "name": "Capcom CPS-1", "target_controller": None,
     "fixed_mapping_note": "RetroPad → CPS-1: B=Light Punch · A=Med Punch · R=Heavy Punch · Y=Light Kick · X=Med Kick · L=Heavy Kick · Select=Coin · Start=Start (FBNeo SF2 layout)"},
    {"id": "cps2",         "name": "Capcom CPS-2", "target_controller": None,
     "fixed_mapping_note": "RetroPad → CPS-2: B=Light Punch · A=Med Punch · R=Heavy Punch · Y=Light Kick · X=Med Kick · L=Heavy Kick · Select=Coin · Start=Start (FBNeo SSF2/MvC layout)"},
    {"id": "cps3",         "name": "Capcom CPS-3", "target_controller": None,
     "fixed_mapping_note": "RetroPad → CPS-3: B=Light Punch · A=Med Punch · R=Heavy Punch · Y=Light Kick · X=Med Kick · L=Heavy Kick · Select=Coin · Start=Start (FBNeo SF3/JoJo layout)"},

    # --- Tier 3: handhelds / niche-but-popular ---
    {"id": "lynx",         "name": "Atari Lynx", "target_controller": None,
     "fixed_mapping_note": "RetroPad → Lynx: B=B · A=A · Y=Option 1 · X=Option 2 · Start=Pause · D-pad=D-pad (Handy / Beetle Lynx)"},
    {"id": "wonderswan",   "name": "Bandai WonderSwan", "target_controller": None,
     "fixed_mapping_note": "RetroPad → WonderSwan: B=B · A=A · Y=Y1 · X=Y2 · Start=Start · L=X1 · R=X2 (Beetle Cygne / Mednafen Wswan; vertical mode rotates Y/X cluster to D-pad)"},
    {"id": "wswan",        "name": "Bandai WonderSwan", "target_controller": None,
     "fixed_mapping_note": "RetroPad → WonderSwan: B=B · A=A · Y=Y1 · X=Y2 · Start=Start · L=X1 · R=X2 (some es_systems.cfg variants use 'wswan' as the id)"},
    {"id": "ngp",          "name": "SNK Neo Geo Pocket", "target_controller": None,
     "fixed_mapping_note": "RetroPad → NGP: B=B · A=A · Start=Option · D-pad=D-pad (Beetle NeoPop — only 2 buttons + Option)"},
    {"id": "ngpc",         "name": "SNK Neo Geo Pocket Color", "target_controller": None,
     "fixed_mapping_note": "RetroPad → NGPC: B=B · A=A · Start=Option · D-pad=D-pad (Beetle NeoPop)"},
    {"id": "atari2600",    "name": "Atari 2600", "target_controller": None,
     "fixed_mapping_note": "RetroPad → Atari 2600: B=Fire · Select=Select · Start=Reset · D-pad=joystick (Stella default — the 2600 only has one fire button)"},
    {"id": "atari7800",    "name": "Atari 7800", "target_controller": None,
     "fixed_mapping_note": "RetroPad → Atari 7800: B=Button 1 · A=Button 2 · Select=Select · Start=Pause · D-pad=joystick (ProSystem default)"},

    # --- Tier 4: retro home computers (heavier keyboard takeover) ---
    {"id": "atarist",      "name": "Atari ST", "target_controller": "joystick_1btn",
     "fixed_mapping_note": "Hatari: D-pad/stick → joy direction · B → fire · keyboard pass-through for Help/Undo/F-keys (Atari ST is single-button-joystick natively, hence joystick_1btn target)"},
    {"id": "zxspectrum",   "name": "Sinclair ZX Spectrum", "target_controller": "joystick_1btn",
     "fixed_mapping_note": "Fuse: D-pad/stick → Kempston joy · B → fire · keyboard pass-through for game-specific keys (default Kempston interface; Sinclair-1/Sinclair-2/Cursor configurable per-game)"},
    {"id": "msx",          "name": "MSX", "target_controller": "joystick_1btn",
     "fixed_mapping_note": "blueMSX / fMSX: D-pad/stick → joy · B → trigger A · A → trigger B · keyboard pass-through for SPACE/ESC/F-keys"},
    {"id": "msx1",         "name": "MSX", "target_controller": "joystick_1btn",
     "fixed_mapping_note": "blueMSX / fMSX: D-pad/stick → joy · B → trigger A · A → trigger B · keyboard pass-through for SPACE/ESC/F-keys"},
    {"id": "amstradcpc",   "name": "Amstrad CPC", "target_controller": "joystick_1btn",
     "fixed_mapping_note": "Caprice32 (cap32): D-pad/stick → joy · B → fire 1 · A → fire 2 · X → SPACE · keyboard pass-through configurable via cap32_combokey"},
    {"id": "colecovision", "name": "ColecoVision", "target_controller": "colecovision_pad",
     "fixed_mapping_note": "blueMSX (libretro): D-pad → joy · B = Fire 1 (red button 1) · A = Fire 2 (red button 2) · Y = keypad * · X = keypad # · Select / Start unmapped (12-key keypad accessed via core overlay for less-common keys)"},

    # --- Tier 5: arcade hardware (per user request — usually straightforward) ---
    # Sega Naomi family: Atomiswave shares Naomi ROM board, mapping is identical.
    {"id": "naomi",        "name": "Sega Naomi", "target_controller": None,
     "fixed_mapping_note": "Flycast: D-pad/stick → joy · B=A · A=B · X=X · Y=Y · L=Coin · R=Start (1P) · stick = analog when game supports it"},
    {"id": "naomi2",       "name": "Sega Naomi 2", "target_controller": None,
     "fixed_mapping_note": "Flycast: same as Naomi — B=A · A=B · X=X · Y=Y · L=Coin · R=Start"},
    {"id": "atomiswave",   "name": "Sammy Atomiswave", "target_controller": None,
     "fixed_mapping_note": "Flycast: B=A · A=B · X=X · Y=Y · L=Coin · R=Start (Naomi-derived hardware, identical pad mapping)"},
    # Sega Model 2/3 / Chihiro / Triforce — emulator-launched (m2emulator / Supermodel / Dolphin)
    {"id": "model2",       "name": "Sega Model 2", "target_controller": None,
     "fixed_mapping_note": "m2emulator: D-pad → joy · B/A/X/Y → arcade button 1-4 · L=button 5 · R=button 6 · Select=Coin · Start=Start (per-game button count varies; check the game's I/O panel)"},
    {"id": "model3",       "name": "Sega Model 3", "target_controller": None,
     "fixed_mapping_note": "Supermodel: B/A/X/Y → arcade button 1-4 · L=button 5 · R=button 6 · Select=Coin · Start=Start · L3/R3 → service / test (Daytona steering needs analog stick)"},
    {"id": "chihiro",      "name": "Sega Chihiro", "target_controller": None,
     "fixed_mapping_note": "Cxbx-R: B=A · A=B · X=X · Y=Y · L=Black · R=White · Select=Back · Start=Start (Xbox-derived hardware, native Xbox controller mapping)"},
    {"id": "triforce",     "name": "Triforce (Nintendo+Sega+Namco)", "target_controller": None,
     "fixed_mapping_note": "Dolphin: GameCube-style — B=A · A=B · X=X · Y=Y · L=L · R=R · Z=Z (Z usually L2/R2) · Start=Start"},
    # Daphne — laserdisc games. Single Action button + Start.
    {"id": "daphne",       "name": "Daphne (laserdisc)", "target_controller": None,
     "fixed_mapping_note": "hypseus-singe: D-pad → joy · B = Action 1 · A = Action 2 · X = Action 3 · Select = Coin · Start = Start (most games use 1-2 action buttons; Dragon's Lair: B = Sword)"},
    # Cave shmup hardware
    {"id": "cave",         "name": "Cave Arcade", "target_controller": None,
     "fixed_mapping_note": "FBNeo: B = Shot · A = Bomb · X = Auto-fire · Y = (unused on most) · Select = Coin · Start = Start"},
    # Gaelco — Spanish arcade boards
    {"id": "gaelco",       "name": "Gaelco Arcade", "target_controller": None,
     "fixed_mapping_note": "MAME: D-pad → joy · B/A/X/Y → arcade button 1-4 · Select = Coin · Start = Start (button count varies — World Rally uses 1, Speed Up uses analog wheel)"},
    # Namco arcade family
    {"id": "namco2x6",     "name": "Namco System 246/256", "target_controller": None,
     "fixed_mapping_note": "PCSX2 / play!: PS2-derived — B=Cross · A=Circle · X=Square · Y=Triangle · L=L1 · R=R1 · L2=L2 · R2=R2 · Select=Select · Start=Start"},
    # HBMAME — homebrew MAME variant, identical mapping.
    {"id": "hbmame",       "name": "HBMAME (homebrew MAME)", "target_controller": None,
     "fixed_mapping_note": "MAME: same as MAME — D-pad → joy · B/A/X/Y → arcade button 1-4 · L/R/L2/R2 → button 5-8 · Select = Coin · Start = Start"},

    # --- Tier 6: personal request (Odyssey2 / Videopac) ---
    {"id": "odyssey2",     "name": "Magnavox Odyssey² / Philips Videopac", "target_controller": "joystick_1btn",
     "fixed_mapping_note": "O2EM: D-pad/stick → joy · B = Action button (single-action controller) · keyboard pass-through for the console's built-in alphanumeric keyboard (Voice/Quest games)"},
]


def _load_systems_from_retrobat() -> list[dict]:
    """Parse es_systems.cfg and return one dict per `<system>` element.

    Mirrors the small parser in audit_media.py (kept inlined to avoid
    importing audit_media at GUI startup). Returns [] if the install
    isn't detected or the file is missing/unparseable.
    """
    if RETROBAT_ROOT is None or not ES_SYSTEMS_CFG.exists():
        return []
    try:
        tree = xml_safe.safe_parse(ES_SYSTEMS_CFG)
    except ET.ParseError as e:
        print(f"[rbcf_gui] could not parse es_systems.cfg: {e}", file=sys.stderr)
        return []
    except xml_safe.XMLSecurityError as e:
        print(f"[rbcf_gui] {e}", file=sys.stderr)
        return []
    out: list[dict] = []
    for sys_node in tree.getroot().findall("system"):
        name = (sys_node.findtext("name") or "").strip()
        if not name:
            continue
        fullname = (sys_node.findtext("fullname") or "").strip()
        ext_raw = (sys_node.findtext("extension") or "").strip()
        exts = [tok.lower() for tok in ext_raw.split() if tok.startswith(".")]
        out.append({
            "id": name,
            "name": fullname or name,
            "target_controller": None,
            "fixed_mapping_note": None,
            "extensions": exts,
        })
    out.sort(key=lambda s: s["name"].lower())
    return out


def _merge_systems() -> list[dict]:
    """Merge discovered systems with HARDCODED_SYSTEMS metadata overlay.

    The hardcoded entry's `name`, `target_controller`, `fixed_mapping_note`
    win for ids present in both lists; the discovered `extensions` is
    preserved. If RetroBat isn't detected, falls back to HARDCODED_SYSTEMS
    only so the editor still works for the curated 4.
    """
    discovered = _load_systems_from_retrobat()
    if not discovered:
        # No install detected — return curated 4 with empty extensions.
        return [{**s, "extensions": []} for s in HARDCODED_SYSTEMS]
    overlay = {s["id"]: s for s in HARDCODED_SYSTEMS}
    merged: list[dict] = []
    for entry in discovered:
        ov = overlay.get(entry["id"])
        if ov is not None:
            merged_entry = {
                "id": entry["id"],
                "name": ov["name"],
                "target_controller": ov["target_controller"],
                "fixed_mapping_note": ov["fixed_mapping_note"],
                "extensions": entry["extensions"],
            }
            # Optional: target_layout descriptor for generic SVG generation
            if "target_layout" in ov:
                merged_entry["target_layout"] = ov["target_layout"]
            merged.append(merged_entry)
        else:
            merged.append(entry)
    # If a hardcoded entry has no matching <system> in es_systems.cfg
    # (unusual — install missing the system folder?), still surface it so
    # the editor remains usable for that curated system.
    discovered_ids = {e["id"] for e in discovered}
    for hc in HARDCODED_SYSTEMS:
        if hc["id"] not in discovered_ids:
            merged.append({**hc, "extensions": []})
    merged.sort(key=lambda s: s["name"].lower())
    return merged


# Module-level cache, mirroring the KNOWN_CONTROLLERS = load_catalog() pattern.
SYSTEMS = _merge_systems()


def refresh_systems():
    """Re-read es_systems.cfg and rebuild the merged SYSTEMS list."""
    global SYSTEMS
    SYSTEMS = _merge_systems()

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

def _find_image_for(vid: str, pid: str) -> str:
    """Look up the best image URL for a VID:PID.

    Preference order:
      1. gui/img/contrib/<VID>_<PID>.<ext>  (user-supplied via the cog UI)
      2. gui/img/known/<VID>_<PID>.<ext>    (synced from controller_sync)
      3. ""                                  (no local image)

    Within each directory, extensions are tried in IMG_EXT_PREF order.
    Returns a relative URL like "/img/contrib/2DC8_310B.png" or "".
    """
    for base_dir, url_prefix in (
        (CONTRIB_IMG_DIR, "/img/contrib/"),
        (KNOWN_IMG_DIR, "/img/known/"),
    ):
        if not base_dir.exists():
            continue
        for ext in IMG_EXT_PREF:
            p = base_dir / f"{vid}_{pid}{ext}"
            if p.exists():
                return url_prefix + p.name
    return ""


def load_catalog() -> dict:
    """Read controller_catalog.yaml and produce a VID:PID → metadata map.

    Image URLs prefer user-uploaded contrib (gui/img/contrib/) over the
    sync cache (gui/img/known/); empty string when neither exists.
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
        out[key] = {
            "name": entry.get("name") or key,
            "image": _find_image_for(vid, pid),
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
        else:
            # Even for catalog-misses, surface a contrib/known image if the
            # user has uploaded one for this VID:PID via the settings cog.
            img = _find_image_for(entry["vid"], entry["pid"])
            if img:
                entry["image"] = img
        out_list.append(entry)
    out_list.sort(key=lambda e: (not e["xinput"], not e.get("name"), e["key"]))
    return out_list


def system_extensions(system: str) -> set[str]:
    """Read es_systems.cfg and return the file extensions for this system."""
    if not ES_SYSTEMS_CFG.exists():
        return set()
    try:
        tree = xml_safe.safe_parse(ES_SYSTEMS_CFG)
    except (ET.ParseError, xml_safe.XMLSecurityError):
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


def system_default_path(system: str) -> Path:
    return PROFILES_DIR / system / "_default.yaml"


def load_profile(system: str, rom: str) -> dict:
    p = profile_path(system, rom)
    if not p.exists():
        return {}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        return {"_error": f"YAML parse error: {e}"}


def load_system_default(system: str) -> dict:
    """Load <system>/_default.yaml if it exists. Used by Flow 4 (game-detail
    view) so the frontend can compute the inheritance overlay client-side
    without re-implementing _default.yaml resolution."""
    if not system:
        return {}
    p = system_default_path(system)
    if not p.exists():
        return {}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        return {"_error": f"YAML parse error: {e}"}


# ============================================================
# Click-across remap (Task 4 of v0.1.3-stretch — partial scope)
# ------------------------------------------------------------
# Per-game RetroArch input remaps written to:
#   <RetroBat>/emulators/retroarch/config/remaps/<core display>/<rom>.rmp
#
# Each line has the form:
#   input_remap_id_1_btn_<source> = <libretro_index>
#
# i.e. "physical RetroPad <source> button now produces what RetroPad
# <libretro_index> normally produces". Values 0..15 are the standard
# libretro RetroPad indices (B=0, Y=1, Select=2, Start=3, U/D/L/R=4..7,
# A=8, X=9, L=10, R=11, L2=12, R2=13, L3=14, R3=15).
#
# In v0.1.3 we only enable click-across for systems lacking
# `fixed_mapping_note` — the curated set keeps RetroBat's defaults.
# ============================================================

# Common defaults so users get *something* even on systems where
# es_settings.cfg hasn't been touched. Subset — extends naturally as we
# learn more.
DEFAULT_CORE_FOR_SYSTEM = {
    "snes":         "snes9x",
    "sfc":          "snes9x",
    "nes":          "fceumm",
    "fds":          "fceumm",
    "megadrive":    "genesis_plus_gx",
    "genesis":      "genesis_plus_gx",
    "mastersystem": "genesis_plus_gx",
    "gamegear":     "genesis_plus_gx",
    "sega32x":      "picodrive",
    "segacd":       "genesis_plus_gx",
    "gb":           "gambatte",
    "gbc":          "gambatte",
    "gba":          "mgba",
    "n64":          "mupen64plus_next",
    "psx":          "swanstation",
    "saturn":       "kronos",
    "dreamcast":    "flycast",
    "pcengine":     "mednafen_pce",
    "pcenginecd":   "mednafen_pce",
    "supergrafx":   "mednafen_supergrafx",
    "ngp":          "mednafen_ngp",
    "ngpc":         "mednafen_ngp",
    "lynx":         "handy",
    "wonderswan":   "mednafen_wswan",
    "wswan":        "mednafen_wswan",
    "atari2600":    "stella",
    "atari7800":    "prosystem",
    "neogeo":       "fbneo",
    "neogeocd":     "neocd",
    "mame":         "mame",
    "fbneo":        "fbneo",
    "cps1":         "fbalpha2012_cps1",
    "cps2":         "fbalpha2012_cps2",
    "cps3":         "fbalpha2012_cps3",
    "amstradcpc":   "cap32",
    "zxspectrum":   "fuse",
    "msx":          "bluemsx",
    "msx2":         "bluemsx",
    "atarist":      "hatari",
    "thomson":      "theodore",
    "c64":          "vice_x64",
}


def core_for_system(system_id: str) -> str | None:
    """Find the libretro core_id RetroBat uses for a system.

    Reads `<system>.core` from es_settings.cfg first (user override),
    falls back to DEFAULT_CORE_FOR_SYSTEM. Returns None if neither
    knows; callers should error out.
    """
    if not system_id:
        return None
    # Prefer user override from es_settings.cfg
    try:
        es_path = RETROBAT_ROOT / "emulationstation" / ".emulationstation" / "es_settings.cfg"
        if es_path.exists():
            text = es_path.read_text(encoding="utf-8", errors="ignore")
            m = re.search(rf'<string name="{re.escape(system_id)}\.core" value="([^"]+)"',
                          text)
            if m:
                return m.group(1)
    except (OSError, AttributeError):
        pass
    return DEFAULT_CORE_FOR_SYSTEM.get(system_id)


def core_display_name(core_id: str) -> str | None:
    """Read the libretro info file to find the FOLDER name RetroArch uses
    under config/remaps/. That's the `corename` field (short, e.g.
    "Snes9x" / "VICE x64") — NOT `display_name` which is longer
    ("Nintendo - SNES / SFC (Snes9x)"). Falls back to display_name only
    if corename is missing."""
    if not core_id or RETROBAT_ROOT is None:
        return None
    info_path = RETROBAT_ROOT / "emulators" / "retroarch" / "info" / f"{core_id}_libretro.info"
    if not info_path.exists():
        return None
    corename = None
    display = None
    try:
        for line in info_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = re.match(r'\s*corename\s*=\s*"([^"]+)"', line)
            if m: corename = m.group(1).strip(); continue
            m = re.match(r'\s*display_name\s*=\s*"([^"]+)"', line)
            if m: display = m.group(1).strip()
    except OSError:
        pass
    return corename or display


def remap_path(system_id: str, rom: str) -> Path | None:
    """Resolve the per-game .rmp path for a (system, rom) pair, or None
    if any lookup along the chain fails."""
    if RETROBAT_ROOT is None:
        return None
    cid = core_for_system(system_id)
    if not cid:
        return None
    disp = core_display_name(cid)
    if not disp:
        return None
    # Strip any extension off the rom basename for the .rmp filename
    rom_stem = Path(rom).stem
    return (RETROBAT_ROOT / "emulators" / "retroarch" / "config" / "remaps"
            / disp / f"{rom_stem}.rmp")


# Standard libretro RetroPad button indices. Values 0..15.
LIBRETRO_BUTTON_INDEX = {
    "b": 0, "y": 1, "select": 2, "start": 3,
    "up": 4, "down": 5, "left": 6, "right": 7,
    "a": 8, "x": 9, "l": 10, "r": 11,
    "l2": 12, "r2": 13, "l3": 14, "r3": 15,
}


def read_remap(system: str, rom: str) -> dict:
    """Return current per-source remap values from the .rmp, plus the
    resolved path so the UI can show whether persistence is wired up."""
    out = {"path": None, "core": None, "display": None, "bindings": {}, "exists": False}
    p = remap_path(system, rom)
    cid = core_for_system(system)
    out["core"] = cid
    if cid:
        out["display"] = core_display_name(cid)
    if p is None:
        return out
    out["path"] = str(p).replace("\\", "/")
    if not p.exists():
        return out
    out["exists"] = True
    pat = re.compile(r'^input_remap_id_1_btn_([a-z0-9]+)\s*=\s*"?(-?\d+)"?\s*$')
    try:
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = pat.match(line.strip())
            if not m:
                continue
            src, idx = m.group(1), int(m.group(2))
            out["bindings"][src] = idx
    except OSError:
        pass
    return out


def write_remap(data: dict) -> dict:
    """Write a single physical-source → libretro-index binding into the
    per-game .rmp. Body schema:
        {system, rom, source: "a", target_index: 0}
        — or —
        {system, rom, bindings: {a:0, b:8, ...}, replace: false}
    Replace=false (default) merges with existing bindings; replace=true
    rewrites the file from scratch.
    """
    system = (data.get("system") or "").strip()
    rom = (data.get("rom") or "").strip()
    if not system or not rom:
        return {"ok": False, "error": "missing 'system' or 'rom'"}
    p = remap_path(system, rom)
    if p is None:
        return {"ok": False, "error": "could not resolve core for this system "
                "(missing es_settings.cfg / core not in DEFAULT_CORE_FOR_SYSTEM)"}

    # Compose desired binding set
    target = {}
    if isinstance(data.get("bindings"), dict):
        for k, v in data["bindings"].items():
            if k in LIBRETRO_BUTTON_INDEX and isinstance(v, int) and 0 <= v <= 15:
                target[k] = v
    elif "source" in data and "target_index" in data:
        src = str(data["source"]).strip().lower()
        idx = int(data["target_index"])
        if src not in LIBRETRO_BUTTON_INDEX:
            return {"ok": False, "error": f"unknown source button '{src}'"}
        if not (0 <= idx <= 15):
            return {"ok": False, "error": f"target_index out of range: {idx}"}
        target[src] = idx
    else:
        return {"ok": False, "error": "no bindings supplied"}

    # Merge with existing unless replace=true
    existing_lines = []
    existing_bindings = {}
    if p.exists():
        try:
            existing_lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
            pat = re.compile(r'^input_remap_id_1_btn_([a-z0-9]+)\s*=\s*"?(-?\d+)"?\s*$')
            for line in existing_lines:
                m = pat.match(line.strip())
                if m:
                    existing_bindings[m.group(1)] = int(m.group(2))
        except OSError:
            pass

    if data.get("replace"):
        merged = target
    else:
        merged = {**existing_bindings, **target}
        # Allow explicit-clear via target_index = -1
        merged = {k: v for k, v in merged.items() if v >= 0}

    # Write — preserve any non-`btn_` lines RetroArch may have written
    # (analog dpad mode, device type, turbo etc.). Only replace our keys.
    p.parent.mkdir(parents=True, exist_ok=True)
    out_lines = []
    keys_seen = set()
    for line in existing_lines:
        m = re.match(r'^(input_remap_id_1_btn_)([a-z0-9]+)\s*=', line.strip())
        if m:
            keys_seen.add(m.group(2))
            if m.group(2) in merged:
                out_lines.append(f'input_remap_id_1_btn_{m.group(2)} = "{merged[m.group(2)]}"')
            # else: drop the line (key cleared)
        else:
            if line.strip():
                out_lines.append(line)
    # New keys that didn't exist yet
    for src, idx in merged.items():
        if src not in keys_seen:
            out_lines.append(f'input_remap_id_1_btn_{src} = "{idx}"')
    p.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return {"ok": True, "path": str(p).replace("\\", "/"), "bindings": merged}


def list_templates(system: str) -> list[dict]:
    """List profile templates available for a given system.

    Templates live in profile_templates/<system>/<name>.yaml — they're
    profile YAMLs without a `rom:` field but WITH a `template:` field that
    names them for the picker UI. Returns metadata only; the GUI fetches
    the full YAML via /api/template?system=X&id=Y when the user selects
    one.
    """
    out = []
    if not system:
        return out
    sys_dir = TEMPLATES_DIR / system
    if not sys_dir.is_dir():
        return out
    for yml in sorted(sys_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(yml.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        out.append({
            "id": yml.stem,                              # filename sans .yaml
            "name": data.get("template") or yml.stem,
            "description": (data.get("description") or "").strip(),
        })
    return out


def load_template(system: str, template_id: str) -> dict:
    if not system or not template_id:
        return {}
    safe_id = re.sub(r"[^A-Za-z0-9_\-]", "", template_id)
    p = TEMPLATES_DIR / system / f"{safe_id}.yaml"
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


def launch_test(data: dict) -> dict:
    """Launch RetroBat with a specific ROM for live mapping testing.

    Phase A (v0.1.3): spawn RetroBat.exe with -system / -rom args. Don't
    wait for it; user can close it whenever and the GUI stays responsive.
    Window-docking via ctypes/SetWindowPos is parked for v0.1.3-stretch
    or v0.1.4 — see v0.1.3-PLAN.md Task 4 notes.
    """
    system = (data.get("system") or "").strip()
    rom = (data.get("rom") or "").strip()
    if not system or not rom:
        return {"ok": False, "error": "missing 'system' or 'rom'"}
    if RETROBAT_ROOT is None:
        return {"ok": False, "error": "RetroBat root not configured"}
    rom_path = ROMS_ROOT / system / rom
    if not rom_path.exists():
        return {"ok": False, "error": f"ROM not found: {rom_path}"}
    retrobat_exe = RETROBAT_ROOT / "RetroBat.exe"
    if not retrobat_exe.exists():
        return {"ok": False, "error": f"RetroBat.exe not found at {retrobat_exe}"}

    # Conservative arg set — `-rom` alone tells RetroBat to launch into the
    # ROM via its own launch pipeline (es_systems.cfg + emulatorLauncher).
    # If RetroBat ignores -rom in some configurations we can fall back to
    # spawning emulatorLauncher.exe directly with full argv.
    cmd = [str(retrobat_exe), "-system", system, "-rom", str(rom_path)]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(RETROBAT_ROOT),
            # CREATE_NEW_PROCESS_GROUP so closing our server doesn't kill
            # the emulator. Windows-only flag.
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    except OSError as e:
        return {"ok": False, "error": f"spawn failed: {e}"}

    return {
        "ok": True,
        "pid": proc.pid,
        "system": system,
        "rom": rom,
        "rom_path": str(rom_path).replace("\\", "/"),
        "cmd": " ".join(cmd),
    }


def run_apply() -> dict:
    """Run `rbcf apply` in-process by importing and calling cmd_apply().

    Was previously a subprocess against rbcf.py, but PyInstaller bundles
    the .py source into the PYZ archive — there's no rbcf.py file on
    disk in the .exe distribution. Calling cmd_apply directly works in
    both dev and frozen modes, has zero spawn cost, and captures the
    result more cleanly.
    """
    import contextlib
    import io
    try:
        from rbcf import load_profiles as _load_profiles, cmd_apply as _cmd_apply
    except ImportError as e:
        return {"ok": False, "error": f"rbcf module unavailable: {e}"}

    profiles = _load_profiles()
    if not profiles:
        return {"ok": True, "stdout": "[info] no profiles found",
                "stderr": "", "returncode": 0}

    out_buf = io.StringIO()
    err_buf = io.StringIO()
    rc = 0
    try:
        with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
            _cmd_apply(profiles, target_id=None)
    except SystemExit as e:
        # cmd_apply uses sys.exit on fatal errors (e.g. unknown target_id);
        # we pass target_id=None so this shouldn't fire, but guard anyway.
        rc = int(e.code) if isinstance(e.code, int) else 1
    except Exception as e:  # noqa: BLE001 — surface any apply failure to the UI
        return {
            "ok": False,
            "stdout": out_buf.getvalue(),
            "stderr": err_buf.getvalue() + f"\n[apply] uncaught: {e}",
            "returncode": 1,
            "error": str(e),
        }
    return {
        "ok": rc == 0,
        "stdout": out_buf.getvalue(),
        "stderr": err_buf.getvalue(),
        "returncode": rc,
    }


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


def _count_roms_in_system(system_dir: Path,
                           sys_name: str | None = None,
                           excludes: dict | None = None) -> int:
    """Count ROM files recursively under a system folder, skipping reserved
    asset subdirs and hidden / dotfiles. Used by /api/scan only — list_roms()
    above is the canonical per-system enumerator for the editor flow.

    Honours per-user excludes when sys_name + excludes are provided.
    """
    if not system_dir.exists() or not system_dir.is_dir():
        return 0
    excluded_names = set()
    if sys_name and excludes:
        excluded_names = {p.split("/")[0] for p in excludes.get(sys_name, [])}
    total = 0
    try:
        for entry in system_dir.iterdir():
            name = entry.name
            if name.startswith("."):
                continue
            if entry.is_dir():
                if name.lower() in ONBOARD_RESERVED_DIRS:
                    continue
                if name in excluded_names:
                    continue
                if (entry / ".rbcf-ignore").is_file():
                    continue
                # Recurse into non-reserved subdir (rare: multi-disk folders, etc.)
                # Don't pass excludes deeper — the JSON keys are top-level subdirs.
                total += _count_roms_in_system(entry)
                continue
            if entry.is_file():
                total += 1
    except OSError:
        return total
    return total


def _iter_rom_files(system_dir: Path,
                     sys_name: str | None = None,
                     excludes: dict | None = None):
    """Yield Path objects for every ROM file under a system dir, skipping
    reserved asset subdirs, hidden entries, and dotfiles.

    When sys_name + excludes are provided, also skips any top-level
    subdir whose name appears in the system's exclude list, plus any
    subtree containing a `.rbcf-ignore` marker file.
    """
    if not system_dir.exists() or not system_dir.is_dir():
        return
    excluded_names: set[str] = set()
    if sys_name and excludes:
        excluded_names = {p.split("/")[0] for p in excludes.get(sys_name, [])}
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
            if name in excluded_names:
                continue
            if (entry / ".rbcf-ignore").is_file():
                continue
            # Recurse for any other subdir. Don't propagate excludes into
            # the recursion — the JSON's keys are immediate children of
            # the system dir, not arbitrary deep paths.
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
        # Filter out RetroBat systems the user has zero ROMs for AND
        # zero profiles for. These are typically integration stubs
        # (Amazon Luna, "2ship", etc.) declared in es_systems.cfg but
        # never actually populated. Showing them as 0/0/0 rows in the
        # onboarding scan is noise.
        if rom_count == 0 and profiles_count == 0:
            continue
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


# -------- per-user scaffold excludes (v0.1.1) --------
#
# Lives at %APPDATA%/RB-Controller_fix/scaffold-excludes.json with shape:
#   {"<system_id>": ["Demos", "Other-subdir"], ...}
# Entries are top-level subdirectory names under the system's ROM dir.
# `.rbcf-ignore` drop-in files are also honoured by _iter_rom_files —
# both mechanisms compose; the file is the power-user gitignore-style
# escape hatch, the JSON is what the GUI manages via its modal.

def _scaffold_excludes_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "RB-Controller_fix" / "scaffold-excludes.json"
    return ROOT / ".scaffold-excludes.json"


SCAFFOLD_EXCLUDES_PATH = _scaffold_excludes_path()


def _load_excludes() -> dict[str, list[str]]:
    """Returns {system_id: [relative_path_under_system_rom_dir]}."""
    try:
        if not SCAFFOLD_EXCLUDES_PATH.is_file():
            return {}
        data = json.loads(SCAFFOLD_EXCLUDES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    # Defensive: only keep string keys mapping to list-of-string values.
    out: dict[str, list[str]] = {}
    for k, v in data.items():
        if isinstance(k, str) and isinstance(v, list):
            out[k] = [s for s in v if isinstance(s, str)]
    return out


def _save_excludes(excludes: dict[str, list[str]]) -> None:
    """Persists; ensures parent dir exists; pretty-printed JSON."""
    SCAFFOLD_EXCLUDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCAFFOLD_EXCLUDES_PATH.write_text(
        json.dumps(excludes, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _validate_exclude_entry(entry: str) -> bool:
    """Path-traversal guard. Reject anything that climbs out of the
    system's ROM dir, names a drive, or is absolute. Each entry must be
    a simple relative subdir name (or limited slash-joined relative path).
    """
    if not isinstance(entry, str) or not entry.strip():
        return False
    e = entry.strip().replace("\\", "/")
    if e.startswith("/") or e.startswith("./") or e == "." or e == "..":
        return False
    if ".." in e.split("/"):
        return False
    if len(e) >= 2 and e[1] == ":":  # drive letter
        return False
    return True


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
    excludes = _load_excludes()

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
        rom_count = _count_roms_in_system(sys_dir, sys_name, excludes)
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
        for rom_path in _iter_rom_files(sys_dir, sys_name, excludes):
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


# -------- streaming scaffold (v0.1.1 progress bar) --------
#
# These build the same write-list as the non-streaming variants, then
# yield SSE events as each file is written so the UI can show a progress
# bar instead of a "frozen" spinner.

def _scaffold_build_write_list(mode: str) -> list[tuple[Path, dict]]:
    """Compute the (target_path, scaffold_dict) work list for the
    given mode without writing anything. The non-streaming variants
    inline this logic; the streaming variants call it then iterate.

    `mode` must be 'all' or 'defaults'. We re-use the non-streaming
    variant in preview mode (apply=False) and steal its result['preview']
    structure to figure out what to write — but for cleanliness we
    inline the build here so the work list is the source of truth.
    """
    # Cleanest path: call the non-streaming variant in preview mode and
    # then rebuild write_targets from result['preview']. That keeps the
    # write logic in one place. The cost is a second walk through the
    # tree but it's identical work either way.
    if mode == "all":
        result = _scaffold_all(apply=False)
    else:
        result = _scaffold_defaults(apply=False)
    today = date.today().isoformat()
    write_list: list[tuple[Path, dict]] = []
    for entry in result.get("preview", []):
        sys_name = entry.get("system")
        rom = entry.get("rom")
        path_rel = entry.get("path", "")
        # Reconstruct the target path under PROFILES_DIR.
        target = PROFILES_DIR / sys_name / Path(path_rel).name
        if rom:
            scaffold = {
                "system": sys_name, "rom": rom,
                "title": Path(rom).stem,
                "confidence": "T",
                "notes": (
                    f"Auto-scaffolded by /api/scaffold-{mode} on {today}.\n"
                    f"Inherits from {sys_name}/_default.yaml. "
                    f"Promote to V or K once verified.\n"
                ),
                "es_settings": {}, "core_options": {},
            }
        else:
            scaffold = {
                "system": sys_name,
                "title": f"{sys_name} (system default)",
                "confidence": "T",
                "notes": (
                    f"Auto-scaffolded by /api/scaffold-{mode} on {today}.\n"
                    f"Empty placeholder — fill in es_settings / "
                    f"core_options as you verify which keys survive "
                    f"RetroBat regeneration.\n"
                ),
                "es_settings": {}, "core_options": {},
            }
        write_list.append((target, scaffold))
    return write_list


def _scaffold_stream_events(mode: str):
    """Yield SSE event dicts for streaming scaffold-{all,defaults}/stream
    with apply=true. Throttles 'progress' events to 1 per ~1% increment OR
    every 50 files (whichever fires more often).
    """
    write_list = _scaffold_build_write_list(mode)
    total = len(write_list)
    yield {"event": "start", "total": total}

    profiles_root = PROFILES_DIR.resolve()
    written: list[str] = []
    skipped_count = 0
    last_progress_pct = -1
    files_since_last = 0

    for idx, (target, scaffold) in enumerate(write_list, 1):
        rel_display = f"profiles/{target.parent.name}/{target.name}"
        try:
            resolved_parent = target.parent.resolve()
        except OSError:
            yield {"event": "skipped", "path": rel_display, "reason": "io-error"}
            skipped_count += 1
            continue
        try:
            resolved_parent.relative_to(profiles_root)
        except ValueError:
            yield {"event": "skipped", "path": rel_display, "reason": "outside-profiles"}
            skipped_count += 1
            continue
        if target.exists():
            yield {"event": "skipped", "path": rel_display, "reason": "exists"}
            skipped_count += 1
        else:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    yaml.safe_dump(scaffold, sort_keys=False,
                                   allow_unicode=True, width=120),
                    encoding="utf-8",
                )
                written.append(rel_display)
            except OSError as e:
                yield {"event": "skipped", "path": rel_display,
                       "reason": "io-error", "error": str(e)}
                skipped_count += 1
                continue

        # Throttled progress: every 1% bucket OR every 50 files.
        files_since_last += 1
        cur_pct = (idx * 100 // total) if total else 100
        if cur_pct != last_progress_pct or files_since_last >= 50:
            yield {"event": "progress", "done": idx, "total": total,
                   "current": rel_display}
            last_progress_pct = cur_pct
            files_since_last = 0

    yield {"event": "finish", "applied": bool(written),
           "count": len(written), "written": written,
           "skipped": skipped_count}


# -------- per-system subdir listing for the excludes UI --------

def _system_subdirs(sys_name: str) -> list[dict]:
    """Return the immediate subdirectories of <ROMS_ROOT>/<sys_name>/
    along with each subdir's rom-count and current excluded state.
    """
    if RETROBAT_ROOT is None or not ROMS_ROOT.exists():
        return []
    sys_dir = ROMS_ROOT / sys_name
    if not sys_dir.is_dir():
        return []
    excludes = _load_excludes()
    excluded_names = {p.split("/")[0] for p in excludes.get(sys_name, [])}
    out: list[dict] = []
    try:
        for entry in sorted(sys_dir.iterdir(), key=lambda p: p.name.lower()):
            if not entry.is_dir():
                continue
            name = entry.name
            if name.startswith("."):
                continue
            if name.lower() in ONBOARD_RESERVED_DIRS:
                continue
            out.append({
                "name": name,
                "rom_count": _count_roms_in_system(entry),
                "excluded": name in excluded_names,
                "has_rbcf_ignore": (entry / ".rbcf-ignore").is_file(),
            })
    except OSError:
        pass
    return out


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


def _system_lookup_endpoint(data: dict) -> dict:
    """POST /api/system-lookup — surface system_lookup.lookup() result over HTTP.

    Body: ``{system, allow_online?, force_refresh?}``.

    Returns a dict shaped like LookupResult plus a ``cached`` flag (true if
    served from disk cache). If a curated entry exists for this system in
    HARDCODED_SYSTEMS we return ``source='curated'`` so the frontend can
    avoid showing a lookup affordance for systems we already cover — defence
    in depth, since the frontend already filters this case before calling.
    """
    sys_id = (data.get("system") or "").strip()
    allow_online = bool(data.get("allow_online"))
    force_refresh = bool(data.get("force_refresh"))

    if not sys_id:
        return {"ok": False, "error": "missing 'system' in body"}

    # Defence in depth: refuse to look up systems that already have curated
    # metadata. The frontend should never call us for these but we don't want
    # to ever overwrite a curated entry with a guessed online proposal.
    curated = next(
        (s for s in HARDCODED_SYSTEMS
         if s["id"] == sys_id
         and (s.get("fixed_mapping_note") or s.get("target_controller"))),
        None,
    )
    if curated is not None:
        return {
            "ok": True,
            "system_id": sys_id,
            "source": "curated",
            "name": curated.get("name"),
            "mapping_note": curated.get("fixed_mapping_note"),
            "target_controller": curated.get("target_controller"),
            "source_url": None,
            "excerpt": None,
            "error": None,
            "cached_at": None,
            "cached": False,
        }

    try:
        result = system_lookup.lookup(
            sys_id,
            allow_online=allow_online,
            force_refresh=force_refresh,
        )
    except Exception as e:
        return {"ok": False, "error": f"lookup failed: {e}"}

    payload = result.to_dict()
    payload["ok"] = True
    payload["cached"] = (result.source == "cache")
    return payload


def _system_lookup_clear(data: dict) -> dict:
    """Helper invoked by the frontend's 'Reject' button — drops the cache."""
    sys_id = (data.get("system") or "").strip() or None
    try:
        n = system_lookup.clear_cache(sys_id)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "removed": n}


def _update_check_endpoint(data: dict) -> dict:
    """POST /api/update-check — surface update_check.check_for_updates() over HTTP.

    Body: ``{allow_online?, force?}``.

    Mirrors the shape of /api/system-lookup: returns the dataclass fields
    flat under the response, plus an ``ok`` flag. The frontend reads
    ``source`` to decide what to render (cache / live / unreleased / error).
    """
    allow_online = bool(data.get("allow_online"))
    force = bool(data.get("force"))
    try:
        info = update_check.check_for_updates(allow_online=allow_online, force=force)
    except Exception as e:
        return {"ok": False, "error": f"update check failed: {e}"}
    payload = info.to_dict()
    payload["ok"] = True
    return payload


def _update_check_cached() -> dict:
    """GET /api/update-check — cached-only, never hits the network.

    Used by the frontend at page load to decide whether to render the header
    update badge without forcing a network request (and re-prompting for
    consent). Returns {ok, has_cache, ...UpdateInfo-or-empty}.
    """
    cached = update_check.load_cached()
    if cached is None:
        return {
            "ok": True,
            "has_cache": False,
            "current": RBCF_VERSION,
            "latest": None,
            "update_available": False,
            "release_url": None,
            "release_notes_excerpt": None,
            "published_at": None,
            "checked_at": "",
            "source": "cache",
            "error": None,
        }
    payload = cached.to_dict()
    payload["ok"] = True
    payload["has_cache"] = True
    return payload


# ------------------------------ GUID watcher (Phase 2) -------------------

def _watcher_get() -> dict:
    """GET /api/guid/watcher — surface guid_watcher state + recent log."""
    try:
        import guid_watcher
        state = guid_watcher.get_state()
        recent = [e.to_dict() for e in guid_watcher.read_log(limit=50)]
        return {
            "ok": True,
            "mode": state.get("mode"),
            "last_seen_mtime": state.get("last_seen_mtime"),
            "last_event_at": state.get("last_event_at"),
            "log_count": state.get("log_count", 0),
            "recent": recent,
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"watcher state read failed: {e}"}


def _watcher_set(data: dict) -> dict:
    """POST /api/guid/watcher — body: {mode}. Persist + return new mode."""
    try:
        import guid_watcher
        mode = (data.get("mode") or "").strip()
        if mode not in guid_watcher.VALID_MODES:
            return {
                "ok": False,
                "error": f"invalid mode {mode!r}; "
                         f"expected one of {list(guid_watcher.VALID_MODES)}",
            }
        guid_watcher.set_mode(mode)
        return {"ok": True, "mode": mode}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"set mode failed: {e}"}


def _watcher_fold_pending(data: dict) -> dict:
    """POST /api/guid/fold-pending — manually fold a single VID:PID group.

    Body: ``{vid, pid}``. Used when the watcher is in 'detect' mode and
    the user clicks "fold this" in the GUI for a specific group.
    """
    vid = (data.get("vid") or "").strip().lower()
    pid = (data.get("pid") or "").strip().lower()
    if not (HEX4_RE.match(vid) and HEX4_RE.match(pid)):
        return {"ok": False, "error": "vid/pid must be 4-char hex strings"}

    try:
        from config import ES_INPUT
        from guid_aliases import (
            parse_es_input, group_aliases, expand_inputconfig,
        )
    except ImportError as e:
        return {"ok": False, "error": f"alias module import failed: {e}"}

    if not ES_INPUT.exists():
        return {"ok": False, "error": f"es_input.cfg not found at {ES_INPUT}"}

    try:
        aliases = parse_es_input(ES_INPUT)
        groups = group_aliases(aliases)
        members = groups.get((vid, pid))
        if not members:
            return {
                "ok": False,
                "error": f"no alias group for vid={vid} pid={pid}",
            }
        if len(members) < 2:
            return {
                "ok": True,
                "added": 0,
                "kept": 0,
                "note": "singleton group — nothing to fold",
            }
        added, kept = expand_inputconfig(ES_INPUT, members, dry=False)
        return {
            "ok": True,
            "vid": vid,
            "pid": pid,
            "added": added,
            "kept": kept,
        }
    except (OSError, ValueError) as e:
        return {"ok": False, "error": f"fold failed: {e}"}


# ------------------------------ Controller-image upload ------------------

def _sniff_image_ext(payload: bytes) -> str | None:
    """Sniff magic bytes; return canonical extension or None.

    Returns one of ALLOWED_UPLOAD_EXTS (.png/.jpg/.webp/.svg) or None when
    the bytes don't match any allowed format.
    """
    if not payload:
        return None
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if payload.startswith(b"\xFF\xD8\xFF"):
        return ".jpg"
    # WebP: "RIFF....WEBP"
    if len(payload) >= 12 and payload[0:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return ".webp"
    # SVG: text — optional XML prologue, then "<svg" somewhere near the start.
    head = payload[:1024].lstrip()
    if head.startswith(b"<?xml"):
        # skip to first '>' then continue stripping whitespace
        try:
            head = head.split(b"?>", 1)[1].lstrip()
        except IndexError:
            head = b""
    # Allow comments / DOCTYPE before <svg.
    while head.startswith(b"<!"):
        end = head.find(b">")
        if end < 0:
            break
        head = head[end + 1:].lstrip()
    if head.startswith(b"<svg"):
        return ".svg"
    return None


def _parse_multipart(headers, body: bytes) -> dict:
    """Parse multipart/form-data using stdlib email parser.

    Returns a dict where each entry is either a string (text field) or a
    {"filename": str, "payload": bytes} dict (file field). Raises ValueError
    on unparseable / non-multipart content.
    """
    ctype = headers.get("Content-Type") or ""
    if "multipart/form-data" not in ctype.lower():
        raise ValueError("expected multipart/form-data")
    parser = BytesParser(policy=email_default_policy)
    msg = parser.parsebytes(
        b"Content-Type: " + ctype.encode("latin-1") + b"\r\n\r\n" + body
    )
    if not msg.is_multipart():
        raise ValueError("body is not multipart")
    out: dict = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        filename = part.get_filename()
        payload = part.get_payload(decode=True)
        if filename:
            out[name] = {"filename": filename, "payload": payload or b""}
        else:
            # Text field — get_payload(decode=True) returns bytes; decode utf-8.
            text = payload.decode("utf-8", errors="replace") if payload else ""
            out[name] = text
    return out


def _save_controller_image(fields: dict) -> dict:
    """POST /api/controller-image handler.

    Validates VID/PID, magic bytes, size; writes to gui/img/contrib/
    after deleting any previous contrib image for the same VID:PID under a
    different extension.
    """
    vid_raw = (fields.get("vid") or "").strip()
    pid_raw = (fields.get("pid") or "").strip()
    if not HEX4_RE.match(vid_raw):
        return {"ok": False, "error": "invalid vid (need 4 hex chars)"}
    if not HEX4_RE.match(pid_raw):
        return {"ok": False, "error": "invalid pid (need 4 hex chars)"}
    vid = vid_raw.upper()
    pid = pid_raw.upper()

    file_field = fields.get("file")
    if not isinstance(file_field, dict) or not file_field.get("payload"):
        return {"ok": False, "error": "missing file"}
    payload: bytes = file_field["payload"]
    if len(payload) > MAX_CONTRIB_IMG_BYTES:
        return {"ok": False, "error": f"too large (max {MAX_CONTRIB_IMG_BYTES} bytes)"}

    ext = _sniff_image_ext(payload)
    if not ext:
        return {"ok": False, "error": "unsupported image type (PNG/JPG/WebP/SVG only)"}

    try:
        CONTRIB_IMG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {"ok": False, "error": f"cannot create contrib dir: {e}"}

    target = CONTRIB_IMG_DIR / f"{vid}_{pid}{ext}"
    # Path-traversal guard: target must resolve under CONTRIB_IMG_DIR.
    try:
        resolved = target.resolve()
        contrib_root = CONTRIB_IMG_DIR.resolve()
        resolved.relative_to(contrib_root)
    except (OSError, ValueError):
        return {"ok": False, "error": "path traversal refused"}

    # Remove any other extension we might already have for this VID:PID.
    for other_ext in ALLOWED_UPLOAD_EXTS:
        if other_ext == ext:
            continue
        old = CONTRIB_IMG_DIR / f"{vid}_{pid}{other_ext}"
        if old.exists():
            try:
                old.unlink()
            except OSError:
                pass

    try:
        target.write_bytes(payload)
    except OSError as e:
        return {"ok": False, "error": f"write failed: {e}"}

    refresh_catalog()
    return {"ok": True, "path": f"/img/contrib/{target.name}"}


def _delete_controller_image(vid_raw: str, pid_raw: str) -> dict:
    """DELETE /api/controller-image — drop any contrib image for this pair."""
    if not HEX4_RE.match(vid_raw or ""):
        return {"ok": False, "error": "invalid vid"}
    if not HEX4_RE.match(pid_raw or ""):
        return {"ok": False, "error": "invalid pid"}
    vid = vid_raw.upper()
    pid = pid_raw.upper()
    removed = False
    for ext in ALLOWED_UPLOAD_EXTS:
        p = CONTRIB_IMG_DIR / f"{vid}_{pid}{ext}"
        if p.exists():
            try:
                p.unlink()
                removed = True
            except OSError as e:
                return {"ok": False, "error": f"unlink failed: {e}", "removed": removed}
    refresh_catalog()
    return {"ok": True, "removed": removed}


# ------------------------------ HTTP layer ------------------------------

# Audit finding H3: cap on JSON request bodies. The image upload
# endpoint already had its own (much larger) cap; this catches every
# OTHER POST endpoint that reads Content-Length blind.
MAX_JSON_BODY_BYTES = 1_000_000  # 1 MB — well above any legitimate payload.

# Audit finding H1: Origin / Host whitelist for state-changing requests.
# DNS-rebinding turns localhost into a same-origin attack surface unless
# we explicitly check who's calling. Allowed origins for write methods:
#   - empty / missing Origin   (curl, native clients, our own SSE)
#   - http://127.0.0.1:<port>
#   - http://localhost:<port>
# Anything else → 403.
_ALLOWED_ORIGIN_HOSTS = ("127.0.0.1", "localhost", "[::1]")


def _origin_ok(origin: str | None, port: int) -> bool:
    """Return True if an Origin header value is acceptable for a
    state-changing request. Empty/None passes (CLI/native callers)."""
    if not origin:
        return True  # no Origin header — not a browser request
    o = origin.strip().lower()
    # Accept http(s)://<allowed-host>(:<port>)?
    for host in _ALLOWED_ORIGIN_HOSTS:
        for proto in ("http://", "https://"):
            base = proto + host
            if o == base or o == f"{base}:{port}":
                return True
    return False


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(GUI_DIR), **kwargs)

    def _check_origin_or_403(self) -> bool:
        """Reject the request with 403 if the Origin header is set and
        doesn't match the local-server allowlist. Return True if the
        caller can proceed.
        """
        origin = self.headers.get("Origin")
        port = self.server.server_address[1] if self.server else 8765
        if _origin_ok(origin, port):
            return True
        self._json(
            {"ok": False,
             "error": f"refusing cross-origin request from {origin!r}"},
            status=403,
        )
        return False

    def _read_capped_body(self) -> tuple[bytes | None, int]:
        """Read the request body, refusing if Content-Length exceeds
        MAX_JSON_BODY_BYTES. Returns (body_bytes, content_length).
        On overflow returns (None, length) and emits a 413 response.
        """
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length > MAX_JSON_BODY_BYTES:
            self._json(
                {"ok": False,
                 "error": f"body too large (max {MAX_JSON_BODY_BYTES} bytes)"},
                status=413,
            )
            return None, length
        return self.rfile.read(length) if length else b"", length

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # Note: Cache-Control: no-store is added by end_headers() — don't
        # send it here too (audit LOW: dup header).
        self.end_headers()
        self.wfile.write(body)

    def _sse(self, event_iter):
        """Server-Sent Events writer. Iterates `event_iter`, encoding
        each yielded dict as `data: <json>\\n\\n` and flushing.
        """
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")  # disables proxy buffering
            self.end_headers()
            for event in event_iter:
                line = "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                self.wfile.write(line.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            # Client closed the EventSource — expected, not an error.
            return
        except Exception as e:  # noqa: BLE001
            # Any other failure: try to emit one error event then close.
            try:
                err = "data: " + json.dumps({"event": "error", "error": str(e)}) + "\n\n"
                self.wfile.write(err.encode("utf-8"))
                self.wfile.flush()
            except Exception:
                pass

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
            # Flow 4 (game-detail view) consumes `system_default` to render
            # the inheritance overlay without a second round-trip. Existing
            # callers that don't read it (e.g. Stream-E onboarding) ignore
            # the extra field.
            return self._json({
                "system": sys_id,
                "rom": rom,
                "profile": load_profile(sys_id, rom),
                "system_default": load_system_default(sys_id),
            })
        if u.path == "/api/profile-default":
            q = self._query()
            sys_id = (q.get("system", [""])[0] or "").strip()
            return self._json({"system": sys_id, "profile": load_system_default(sys_id)})
        # v0.1.5 Task 1: surface bundled bindings_db suggestions into the
        # GUI. lookup() walks user → bundled → arcade in priority order.
        # Stays offline (include_online=False) so profile-load latency is
        # filesystem-only. A separate /api/suggestions/online endpoint
        # exposes the slow Vimm fallback behind an explicit click.
        if u.path == "/api/suggestions":
            q = self._query()
            sys_id = (q.get("system", [""])[0] or "").strip()
            rom    = (q.get("rom",    [""])[0] or "").strip()
            try:
                import bindings_lookup
                hit = bindings_lookup.lookup(sys_id, rom, include_online=False)
            except Exception as e:  # noqa: BLE001
                return self._json({"ok": False, "error": str(e), "hit": None})
            return self._json({"ok": True, "system": sys_id, "rom": rom, "hit": hit})
        if u.path == "/api/suggestions/online":
            q = self._query()
            sys_id = (q.get("system", [""])[0] or "").strip()
            rom    = (q.get("rom",    [""])[0] or "").strip()
            try:
                import bindings_lookup
                hit = bindings_lookup.online_lookup(sys_id, rom)
            except Exception as e:  # noqa: BLE001
                return self._json({"ok": False, "error": str(e), "hit": None})
            return self._json({"ok": True, "system": sys_id, "rom": rom, "hit": hit})
        if u.path == "/api/templates":
            q = self._query()
            sys_id = (q.get("system", [""])[0] or "").strip()
            return self._json({"system": sys_id, "templates": list_templates(sys_id)})
        if u.path == "/api/template":
            q = self._query()
            sys_id = (q.get("system", [""])[0] or "").strip()
            tpl_id = (q.get("id", [""])[0] or "").strip()
            return self._json({
                "system": sys_id,
                "id": tpl_id,
                "template": load_template(sys_id, tpl_id),
            })
        if u.path == "/api/remap":
            q = self._query()
            sys_id = (q.get("system", [""])[0] or "").strip()
            rom = (q.get("rom", [""])[0] or "").strip()
            return self._json(read_remap(sys_id, rom))
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
        # H2 audit fix: write-mode endpoints must use POST. GET only
        # serves the preview / read-only response — `?apply=true` on
        # GET is intentionally ignored to prevent CSRF via <img> tags.
        if u.path == "/api/scaffold-all":
            return self._json(_scaffold_all(apply=False))
        if u.path == "/api/scaffold-defaults":
            return self._json(_scaffold_defaults(apply=False))
        if u.path in ("/api/scaffold-all/stream", "/api/scaffold-defaults/stream"):
            # Streaming endpoints WROTE files via GET — pure CSRF
            # vector. Now POST-only.
            return self._json(
                {"ok": False,
                 "error": "stream endpoint moved to POST (audit H2)"},
                status=405,
            )
        if u.path == "/api/scaffold-excludes":
            return self._json({"ok": True, "excludes": _load_excludes()})
        if u.path == "/api/system-subdirs":
            q = self._query()
            sys_name = (q.get("system", [""])[0] or "").strip()
            if not sys_name:
                return self._json(
                    {"ok": False, "error": "missing 'system' query param"},
                    status=400,
                )
            return self._json({"ok": True, "system": sys_name,
                               "subdirs": _system_subdirs(sys_name)})
        if u.path == "/api/bezel-cutoffs":
            return self._json(_bezel_cutoffs(apply=False))
        if u.path == "/api/backup/list":
            return self._json(_backup_list())
        if u.path == "/api/update-check":
            return self._json(_update_check_cached())
        if u.path == "/api/guid/watcher":
            return self._json(_watcher_get())
        if u.path in ("", "/"):
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        # H1 audit fix: every state-changing request must come from a
        # same-origin caller (or have no Origin at all = CLI). Browsers
        # cross-origin via DNS rebinding bounce off this gate.
        if not self._check_origin_or_403():
            return
        u = urllib.parse.urlparse(self.path)

        # v0.1.5 Task 5 (BW-8): user-contribution PDF drop. Multipart
        # like /api/controller-image. End-user environment doesn't have
        # tesseract → manual_user_contribution explicitly disables OCR;
        # scanned PDFs surface a friendly "needs OCR" warning the GUI
        # shows. Cap at 50 MiB (manuals over that are vanishingly rare,
        # and pypdf chokes anyway).
        if u.path == "/api/contribute-pdf":
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return self._json({"ok": False, "error": "bad content-length"}, status=400)
            MAX_PDF_BYTES = 50 * 1024 * 1024
            if length > MAX_PDF_BYTES + 65_536:
                return self._json({"ok": False, "error": "PDF too large (>50 MiB)"}, status=413)
            body = self.rfile.read(length) if length else b""
            try:
                fields = _parse_multipart(self.headers, body)
            except Exception as e:  # noqa: BLE001
                return self._json({"ok": False, "error": f"bad multipart: {e}"}, status=400)
            try:
                import tempfile
                from pathlib import Path as _Path
                pdf_field = fields.get("pdf") or fields.get("file")
                if not pdf_field or not pdf_field.get("data"):
                    return self._json({"ok": False, "error": "missing PDF in 'pdf' field"}, status=400)
                sys_id = (fields.get("system_id", {}).get("data") or b"").decode("utf-8", "replace").strip()
                rom    = (fields.get("rom_name",  {}).get("data") or b"").decode("utf-8", "replace").strip()
                if not sys_id or not rom:
                    return self._json({"ok": False, "error": "missing system_id or rom_name"}, status=400)
                # Stash bytes to a temp .pdf the extractor can read.
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
                    tf.write(pdf_field["data"])
                    tmp_path = _Path(tf.name)
                try:
                    import manual_user_contribution as muc
                    result = muc.extract_user_pdf(tmp_path, sys_id, rom)
                finally:
                    try: tmp_path.unlink()
                    except OSError: pass
                return self._json({"ok": True, "result": result})
            except Exception as e:  # noqa: BLE001
                return self._json({"ok": False, "error": str(e)}, status=500)

        # The controller-image endpoint speaks multipart/form-data; handle
        # it before the JSON-decoding block below.
        if u.path == "/api/controller-image":
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return self._json({"ok": False, "error": "bad content-length"}, status=400)
            # Hard cap on raw upload size — refuse before reading anything.
            # 64 KiB headroom over MAX_CONTRIB_IMG_BYTES for multipart envelope.
            if length > MAX_CONTRIB_IMG_BYTES + 65_536:
                return self._json({"ok": False, "error": "too large"}, status=413)
            body = self.rfile.read(length) if length else b""
            try:
                fields = _parse_multipart(self.headers, body)
            except Exception as e:  # noqa: BLE001 - email parser raises a variety
                return self._json({"ok": False, "error": f"bad multipart: {e}"}, status=400)
            result = _save_controller_image(fields)
            # Map well-known errors to specific HTTP status so downstream
            # tooling sees the same code on both the outer envelope-size
            # branch (line ~1930) and the inner payload-size branch.
            status = 200
            if not result.get("ok"):
                err = (result.get("error") or "").lower()
                if "too large" in err:
                    status = 413
                elif "missing file" in err or "invalid" in err or "unsupported" in err:
                    status = 400
                else:
                    status = 400
            return self._json(result, status=status)

        # H3 audit fix: cap on JSON body size for every other POST.
        body_bytes, _ = self._read_capped_body()
        if body_bytes is None:
            return  # 413 already sent
        try:
            data = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except (ValueError, json.JSONDecodeError) as e:
            return self._json({"ok": False, "error": f"bad request: {e}"}, status=400)

        if u.path == "/api/save":
            result = save_profile(data)
            if result.get("ok") and data.get("apply"):
                result["apply"] = run_apply()
            return self._json(result)
        # v0.1.5 Task 1 + Task 5: persist user-confirmed bindings to the
        # per-machine user DB. Accepts the bindings list directly (the
        # GUI may have let the user edit auto-extracted suggestions
        # before save). With submit=true, also queues for community
        # submission (local-only stub today; the Task-15 GitHub flow
        # adopts this queue file as its input when wired).
        if u.path == "/api/contribute-save":
            try:
                import manual_user_contribution as muc
                payload = {
                    "system_id": (data.get("system_id") or "").strip(),
                    "rom_name":  (data.get("rom_name")  or "").strip(),
                    "title":     (data.get("title") or data.get("rom_name") or "").strip(),
                    "bindings":  data.get("bindings") or [],
                    "extra":     data.get("extra") or {},
                }
                if not payload["system_id"] or not payload["rom_name"]:
                    return self._json({"ok": False, "error": "missing system_id or rom_name"}, status=400)
                res = muc.save_and_optionally_submit(
                    payload,
                    submit=bool(data.get("submit")),
                    edited_bindings=data.get("bindings"),
                )
                return self._json({"ok": True, "result": res})
            except Exception as e:  # noqa: BLE001
                return self._json({"ok": False, "error": str(e)}, status=500)
        if u.path == "/api/apply":
            return self._json(run_apply())
        if u.path == "/api/launch-test":
            return self._json(launch_test(data))
        if u.path == "/api/remap":
            return self._json(write_remap(data))
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
        if u.path == "/api/system-lookup":
            return self._json(_system_lookup_endpoint(data))
        if u.path == "/api/system-lookup/clear":
            return self._json(_system_lookup_clear(data))
        # H2 audit fix: write-mode scaffold + bezel endpoints. POST
        # required so they're not reachable via <img src=...> CSRF.
        if u.path == "/api/scaffold-all":
            return self._json(_scaffold_all(apply=True))
        if u.path == "/api/scaffold-defaults":
            return self._json(_scaffold_defaults(apply=True))
        if u.path in ("/api/scaffold-all/stream", "/api/scaffold-defaults/stream"):
            mode = "all" if "scaffold-all" in u.path else "defaults"
            return self._sse(_scaffold_stream_events(mode))
        if u.path == "/api/bezel-cutoffs":
            return self._json(_bezel_cutoffs(apply=True))
        if u.path == "/api/scaffold-excludes":
            sys_name = (data.get("system") or "").strip()
            entries = data.get("excludes", [])
            if not sys_name:
                return self._json(
                    {"ok": False, "error": "missing 'system'"},
                    status=400,
                )
            if not isinstance(entries, list):
                return self._json(
                    {"ok": False, "error": "'excludes' must be an array"},
                    status=400,
                )
            cleaned: list[str] = []
            for e in entries:
                if not _validate_exclude_entry(e):
                    return self._json(
                        {"ok": False, "error": f"invalid exclude entry: {e!r}"},
                        status=400,
                    )
                cleaned.append(e.strip().replace("\\", "/"))
            excludes = _load_excludes()
            if cleaned:
                excludes[sys_name] = sorted(set(cleaned))
            else:
                excludes.pop(sys_name, None)
            try:
                _save_excludes(excludes)
            except OSError as ex:
                return self._json({"ok": False, "error": str(ex)}, status=500)
            return self._json({"ok": True, "system": sys_name,
                               "excludes": excludes.get(sys_name, [])})
        if u.path == "/api/update-check":
            return self._json(_update_check_endpoint(data))
        if u.path == "/api/guid/watcher":
            return self._json(_watcher_set(data))
        if u.path == "/api/guid/fold-pending":
            return self._json(_watcher_fold_pending(data))
        return self._json({"ok": False, "error": "unknown endpoint"}, status=404)

    def do_DELETE(self):
        if not self._check_origin_or_403():
            return
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/controller-image":
            q = self._query()
            vid = (q.get("vid", [""])[0] or "").strip()
            pid = (q.get("pid", [""])[0] or "").strip()
            return self._json(_delete_controller_image(vid, pid))
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
    print(f"RetroControlMapper GUI -> {url}")
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


def _handle_installer_cli(args) -> bool:
    """Handle installer-time CLI flags. Returns True if anything was
    handled (caller should exit instead of starting the GUI)."""
    handled = False

    if args.capture_factory_snapshot:
        try:
            import backups
            snap = backups.snapshot('factory',
                                    description='Captured during install')
            if snap is None:
                # Already exists — refused. Inno's repair branch hits this
                # on every re-run; not an error.
                print("[install] factory snapshot already exists; skipped.")
            else:
                print(f"[install] factory snapshot captured: {snap.id}")
        except Exception as e:
            print(f"[install] WARN: factory snapshot failed: {e}",
                  file=sys.stderr)
        handled = True

    if args.set_autostart in ("on", "off"):
        try:
            from tray import _set_autostart
            _set_autostart(args.set_autostart == "on")
            print(f"[install] autostart: {args.set_autostart}")
        except Exception as e:
            print(f"[install] WARN: set-autostart failed: {e}",
                  file=sys.stderr)
        handled = True

    if args.set_watcher_mode in ("off", "detect", "auto-fold"):
        try:
            import guid_watcher
            guid_watcher.set_mode(args.set_watcher_mode)
            print(f"[install] watcher mode: {args.set_watcher_mode}")
        except Exception as e:
            print(f"[install] WARN: set-watcher-mode failed: {e}",
                  file=sys.stderr)
        handled = True

    if args.set_update_check_consent in ("on", "off"):
        try:
            import update_check
            update_check.set_consent(args.set_update_check_consent == "on")
            print(f"[install] update-check consent: "
                  f"{args.set_update_check_consent}")
        except Exception as e:
            print(f"[install] WARN: set-update-check-consent failed: {e}",
                  file=sys.stderr)
        handled = True

    return handled


def _seed_profiles_on_first_run() -> None:
    """If running from a frozen PyInstaller bundle and the user's
    %APPDATA% profiles dir doesn't exist, copy the bundled defaults.

    The bundle ships profiles/ as read-only inside sys._MEIPASS; the
    user's editable copy lives at %APPDATA%/RB-Controller_fix/profiles/.
    Loader switches to the APPDATA copy after the seed.
    """
    if not getattr(sys, 'frozen', False):
        return  # dev mode — profiles/ next to the script is editable
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return  # nothing we can do
    user_profiles = Path(appdata) / "RB-Controller_fix" / "profiles"
    if user_profiles.exists():
        return  # already seeded
    bundle_profiles = Path(sys._MEIPASS) / "profiles"  # type: ignore[attr-defined]
    if not bundle_profiles.is_dir():
        return  # nothing to seed
    try:
        import shutil
        shutil.copytree(bundle_profiles, user_profiles)
        print(f"[first-run] seeded {user_profiles} from bundle")
    except OSError as e:
        print(f"[first-run] WARN: could not seed profiles: {e}",
              file=sys.stderr)


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
    # Installer-time flags. Each runs its action and exits without
    # starting the GUI/server. Idempotent so the Inno Repair branch
    # can re-fire them safely.
    ap.add_argument("--capture-factory-snapshot", action="store_true",
                    help=argparse.SUPPRESS)
    ap.add_argument("--set-autostart", choices=("on", "off"),
                    default=None, help=argparse.SUPPRESS)
    ap.add_argument("--set-watcher-mode",
                    choices=("off", "detect", "auto-fold"),
                    default=None, help=argparse.SUPPRESS)
    ap.add_argument("--set-update-check-consent", choices=("on", "off"),
                    default=None, help=argparse.SUPPRESS)
    args = ap.parse_args()

    # Installer-time flags short-circuit before any GUI startup.
    if _handle_installer_cli(args):
        return

    # First-run profile seed (no-op in dev mode and after first run).
    _seed_profiles_on_first_run()

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
