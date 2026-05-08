"""
Online manual research — Flaresolverr-based fetcher + per-site scrapers.

Looks up game manuals on three large public archives when the local
Manual_Package archive doesn't have what we need:

  1. https://vimm.net/manual              (Vimm's Lair — well-structured, easy)
  2. https://www.gamesdatabase.org/all_manuals
  3. https://replacementdocs.com/download.php

All three are behind Cloudflare or similar anti-bot layers, so we route
all HTTP through **Flaresolverr** — a small headless-browser proxy that
solves Cloudflare's JS challenge and returns the resolved HTML.

## Flaresolverr setup

Flaresolverr runs as a local HTTP service (default `localhost:8191`).
Easiest install via Docker:

    docker run -d --name=flaresolverr \\
        --restart=unless-stopped \\
        -p 8191:8191 \\
        -e LOG_LEVEL=info \\
        ghcr.io/flaresolverr/flaresolverr:latest

For non-Docker users: clone https://github.com/FlareSolverr/FlareSolverr
and `python3 src/flaresolverr.py`.

## Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌──────────────┐
│ research_manual │ -> │ FlaresolverClient │ -> │ Flaresolverr │
│   (orchestr.)   │    │   (proxy adapter) │    │  (localhost) │
└─────────────────┘    └──────────────────┘    └──────────────┘
        │
        v
┌──────────────────────────────────────────┐
│  Per-site scrapers (subclass ManualSite) │
│   • VimmManualSite      — implemented    │
│   • GamesDatabaseSite   — TODO           │
│   • ReplacementDocsSite — TODO           │
└──────────────────────────────────────────┘
```

`research_manual(system_id, rom_name)` is the entry point. It tries each
configured site in order until one returns a hit, caches the result
(URL + downloaded PDF), and returns structured info that downstream
code can feed into the profile.

## State of implementation (v0.1.4-stage-2)

This module ships the FRAMEWORK and ONE complete site (Vimm). The
other two scrapers are stubbed; their adapters need HTML-parsing logic
in `_search_results` and `_manual_url_from_page`. See site-specific
TODO blocks below.

## Usage

    py manual_research_online.py status     # check Flaresolverr health
    py manual_research_online.py lookup snes "Super Mario World"

Programmatic:

    from manual_research_online import research_manual
    hit = research_manual("nes", "Castlevania")
    if hit:
        print(hit["pdf_path"])  # downloaded local cache
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
ONLINE_CACHE_DIR = DATA_DIR / "manuals_online"
ONLINE_CACHE_INDEX = DATA_DIR / "manuals_online_cache.json"

FLARESOLVERR_URL = "http://localhost:8191/v1"
DEFAULT_TIMEOUT_MS = 60_000          # 60s per request
USER_AGENT = "RB-Controller_fix/0.1.4 manual-research"


# ============================================================
# Flaresolverr client
# ============================================================

class FlaresolverrError(RuntimeError):
    pass


class FlaresolverrClient:
    """Tiny client for the Flaresolverr proxy. Posts {cmd, url} and
    returns the resolved HTML."""

    def __init__(self, endpoint: str = FLARESOLVERR_URL,
                 timeout_ms: int = DEFAULT_TIMEOUT_MS):
        self.endpoint = endpoint
        self.timeout_ms = timeout_ms
        self.session_id: str | None = None

    def _post(self, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_ms / 1000 + 5) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise FlaresolverrError(
                f"Flaresolverr unreachable at {self.endpoint} — is it running?\n"
                f"  Start with: docker run -d -p 8191:8191 ghcr.io/flaresolverr/flaresolverr:latest\n"
                f"  ({e})"
            ) from e

    def health(self) -> dict:
        """Return Flaresolverr's status, or raise FlaresolverrError."""
        # Flaresolverr's GET / returns a status banner
        try:
            req = urllib.request.Request(self.endpoint.replace("/v1", "/"),
                                         headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise FlaresolverrError(f"Flaresolverr not reachable: {e}") from e

    def open_session(self) -> str:
        """Create a Flaresolverr session for cookie persistence across requests."""
        r = self._post({"cmd": "sessions.create"})
        sid = r.get("session")
        if not sid:
            raise FlaresolverrError(f"sessions.create failed: {r}")
        self.session_id = sid
        return sid

    def close_session(self):
        if not self.session_id: return
        try:
            self._post({"cmd": "sessions.destroy", "session": self.session_id})
        except FlaresolverrError:
            pass
        self.session_id = None

    def get(self, url: str) -> str:
        """Fetch a URL through Flaresolverr — returns the resolved HTML."""
        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": self.timeout_ms,
        }
        if self.session_id: payload["session"] = self.session_id
        r = self._post(payload)
        if r.get("status") != "ok":
            raise FlaresolverrError(
                f"GET {url} failed: status={r.get('status')} "
                f"message={r.get('message')!r}"
            )
        sol = r.get("solution") or {}
        if sol.get("status", 0) >= 400:
            raise FlaresolverrError(f"GET {url} → HTTP {sol['status']}")
        return sol.get("response") or ""

    def __enter__(self):
        try:
            self.open_session()
        except FlaresolverrError:
            pass  # sessions are optional; fall back to per-request mode
        return self

    def __exit__(self, *args):
        self.close_session()


