"""
system_lookup.py — best-effort online lookup for systems missing curated metadata.

Stdlib-only. Driven by the GUI when the user picks a system that has no entry in
HARDCODED_SYSTEMS (no `target_controller` and no `fixed_mapping_note`). The user
is asked for explicit consent before any network request leaves the box.

Usage:
    res = lookup("astrocade", allow_online=True)
    if res.source != "none":
        print(res.mapping_note, "from", res.source_url)

Cache:
    %APPDATA%/RetroControlMapper/system-lookups/<system_id>.json   (Windows)
    <project_root>/.system-lookups/<system_id>.json                (fallback)

Cache is also written for failures so we don't pummel the network. Use
``force_refresh=True`` (or ``clear_cache(system_id)``) to bust it.
"""
from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

from config import __version__ as _rbcf_v
USER_AGENT = f"RetroControlMapper/{_rbcf_v} (+https://github.com/ITViking-FIN/RetroControlMapper)"
HTTP_TIMEOUT = 10  # seconds — every outbound request

# system_id sanity. Anything outside this is rejected (path-traversal guard).
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _resolve_cache_dir() -> Path:
    """Locate the lookup cache. Prefer %APPDATA%; fall back to project root."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        try:
            p = Path(appdata) / "RetroControlMapper" / "system-lookups"
            p.mkdir(parents=True, exist_ok=True)
            return p
        except OSError:
            pass
    fallback = Path(__file__).resolve().parent / ".system-lookups"
    try:
        fallback.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return fallback


LOOKUP_CACHE_DIR = _resolve_cache_dir()


@dataclass
class LookupResult:
    system_id: str
    source: str = "none"  # 'cache' | 'retrobat-wiki' | 'libretro-docs' | 'launcher-source' | 'none'
    name: str | None = None
    mapping_note: str | None = None
    target_controller: str | None = None
    source_url: str | None = None
    excerpt: str | None = None
    error: str | None = None
    cached_at: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# system_id sanity + cache I/O
# ---------------------------------------------------------------------------

def _safe_id(system_id: str) -> str:
    """Reject ids that could escape the cache dir. Returns a clean id or raises."""
    sid = (system_id or "").strip().lower()
    if not sid or not _SAFE_ID_RE.match(sid):
        raise ValueError(f"invalid system_id: {system_id!r}")
    return sid


def _cache_path(system_id: str) -> Path:
    return LOOKUP_CACHE_DIR / f"{_safe_id(system_id)}.json"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def _write_cache(result: LookupResult) -> None:
    """Persist a result. Cache misses ALSO get persisted so we don't re-hit."""
    try:
        path = _cache_path(result.system_id)
    except ValueError:
        return
    payload = result.to_dict()
    payload["cached_at"] = _now_iso()
    try:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass


def load_cached(system_id: str) -> LookupResult | None:
    """Return the cached LookupResult, or None if there is no cache entry."""
    try:
        path = _cache_path(system_id)
    except ValueError:
        return None
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return LookupResult(
        system_id=data.get("system_id", system_id),
        source="cache",
        name=data.get("name"),
        mapping_note=data.get("mapping_note"),
        target_controller=data.get("target_controller"),
        source_url=data.get("source_url"),
        excerpt=data.get("excerpt"),
        error=data.get("error"),
        cached_at=data.get("cached_at"),
    )


def clear_cache(system_id: str | None = None) -> int:
    """Delete one cache entry (if ``system_id`` given) or all of them. Returns count."""
    if system_id is not None:
        try:
            path = _cache_path(system_id)
        except ValueError:
            return 0
        if path.exists():
            try:
                path.unlink()
                return 1
            except OSError:
                return 0
        return 0
    n = 0
    if not LOOKUP_CACHE_DIR.exists():
        return 0
    for p in LOOKUP_CACHE_DIR.glob("*.json"):
        try:
            p.unlink()
            n += 1
        except OSError:
            continue
    return n


# ---------------------------------------------------------------------------
# Online fetch helpers
# ---------------------------------------------------------------------------

def _http_get(url: str) -> tuple[int, str] | tuple[int, None]:
    """GET ``url`` and return (status, text). Best-effort; never raises.

    Returns (-1, None) on transport failure (DNS / timeout / TLS / etc.).
    """
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            status = getattr(resp, "status", None) or resp.getcode() or 0
            raw = resp.read(512_000)  # hard cap — we only want a small excerpt
            charset = resp.headers.get_content_charset() or "utf-8"
            try:
                text = raw.decode(charset, errors="replace")
            except LookupError:
                text = raw.decode("utf-8", errors="replace")
            return status, text
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, TimeoutError, OSError):
        return -1, None
    except Exception:  # pragma: no cover - defensive
        return -1, None


