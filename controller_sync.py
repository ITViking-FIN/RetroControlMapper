"""
RB-Controller_fix — controller image sync tool.

Reads controller_catalog.yaml, queries Wikimedia Commons API for each known
file's metadata, downloads (or re-downloads) any image whose remote SHA1
differs from the local cached copy. Designed to run nightly via Windows
Task Scheduler (see setup_schedule.ps1).

Usage:
    py controller_sync.py             # full sync, log to controller_sync.log
    py controller_sync.py --dry-run   # check what would change, no downloads
    py controller_sync.py --verbose   # also log no-op entries
    py controller_sync.py --once <VID:PID>   # sync just one entry

The Commons API endpoint:
    https://commons.wikimedia.org/w/api.php?action=query
        &titles=File:<name>&prop=imageinfo
        &iiprop=url|sha1|size|timestamp&format=json

State file at sync_manifest.json tracks last sync time + per-entry SHA1
so we can be idempotent and only emit "changed" log lines for actual diffs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
CATALOG = ROOT / "controller_catalog.yaml"
KNOWN_DIR = ROOT / "gui" / "img" / "known"
MANIFEST = ROOT / "sync_manifest.json"
LOG_FILE = ROOT / "controller_sync.log"

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
from config import __version__ as _rbcf_v
USER_AGENT = f"RetroControlMapper/{_rbcf_v} controller-catalog-sync (+https://github.com/ITViking-FIN/RetroControlMapper)"
TIMEOUT_S = 20
MAX_RETRIES = 3
RETRY_SLEEP_S = 4


def log(line: str, also_stdout: bool = True):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full = f"[{ts}] {line}"
    if also_stdout:
        print(full)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(full + "\n")
    except OSError:
        pass


def load_catalog() -> list[dict]:
    if not CATALOG.exists():
        log(f"[fatal] catalog not found: {CATALOG}")
        sys.exit(1)
    data = yaml.safe_load(CATALOG.read_text(encoding="utf-8")) or {}
    return data.get("controllers", [])


def load_manifest() -> dict:
    if not MANIFEST.exists():
        return {"last_sync": None, "entries": {}}
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"last_sync": None, "entries": {}}


def save_manifest(m: dict):
    m["last_sync"] = datetime.now(timezone.utc).isoformat()
    MANIFEST.write_text(json.dumps(m, indent=2), encoding="utf-8")


def http_json(url: str) -> dict:
    """Fetch a URL and parse JSON, with retries."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(RETRY_SLEEP_S)
    return {}


def http_download(url: str, dest: Path):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r, \
                 dest.open("wb") as f:
                while True:
                    chunk = r.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
            return
        except Exception:
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(RETRY_SLEEP_S)