# ============================================================
# Site-scraper base + implementations
# ============================================================

class ManualSite:
    """Base adapter — subclass per site."""
    name: str = "unknown"
    base_url: str = ""

    def __init__(self, client: FlaresolverrClient):
        self.client = client

    def search(self, system_id: str, rom_name: str) -> list[dict]:
        """Return list of {title, page_url, score} candidates."""
        raise NotImplementedError

    def find_pdf_url(self, candidate: dict) -> str | None:
        """Given a candidate from search(), follow its page_url and
        extract the actual PDF download URL. None if not found."""
        raise NotImplementedError


class _LinkExtractor(HTMLParser):
    """Tiny HTMLParser-based <a href> extractor. Stdlib only — no
    BeautifulSoup dependency."""
    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []   # (href, text)
        self._cur_href: str | None = None
        self._cur_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            d = dict(attrs)
            self._cur_href = d.get("href")
            self._cur_text = []

    def handle_endtag(self, tag):
        if tag == "a" and self._cur_href is not None:
            txt = "".join(self._cur_text).strip()
            self.links.append((self._cur_href, txt))
            self._cur_href = None

    def handle_data(self, data):
        if self._cur_href is not None:
            self._cur_text.append(data)


# ----- Vimm's Lair (vimm.net/manual) -----

