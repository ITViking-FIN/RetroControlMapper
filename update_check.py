"""
update_check.py — passive "check for updates" against the project's GitHub repo.

Stdlib-only. Compares the local ``__version__`` (config.py) against
``tag_name`` from the latest GitHub release of the configured repo
(``GITHUB_OWNER`` / ``GITHUB_REPO`` constants in config.py). Same shape
as ``system_lookup.py``: dataclass + cache file + lookup function +
``load_cached`` / ``clear_cache`` helpers.

Usage (typical, from the GUI server):
    res = check_for_updates(allow_online=True)
    if res.update_available:
        ...

Cache:
    %APPDATA%/RB-Controller_fix/update-check.json   (Windows)
    <project_root>/.update-check.json               (fallback)

The cache is a single file, not a per-key directory: there is exactly
one record (the latest release polled). 24h TTL for normal results
(``live`` / ``unreleased``). 1h TTL for ``error`` entries so we retry
sooner when the network was misbehaving but don't spam GitHub when it's
healthy.

GitHub returns ``404 {"message": "Not Found"}`` for repos with no
releases yet, which is the case while RetroControlMapper is pre-1.0.
We map that specifically to ``source='unreleased'`` (not ``'error'``)
so the frontend can render "no releases yet — you're on the latest dev
build" rather than a scary error pill.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from config import GITHUB_OWNER, GITHUB_REPO, __version__

USER_AGENT = f"RB-Controller_fix/{__version__}"
HTTP_TIMEOUT = 10  # seconds — every outbound request

# Cache TTLs.
CACHE_TTL_OK = 24 * 60 * 60     # 24h for live / unreleased / cache
CACHE_TTL_ERR = 1 * 60 * 60     # 1h for transient network errors


def _resolve_cache_path() -> Path:
    """Locate the single update-check.json. Prefer %APPDATA%; fallback to project."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        try:
            d = Path(appdata) / "RB-Controller_fix"
            d.mkdir(parents=True, exist_ok=True)
            return d / "update-check.json"
        except OSError:
            pass
    return Path(__file__).resolve().parent / ".update-check.json"


UPDATE_CACHE_PATH = _resolve_cache_path()


@dataclass
class UpdateInfo:
    current: str = __version__
    latest: str | None = None
    update_available: bool = False
    release_url: str | None = None
    release_notes_excerpt: str | None = None
    published_at: str | None = None       # ISO from GitHub
    checked_at: str = ""                  # ISO when WE checked
    source: str = "cache"                 # 'cache' | 'live' | 'unreleased' | 'error'
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Time / cache helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def _parse_iso(s: str) -> float | None:
    """Parse an ISO ``YYYY-MM-DDTHH:MM:SSZ`` to epoch seconds. None on failure.

    Uses datetime.fromisoformat with explicit UTC tzinfo so the result
    is unambiguously a UTC epoch — the previous time.mktime() path
    interpreted the struct as local-time and double-corrected via
    time.timezone, which was off by the DST offset in DST-observing
    locales (audit finding M6).
    """
    if not s:
        return None
    try:
        from datetime import datetime, timezone
        cleaned = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def _write_cache(info: UpdateInfo) -> None:
    """Persist ``info`` to UPDATE_CACHE_PATH. Best-effort; never raises."""
    payload = info.to_dict()
    try:
        UPDATE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        UPDATE_CACHE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass


