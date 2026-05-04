"""GUID drift mitigation: detect and fold SDL controller GUID aliases.

Scaffold module — function bodies pending review. Implementation tracked
in ``docs/GUID_DRIFT_DESIGN.md``. See that document for the alias-group
definition, dual-pad disambiguation strategy, and risk surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class GuidAlias:
    """One SDL controller GUID observation, indexed for alias grouping.

    ``guid`` is the 32-hex-char lowercase SDL2 ``SDL_JoystickGUID`` as
    written to ``es_input.cfg`` ``deviceGUID`` attributes. ``vid`` and
    ``pid`` are extracted from bytes 4-5 and 8-9 of that GUID (see design
    doc 1, "GUID layout") and serve as the alias-group key. ``instance_id``
    is the Windows HID ``InstanceId`` if known (used to disambiguate two
    physically-distinct pads sharing a VID:PID, e.g. the user's two 8BitDo
    Ultimates per CLAUDE.md). ``last_seen`` is an ISO-8601 timestamp from
    our sidecar history, ``None`` when the alias was discovered solely from
    on-disk parsing.
    """

    guid: str
    vid: str
    pid: str
    instance_id: str | None = None
    last_seen: str | None = None


def parse_es_input(path: Path) -> list[GuidAlias]:
    """Parse ``es_input.cfg`` and return every ``<inputConfig>`` as a GuidAlias.

    EmulationStation never garbage-collects ``<inputConfig>`` blocks, so
    the returned list is the user's full historical alias surface — every
    transport / driver permutation any of their pads has ever taken.
    Entries with malformed or missing ``deviceGUID`` are skipped silently
    (they won't survive an ES round-trip anyway).
    """
    raise NotImplementedError("Stream B scaffold — implementation pending review")


def group_aliases(aliases: list[GuidAlias]) -> dict[tuple[str, str], list[GuidAlias]]:
    """Group aliases into candidate alias-groups keyed by ``(vid, pid)``.

    A single returned list is *one* alias group only when no two physical
    pads share that VID:PID. The dual-8BitDo case must be split further
    via instance-id disambiguation before any rewrite — see design doc 6.
    Callers performing a write MUST run that split first.
    """
    raise NotImplementedError("Stream B scaffold — implementation pending review")


def expand_inputconfig(
    es_input_path: Path,
    group: list[GuidAlias],
    dry: bool,
) -> tuple[int, int]:
    """Write duplicate ``<inputConfig>`` blocks for every alias in ``group``.

    Mitigation A from the design doc: pick the most-recent block in the
    group as the source of truth, then ensure every alias GUID has an
    ``<inputConfig>`` whose ``<input>`` children mirror it. Returns
    ``(added, kept)`` — new blocks synthesised vs existing blocks
    updated in place. With ``dry=True`` the file is not written and the
    returned counts describe what *would* change.

    Atomicity: writes via temp + ``os.replace``. A daily one-shot
    ``.bak.rbcf.<YYYYMMDD>`` is created on first mutation per day, per
    the convention in CLAUDE.md.
    """
    raise NotImplementedError("Stream B scaffold — implementation pending review")
