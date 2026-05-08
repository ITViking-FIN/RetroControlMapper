"""
Arcade controls data — fetcher + cache + lookup helper.

v0.1.4 Tier 1 Task 1. Pulls `restructuredControls.json` from
yo1dog/controls-dat-json (an MIT-licensed JSON conversion of the
historical MAME `controls.dat` project) and caches it locally at
data/arcade_controls.json. Provides a lookup helper that returns
button labels for a given ROM name across MAME / FBNeo / hbmame /
neogeo / cps* systems.

The source data is community-maintained and last canonical-revised
~MAME 0.140 (2010-era). Arcade games don't get re-released, so the
data is still accurate for the historical canon (~30k titles) — but
post-2010 MAME additions won't be covered.

Usage:
    py data_arcade_controls.py [--force] [--no-network]
    py data_arcade_controls.py --lookup sf2     # show what we have for sf2

Programmatic API:
    from data_arcade_controls import (
        ensure_cache, lookup_arcade_controls, ARCADE_SYSTEMS,
    )
    info = lookup_arcade_controls("sf2")
    if info:
        for player, btns in info["players"].items():
            for label, desc in btns.items():
                print(f"  {player} {label}: {desc}")
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
# Two caches:
#   arcade_controls.json — restructured/cabinet-shape data (joy-*, paddle,
#                          spinner etc. with directional labels)
#   controls_buttons.json — original DTD-derived data with rich per-game
#                           button labels (P1_BUTTON1 = "Light Punch", etc.)
# We pull both because each is missing what the other has — `controls.json`
# omits joystick direction labels; `restructuredControls.json` omits
# button labels entirely. Merging gives the richest lookup.
CACHE_PATH = DATA_DIR / "arcade_controls.json"
BUTTONS_CACHE_PATH = DATA_DIR / "controls_buttons.json"
META_PATH = DATA_DIR / "arcade_controls.meta.json"

SOURCE_URL = (
    "https://raw.githubusercontent.com/yo1dog/controls-dat-json/master/"
    "json/restructuredControls.json"
)
BUTTONS_SOURCE_URL = (
    "https://raw.githubusercontent.com/yo1dog/controls-dat-json/master/"
    "json/controls.json"
)
USER_AGENT = "RB-Controller_fix/0.1.4 arcade-controls-fetcher (+https://github.com/ITViking-FIN/RetroControlMapper)"
TIMEOUT_S = 30

# Systems whose ROMs are looked up against this catalog. Each system's
# ROM filename (sans extension) is the key. A few systems share the
# arcade DB even though their RetroBat ids differ.
ARCADE_SYSTEMS = {
    "mame", "fbneo", "hbmame",
    "neogeo", "neogeocd",
    "cps1", "cps2", "cps3",
    "naomi", "naomi2", "atomiswave",
    "model2", "model3",
    "raine", "fbalpha",
}


def http_get(url: str, timeout: int = TIMEOUT_S) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def ensure_cache(force: bool = False, allow_network: bool = True) -> dict:
    """Load both arcade controls JSONs (restructured + buttons), fetching
    from the upstream sources if no local cache exists (or `force=True`).
    Returns a merged dict of:
        {
            "shape": <restructuredControls.json contents>,
            "buttons": <controls.json contents>,
            "buttons_index": <romname -> entry dict, built once>,
        }
    Empty dict on failure."""
    out = {}

    # Shape file (joystick direction labels, cabinet types)
    if not force and CACHE_PATH.exists():
        try:
            out["shape"] = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"[warn] shape cache parse error, re-fetching: {e}", file=sys.stderr)
    if "shape" not in out:
        if not allow_network:
            return {}
        try:
            print(f"Fetching {SOURCE_URL}")
            body = http_get(SOURCE_URL)
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            CACHE_PATH.write_bytes(body)
            out["shape"] = json.loads(body)
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
            print(f"[error] shape fetch failed: {e}", file=sys.stderr)
            return {}

    # Buttons file (per-game button labels — the v0.1.4 intelligence value)
    if not force and BUTTONS_CACHE_PATH.exists():
        try:
            out["buttons"] = json.loads(BUTTONS_CACHE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"[warn] buttons cache parse error, re-fetching: {e}", file=sys.stderr)
    if "buttons" not in out:
        if allow_network:
            try:
                print(f"Fetching {BUTTONS_SOURCE_URL}")
                body = http_get(BUTTONS_SOURCE_URL)
                BUTTONS_CACHE_PATH.write_bytes(body)
                out["buttons"] = json.loads(body)
            except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
                print(f"[error] buttons fetch failed: {e}", file=sys.stderr)
                out["buttons"] = {"games": []}
        else:
            out["buttons"] = {"games": []}

    # Build romname -> entry index so lookups are O(1) instead of O(n)
    buttons_games = (out.get("buttons") or {}).get("games") or []
    out["buttons_index"] = {g.get("romname"): g for g in buttons_games if g.get("romname")}

    # Persist metadata
    META_PATH.write_text(json.dumps({
        "fetched": datetime.now(timezone.utc).isoformat(),
        "shape_source": SOURCE_URL,
        "buttons_source": BUTTONS_SOURCE_URL,
        "shape_games": len((out.get("shape") or {}).get("gameMap") or {}),
        "buttons_games": len(out["buttons_index"]),
    }, indent=2), encoding="utf-8")

    return out


def cache_age_days() -> float | None:
    """How old (in days) is the cached file? None if no cache."""
    if not CACHE_PATH.exists():
        return None
    try:
        meta = json.loads(META_PATH.read_text(encoding="utf-8")) if META_PATH.exists() else {}
        if "fetched" in meta:
            t = datetime.fromisoformat(meta["fetched"].replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - t).total_seconds() / 86400.0
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return None


def lookup_arcade_controls(rom_name: str, data: dict | None = None) -> dict | None:
    """Look up button-label metadata for a ROM name.

    `rom_name` should be the ROM stem (no extension). Common variants
    are tried (lowercase, without parenthetical region tags) so a ROM
    file `Street Fighter II (USA).zip` resolves to `sf2`-ish entries
    where applicable. Returns None if no match.

    Output schema:
        {
            "rom":     "<matched key>",
            "game":    "<friendly name>",
            "num_players": 2,
            "notes":   "...",   # optional
            "players": {
                "P1": {"Button 1": "Light Punch", ...},
                "P2": {...},
            },
            "joystick": {       # only if a joy-* control exists
                "type": "joy-8way",
                "directions": {"up": "Jump", "down": "Crouch", ...},
            },
        }
    """
    if data is None:
        data = ensure_cache(allow_network=False)
    if not data:
        return None

    shape_games = ((data.get("shape") or {}).get("gameMap") or {})
    buttons_index = data.get("buttons_index") or {}

    candidates = _candidate_rom_keys(rom_name)
    for key in candidates:
        # Prefer entries that exist in BOTH sources (richest data) but
        # accept either if the other is missing.
        shape_entry = shape_games.get(key)
        btn_entry = buttons_index.get(key)
        if shape_entry or btn_entry:
            return _format_entry(key, shape_entry, btn_entry)
    return None


def _candidate_rom_keys(rom_name: str) -> list[str]:
    """Generate plausible MAME-style ROM keys for a filename.
    e.g. "Street Fighter II (USA).zip" -> [
        "street fighter ii (usa)", "street fighter ii", "sf2", ...
    ]
    Only the lowercased stem is tried directly; deeper alias resolution
    would need a name->rom-key index (future work)."""
    stem = Path(rom_name).stem
    out = [stem.lower()]
    # Strip parenthetical / bracketed region/version tags
    import re
    cleaned = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", stem).strip().lower()
    if cleaned and cleaned not in out:
        out.append(cleaned)
    # Underscores and dashes interchangeable
    for s in list(out):
        for repl in (s.replace("_", " "), s.replace("-", " "),
                     s.replace(" ", "_"), s.replace(" ", "")):
            if repl not in out:
                out.append(repl)
    return out


def _format_entry(rom_key: str, shape_entry: dict | None,
                  btn_entry: dict | None = None) -> dict:
    """Combine the two upstream sources into a single GUI-friendly dict.

    `shape_entry` from `restructuredControls.json` provides cabinet shape +
    joystick directional labels. `btn_entry` from `controls.json` provides
    per-game button labels (the actual v0.1.4 value-add).
    """
    # Start from button data if available — it has the cleanest gamename
    out = {
        "rom":         rom_key,
        "game":        "",
        "num_players": 1,
        "notes":       "",
        "players":     {},
        "joystick":    None,
    }
    if btn_entry:
        out["game"] = btn_entry.get("gamename") or rom_key
        out["num_players"] = btn_entry.get("numPlayers") or 1
        out["notes"] = (btn_entry.get("miscDetails") or "").strip()
        # Walk players[].labels[] for button assignments
        for p in btn_entry.get("players") or []:
            pnum = p.get("number", 1)
            p_key = f"P{pnum}"
            labels = p.get("labels") or []
            if not labels: continue
            btns = out["players"].setdefault(p_key, {})
            for lbl in labels:
                name = lbl.get("name") or ""
                value = lbl.get("value") or ""
                # Names look like "P1_BUTTON1", "P1_JOYSTICK_UP", etc.
                # Filter out joystick directions — those go in joystick.
                if "_BUTTON" in name and value:
                    btn_num = name.split("_BUTTON")[-1]
                    pretty = f"Button {btn_num}"
                    btns[pretty] = value
                elif "_JOYSTICK_" in name and value and pnum == 1 \
                     and out["joystick"] is None:
                    pass  # we'll fill from shape source below if available
            if not btns: out["players"].pop(p_key, None)
    if shape_entry:
        if not out["game"]:
            out["game"] = shape_entry.get("description") or rom_key
        if not out["num_players"]:
            out["num_players"] = shape_entry.get("numPlayers") or 1
        if not out["notes"]:
            out["notes"] = (shape_entry.get("notes") or "").strip()
        # Joystick directional labels (richer than buttons file)
        cfgs = shape_entry.get("controlConfigurations") or []
        cfg = next((c for c in cfgs
                    if c.get("targetCabinetType") == "upright"), None) or (cfgs[0] if cfgs else None)
        if cfg:
            for cset in (cfg.get("controlSets") or []):
                pnums = cset.get("supportedPlayerNums") or [1]
                if 1 not in pnums: continue
                for ctrl in (cset.get("controls") or []):
                    if not (ctrl.get("type") or "").startswith("joy"):
                        continue
                    if out["joystick"] is not None:
                        break
                    dirs = {}
                    for direction, info in (ctrl.get("outputToInputMap") or {}).items():
                        lbl = (info or {}).get("label")
                        if lbl: dirs[direction] = lbl
                    if dirs:
                        out["joystick"] = {"type": ctrl["type"], "directions": dirs}
                        break
    if not out["game"]:
        out["game"] = rom_key
    return out


def _legacy_format_entry(rom_key: str, entry: dict) -> dict:
    """Squash the upstream JSON shape into something easier for the GUI.

    Upstream shape (gameMap[<rom_key>]):
        description, numPlayers, notes,
        controlConfigurations: [
            {
                targetCabinetType, controlSets: [
                    {
                        supportedPlayerNums: [1] | [2] | [1,2,...],
                        controls: [
                            {
                                type: 'joy-8way' | 'button' | 'joy-4way' | ...,
                                outputToInputMap: {
                                    'B0': { label: 'Light Punch', mameInputPort: ... },
                                    'B1': { ... },
                                    'up': { ... },   # for joy-* types
                                    ...
                                },
                            },
                            ...
                        ],
                    },
                    ...
                ],
            },
        ]
    """
    out = {
        "rom":         rom_key,
        "game":        entry.get("description") or rom_key,
        "num_players": entry.get("numPlayers") or 1,
        "notes":       (entry.get("notes") or "").strip(),
        "players":     {},
        "joystick":    None,
    }
    cfgs = entry.get("controlConfigurations") or []
    if not cfgs:
        return out
    # Prefer the upright (cabinet) config since that's what most users
    # play. Fall back to the first config available.
    cfg = next((c for c in cfgs
                if c.get("targetCabinetType") == "upright"), None) or cfgs[0]
    for cset in (cfg.get("controlSets") or []):
        # Each control set is associated with one or more player numbers.
        # We index our output by P1/P2/..., taking the first supported.
        pnums = cset.get("supportedPlayerNums") or [1]
        primary_p = pnums[0]
        p_key = f"P{primary_p}"
        for ctrl in (cset.get("controls") or []):
            ctype = ctrl.get("type") or ""
            mapping = ctrl.get("outputToInputMap") or {}
            if ctype.startswith("joy"):
                # Stash directional labels under "joystick" once, P1-only
                if primary_p == 1 and out["joystick"] is None:
                    dirs = {}
                    for direction, info in mapping.items():
                        lbl = (info or {}).get("label")
                        if lbl: dirs[direction] = lbl
                    if dirs:
                        out["joystick"] = {"type": ctype, "directions": dirs}
                continue
            # Buttons (and analog sticks treated as button-like by upstream)
            btns = out["players"].setdefault(p_key, {})
            for output_key, info in mapping.items():
                lbl = (info or {}).get("label")
                if not lbl:
                    continue
                # `output_key` is e.g. B0/B1/... — translate to "Button 1"
                pretty = _prettify_output_key(output_key)
                btns[pretty] = lbl
    return out


def _prettify_output_key(k: str) -> str:
    """B0 -> 'Button 1', B5 -> 'Button 6', PEDAL -> 'Pedal', else passthrough."""
    if not k:
        return k
    if len(k) > 1 and k[0].upper() == "B" and k[1:].isdigit():
        return f"Button {int(k[1:]) + 1}"
    return k.replace("_", " ").title()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true",
                    help="Re-fetch even if a local cache exists.")
    ap.add_argument("--no-network", action="store_true",
                    help="Use cache only; don't fetch.")
    ap.add_argument("--lookup", metavar="ROM",
                    help="Query the cache for one ROM, print the entry.")
    args = ap.parse_args()

    data = ensure_cache(force=args.force, allow_network=not args.no_network)
    if not data:
        print("[fatal] no data — cache empty and network disabled or unreachable", file=sys.stderr)
        sys.exit(1)

    shape_games = ((data.get("shape") or {}).get("gameMap") or {})
    btn_games = data.get("buttons_index") or {}
    age = cache_age_days()
    age_str = f"{age:.1f}d old" if age is not None else "fresh"
    print(f"Caches:")
    print(f"  shape:   {CACHE_PATH}  ({len(shape_games)} games)")
    print(f"  buttons: {BUTTONS_CACHE_PATH}  ({len(btn_games)} games)  [{age_str}]")

    if args.lookup:
        result = lookup_arcade_controls(args.lookup, data=data)
        if not result:
            print(f"[miss] no entry found for '{args.lookup}'")
            sys.exit(2)
        print()
        print(f"Game:    {result['game']}")
        print(f"ROM:     {result['rom']}")
        print(f"Players: {result['num_players']}")
        if result.get("notes"): print(f"Notes:   {result['notes']}")
        if result.get("joystick"):
            j = result["joystick"]
            print()
            print(f"Joystick ({j['type']}):")
            for d, lbl in j["directions"].items():
                print(f"  {d:<10} {lbl}")
        for player, btns in result["players"].items():
            print()
            print(f"{player}:")
            for lbl, desc in btns.items():
                print(f"  {lbl:<14} {desc}")


if __name__ == "__main__":
    main()