# ---------------------------------------------------------------------------
# Per-source URL probes + parsers
# ---------------------------------------------------------------------------

# Heuristic: system_id → libretro-docs core slug. Best-effort; many won't match,
# in which case we just skip libretro-docs in the chain.
_LIBRETRO_CORE_GUESS = {
    "snes": "bsnes",
    "nes": "nestopia",
    "n64": "mupen64plus",
    "gb": "gambatte",
    "gbc": "gambatte",
    "gba": "mgba",
    "psx": "beetle_psx_hw",
    "saturn": "beetle_saturn",
    "dreamcast": "flycast",
    "megadrive": "genesis_plus_gx",
    "genesis": "genesis_plus_gx",
    "mastersystem": "genesis_plus_gx",
    "gamegear": "genesis_plus_gx",
    "pcengine": "beetle_pce",
    "lynx": "handy",
    "wonderswan": "beetle_wonderswan",
    "wswan": "beetle_wonderswan",
    "ngp": "beetle_neopop",
    "ngpc": "beetle_neopop",
    "atari2600": "stella",
    "atari7800": "prosystem",
    "neogeo": "fbneo",
    "neogeocd": "neocd",
    "mame": "mame",
    "fbneo": "fbneo",
    "cps1": "fbneo",
    "cps2": "fbneo",
    "cps3": "fbneo",
}

# launcher-source slug overrides where the .Generator.cs filename doesn't equal
# Title-cased system id. Best-effort — anything else falls back to slug-as-is.
_LAUNCHER_SLUG = {
    "psx": "DuckStation",      # Several PSX generators exist; this is one
    "snes": "Snes9x",
    "nes": "Nes",
    "n64": "Mupen64",
    "gb": "GameBoy",
    "gbc": "GameBoy",
    "gba": "MGba",
    "saturn": "Mednafen",
    "dreamcast": "Reicast",
    "megadrive": "GenesisPlusGx",
    "genesis": "GenesisPlusGx",
    "mastersystem": "GenesisPlusGx",
    "atari2600": "Stella",
    "neogeo": "FbNeo",
}


def _build_urls(system_id: str) -> list[tuple[str, str]]:
    """Return [(source_label, url), ...] in fallback order."""
    sid = _safe_id(system_id)
    urls: list[tuple[str, str]] = []

    # 1) RetroBat wiki — system pages live under several parent paths and the
    #    exact slug varies. We try a couple of plausible URL shapes.
    urls.append((
        "retrobat-wiki",
        f"https://wiki.retrobat.org/systems-and-emulators/supported-game-systems/{sid}",
    ))
    urls.append((
        "retrobat-wiki",
        f"https://wiki.retrobat.org/systems-and-emulators/{sid}",
    ))

    # 2) libretro docs — guess a likely core slug.
    core = _LIBRETRO_CORE_GUESS.get(sid, sid)
    urls.append((
        "libretro-docs",
        f"https://docs.libretro.com/library/{core}/",
    ))

    # 3) launcher source — raw view on github.
    slug = _LAUNCHER_SLUG.get(sid, sid.capitalize())
    urls.append((
        "launcher-source",
        (
            "https://raw.githubusercontent.com/RetroBat-Official/emulatorlauncher/"
            f"master/emulatorLauncher/Generators/{slug}.Generator.cs"
        ),
    ))

    return urls


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_TABLE_RE = re.compile(r"<table[\s\S]*?</table>", re.IGNORECASE)
_BUTTON_HINT_RE = re.compile(
    r"\b(retropad|button|d-pad|joystick|trigger|shoulder|select|start|l1|l2|r1|r2)\b",
    re.IGNORECASE,
)


