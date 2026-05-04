"""GUID drift watcher daemon — Phase 2 of decision #1 (tray app).

A daemon-thread watcher for ``ES_INPUT`` (the EmulationStation
``es_input.cfg``). On each poll tick it stat()s the file; if mtime has
moved we re-parse + group via :mod:`guid_aliases` and either log what
*would* be folded (``mode='detect'`` — safe, default) or actually fold
silently (``mode='auto-fold'`` — opt-in, decision #4 dual-pad case).

Three modes (persisted via :data:`WATCHER_STATE_PATH`):

- ``'off'``      — thread idles. Lets the user toggle without restarting
                    the tray.
- ``'detect'``   — poll, log ``WatcherEvent(kind='detected')`` events
                    when a fold *would* be needed. Never modifies the
                    es_input.cfg. Default.
- ``'auto-fold'`` — poll, then call ``expand_inputconfig(dry=False)`` on
                    every group that has aliases to add. Logs
                    ``WatcherEvent(kind='folded')`` with ``(added, kept)``
                    counts. Per :mod:`guid_aliases`, this writes a daily
                    backup AND a ring-buffer history snapshot.

Stdlib only. Reads ``ES_INPUT`` and the alias machinery from
:mod:`config` and :mod:`guid_aliases` respectively.

State + log files live under ``%APPDATA%/RB-Controller_fix/`` (falling
back to the project dir when ``%APPDATA%`` is unavailable, e.g. CI).

Public API:
    WATCHER_STATE_PATH, WATCHER_LOG_PATH        — module-level paths
    WatcherEvent (dataclass)                    — log record schema
    start_watcher(shutdown_event, mode='detect') -> Thread
    get_state() -> dict
    set_mode(mode) -> None
    read_log(limit=50) -> list[WatcherEvent]
    clear_log() -> int
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

# Constants ----------------------------------------------------------------

VALID_MODES = ("off", "detect", "auto-fold")
DEFAULT_MODE = "detect"
POLL_INTERVAL_SEC = 5.0
# When the log grows past this many lines we prune from the head.
LOG_PRUNE_LIMIT = 500
# How often (in poll ticks) to run the prune sweep — saves a re-read
# every poll. ~600s with the 5s poll interval.
LOG_PRUNE_TICKS = 120


def _appdata_dir() -> Path:
    """Resolve ``%APPDATA%/RB-Controller_fix/`` — falls back to project root."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "RB-Controller_fix"
    return Path(__file__).resolve().parent / ".rbcf-data"


WATCHER_STATE_PATH: Path = _appdata_dir() / "guid-watcher-state.json"
WATCHER_LOG_PATH: Path = _appdata_dir() / "watcher-log.jsonl"


# Thread-safe state holder -------------------------------------------------

# The watcher thread reads STATE['mode'] on each tick, so set_mode() can
# update it from the tray callback without restarting the thread. Guarded
# by _STATE_LOCK so set_mode + read are consistent.
_STATE_LOCK = threading.Lock()
_STATE: dict[str, Any] = {
    "mode": DEFAULT_MODE,
    "last_seen_mtime": None,
    "last_event_at": None,
}


# Dataclass ---------------------------------------------------------------

@dataclass
class WatcherEvent:
    """One observation written to ``WATCHER_LOG_PATH``.

    ``kind`` is one of:
      - ``'detected'``  — detect-mode found pendings; nothing was written.
      - ``'folded'``    — auto-fold mode actually folded; ``groups`` entries
                          carry ``added`` / ``kept`` counts as the result.
      - ``'error'``     — the poll cycle threw; ``error`` carries the
                          string. Doesn't kill the thread.

    ``timestamp`` is ISO-8601 local time (no tz suffix — matches our
    other artefacts under %APPDATA%/RB-Controller_fix/).

    ``groups`` is a list of dicts, one per alias-group with ``len > 1``:
      ``{vid, pid, alias_count, would_fold[, added, kept]}``.
      ``added`` / ``kept`` are present only on ``kind='folded'`` records.
    """

    kind: str
    timestamp: str
    groups: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WatcherEvent":
        return cls(
            kind=str(data.get("kind", "")),
            timestamp=str(data.get("timestamp", "")),
            groups=list(data.get("groups", []) or []),
            error=data.get("error"),
        )


