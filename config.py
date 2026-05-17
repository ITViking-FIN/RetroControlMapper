"""
RB-Controller_fix runtime path resolution.

Replaces the hardcoded ``E:/RetroBat`` paths that used to live inline in
``rbcf.py`` and ``rbcf_gui.py``. At import time we probe the registry, an
environment-variable override, and a list of common install drives, then
pick the first candidate whose ``emulationstation/.emulationstation/
es_settings.cfg`` exists. The result is cached on ``RETROBAT_ROOT``.

If detection fails, ``RETROBAT_ROOT`` is ``None`` and the derived path
constants point at sentinel ``Path``s under the missing root — this keeps
type hints/imports working while still allowing read-only commands like
``rbcf validate`` to run without RetroBat installed.

Probe order:
    1. ``RBCF_RETROBAT_ROOT`` environment variable.
    2. Registry: ``HKLM\\SOFTWARE\\RetroBat``, ``HKCU\\SOFTWARE\\RetroBat``,
       ``HKLM\\SOFTWARE\\WOW6432Node\\RetroBat`` — values
       ``InstallPath`` / ``LatestKnownInstallPath`` / default value.
    3. Common install paths: ``C:/RetroBat``, ``D:/RetroBat``,
       ``E:/RetroBat``, ``%USERPROFILE%/RetroBat``, ``%APPDATA%/RetroBat``.

Stdlib only — ``winreg`` is part of the standard library on Windows.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable

try:
    import winreg  # type: ignore[import-not-found]
except ImportError:  # non-Windows; tool is Windows-only but keep import safe
    winreg = None  # type: ignore[assignment]


__version__ = "0.1.6"

# GitHub repo coordinates — used by update_check.py for releases polling.
GITHUB_OWNER = "ITViking-FIN"
GITHUB_REPO = "RetroControlMapper"

ENV_OVERRIDE = "RBCF_RETROBAT_ROOT"

# v0.1.6: user-data folder rename. The product's canonical name is
# `RetroControlMapper`; the legacy `RB-Controller_fix` codename used
# in v0.1.0–v0.1.5.2 is migrated on first launch via the function
# below. Importers should call ``user_data_root()`` rather than
# hardcoding the folder name so future renames stay one-place.
USER_DATA_FOLDER = "RetroControlMapper"
LEGACY_USER_DATA_FOLDER = "RB-Controller_fix"


def user_data_root() -> Path:
    """Return %APPDATA%/RetroControlMapper/ (or the dev source dir
    when %APPDATA% is unavailable — e.g. running from source without
    Windows env vars set)."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / USER_DATA_FOLDER
    return Path(__file__).resolve().parent


def _migrate_legacy_user_data() -> dict:
    """v0.1.6 first-launch migration. If the legacy
    ``%APPDATA%/RB-Controller_fix/`` folder is present, move its
    contents under the new ``%APPDATA%/RetroControlMapper/`` name.

    Handles three cases:
      * Legacy-only: atomic rename of the whole folder.
      * Legacy + new (mixed): per-entry move; conflicting entries
        keep whichever is already in new (the installer-placed copy).
      * New-only / neither: no-op.

    Idempotent. Never raises — failures are logged into the return
    dict and the app continues with the legacy path readable via
    fall-through lookups.
    """
    import shutil
    result: dict = {"performed": False, "mode": "none", "errors": []}
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return result
    legacy = Path(appdata) / LEGACY_USER_DATA_FOLDER
    new = Path(appdata) / USER_DATA_FOLDER
    if not legacy.exists():
        return result
    try:
        if not new.exists():
            # Clean case — atomic rename.
            shutil.move(str(legacy), str(new))
            result["performed"] = True
            result["mode"] = "rename"
            return result
        # Mixed state. Per-entry move: anything in legacy not present
        # in new gets moved across. Conflicts keep the new side
        # (typically the installer's freshly bundled bindings_db).
        moved: list[str] = []
        kept_conflicts: list[str] = []
        for entry in legacy.iterdir():
            target = new / entry.name
            if target.exists():
                kept_conflicts.append(entry.name)
                continue
            try:
                shutil.move(str(entry), str(target))
                moved.append(entry.name)
            except OSError as e:
                result["errors"].append(f"{entry.name}: {e}")
        # If legacy is now empty, remove it. If anything's left,
        # leave it for the user to inspect.
        try:
            if not any(legacy.iterdir()):
                legacy.rmdir()
        except OSError:
            pass
        result["performed"] = bool(moved)
        result["mode"] = "merge"
        result["moved"] = moved
        result["kept_conflicts"] = kept_conflicts
        return result
    except Exception as e:  # noqa: BLE001 — never crash on migration
        result["errors"].append(str(e))
        return result