def sha1_of_file(p: Path) -> str:
    h = hashlib.sha1()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(64 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def query_commons(file_name: str) -> dict | None:
    """Query the Commons API for one file's imageinfo."""
    params = {
        "action": "query",
        "titles": f"File:{file_name}",
        "prop": "imageinfo",
        "iiprop": "url|sha1|size|timestamp|mime",
        "format": "json",
        "formatversion": "2",
    }
    url = f"{COMMONS_API}?{urllib.parse.urlencode(params)}"
    data = http_json(url)
    pages = data.get("query", {}).get("pages", [])
    if not pages:
        return None
    info_list = pages[0].get("imageinfo") or []
    if not info_list:
        return None
    info = info_list[0]
    return {
        "url": info.get("url", ""),
        "sha1": info.get("sha1", ""),
        "size": info.get("size", 0),
        "timestamp": info.get("timestamp", ""),
        "mime": info.get("mime", ""),
        "missing": pages[0].get("missing", False),
    }


def desired_local_path(entry: dict, mime: str = "") -> Path:
    """Decide the local file path for an entry, derived from VID:PID +
    extension inferred from mime type."""
    vid = entry["vid"].upper()
    pid = entry["pid"].upper()
    ext = ".jpg"
    if mime in ("image/png",):
        ext = ".png"
    elif mime in ("image/jpeg", "image/jpg"):
        ext = ".jpg"
    elif mime in ("image/svg+xml",):
        ext = ".svg"
    elif mime in ("image/webp",):
        ext = ".webp"
    return KNOWN_DIR / f"{vid}_{pid}{ext}"


def sync_entry(entry: dict, manifest: dict, dry_run: bool, verbose: bool) -> str:
    """Sync one catalog entry. Returns a short status code:
       "skip" / "miss" / "noop" / "downloaded" / "stale-cleaned" / "error" """
    vid_pid = f"{entry['vid'].upper()}:{entry['pid'].upper()}"
    name = entry.get("name", vid_pid)
    file_name = (entry.get("wiki_file") or "").strip()

    if not file_name:
        if verbose:
            log(f"  [skip ] {vid_pid} {name} — no wiki_file in catalog")
        return "skip"

    try:
        info = query_commons(file_name)
    except Exception as e:
        log(f"  [error] {vid_pid} {name} — Commons query failed: {e}")
        return "error"

    if not info:
        log(f"  [miss ] {vid_pid} {name} — Commons returned no imageinfo for File:{file_name}")
        return "miss"

    remote_sha1 = info.get("sha1") or ""
    remote_url  = info.get("url")  or ""
    if not remote_url:
        log(f"  [miss ] {vid_pid} {name} — no URL in Commons response")
        return "miss"

    local_path = desired_local_path(entry, info.get("mime", ""))
    prev = manifest["entries"].get(vid_pid, {})
    prev_sha = prev.get("sha1") or ""
    have_local = local_path.exists()

    # Decide whether to download
    need = (not have_local) or (remote_sha1 and remote_sha1 != prev_sha)
    if not need and have_local:
        # Defensive: also verify the local file actually has the recorded SHA1
        try:
            actual = sha1_of_file(local_path)
            if remote_sha1 and actual != remote_sha1:
                need = True
        except OSError:
            need = True

    if not need:
        if verbose:
            log(f"  [noop ] {vid_pid} {name}")
        return "noop"

    if dry_run:
        log(f"  [diff ] {vid_pid} {name} — would download {info.get('size', '?')} bytes from {remote_url}")
        return "downloaded"  # for counts

    KNOWN_DIR.mkdir(parents=True, exist_ok=True)
    # Clean up any stale older-extension copies of the same vid_pid
    for old in KNOWN_DIR.glob(f"{entry['vid'].upper()}_{entry['pid'].upper()}.*"):
        if old != local_path:
            try:
                old.unlink()
            except OSError:
                pass
    try:
        http_download(remote_url, local_path)
    except Exception as e:
        log(f"  [error] {vid_pid} {name} — download failed: {e}")
        return "error"

    actual = sha1_of_file(local_path)
    if remote_sha1 and actual != remote_sha1:
        log(f"  [warn ] {vid_pid} {name} — sha1 mismatch after download (remote={remote_sha1}, local={actual})")
    manifest["entries"][vid_pid] = {
        "wiki_file": file_name,
        "sha1": actual,
        "url": remote_url,
        "synced": datetime.now(timezone.utc).isoformat(),
        "local": str(local_path.relative_to(ROOT)).replace("\\", "/"),
        "name": name,
    }
    log(f"  [done ] {vid_pid} {name} -> {local_path.name} ({info.get('size', '?')} bytes)")
    return "downloaded"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="Don't write files; just report what would change.")
    ap.add_argument("--verbose", action="store_true",
                    help="Log no-op entries too.")
    ap.add_argument("--once", metavar="VID:PID",
                    help="Sync just one entry (VID:PID, uppercase).")
    args = ap.parse_args()

    catalog = load_catalog()
    manifest = load_manifest()

    log(f"=== sync run started ({len(catalog)} entries; dry_run={args.dry_run}) ===")
    counts = {"skip": 0, "miss": 0, "noop": 0, "downloaded": 0, "error": 0}
    for entry in catalog:
        if args.once:
            if f"{entry['vid'].upper()}:{entry['pid'].upper()}" != args.once.upper():
                continue
        try:
            status = sync_entry(entry, manifest, args.dry_run, args.verbose)
            counts[status] = counts.get(status, 0) + 1
        except KeyboardInterrupt:
            log("[interrupt] stopping early")
            break
        except Exception as e:
            log(f"  [error] {entry.get('vid','?')}:{entry.get('pid','?')} unhandled: {e}")
            counts["error"] += 1

    if not args.dry_run:
        save_manifest(manifest)
    log(f"=== summary: downloaded={counts['downloaded']} noop={counts['noop']} miss={counts['miss']} skip={counts['skip']} error={counts['error']} ===")


if __name__ == "__main__":
    main()