def _strip_html(s: str) -> str:
    """Cheap text extraction. Not a full HTML parser; not trying to be."""
    s = _TAG_RE.sub(" ", s)
    s = html.unescape(s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def _parse_html(text: str, system_id: str, source: str) -> dict:
    """Pull a name + mapping note + excerpt out of an HTML page. Best-effort."""
    out: dict = {}

    # Display name from <h1> or <title>.
    name = None
    m = _H1_RE.search(text)
    if m:
        name = _strip_html(m.group(1))
    if not name:
        m = _TITLE_RE.search(text)
        if m:
            name = _strip_html(m.group(1))
            # Trim trailing site name (" - RetroBat Wiki" etc.)
            for sep in (" - ", " | ", " — "):
                if sep in name:
                    name = name.split(sep, 1)[0].strip()
    if name:
        out["name"] = name[:120]

    # Mapping note: prefer the first <table> that mentions a button-ish word.
    note = None
    for tbl in _TABLE_RE.findall(text):
        if _BUTTON_HINT_RE.search(tbl):
            flat = _strip_html(tbl)
            if flat:
                note = flat[:400]
                break
    if not note:
        # Fallback: any sentence with a button-hint word.
        flat = _strip_html(text)
        m = _BUTTON_HINT_RE.search(flat)
        if m:
            start = max(0, m.start() - 120)
            note = flat[start:start + 360].strip()
    if note:
        out["mapping_note"] = note

    # Short excerpt for the user to verify the source isn't garbage.
    flat_all = _strip_html(text)
    out["excerpt"] = flat_all[:240]

    return out


def _parse_cs_source(text: str, system_id: str) -> dict:
    """Pull binding hints out of an emulatorLauncher .Generator.cs raw file."""
    out: dict = {"name": system_id}

    # Lines like ``ctrlrCfg["b"] = "RetroPad-A";`` or similar. We don't try to
    # interpret — just surface a few of them as the proposed mapping note.
    bind_lines = []
    for line in text.splitlines():
        ln = line.strip()
        if len(bind_lines) >= 8:
            break
        if not ln or ln.startswith("//"):
            continue
        if any(tok in ln for tok in ("ctrlrCfg[", "Button(", "Mapping(", "RetroPad", "input_player1_")):
            # Strip C# noise
            cleaned = re.sub(r"\s+", " ", ln).strip(" ;{}")
            if 4 < len(cleaned) < 200:
                bind_lines.append(cleaned)

    if bind_lines:
        out["mapping_note"] = " | ".join(bind_lines)
    out["excerpt"] = "\n".join(text.splitlines()[:8])[:240]
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lookup(
    system_id: str,
    allow_online: bool = False,
    force_refresh: bool = False,
) -> LookupResult:
    """Look up controller info for ``system_id``.

    Order:
      1. Cache hit (unless ``force_refresh``).
      2. If ``allow_online`` is False → return source='none' with auth error.
      3. Try wiki / libretro-docs / launcher-source in order until we get
         a 200 with usable content.
      4. Cache whatever we got (success or error) and return.
    """
    try:
        sid = _safe_id(system_id)
    except ValueError as e:
        return LookupResult(system_id=system_id, source="none", error=str(e))

    if not force_refresh:
        cached = load_cached(sid)
        if cached is not None:
            return cached

    if not allow_online:
        return LookupResult(system_id=sid, source="none", error="online lookup not authorised")

    last_error: str | None = None
    for source_label, url in _build_urls(sid):
        status, text = _http_get(url)
        if status == 200 and text:
            # Source-specific parsing
            try:
                if source_label == "launcher-source":
                    parsed = _parse_cs_source(text, sid)
                else:
                    parsed = _parse_html(text, sid, source_label)
            except Exception as e:  # pragma: no cover - parser robustness
                last_error = f"parse failed for {source_label}: {e}"
                continue
            if parsed.get("mapping_note") or parsed.get("name"):
                result = LookupResult(
                    system_id=sid,
                    source=source_label,
                    name=parsed.get("name"),
                    mapping_note=parsed.get("mapping_note"),
                    target_controller=None,  # too risky to infer; user picks
                    source_url=url,
                    excerpt=parsed.get("excerpt"),
                )
                _write_cache(result)
                return result
            last_error = f"{source_label} returned 200 but yielded no usable content"
            continue
        if status == -1:
            last_error = f"{source_label} unreachable (network error)"
        elif status == 404:
            last_error = f"{source_label} 404"
        else:
            last_error = f"{source_label} HTTP {status}"

    result = LookupResult(
        system_id=sid,
        source="none",
        error=last_error or "no source returned usable content",
    )
    _write_cache(result)
    return result


__all__ = [
    "LOOKUP_CACHE_DIR",
    "USER_AGENT",
    "LookupResult",
    "lookup",
    "load_cached",
    "clear_cache",
]