# Run migration at import time so every downstream path resolution
# sees the new location. Cheap on the no-op path (just one stat()).
_MIGRATION_RESULT = _migrate_legacy_user_data()


def _rbcfrc_path() -> Path:
    """Location of the persisted user override file.

    Stored under ``%APPDATA%/RetroControlMapper/rbcfrc`` (single-line
    text: the RetroBat install root). Created by PUT /api/retrobat-root
    and read here at module import time. If %APPDATA% is unavailable,
    falls back to the project directory.
    """
    return user_data_root() / "rbcfrc"


RBCFRC_PATH = _rbcfrc_path()


def _read_rbcfrc() -> Path | None:
    """Read the persisted override path from .rbcfrc, if present."""
    try:
        if not RBCFRC_PATH.is_file():
            return None
        raw = RBCFRC_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    cleaned = raw.strip().strip('"').strip("'")
    return Path(cleaned)


def write_rbcfrc(path: Path | str) -> None:
    """Persist a user-supplied RetroBat root path to .rbcfrc.

    Caller (PUT /api/retrobat-root) is responsible for prompting the user
    to restart the server — RETROBAT_ROOT is cached at import time, so a
    written .rbcfrc only takes effect on next process start.
    """
    raw = str(path).strip().strip('"').strip("'")
    RBCFRC_PATH.parent.mkdir(parents=True, exist_ok=True)
    RBCFRC_PATH.write_text(raw + "\n", encoding="utf-8")


def clear_rbcfrc() -> bool:
    """Remove the .rbcfrc override. Returns True if a file was removed."""
    try:
        if RBCFRC_PATH.is_file():
            RBCFRC_PATH.unlink()
            return True
    except OSError:
        pass
    return False


# Marker file: if this file exists under a candidate root, we accept the
# candidate. Chosen because RetroBat always ships an ES settings file even
# on a fresh install (the launcher creates it on first run).
MARKER_RELATIVE = Path("emulationstation") / ".emulationstation" / "es_settings.cfg"

# Registry locations, in priority order.
_REGISTRY_KEYS: tuple[tuple[str, str], ...] = (
    ("HKLM", r"SOFTWARE\RetroBat"),
    ("HKCU", r"SOFTWARE\RetroBat"),
    ("HKLM", r"SOFTWARE\WOW6432Node\RetroBat"),
)
_REGISTRY_VALUES: tuple[str, ...] = ("InstallPath", "LatestKnownInstallPath", "")

# Hardcoded common install paths, in priority order.
def _common_paths() -> list[Path]:
    candidates = [
        Path(r"C:/RetroBat"),
        Path(r"D:/RetroBat"),
        Path(r"E:/RetroBat"),
    ]
    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        candidates.append(Path(userprofile) / "RetroBat")
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "RetroBat")
    return candidates


def _is_valid_root(p: Path | None) -> bool:
    if p is None:
        return False
    try:
        return (p / MARKER_RELATIVE).is_file()
    except OSError:
        return False


def _registry_candidates() -> Iterable[Path]:
    """Yield Path candidates discovered via the Windows registry."""
    if winreg is None:
        return
    hive_map = {"HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCU": winreg.HKEY_CURRENT_USER}
    for hive_name, subkey in _REGISTRY_KEYS:
        hive = hive_map.get(hive_name)
        if hive is None:
            continue
        try:
            with winreg.OpenKey(hive, subkey) as handle:
                for value_name in _REGISTRY_VALUES:
                    try:
                        raw, _kind = winreg.QueryValueEx(handle, value_name)
                    except FileNotFoundError:
                        continue
                    except OSError:
                        continue
                    if isinstance(raw, str) and raw.strip():
                        # Strip surrounding quotes if any installer quoted them.
                        cleaned = raw.strip().strip('"').strip("'")
                        yield Path(cleaned)
        except FileNotFoundError:
            continue
        except OSError:
            continue