class VimmManualSite(ManualSite):
    """Vimm's Lair has a per-system landing page (e.g. vimm.net/manual?p=SNES)
    listing all manuals as <a href="/manual/N"> entries with the title
    in the link text. The detail page has a <a> pointing to the PDF."""
    name = "vimm"
    base_url = "https://vimm.net"

    # RetroBat id → Vimm system code
    SYSTEM_MAP = {
        "snes":         "SNES",
        "sfc":          "SNES",
        "nes":          "NES",
        "n64":          "N64",
        "gamecube":     "GameCube",
        "gb":           "GB",
        "gbc":          "GBC",
        "gba":          "GBA",
        "nds":          "DS",
        "switch":       "Switch",
        "virtualboy":   "VB",
        "megadrive":    "Genesis",
        "genesis":      "Genesis",
        "mastersystem": "SegaMasterSystem",
        "gamegear":     "GameGear",
        "saturn":       "Saturn",
        "dreamcast":    "Dreamcast",
        "32x":          "Sega32X",
        "sega32x":      "Sega32X",
        "segacd":       "SegaCD",
        "psx":          "PS1",
        "ps2":          "PS2",
        "psp":          "PSP",
        "atari2600":    "Atari2600",
        "atari5200":    "Atari5200",
        "atari7800":    "Atari7800",
        "lynx":         "Lynx",
        "jaguar":       "Jaguar",
        "tg16":         "TG16",
        "pcengine":     "TG16",
        "neogeo":       "NeoGeo",
        "3do":          "3DO",
    }

    def _system_landing_url(self, system_id: str) -> str | None:
        sysc = self.SYSTEM_MAP.get(system_id)
        if not sysc: return None
        return f"{self.base_url}/manual?p={urllib.parse.quote(sysc)}"

    def search(self, system_id: str, rom_name: str) -> list[dict]:
        url = self._system_landing_url(system_id)
        if not url: return []
        try:
            html = self.client.get(url)
        except FlaresolverrError:
            return []
        ex = _LinkExtractor(); ex.feed(html)
        target = _normalise(rom_name)
        candidates = []
        for href, text in ex.links:
            if not href.startswith("/manual/"): continue
            score = _similarity(_normalise(text), target)
            if score > 0:
                candidates.append({
                    "title": text,
                    "page_url": self.base_url + href,
                    "score": score,
                })
        candidates.sort(key=lambda c: -c["score"])
        return candidates[:10]

    def find_pdf_url(self, candidate: dict) -> str | None:
        try:
            html = self.client.get(candidate["page_url"])
        except FlaresolverrError:
            return None
        ex = _LinkExtractor(); ex.feed(html)
        for href, _ in ex.links:
            if ".pdf" in href.lower():
                if href.startswith("/"): href = self.base_url + href
                return href
        return None


# ----- gamesdatabase.org (TODO) -----

class GamesDatabaseSite(ManualSite):
    """https://www.gamesdatabase.org/all_manuals — has a search box and
    per-system catalogues. Manuals link to `/manuals/<system>/<rom>.pdf`
    or similar (varies — needs HTML inspection).

    TODO:
    - Inspect search-result HTML structure (Flaresolverr GET on a known
      query, save HTML, identify the result list selector).
    - Implement search() to return candidates.
    - Implement find_pdf_url() to extract the actual download link.
    """
    name = "gamesdatabase"
    base_url = "https://www.gamesdatabase.org"

    def search(self, system_id: str, rom_name: str) -> list[dict]:
        # TODO: implement
        return []

    def find_pdf_url(self, candidate: dict) -> str | None:
        # TODO: implement
        return None


# ----- replacementdocs.com (TODO) -----

class ReplacementDocsSite(ManualSite):
    """https://replacementdocs.com — search returns a list of doc entries;
    each has a `download.php?id=N` URL that serves the PDF directly.

    TODO:
    - Implement search() — site uses /search.php?advsearch=on&search_query=<terms>
      with system filter via GET param.
    - Implement find_pdf_url() — the result links use download.php with an id.
    """
    name = "replacementdocs"
    base_url = "https://replacementdocs.com"

    def search(self, system_id: str, rom_name: str) -> list[dict]:
        # TODO: implement
        return []

    def find_pdf_url(self, candidate: dict) -> str | None:
        # TODO: implement
        return None


SITES: list[type[ManualSite]] = [
    VimmManualSite,
    GamesDatabaseSite,
    ReplacementDocsSite,
]


# ============================================================
# Orchestration
# ============================================================

def _normalise(s: str) -> str:
    s = Path(s).stem.lower()
    s = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", s)
    s = re.sub(r"[\s_\-:.,!&'+]+", " ", s).strip()
    return s


def _similarity(a: str, b: str) -> float:
    """Cheap similarity: |intersection of word sets| / |union|."""
    if not a or not b: return 0.0
    sa, sb = set(a.split()), set(b.split())
    inter = sa & sb
    if not inter: return 0.0
    return len(inter) / len(sa | sb)


def _cache_key(system_id: str, rom_name: str) -> str:
    return hashlib.sha1(
        f"{system_id}|{_normalise(rom_name)}".encode("utf-8")
    ).hexdigest()[:16]


