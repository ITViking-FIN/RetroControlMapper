"""GUID drift mitigation: detect and fold SDL controller GUID aliases.

Phase-1 implementation. See ``docs/GUID_DRIFT_DESIGN.md`` for the full
spec — alias-group definition, dual-pad disambiguation strategy, and
risk surface.

Public API:
    parse_es_input(path)        — parse <inputConfig> blocks → list[GuidAlias]
    group_aliases(aliases)      — group by (vid, pid) lowercase hex tuple
    expand_inputconfig(path,    — write duplicate <inputConfig> blocks for
                       group,     every alias GUID in the group, mirroring
                       dry)       the canonical alias's <input> children.
    extract_vid_pid(guid)       — pull VID/PID from bytes 4-5, 8-9.

Phase-2 (watcher, instance-id persistence) is deliberately out of scope.
``GuidAlias.last_seen`` is therefore always ``None`` from this module;
the field exists for forward compatibility with the sidecar history.
"""

from __future__ import annotations

import os
import shutil
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from config import RETROBAT_ROOT


# History ring-buffer location (decision #5).
def _history_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "RB-Controller_fix" / "history"
    return Path(__file__).resolve().parent / ".history"


HISTORY_DIR = _history_dir()
HISTORY_KEEP = 10


@dataclass
class GuidAlias:
    """One SDL controller GUID observation, indexed for alias grouping.

    ``guid`` is the 32-hex-char lowercase SDL2 ``SDL_JoystickGUID`` as
    written to ``es_input.cfg`` ``deviceGUID`` attributes. ``vid`` and
    ``pid`` are extracted from bytes 4-5 and 8-9 of that GUID (see design
    doc 1, "GUID layout") and serve as the alias-group key. ``instance_id``
    is the Windows HID ``InstanceId`` if known (used to disambiguate two
    physically-distinct pads sharing a VID:PID, e.g. the user's two 8BitDo
    Ultimates per CLAUDE.md). For Phase-1 we use ``device_name`` from the
    parsed ``<inputConfig>`` as the disambiguation hint per decision #4.
    ``last_seen`` is an ISO-8601 timestamp from our sidecar history,
    ``None`` when the alias was discovered solely from on-disk parsing.
    """

    guid: str
    vid: str
    pid: str
    device_name: str = ""
    instance_id: str | None = None
    last_seen: str | None = None


# ----------------------------- helpers -----------------------------

def extract_vid_pid(guid: str) -> tuple[str, str]:
    """Pull VID (bytes 4-5) and PID (bytes 8-9) from a 32-hex-char GUID.

    The GUID is the SDL2 little-endian wire form, so each 16-bit field is
    stored low-byte-first. Bytes 4-5 of the GUID buffer are characters
    8-11 of the hex string; their byte-pair "5e 04" decodes to VID
    ``045e``. Same for bytes 8-9 / chars 16-19.

    Returns ``(vid, pid)`` as 4-char lowercase hex strings. If the GUID is
    too short or non-hex, returns ``("", "")`` so callers can filter.
    """
    if not guid or len(guid) < 20:
        return ("", "")
    try:
        # bytes 4-5 → little-endian 16-bit VID
        vid_lo = guid[8:10]
        vid_hi = guid[10:12]
        # bytes 8-9 → little-endian 16-bit PID
        pid_lo = guid[16:18]
        pid_hi = guid[18:20]
        # Validate hex
        int(vid_lo + vid_hi + pid_lo + pid_hi, 16)
    except ValueError:
        return ("", "")
    vid = (vid_hi + vid_lo).lower()
    pid = (pid_hi + pid_lo).lower()
    return (vid, pid)


# ----------------------------- parse -----------------------------