# State persistence -------------------------------------------------------

def _load_state_from_disk() -> dict[str, Any]:
    """Read the persisted state file. Returns defaults on missing/corrupt."""
    try:
        if not WATCHER_STATE_PATH.is_file():
            return {
                "mode": DEFAULT_MODE,
                "last_seen_mtime": None,
                "last_event_at": None,
            }
        raw = WATCHER_STATE_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
        mode = data.get("mode")
        if mode not in VALID_MODES:
            mode = DEFAULT_MODE
        return {
            "mode": mode,
            "last_seen_mtime": data.get("last_seen_mtime"),
            "last_event_at": data.get("last_event_at"),
        }
    except (OSError, ValueError, json.JSONDecodeError):
        return {
            "mode": DEFAULT_MODE,
            "last_seen_mtime": None,
            "last_event_at": None,
        }


def _persist_state() -> None:
    """Write the current in-memory STATE to disk. Best-effort."""
    try:
        WATCHER_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _STATE_LOCK:
            payload = dict(_STATE)
        WATCHER_STATE_PATH.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        print(f"[guid_watcher] persist state failed: {e}", file=sys.stderr)


def _hydrate_state_once() -> None:
    """Load persisted state into _STATE on first import / start_watcher call.

    Idempotent — calling twice is fine, the second call just re-reads the
    same file.
    """
    loaded = _load_state_from_disk()
    with _STATE_LOCK:
        _STATE.update(loaded)


# Hydrate at module import so get_state() is correct before start_watcher.
_hydrate_state_once()


def get_state() -> dict[str, Any]:
    """Return a snapshot of the watcher's current state for the GUI/tray."""
    with _STATE_LOCK:
        snapshot = dict(_STATE)
    snapshot["log_count"] = _count_log_lines()
    return snapshot


def set_mode(mode: str) -> None:
    """Persist a new watcher mode. Live thread picks it up on next tick.

    Raises ``ValueError`` for unknown modes.
    """
    if mode not in VALID_MODES:
        raise ValueError(
            f"invalid mode {mode!r}; expected one of {VALID_MODES}"
        )
    with _STATE_LOCK:
        _STATE["mode"] = mode
    _persist_state()


# Log file management -----------------------------------------------------

def _count_log_lines() -> int:
    try:
        if not WATCHER_LOG_PATH.is_file():
            return 0
        with WATCHER_LOG_PATH.open("r", encoding="utf-8") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def _append_event(event: WatcherEvent) -> None:
    """Append one event as a JSONL line. Best-effort — never raises."""
    try:
        WATCHER_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event.to_dict(), ensure_ascii=False)
        with WATCHER_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        with _STATE_LOCK:
            _STATE["last_event_at"] = event.timestamp
        _persist_state()
    except OSError as e:
        print(f"[guid_watcher] append log failed: {e}", file=sys.stderr)


def _prune_log() -> None:
    """Trim the log file from the head when it grows past LOG_PRUNE_LIMIT."""
    try:
        if not WATCHER_LOG_PATH.is_file():
            return
        with WATCHER_LOG_PATH.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
        if len(lines) <= LOG_PRUNE_LIMIT:
            return
        keep = lines[-LOG_PRUNE_LIMIT:]
        # Atomic rewrite via tmp.
        tmp = WATCHER_LOG_PATH.with_suffix(WATCHER_LOG_PATH.suffix + ".tmp")
        tmp.write_text("".join(keep), encoding="utf-8")
        os.replace(tmp, WATCHER_LOG_PATH)
    except OSError as e:
        print(f"[guid_watcher] prune log failed: {e}", file=sys.stderr)


def read_log(limit: int = 50) -> list[WatcherEvent]:
    """Return the last ``limit`` events, oldest-first.

    Skips malformed lines silently — we'd rather lose a corrupted record
    than raise from a tray-menu refresh callback.
    """
    if limit <= 0:
        return []
    try:
        if not WATCHER_LOG_PATH.is_file():
            return []
        with WATCHER_LOG_PATH.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return []
    tail = lines[-limit:] if limit < len(lines) else lines
    out: list[WatcherEvent] = []
    for line in tail:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(WatcherEvent.from_dict(json.loads(line)))
        except (ValueError, json.JSONDecodeError):
            continue
    return out


