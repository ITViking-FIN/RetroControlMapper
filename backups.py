"""Two-tier backup subsystem (DECISIONS.md #5).

Tier 1 — Pre-install ("factory") snapshot.
    Captured during onboarding/install when the user clicks
    *"Yes, back up current RetroBat settings"*. Stored permanently
    under ``%APPDATA%/RB-Controller_fix/factory/``. Never overwritten —
    this is the "nothing else works, get me out" revert.

Tier 2 — Working snapshots.
    Per-edit, rolling history at
    ``%APPDATA%/RB-Controller_fix/snapshots/<YYYYMMDD-HHMMSS>/``.
    Capped at ``SNAPSHOT_HISTORY_CAP`` entries (oldest pruned by mtime).
    Auto-snapshots are taken before ``rbcf apply`` and before any
    ``restore()`` so the restore itself is revertible.

Storage layout:
    %APPDATA%/RB-Controller_fix/
    ├── factory/                                 (tier 1, at most one)
    │   ├── manifest.json
    │   └── <relative RetroBat paths preserved>
    └── snapshots/                               (tier 2, ring buffer)
        └── <YYYYMMDD-HHMMSS>/
            ├── manifest.json
            └── <relative RetroBat paths preserved>

The relative-path-under-RETROBAT_ROOT convention lets ``restore()``
mechanically copy each captured file back to its canonical home with no
per-file mapping table.

Stdlib only — pathlib, shutil, os, json, datetime, dataclasses. The
module coexists with ``guid_aliases.HISTORY_DIR`` (a narrower es_input
ring buffer); the two do not duplicate each other.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from config import RETROBAT_ROOT


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

def _appdata_subdir(name: str) -> Path:
    """Return ``%APPDATA%/RB-Controller_fix/<name>``, falling back to a
    project-local hidden dir if APPDATA is unset (CI / containers)."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "RB-Controller_fix" / name
    return Path(__file__).resolve().parent / f".{name}"


FACTORY_DIR: Path = _appdata_subdir("factory")
SNAPSHOTS_DIR: Path = _appdata_subdir("snapshots")
SNAPSHOT_HISTORY_CAP: int = 30

# Relative paths under RETROBAT_ROOT to capture. Each is checked at
# snapshot time; missing files are silently skipped (RetroBat may not
# have generated them yet on a fresh install).
RETROBAT_FILES_TO_SNAPSHOT: tuple[str, ...] = (
    "emulationstation/.emulationstation/es_settings.cfg",
    "emulationstation/.emulationstation/es_input.cfg",
    "emulators/retroarch/retroarch-core-options.cfg",
)