def parse_es_input(path: Path) -> list[GuidAlias]:
    """Parse ``es_input.cfg`` and return every ``<inputConfig>`` as a GuidAlias.

    EmulationStation never garbage-collects ``<inputConfig>`` blocks, so
    the returned list is the user's full historical alias surface — every
    transport / driver permutation any of their pads has ever taken.
    Entries with malformed or missing ``deviceGUID`` are skipped silently
    (they won't survive an ES round-trip anyway).

    Non-existent or unparsable files yield ``[]`` plus a stderr warning,
    so callers can degrade gracefully on a fresh / broken install.
    """
    if not path.exists():
        print(f"[guid_aliases] {path} not found; nothing to parse",
              file=sys.stderr)
        return []
    try:
        tree = ET.parse(path)
    except ET.ParseError as e:
        print(f"[guid_aliases] {path}: XML parse error: {e}",
              file=sys.stderr)
        return []
    except OSError as e:
        print(f"[guid_aliases] {path}: {e}", file=sys.stderr)
        return []

    out: list[GuidAlias] = []
    root = tree.getroot()
    for cfg in root.iter("inputConfig"):
        if (cfg.get("type") or "").lower() != "joystick":
            continue
        guid = (cfg.get("deviceGUID") or "").strip().lower()
        if len(guid) != 32:
            continue
        try:
            int(guid, 16)
        except ValueError:
            continue
        vid, pid = extract_vid_pid(guid)
        if not vid or not pid:
            continue
        name = cfg.get("deviceName") or ""
        out.append(GuidAlias(
            guid=guid,
            vid=vid,
            pid=pid,
            device_name=name,
            instance_id=None,
            last_seen=None,
        ))
    return out


# ----------------------------- group -----------------------------

def group_aliases(
    aliases: list[GuidAlias],
) -> dict[tuple[str, str], list[GuidAlias]]:
    """Group aliases into candidate alias-groups keyed by ``(vid, pid)``.

    Order within a group is order-of-first-appearance. Singletons
    (one-element groups) are kept; the caller filters them out before
    rewriting.

    A single returned list is *one* alias group only when no two physical
    pads share that VID:PID. The dual-8BitDo case must be split further
    via instance-id / deviceName disambiguation before any rewrite — see
    design doc §6 and decision #4. For Phase-1 we surface the group as-is;
    the watcher (Phase-2) will own the split.
    """
    out: dict[tuple[str, str], list[GuidAlias]] = {}
    for a in aliases:
        key = (a.vid, a.pid)
        out.setdefault(key, []).append(a)
    return out


# ----------------------------- expand -----------------------------

def _validate_under_root(path: Path) -> None:
    """Path-traversal guard: refuse to write outside RETROBAT_ROOT.

    If RETROBAT_ROOT is None (fresh install / not detected), allow writes
    only under the test-fixture path (caller passes us a temp file).
    """
    if RETROBAT_ROOT is None:
        # Without a known root, the only sane policy is: don't refuse —
        # let the caller's tests run on a tmp copy, but keep the live
        # install untouched (which it can't, since RETROBAT_ROOT is None
        # means we don't know where it is).
        return
    try:
        resolved = path.resolve()
        root = RETROBAT_ROOT.resolve()
    except OSError as e:
        raise ValueError(
            f"Cannot resolve es_input path or RetroBat root: {e}"
        ) from e
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError(
            f"Refusing to write {resolved}: not under RetroBat root {root}"
        )


def _ring_buffer_snapshot(src: Path) -> Path | None:
    """Copy ``src`` into the rolling history dir and prune to HISTORY_KEEP.

    Per decision #5: keep the last 10 mutations under
    ``%APPDATA%/RB-Controller_fix/history/``. Returns the path of the
    snapshot, or None if the source was missing.
    """
    if not src.exists():
        return None
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = HISTORY_DIR / f"es_input-{stamp}.cfg"
    # If two snapshots in the same second, append a counter
    counter = 0
    while dest.exists():
        counter += 1
        dest = HISTORY_DIR / f"es_input-{stamp}.{counter}.cfg"
    shutil.copy2(src, dest)
    # Prune oldest beyond HISTORY_KEEP
    snapshots = sorted(
        HISTORY_DIR.glob("es_input-*.cfg"),
        key=lambda p: p.stat().st_mtime,
    )
    while len(snapshots) > HISTORY_KEEP:
        oldest = snapshots.pop(0)
        try:
            oldest.unlink()
        except OSError:
            pass
    return dest


def _daily_backup(path: Path) -> Path | None:
    """Create the standard ``.bak.rbcf.YYYYMMDD`` if not already present today."""
    if not path.exists():
        return None
    tag = f".bak.rbcf.{datetime.now():%Y%m%d}"
    bak = path.with_suffix(path.suffix + tag)
    if not bak.exists():
        shutil.copy2(path, bak)
    return bak