def clear_log() -> int:
    """Truncate the log file. Returns the number of lines that were dropped."""
    try:
        if not WATCHER_LOG_PATH.is_file():
            return 0
        n = _count_log_lines()
        WATCHER_LOG_PATH.write_text("", encoding="utf-8")
        return n
    except OSError as e:
        print(f"[guid_watcher] clear log failed: {e}", file=sys.stderr)
        return 0


# Watcher thread ----------------------------------------------------------

def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _scan_groups(es_input_path: Path) -> tuple[list[dict[str, Any]], int]:
    """Parse + group + dry-run-expand. Returns (group_summaries, total_added).

    Each summary dict has ``vid, pid, alias_count, would_fold`` where
    ``would_fold`` is the dry-run "added" count (number of new
    ``<inputConfig>`` blocks the canonical fold would synthesise).

    Only multi-alias groups are returned — singletons are silently dropped
    since they can't fold.
    """
    # Lazy import to keep guid_watcher importable without RetroBat present
    # (so tests that monkey-patch ES_INPUT can still drive this module).
    from guid_aliases import parse_es_input, group_aliases, expand_inputconfig

    aliases = parse_es_input(es_input_path)
    groups = group_aliases(aliases)

    summaries: list[dict[str, Any]] = []
    total_added = 0
    for (vid, pid), members in groups.items():
        if len(members) < 2:
            continue
        try:
            added, _kept = expand_inputconfig(es_input_path, members, dry=True)
        except (OSError, ValueError) as e:
            print(
                f"[guid_watcher] dry-run expand failed for {vid}:{pid}: {e}",
                file=sys.stderr,
            )
            continue
        if added > 0:
            total_added += added
            summaries.append({
                "vid": vid,
                "pid": pid,
                "alias_count": len(members),
                "would_fold": added,
            })
    return summaries, total_added