def find_retrobat() -> Path | None:
    """Locate the RetroBat install root.

    Returns the first candidate whose marker file exists, or ``None`` if
    nothing matched.
    """
    seen: set[str] = set()

    def _try(p: Path | None) -> Path | None:
        if p is None:
            return None
        try:
            key = str(p.resolve()).lower()
        except OSError:
            key = str(p).lower()
        if key in seen:
            return None
        seen.add(key)
        return p if _is_valid_root(p) else None

    # 1. .rbcfrc persisted user override (highest priority — set explicitly).
    rcfile = _read_rbcfrc()
    if rcfile is not None:
        hit = _try(rcfile)
        if hit is not None:
            return hit

    # 2. Env override.
    override = os.environ.get(ENV_OVERRIDE)
    if override:
        hit = _try(Path(override.strip().strip('"').strip("'")))
        if hit is not None:
            return hit

    # 3. Registry.
    for candidate in _registry_candidates():
        hit = _try(candidate)
        if hit is not None:
            return hit

    # 4. Common install paths.
    for candidate in _common_paths():
        hit = _try(candidate)
        if hit is not None:
            return hit

    return None


def _probed_locations_summary() -> list[str]:
    """Human-readable list of every place we looked, for error reporting."""
    locations: list[str] = []
    rc = _read_rbcfrc()
    if rc is not None:
        locations.append(f".rbcfrc: {rc}")
    else:
        locations.append(f".rbcfrc: {RBCFRC_PATH} (absent)")
    override = os.environ.get(ENV_OVERRIDE)
    if override:
        locations.append(f"env {ENV_OVERRIDE}={override}")
    else:
        locations.append(f"env {ENV_OVERRIDE} (unset)")
    for hive_name, subkey in _REGISTRY_KEYS:
        for value_name in _REGISTRY_VALUES:
            label = value_name or "(default)"
            locations.append(rf"registry {hive_name}\{subkey}!{label}")
    for path in _common_paths():
        locations.append(str(path))
    return locations


# --------------------------------------------------------------------------
# Cached module-level constants. Importers read these directly.
# --------------------------------------------------------------------------

RETROBAT_ROOT: Path | None = find_retrobat()

if RETROBAT_ROOT is None:
    # Fall back to a sentinel so downstream code that *uses* the path only
    # for read-time existence checks still type-checks. None of the .exists()
    # checks will succeed for these sentinel paths, which is what we want.
    _ROOT_OR_SENTINEL = Path(r"E:/RetroBat")  # historical default, still won't exist on most machines
    print(
        "[config] RetroBat install not found. Probed:\n  - "
        + "\n  - ".join(_probed_locations_summary())
        + f"\n  Set {ENV_OVERRIDE} to your install root to override.",
        file=sys.stderr,
    )
else:
    _ROOT_OR_SENTINEL = RETROBAT_ROOT

ES_SETTINGS: Path = _ROOT_OR_SENTINEL / "emulationstation" / ".emulationstation" / "es_settings.cfg"
ES_SYSTEMS_CFG: Path = _ROOT_OR_SENTINEL / "emulationstation" / ".emulationstation" / "es_systems.cfg"
ES_INPUT: Path = _ROOT_OR_SENTINEL / "emulationstation" / ".emulationstation" / "es_input.cfg"
RA_CORE_OPTS: Path = _ROOT_OR_SENTINEL / "emulators" / "retroarch" / "retroarch-core-options.cfg"
BEZELS_DIR: Path = _ROOT_OR_SENTINEL / "decorations" / "thebezelproject" / "systems"
ROMS_ROOT: Path = _ROOT_OR_SENTINEL / "roms"


__all__ = [
    "ENV_OVERRIDE",
    "RBCFRC_PATH",
    "write_rbcfrc",
    "clear_rbcfrc",
    "find_retrobat",
    "RETROBAT_ROOT",
    "ES_SETTINGS",
    "ES_SYSTEMS_CFG",
    "ES_INPUT",
    "RA_CORE_OPTS",
    "BEZELS_DIR",
    "ROMS_ROOT",
    "__version__",
    "GITHUB_OWNER",
    "GITHUB_REPO",
]