# Glob patterns (relative to RETROBAT_ROOT) — expanded at snapshot time.
RETROBAT_GLOBS_TO_SNAPSHOT: tuple[str, ...] = (
    "decorations/thebezelproject/systems/*.info",
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Snapshot:
    """Manifest record describing one captured snapshot.

    Attributes:
        id: ``factory`` for tier 1, otherwise a ``YYYYMMDD-HHMMSS`` stamp.
        kind: ``'factory'`` or ``'working'``.
        created_at: ISO-8601 datetime string (local time, no tz suffix —
            matches guid_aliases sidecar history conventions).
        description: Free-text label supplied by the caller (e.g.
            ``"auto-snap before apply (3 profiles)"``).
        files: Relative paths under RETROBAT_ROOT that were captured.
            A file present here is guaranteed to exist inside the
            snapshot dir at the same relative path.
        retrobat_root: The absolute RetroBat root path at capture time,
            recorded for forensic / cross-machine debugging only — not
            used during restore (restore always targets the *current*
            RETROBAT_ROOT).
    """
    id: str
    kind: str
    created_at: str
    description: str = ""
    files: list[str] = field(default_factory=list)
    retrobat_root: str = ""


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _snapshot_dir(snapshot_id: str) -> Path:
    """Resolve the on-disk directory for a snapshot id."""
    if snapshot_id == "factory":
        return FACTORY_DIR
    return SNAPSHOTS_DIR / snapshot_id


def _manifest_path(snapshot_id: str) -> Path:
    return _snapshot_dir(snapshot_id) / "manifest.json"


def _now_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _iso_now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def _candidate_relative_paths(root: Path) -> list[str]:
    """Resolve the configured static + glob targets against ``root``.

    Returns a deduplicated list of POSIX-style relative paths. Only
    includes targets that *actually exist* on disk — the caller skips
    missing paths anyway, but resolving them up-front keeps the manifest
    truthful.
    """
    out: list[str] = []
    seen: set[str] = set()

    def _add(rel: str) -> None:
        rel = rel.replace("\\", "/")
        if rel in seen:
            return
        seen.add(rel)
        out.append(rel)

    for rel in RETROBAT_FILES_TO_SNAPSHOT:
        if (root / rel).is_file():
            _add(rel)

    for pattern in RETROBAT_GLOBS_TO_SNAPSHOT:
        # Path.glob handles the wildcard; we walk relative to root and
        # convert each match back to a POSIX-style relative path.
        try:
            for hit in root.glob(pattern):
                if hit.is_file():
                    _add(str(hit.relative_to(root)).replace("\\", "/"))
        except OSError:
            continue

    return out


def _is_under(child: Path, parent: Path) -> bool:
    """True iff ``child`` resolves inside ``parent`` (path-traversal guard)."""
    try:
        child_r = child.resolve()
        parent_r = parent.resolve()
    except OSError:
        return False
    try:
        child_r.relative_to(parent_r)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Public: capture
# ---------------------------------------------------------------------------

def factory_exists() -> bool:
    """True iff a tier-1 (factory) snapshot has been taken."""
    return _manifest_path("factory").is_file()


def _read_manifest(snapshot_id: str) -> Snapshot | None:
    mp = _manifest_path(snapshot_id)
    if not mp.is_file():
        return None
    try:
        data = json.loads(mp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[backups] manifest unreadable for {snapshot_id}: {e}",
              file=sys.stderr)
        return None
    return Snapshot(
        id=str(data.get("id", snapshot_id)),
        kind=str(data.get("kind", "working")),
        created_at=str(data.get("created_at", "")),
        description=str(data.get("description", "")),
        files=list(data.get("files") or []),
        retrobat_root=str(data.get("retrobat_root", "")),
    )


def _write_manifest(snap: Snapshot) -> None:
    mp = _manifest_path(snap.id)
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(
        json.dumps(asdict(snap), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _prune_working(cap: int = SNAPSHOT_HISTORY_CAP) -> list[str]:
    """Remove oldest working snapshots so total count <= cap.

    Sorts by mtime ascending; drops from the front. Returns the list of
    pruned snapshot ids (POSIX relative ids, e.g. ``20260504-120000``).
    Factory snapshots live in a separate directory and are never pruned.
    """
    if not SNAPSHOTS_DIR.is_dir():
        return []
    entries: list[tuple[float, Path]] = []
    for child in SNAPSHOTS_DIR.iterdir():
        if not child.is_dir():
            continue
        if not (child / "manifest.json").is_file():
            continue
        try:
            mt = (child / "manifest.json").stat().st_mtime
        except OSError:
            mt = 0.0
        entries.append((mt, child))
    entries.sort(key=lambda e: e[0])
    pruned: list[str] = []
    while len(entries) > cap:
        _mt, victim = entries.pop(0)
        try:
            shutil.rmtree(victim)
            pruned.append(victim.name)
        except OSError as e:
            print(f"[backups] failed to prune {victim}: {e}",
                  file=sys.stderr)
    return pruned


def snapshot(kind: str, description: str = "") -> Snapshot | None:
    """Capture a snapshot of the current RetroBat config.

    Args:
        kind: ``'factory'`` (tier 1, one-shot) or ``'working'`` (tier 2).
        description: Free-text label stored in the manifest.

    Returns:
        The new ``Snapshot`` on success; ``None`` on refusal (factory
        already taken) or hard failure (no RETROBAT_ROOT, etc).
    """
    if kind not in ("factory", "working"):
        print(f"[backups] unknown snapshot kind: {kind!r}", file=sys.stderr)
        return None

    if RETROBAT_ROOT is None:
        print("[backups] RETROBAT_ROOT not detected; cannot snapshot.",
              file=sys.stderr)
        return None
    root = Path(RETROBAT_ROOT)
    if not root.is_dir():
        print(f"[backups] RETROBAT_ROOT does not exist: {root}",
              file=sys.stderr)
        return None

    if kind == "factory":
        if factory_exists():
            existing = _read_manifest("factory")
            taken = existing.created_at if existing else "(unknown date)"
            print(f"[backups] factory snapshot already exists, taken on "
                  f"{taken}; skipping.", file=sys.stderr)
            return None
        snap_id = "factory"
    else:
        snap_id = _now_id()
        # If the user managed to fire two snapshots in the same second
        # (auto-snap-before-apply firing alongside a manual one, say),
        # disambiguate with a numeric suffix so we don't clobber.
        base = snap_id
        n = 1
        while _snapshot_dir(snap_id).exists():
            n += 1
            snap_id = f"{base}-{n}"

    dest = _snapshot_dir(snap_id)
    try:
        dest.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        # extremely unlikely after the loop above; bail rather than overwrite
        print(f"[backups] snapshot dir already exists: {dest}", file=sys.stderr)
        return None
    except OSError as e:
        print(f"[backups] cannot create snapshot dir {dest}: {e}",
              file=sys.stderr)
        return None

    captured: list[str] = []
    try:
        for rel in _candidate_relative_paths(root):
            src = root / rel
            tgt = dest / rel
            try:
                tgt.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, tgt)
                captured.append(rel)
            except OSError as e:
                print(f"[backups] failed to copy {rel}: {e}", file=sys.stderr)

        snap = Snapshot(
            id=snap_id,
            kind=kind,
            created_at=_iso_now(),
            description=description,
            files=captured,
            retrobat_root=str(root),
        )
        _write_manifest(snap)
    except OSError as e:
        print(f"[backups] snapshot failed mid-write: {e}", file=sys.stderr)
        # best-effort cleanup of partial dir
        try:
            shutil.rmtree(dest, ignore_errors=True)
        except OSError:
            pass
        return None

    if kind == "working":
        # We just created an entry, so the cap calculation is "after this
        # insert it'd exceed cap" → prune until count <= cap.
        _prune_working(cap=SNAPSHOT_HISTORY_CAP)

    return snap


# ---------------------------------------------------------------------------
# Public: enumerate
# ---------------------------------------------------------------------------

def list_snapshots() -> list[Snapshot]:
    """Return every captured snapshot.

    Ordering: working snapshots first, most-recent-first; the factory
    snapshot (if it exists) is appended last. This matches the picker
    UI's "factory pinned to bottom as last-resort" requirement.
    """
    out: list[Snapshot] = []

    # Working snapshots, sorted newest first by manifest mtime.
    if SNAPSHOTS_DIR.is_dir():
        working: list[tuple[float, Snapshot]] = []
        for child in SNAPSHOTS_DIR.iterdir():
            if not child.is_dir():
                continue
            mp = child / "manifest.json"
            if not mp.is_file():
                continue
            try:
                mt = mp.stat().st_mtime
            except OSError:
                mt = 0.0
            snap = _read_manifest(child.name)
            if snap is None:
                continue
            working.append((mt, snap))
        working.sort(key=lambda e: e[0], reverse=True)
        out.extend(s for _mt, s in working)

    # Factory pinned at end.
    factory = _read_manifest("factory")
    if factory is not None:
        out.append(factory)

    return out


# ---------------------------------------------------------------------------
# Public: restore
# ---------------------------------------------------------------------------

def restore(
    snapshot_id: str,
    dry: bool = False,
) -> tuple[list[str], list[tuple[str, str]]]:
    """Restore files from a captured snapshot back to RetroBat.

    Always takes a *working* snapshot of the current state first (with
    description ``"auto-snap before restoring <id>"``) so the restore is
    itself revertible. If ``dry=True``, no auto-snapshot is taken and
    nothing is written — only the planned changes are returned.

    Path-traversal guard: every restore target must resolve under
    ``RETROBAT_ROOT.resolve()``. Anything outside is skipped with a
    ``"path-traversal"`` reason and never written.

    Args:
        snapshot_id: ``"factory"`` for tier 1, otherwise the working
            snapshot id (e.g. ``"20260504-120030"``).
        dry: If True, plan only — no files are copied, no auto-snapshot
            is captured.

    Returns:
        ``(restored, skipped)`` where:
          * ``restored`` is a list of relative paths that were (or would
            be, in dry mode) written.
          * ``skipped`` is a list of ``(path, reason)`` pairs.

        Returns ``([], [])`` if the snapshot is missing or RETROBAT_ROOT
        is unset.
    """
    if RETROBAT_ROOT is None:
        print("[backups] RETROBAT_ROOT not detected; cannot restore.",
              file=sys.stderr)
        return [], []
    root = Path(RETROBAT_ROOT)
    if not root.is_dir():
        print(f"[backups] RETROBAT_ROOT does not exist: {root}",
              file=sys.stderr)
        return [], []

    snap = _read_manifest(snapshot_id)
    if snap is None:
        print(f"[backups] snapshot not found: {snapshot_id}", file=sys.stderr)
        return [], []

    src_root = _snapshot_dir(snapshot_id)
    if not src_root.is_dir():
        print(f"[backups] snapshot dir missing: {src_root}", file=sys.stderr)
        return [], []

    try:
        root_resolved = root.resolve()
    except OSError:
        root_resolved = root

    # Auto-snapshot the current state first — restore is itself revertible.
    # Only when actually applying. Dry-run callers should expose this in
    # the preview message.
    if not dry:
        snapshot(
            "working",
            description=f"auto-snap before restoring {snapshot_id}",
        )

    restored: list[str] = []
    skipped: list[tuple[str, str]] = []

    for rel in snap.files:
        src = src_root / rel
        if not src.is_file():
            skipped.append((rel, "missing-from-snapshot"))
            continue
        tgt = root / rel
        # Path-traversal guard: target MUST be under RETROBAT_ROOT.
        try:
            tgt_resolved = (root / rel).resolve()
        except OSError:
            skipped.append((rel, "path-resolve-failed"))
            continue
        try:
            tgt_resolved.relative_to(root_resolved)
        except ValueError:
            skipped.append((rel, "path-traversal"))
            continue

        if dry:
            restored.append(rel)
            continue

        try:
            tgt.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, tgt)
            restored.append(rel)
        except OSError as e:
            skipped.append((rel, f"copy-failed: {e}"))

    return restored, skipped


__all__ = [
    "Snapshot",
    "FACTORY_DIR",
    "SNAPSHOTS_DIR",
    "SNAPSHOT_HISTORY_CAP",
    "RETROBAT_FILES_TO_SNAPSHOT",
    "RETROBAT_GLOBS_TO_SNAPSHOT",
    "snapshot",
    "list_snapshots",
    "restore",
    "factory_exists",
]