def _do_fold(es_input_path: Path,
             summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply the fold for each pending group; mutates summaries with results.

    Returns the updated summaries (with ``added`` / ``kept`` keys filled in).
    """
    from guid_aliases import parse_es_input, group_aliases, expand_inputconfig

    # Re-parse so we have fresh GuidAlias objects in the order
    # expand_inputconfig expects (canonical = group[0]).
    aliases = parse_es_input(es_input_path)
    groups = group_aliases(aliases)
    out: list[dict[str, Any]] = []
    for entry in summaries:
        key = (entry["vid"], entry["pid"])
        members = groups.get(key)
        if not members or len(members) < 2:
            out.append({**entry, "added": 0, "kept": 0,
                        "error": "group disappeared between scan and fold"})
            continue
        try:
            added, kept = expand_inputconfig(es_input_path, members, dry=False)
        except (OSError, ValueError) as e:
            out.append({**entry, "added": 0, "kept": 0, "error": str(e)})
            continue
        out.append({**entry, "added": added, "kept": kept})
    return out


def _interruptible_sleep(shutdown_event: threading.Event,
                         total_seconds: float = POLL_INTERVAL_SEC,
                         step_seconds: float = 1.0) -> bool:
    """Sleep up to ``total_seconds``, returning early if shutdown_event set.

    Returns True if shutdown was requested, False if we slept the full duration.
    """
    elapsed = 0.0
    while elapsed < total_seconds:
        if shutdown_event.is_set():
            return True
        time.sleep(min(step_seconds, total_seconds - elapsed))
        elapsed += step_seconds
    return shutdown_event.is_set()


def _watcher_loop(shutdown_event: threading.Event,
                  es_input_path: Path) -> None:
    """The poll loop. Runs until shutdown_event is set."""
    tick = 0
    while not shutdown_event.is_set():
        tick += 1
        # Read the *current* mode each tick so set_mode() updates take
        # effect without a thread restart.
        with _STATE_LOCK:
            mode = _STATE.get("mode", DEFAULT_MODE)
            last_mtime = _STATE.get("last_seen_mtime")

        if mode == "off":
            if _interruptible_sleep(shutdown_event):
                return
            continue

        try:
            try:
                stat = es_input_path.stat()
            except FileNotFoundError:
                # No es_input.cfg yet — sleep and re-check. Common on a
                # fresh RetroBat install before ES has been launched.
                if _interruptible_sleep(shutdown_event):
                    return
                continue
            except OSError as e:
                # Surface as an error event but don't kill the thread.
                _append_event(WatcherEvent(
                    kind="error",
                    timestamp=_now_iso(),
                    error=f"stat failed: {e}",
                ))
                if _interruptible_sleep(shutdown_event):
                    return
                continue

            mtime = stat.st_mtime
            if last_mtime is not None and mtime == last_mtime:
                # No change since last tick; nothing to do.
                if tick % LOG_PRUNE_TICKS == 0:
                    _prune_log()
                if _interruptible_sleep(shutdown_event):
                    return
                continue

            # File changed (or first observation). Update mtime first so
            # we don't loop forever on a parse error of an unchanged file.
            with _STATE_LOCK:
                _STATE["last_seen_mtime"] = mtime
            _persist_state()

            summaries, total_added = _scan_groups(es_input_path)

            if total_added == 0:
                # File changed but nothing pending. Don't spam the log.
                if tick % LOG_PRUNE_TICKS == 0:
                    _prune_log()
                if _interruptible_sleep(shutdown_event):
                    return
                continue

            if mode == "detect":
                _append_event(WatcherEvent(
                    kind="detected",
                    timestamp=_now_iso(),
                    groups=summaries,
                ))
            elif mode == "auto-fold":
                folded = _do_fold(es_input_path, summaries)
                _append_event(WatcherEvent(
                    kind="folded",
                    timestamp=_now_iso(),
                    groups=folded,
                ))
                # Refresh mtime — our own write bumped it; without this
                # the next tick would re-trigger.
                try:
                    with _STATE_LOCK:
                        _STATE["last_seen_mtime"] = es_input_path.stat().st_mtime
                    _persist_state()
                except OSError:
                    pass
            # Any other (defensive) — fall through.

        except Exception as e:  # noqa: BLE001 — the whole point: never die
            _append_event(WatcherEvent(
                kind="error",
                timestamp=_now_iso(),
                error=f"poll exception: {e!r}",
            ))

        if tick % LOG_PRUNE_TICKS == 0:
            _prune_log()

        if _interruptible_sleep(shutdown_event):
            return


def start_watcher(shutdown_event: threading.Event,
                  mode: str = DEFAULT_MODE,
                  es_input_path: Path | None = None) -> threading.Thread:
    """Spawn the watcher daemon thread.

    Args:
        shutdown_event: shared with the tray app; setting it causes the
            watcher to exit at its next poll boundary.
        mode: initial mode, persisted on the spot. One of ``VALID_MODES``.
            Default ``'detect'`` per :data:`DEFAULT_MODE`.
        es_input_path: override for tests. Defaults to ``config.ES_INPUT``.

    Returns the daemon thread (already started).
    """
    if mode not in VALID_MODES:
        raise ValueError(
            f"invalid mode {mode!r}; expected one of {VALID_MODES}"
        )

    # Persist the requested mode so subsequent restarts pick it up.
    with _STATE_LOCK:
        _STATE["mode"] = mode
    _persist_state()

    if es_input_path is None:
        # Lazy import — config has Windows-specific imports we want to
        # defer until actually needed.
        from config import ES_INPUT
        es_input_path = ES_INPUT

    thread = threading.Thread(
        target=_watcher_loop,
        args=(shutdown_event, es_input_path),
        name="rbcf-guid-watcher",
        daemon=True,
    )
    thread.start()
    return thread


__all__ = [
    "WATCHER_STATE_PATH",
    "WATCHER_LOG_PATH",
    "VALID_MODES",
    "DEFAULT_MODE",
    "WatcherEvent",
    "start_watcher",
    "get_state",
    "set_mode",
    "read_log",
    "clear_log",
]