def load_cached() -> UpdateInfo | None:
    """Return the cached UpdateInfo, or None if there is no cache file."""
    if not UPDATE_CACHE_PATH.exists():
        return None
    try:
        data = json.loads(UPDATE_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return UpdateInfo(
        current=data.get("current", __version__),
        latest=data.get("latest"),
        update_available=bool(data.get("update_available", False)),
        release_url=data.get("release_url"),
        release_notes_excerpt=data.get("release_notes_excerpt"),
        published_at=data.get("published_at"),
        checked_at=data.get("checked_at", ""),
        source=data.get("source", "cache"),
        error=data.get("error"),
    )


def clear_cache() -> bool:
    """Delete the cache file. Returns True if a file was removed."""
    try:
        if UPDATE_CACHE_PATH.is_file():
            UPDATE_CACHE_PATH.unlink()
            return True
    except OSError:
        pass
    return False


# Update-check consent file. Lives next to the cache. The frontend
# normally manages consent via localStorage['rbcf-update-consent'], but
# the Inno installer needs a server-side way to set the same flag at
# install time without launching a browser. This file is the shared
# source of truth — both the API endpoint and the frontend honour it.
CONSENT_PATH = UPDATE_CACHE_PATH.parent / "update-check-consent.json"


def set_consent(enabled: bool) -> None:
    """Write a persistent update-check consent decision. Used by the
    installer's --set-update-check-consent flag to record the user's
    choice from the wizard without requiring them to open the GUI.
    """
    try:
        CONSENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONSENT_PATH.write_text(
            json.dumps({"enabled": bool(enabled)}, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        print(f"[update_check] WARN: could not write consent: {e}",
              file=sys.stderr)


def get_consent() -> bool | None:
    """Read the persisted consent decision, or None if not set."""
    try:
        if CONSENT_PATH.is_file():
            data = json.loads(CONSENT_PATH.read_text(encoding="utf-8"))
            return bool(data.get("enabled"))
    except (OSError, json.JSONDecodeError):
        pass
    return None


def is_update_pending() -> bool:
    """Cheap check used by the frontend to decide whether to render the badge.

    Reads cache only — never hits the network.
    """
    cached = load_cached()
    return bool(cached and cached.update_available)


# ---------------------------------------------------------------------------
# Semver compare
# ---------------------------------------------------------------------------

_SEMVER_NUM_RE = re.compile(r"^(\d+)(.*)$")


def _split_version(v: str) -> tuple[list[int], str]:
    """Split ``1.2.3-rc1`` into ([1,2,3], 'rc1').

    Anything after the first ``-`` is the pre-release string. Numeric parts
    of the dotted prefix are parsed as ints; non-numeric parts become 0
    (best-effort, defensive against malformed tags).
    """
    s = (v or "").strip()
    # Strip leading v/V.
    if s[:1] in ("v", "V"):
        s = s[1:]
    if "-" in s:
        head, _, pre = s.partition("-")
    else:
        head, pre = s, ""
    parts: list[int] = []
    for chunk in head.split("."):
        m = _SEMVER_NUM_RE.match(chunk)
        if m:
            try:
                parts.append(int(m.group(1)))
            except ValueError:
                parts.append(0)
        else:
            parts.append(0)
    return parts, pre


def _compare_semver(a: str, b: str) -> int:
    """Return -1 if a<b, 0 if a==b, 1 if a>b. Pre-release < release.

    Examples:
        _compare_semver('0.1.0', '0.2.0')      ->  -1
        _compare_semver('1.0.0', '1.0.0-rc1')  ->   1   (release > rc)
        _compare_semver('v1.2.3', '1.2.3')     ->   0
    """
    pa, prea = _split_version(a)
    pb, preb = _split_version(b)

    # Pad shorter list with zeros.
    n = max(len(pa), len(pb))
    pa.extend([0] * (n - len(pa)))
    pb.extend([0] * (n - len(pb)))

    if pa < pb:
        return -1
    if pa > pb:
        return 1
    # Numeric portions equal — handle pre-release.
    # Per semver: 1.0.0-rc1 < 1.0.0. Empty pre = release.
    if prea == preb:
        return 0
    if prea == "":
        return 1   # release > prerelease
    if preb == "":
        return -1  # prerelease < release
    if prea < preb:
        return -1
    if prea > preb:
        return 1
    return 0


# ---------------------------------------------------------------------------
# Cache freshness
# ---------------------------------------------------------------------------

def _is_fresh(info: UpdateInfo) -> bool:
    """True if cached ``info.checked_at`` is within the appropriate TTL."""
    ts = _parse_iso(info.checked_at)
    if ts is None:
        return False
    age = time.time() - ts
    ttl = CACHE_TTL_ERR if info.source == "error" else CACHE_TTL_OK
    return age >= 0 and age < ttl


# ---------------------------------------------------------------------------
# Online fetch
# ---------------------------------------------------------------------------

def _fetch_latest_release() -> tuple[int, dict | None, str | None]:
    """Hit GitHub's releases/latest for the configured repo.

    Returns (status_code, parsed_json_or_None, transport_error_or_None).
    A 404 with body ``{"message": "Not Found"}`` means "no releases yet"
    and is signalled as (404, {...}, None) — caller maps to 'unreleased'.
    Transport failures (DNS, timeout, refused) return (-1, None, "msg").
    """
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            status = getattr(resp, "status", None) or resp.getcode() or 0
            raw = resp.read(1_000_000)  # generous cap; release bodies are small
            try:
                return status, json.loads(raw.decode("utf-8", errors="replace")), None
            except (ValueError, json.JSONDecodeError) as e:
                return status, None, f"bad JSON from GitHub: {e}"
    except urllib.error.HTTPError as e:
        # 404 is the "no releases yet" signal — try to parse the body too.
        try:
            raw = e.read()
            body = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception:
            body = None
        return e.code, body, None
    except urllib.error.URLError as e:
        return -1, None, f"network error: {e.reason}"
    except TimeoutError:
        return -1, None, "timeout"
    except OSError as e:
        return -1, None, f"connection failed: {e}"
    except Exception as e:  # pragma: no cover - defensive
        return -1, None, f"unexpected error: {e}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_for_updates(allow_online: bool = False, force: bool = False) -> UpdateInfo:
    """Look up the latest release and compare with the local version.

    Order:
      1. If a cache exists, is fresh (<24h ok / <1h err), and ``force`` is
         False, return it with ``source='cache'``.
      2. If ``allow_online`` is False, return cached (stale) if any, else
         a stub UpdateInfo carrying ``error='online check not authorised'``.
         The frontend uses this to decide whether to prompt for consent.
      3. Hit GitHub's releases/latest.
         - 200 → parse ``tag_name``, compare with local. ``source='live'``.
         - 404 with ``{"message": "Not Found"}`` → repo has no releases.
           ``source='unreleased'``, ``latest=None``, no error.
         - other HTTP error or transport failure → ``source='error'``.
      4. Cache the result (always, including errors and unreleased — but
         errors get a shorter TTL so we retry sooner).
    """
    cached = load_cached()

    if not force and cached is not None and _is_fresh(cached):
        # Re-stamp source as 'cache' regardless of what we cached it as.
        cached.source = "cache"
        return cached

    if not allow_online:
        if cached is not None:
            cached.source = "cache"
            return cached
        # No cache and user hasn't consented → frontend reads `error` and
        # shows the consent prompt.
        return UpdateInfo(
            current=__version__,
            source="cache",
            error="online check not authorised",
            checked_at=_now_iso(),
        )

    # Online fetch.
    status, body, transport_err = _fetch_latest_release()
    now = _now_iso()

    if transport_err is not None:
        info = UpdateInfo(
            current=__version__,
            source="error",
            error=transport_err,
            checked_at=now,
        )
        _write_cache(info)
        return info

    if status == 404:
        # GitHub says "Not Found" — for an existing public repo, this is the
        # "no releases yet" signal. Distinguish it from a typo'd repo by
        # checking the message body, but be lenient: if body parsing failed,
        # still treat as unreleased rather than an error.
        msg = (body or {}).get("message") if isinstance(body, dict) else None
        info = UpdateInfo(
            current=__version__,
            latest=None,
            update_available=False,
            source="unreleased",
            error=None,
            checked_at=now,
        )
        # Defensive: only override to error if message was clearly something
        # other than "Not Found". (Empty body / unknown shape → treat as
        # unreleased; the repo IS new.)
        if isinstance(msg, str) and msg and msg.lower() != "not found":
            info.source = "error"
            info.error = f"GitHub 404: {msg}"
        _write_cache(info)
        return info

    if status != 200 or not isinstance(body, dict):
        info = UpdateInfo(
            current=__version__,
            source="error",
            error=f"GitHub HTTP {status}",
            checked_at=now,
        )
        _write_cache(info)
        return info

    # Success: extract release fields.
    tag = (body.get("tag_name") or "").strip()
    if not tag:
        info = UpdateInfo(
            current=__version__,
            source="error",
            error="release has empty tag_name",
            checked_at=now,
        )
        _write_cache(info)
        return info

    # Normalise (strip leading v/V) for both display and compare.
    latest_clean = tag[1:] if tag[:1] in ("v", "V") else tag
    raw_body = body.get("body") or ""
    excerpt = raw_body[:300] if raw_body else None

    cmp = _compare_semver(__version__, latest_clean)
    info = UpdateInfo(
        current=__version__,
        latest=latest_clean,
        update_available=(cmp < 0),
        release_url=body.get("html_url"),
        release_notes_excerpt=excerpt,
        published_at=body.get("published_at"),
        checked_at=now,
        source="live",
        error=None,
    )
    _write_cache(info)
    return info


__all__ = [
    "set_consent",
    "get_consent",
    "UPDATE_CACHE_PATH",
    "USER_AGENT",
    "UpdateInfo",
    "check_for_updates",
    "load_cached",
    "clear_cache",
    "is_update_pending",
    "_compare_semver",
]