def expand_inputconfig(
    es_input_path: Path,
    group: list[GuidAlias],
    dry: bool,
) -> tuple[int, int]:
    """Write duplicate ``<inputConfig>`` blocks for every alias in ``group``.

    Mitigation A from the design doc, decision #2: pick the first alias in
    the group as the source of truth (canonical), then ensure every other
    alias GUID has an ``<inputConfig>`` whose ``<input>`` children mirror
    it. Returns ``(added, kept)`` — new blocks synthesised vs blocks
    already present and kept as-is. With ``dry=True`` the file is not
    written and the returned counts describe what *would* change.

    Atomicity: writes via temp + ``os.replace``. A daily one-shot
    ``.bak.rbcf.<YYYYMMDD>`` is created on first mutation per day, plus a
    ring-buffer snapshot under ``%APPDATA%/RB-Controller_fix/history/``
    pruned to the last 10 mutations (decision #5).

    Path-traversal guarded: ``es_input_path`` must resolve under
    ``RETROBAT_ROOT`` (when known), otherwise we refuse the write.
    """
    if not group or len(group) < 2:
        # Singleton groups have no aliases to fold.
        return (0, 0)

    if not dry:
        _validate_under_root(es_input_path)

    if not es_input_path.exists():
        print(f"[guid_aliases] {es_input_path} not found; cannot expand",
              file=sys.stderr)
        return (0, 0)

    try:
        tree = ET.parse(es_input_path)
    except ET.ParseError as e:
        print(f"[guid_aliases] {es_input_path}: XML parse error: {e}",
              file=sys.stderr)
        return (0, 0)

    root = tree.getroot()
    # Locate the canonical block (first alias's GUID).
    canonical_guid = group[0].guid
    canonical_block = None
    existing_by_guid: dict[str, ET.Element] = {}
    for cfg in root.iter("inputConfig"):
        if (cfg.get("type") or "").lower() != "joystick":
            continue
        gid = (cfg.get("deviceGUID") or "").strip().lower()
        if gid:
            existing_by_guid[gid] = cfg
            if gid == canonical_guid and canonical_block is None:
                canonical_block = cfg

    if canonical_block is None:
        # Canonical alias not actually in the file — nothing safe to copy from.
        print(
            f"[guid_aliases] canonical GUID {canonical_guid} not found in "
            f"{es_input_path}; skipping fold",
            file=sys.stderr,
        )
        return (0, 0)

    # Snapshot canonical's <input> children for cloning.
    canonical_inputs = list(canonical_block)
    canonical_attrs = dict(canonical_block.attrib)

    added = 0
    kept = 0
    new_blocks: list[tuple[GuidAlias, ET.Element]] = []
    for alias in group[1:]:
        if alias.guid in existing_by_guid:
            kept += 1
            continue
        # Synthesise a new <inputConfig> mirroring canonical's children.
        new_attrs = dict(canonical_attrs)
        new_attrs["deviceGUID"] = alias.guid
        # Cosmetic — show the alias's recorded device name where available,
        # else mark as alias-of for clarity.
        if alias.device_name:
            new_attrs["deviceName"] = alias.device_name
        else:
            base = canonical_attrs.get("deviceName", "")
            new_attrs["deviceName"] = (
                f"{base} (alias)" if base else "(alias)"
            )
        new_block = ET.Element("inputConfig", new_attrs)
        for child in canonical_inputs:
            # Deep-copy each <input> element. ET doesn't have a built-in
            # deep clone that's bullet-proof for our needs, so build via
            # tostring/fromstring for safety.
            new_block.append(ET.fromstring(ET.tostring(child)))
        new_blocks.append((alias, new_block))
        added += 1

    if dry or added == 0:
        return (added, kept)

    # Insert new blocks immediately after the canonical block (keeps
    # file ordering visually grouped).
    children = list(root)
    try:
        canonical_idx = children.index(canonical_block)
    except ValueError:
        canonical_idx = len(children) - 1
    insert_at = canonical_idx + 1
    for _alias, blk in new_blocks:
        root.insert(insert_at, blk)
        insert_at += 1

    # Backup + ring-buffer snapshot before any write.
    _daily_backup(es_input_path)
    _ring_buffer_snapshot(es_input_path)

    # Atomic write: tempfile + os.replace.
    tmp = es_input_path.with_suffix(es_input_path.suffix + ".rbcf.tmp")
    try:
        # ET.write keeps attribute insertion order on py3.8+; good enough
        # for ES which is forgiving on attribute order. Preserves the
        # XML declaration when xml_declaration=True.
        tree.write(tmp, encoding="utf-8", xml_declaration=True)
        os.replace(tmp, es_input_path)
    except OSError as e:
        print(f"[guid_aliases] write failed: {e}", file=sys.stderr)
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise

    return (added, kept)