def _load_cache() -> dict:
    if ONLINE_CACHE_INDEX.exists():
        try:
            return json.loads(ONLINE_CACHE_INDEX.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def _save_cache(cache: dict):
    ONLINE_CACHE_INDEX.parent.mkdir(parents=True, exist_ok=True)
    ONLINE_CACHE_INDEX.write_text(
        json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def research_manual(system_id: str, rom_name: str,
                    use_cache: bool = True,
                    sites: list[str] | None = None) -> dict | None:
    """Look up a game manual across configured online sites. Returns
    {site, title, pdf_path, page_url, score} or None.

    Cached by (system_id, normalised_rom_name) so repeated lookups
    don't hammer the sites.
    """
    cache = _load_cache() if use_cache else {}
    key = _cache_key(system_id, rom_name)
    if use_cache and key in cache:
        cached = cache[key]
        if cached.get("pdf_path") and Path(cached["pdf_path"]).exists():
            return cached

    client = FlaresolverrClient()
    try:
        client.health()
    except FlaresolverrError as e:
        print(f"[error] {e}", file=sys.stderr)
        return None

    selected = [c for c in SITES if not sites or c.name in sites] \
               or SITES
    with client:
        for site_cls in selected:
            site = site_cls(client)
            try:
                candidates = site.search(system_id, rom_name)
            except FlaresolverrError as e:
                print(f"[warn] {site.name} search failed: {e}", file=sys.stderr)
                continue
            if not candidates:
                continue
            top = candidates[0]
            pdf_url = site.find_pdf_url(top)
            if not pdf_url:
                continue
            pdf_path = _download(pdf_url, system_id, rom_name)
            if not pdf_path:
                continue
            result = {
                "site": site.name,
                "title": top["title"],
                "pdf_url": pdf_url,
                "pdf_path": str(pdf_path).replace("\\", "/"),
                "page_url": top["page_url"],
                "score": top["score"],
                "system_id": system_id,
                "rom_name": rom_name,
            }
            cache[key] = result
            _save_cache(cache)
            return result
    return None


def _download(pdf_url: str, system_id: str, rom_name: str) -> Path | None:
    safe = re.sub(r"[^A-Za-z0-9._\-]+", "_", _normalise(rom_name))[:80]
    out_dir = ONLINE_CACHE_DIR / system_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_pdf = out_dir / f"{safe}.pdf"
    if out_pdf.exists() and out_pdf.stat().st_size > 1024:
        return out_pdf
    # Direct download via urllib (PDF endpoints don't usually need
    # Flaresolverr; if a site requires it, route through .get + write
    # bytes from the response).
    try:
        req = urllib.request.Request(pdf_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as r, out_pdf.open("wb") as f:
            while True:
                chunk = r.read(64 * 1024)
                if not chunk: break
                f.write(chunk)
    except (urllib.error.URLError, OSError) as e:
        print(f"[error] PDF download failed: {e}", file=sys.stderr)
        return None
    if out_pdf.stat().st_size < 1024:
        out_pdf.unlink(missing_ok=True)
        return None
    return out_pdf


# ============================================================
# CLI
# ============================================================

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=False)
    sub.add_parser("status", help="Check Flaresolverr health.")
    L = sub.add_parser("lookup", help="Search online for a manual.")
    L.add_argument("system_id")
    L.add_argument("rom")
    L.add_argument("--no-cache", action="store_true")
    L.add_argument("--site", help="Limit to one site (vimm | gamesdatabase | replacementdocs)")
    args = ap.parse_args()

    if args.cmd is None:
        ap.print_help(); return

    if args.cmd == "status":
        try:
            print(json.dumps(FlaresolverrClient().health(), indent=2))
        except FlaresolverrError as e:
            print(f"[error] {e}", file=sys.stderr)
            sys.exit(1)
        return

    if args.cmd == "lookup":
        sites = [args.site] if args.site else None
        result = research_manual(args.system_id, args.rom,
                                 use_cache=not args.no_cache,
                                 sites=sites)
        if not result:
            print(f"[miss] no manual found for {args.system_id}/{args.rom}")
            sys.exit(2)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
