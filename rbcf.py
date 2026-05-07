"""
RetroBat Controller Fix — apply per-game / per-system controller profiles.

Profiles live in profiles/<system>/<id>.yaml (per-game, with `rom:` field) or
profiles/<system>/_default.yaml (system-wide, no `rom:` field).

Each profile may declare:
  es_settings:        dict — RetroBat-managed keys, written to es_settings.cfg
                      (per-game: <system>["<rom>"].<key>;
                       system-default: <system>.<key>)
  core_options:       dict — keys written directly to retroarch-core-options.cfg
                      (these are GLOBAL — they affect every game using that core)
  notes:              free-text human documentation
  button_semantics:   informational only — what each button does in this game

Commands:
  list                Show all profiles
  status              Compare profiles against current RetroBat config
  diff                Preview what `apply` would change
  apply [--id ID]     Apply all profiles (or just one)
  revert --id ID      Remove a profile's es_settings entries
  validate            Lint profiles

Files this tool may modify (with backups):
  E:/RetroBat/emulationstation/.emulationstation/es_settings.cfg
  E:/RetroBat/emulators/retroarch/retroarch-core-options.cfg
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import yaml

from config import ES_INPUT, ES_SETTINGS, RA_CORE_OPTS
from guid_aliases import (
    expand_inputconfig,
    group_aliases,
    parse_es_input,
)

ROOT = Path(__file__).resolve().parent
PROFILES_DIR = ROOT / "profiles"


def _backup_tag() -> str:
    """Today's `.bak.rbcf.<YYYYMMDD>` suffix, computed on every call.

    Was a module-level constant frozen at import (audit finding M7) —
    a tray app that ran past midnight stamped backups with yesterday's
    date. Lazy evaluation keeps the date current.
    """
    return f".bak.rbcf.{datetime.now():%Y%m%d}"


# Backwards-compat shim. Existing call sites do `path.suffix + BACKUP_TAG`
# and `f"backups tagged: {BACKUP_TAG}"`. A custom object that defers to
# _backup_tag() on string ops keeps those call sites unchanged while the
# value is recomputed each access.
class _BackupTag:
    def __str__(self) -> str:
        return _backup_tag()
    def __repr__(self) -> str:
        return _backup_tag()
    def __radd__(self, other):
        return other + _backup_tag()
    def __add__(self, other):
        return _backup_tag() + other
    def __format__(self, spec):
        return format(_backup_tag(), spec)


BACKUP_TAG = _BackupTag()


# ------------------------------ profile model ------------------------------

@dataclass
class Profile:
    file: Path
    system: str
    rom: str | None        # None = system default
    title: str
    es_settings: dict
    core_options: dict
    notes: str
    button_semantics: dict
    raw: dict

    @property
    def id(self) -> str:
        if self.rom:
            return f"{self.system}/{self.rom}"
        return f"{self.system}/_default"

    @property
    def is_system_default(self) -> bool:
        return self.rom is None


def load_profiles() -> list[Profile]:
    if not PROFILES_DIR.exists():
        return []
    out = []
    for yml in sorted(PROFILES_DIR.rglob("*.yaml")):
        try:
            data = yaml.safe_load(yml.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            print(f"[warn] {yml}: YAML error {e}", file=sys.stderr)
            continue
        sys_name = data.get("system") or yml.parent.name
        rom = data.get("rom")
        out.append(Profile(
            file=yml,
            system=sys_name,
            rom=rom,
            title=data.get("title") or (rom or "(system default)"),
            es_settings=data.get("es_settings") or {},
            core_options=data.get("core_options") or {},
            notes=(data.get("notes") or "").strip(),
            button_semantics=data.get("button_semantics") or {},
            raw=data,
        ))
    return out


# ------------------------------ es_settings.cfg edit ------------------------------

def es_key_name(p: Profile, setting: str) -> str:
    if p.is_system_default:
        return f"{p.system}.{setting}"
    return f'{p.system}["{p.rom}"].{setting}'


def xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace('"', "&quot;")
             .replace("<", "&lt;").replace(">", "&gt;"))


def planned_es_changes(profiles: Iterable[Profile]) -> dict[str, str]:
    """Return {name: value} pairs we want present in es_settings.cfg."""
    out = {}
    for p in profiles:
        for k, v in p.es_settings.items():
            out[es_key_name(p, k)] = str(v)
    return out


def apply_es_settings(wanted: dict[str, str], path: Path = ES_SETTINGS, dry: bool = False):
    if not wanted:
        return [], []
    text = path.read_text(encoding="utf-8")
    indent = "\t" if "\n\t<" in text else "  "
    line_re = re.compile(r'^(\s*)<string name="([^"]+)" value="([^"]*)" ?/>\s*$', re.MULTILINE)

    seen_names = set()
    changes = []  # (name, old, new)
    additions = []  # (name, value)

    def replace(m: re.Match) -> str:
        whitespace, name, old = m.group(1), m.group(2), m.group(3)
        # Decode XML entities for comparison
        decoded = (name.replace("&quot;", '"').replace("&amp;", "&")
                       .replace("&lt;", "<").replace("&gt;", ">"))
        if decoded in wanted:
            seen_names.add(decoded)
            new = wanted[decoded]
            if new == old:
                return m.group(0)
            changes.append((decoded, old, new))
            return f'{whitespace}<string name="{xml_escape(decoded)}" value="{xml_escape(new)}" />'
        return m.group(0)

    new_text = line_re.sub(replace, text)

    # Insert keys we didn't replace (new entries) before </config>
    new_keys = sorted(set(wanted) - seen_names)
    if new_keys:
        insert = "\n".join(
            f'{indent}<string name="{xml_escape(k)}" value="{xml_escape(wanted[k])}" />'
            for k in new_keys
        )
        for name in new_keys:
            additions.append((name, wanted[name]))
        if "</config>" in new_text:
            new_text = new_text.replace("</config>", insert + "\n</config>", 1)
        else:
            new_text = new_text.rstrip() + "\n" + insert + "\n"

    if not dry and (changes or additions):
        bak = path.with_suffix(path.suffix + BACKUP_TAG)
        if not bak.exists():
            shutil.copy2(path, bak)
        path.write_text(new_text, encoding="utf-8")

    return changes, additions


# ------------------------------ retroarch-core-options.cfg edit ------------------------------

def planned_core_changes(profiles: Iterable[Profile]) -> dict[str, str]:
    """Return GLOBAL key=value pairs we want in retroarch-core-options.cfg.

    Last-profile-wins for conflicts; warn if conflict detected."""
    out = {}
    sources = {}
    conflicts = []
    for p in profiles:
        for k, v in p.core_options.items():
            v = str(v)
            if k in out and out[k] != v:
                conflicts.append((k, sources[k], out[k], p.id, v))
            out[k] = v
            sources[k] = p.id
    for k, srcA, valA, srcB, valB in conflicts:
        print(f"[warn] core_option conflict on '{k}': {srcA}={valA} vs {srcB}={valB} (using {valB})",
              file=sys.stderr)
    return out


def apply_core_options(wanted: dict[str, str], path: Path = RA_CORE_OPTS, dry: bool = False):
    if not wanted:
        return [], []
    text = path.read_text(encoding="utf-8")
    line_re = re.compile(r'^([A-Za-z0-9_\-]+) = "([^"]*)"\s*$', re.MULTILINE)

    seen = set()
    changes = []
    additions = []

    def replace(m: re.Match) -> str:
        key, old = m.group(1), m.group(2)
        if key in wanted:
            seen.add(key)
            new = wanted[key]
            if new == old:
                return m.group(0)
            changes.append((key, old, new))
            return f'{key} = "{new}"'
        return m.group(0)

    new_text = line_re.sub(replace, text)

    new_keys = sorted(set(wanted) - seen)
    for k in new_keys:
        additions.append((k, wanted[k]))
        new_text = new_text.rstrip() + f'\n{k} = "{wanted[k]}"\n'

    if not dry and (changes or additions):
        bak = path.with_suffix(path.suffix + BACKUP_TAG)
        if not bak.exists():
            shutil.copy2(path, bak)
        path.write_text(new_text, encoding="utf-8")

    return changes, additions


# ------------------------------ revert ------------------------------

def revert_profile(profile: Profile, path: Path = ES_SETTINGS, dry: bool = False):
    """Remove the es_settings keys associated with one profile.

    Core options are NOT reverted — they're shared / global and may overlap
    with other profiles. Use --revert-core-options on a separate run if needed.
    """
    if not profile.es_settings:
        return 0
    text = path.read_text(encoding="utf-8")
    targets = {es_key_name(profile, k) for k in profile.es_settings}
    line_re = re.compile(r'^(\s*<string name="([^"]+)" value="[^"]*" ?/>\s*\n?)', re.MULTILINE)

    removed = []
    def maybe_drop(m: re.Match) -> str:
        decoded = (m.group(2).replace("&quot;", '"').replace("&amp;", "&")
                              .replace("&lt;", "<").replace("&gt;", ">"))
        if decoded in targets:
            removed.append(decoded)
            return ""
        return m.group(0)

    new_text = line_re.sub(maybe_drop, text)

    if not dry and removed:
        bak = path.with_suffix(path.suffix + BACKUP_TAG)
        if not bak.exists():
            shutil.copy2(path, bak)
        path.write_text(new_text, encoding="utf-8")

    return removed


# ------------------------------ status / list ------------------------------

def cmd_list(profiles: list[Profile]):
    by_system = {}
    for p in profiles:
        by_system.setdefault(p.system, []).append(p)
    for sys_name in sorted(by_system):
        ps = by_system[sys_name]
        print(f"\n[{sys_name}]")
        for p in sorted(ps, key=lambda x: (not x.is_system_default, x.title.lower())):
            kind = "default " if p.is_system_default else "        "
            print(f"  {kind} {p.title}")
            if p.rom:
                print(f"            rom: {p.rom}")


def cmd_status(profiles: list[Profile]):
    if not ES_SETTINGS.exists():
        print(f"[fatal] {ES_SETTINGS} not found")
        return
    text = ES_SETTINGS.read_text(encoding="utf-8")
    print(f"Checking {len(profiles)} profile(s) against es_settings.cfg...\n")
    line_re = re.compile(r'<string name="([^"]+)" value="([^"]*)"')
    current = {}
    for m in line_re.finditer(text):
        name = (m.group(1).replace("&quot;", '"').replace("&amp;", "&")
                          .replace("&lt;", "<").replace("&gt;", ">"))
        current[name] = m.group(2)

    for p in sorted(profiles, key=lambda x: x.id):
        applied = 0
        outdated = 0
        missing = 0
        for k, v in p.es_settings.items():
            name = es_key_name(p, k)
            if name not in current:
                missing += 1
            elif current[name] != str(v):
                outdated += 1
            else:
                applied += 1
        total = applied + outdated + missing
        if total == 0:
            mark = "-"
        elif missing == 0 and outdated == 0:
            mark = "OK"
        elif applied == 0 and outdated == 0:
            mark = "..."
        else:
            mark = "~"
        print(f"  [{mark}] {p.id:<60} ({applied}/{total} applied"
              + (f", {outdated} outdated" if outdated else "")
              + (f", {missing} missing" if missing else "")
              + ")")


def cmd_diff(profiles: list[Profile]):
    es_changes, es_adds = apply_es_settings(planned_es_changes(profiles), dry=True)
    co_changes, co_adds = apply_core_options(planned_core_changes(profiles), dry=True)
    print(f"\nes_settings.cfg ({len(es_changes)} changes, {len(es_adds)} additions):")
    for name, old, new in es_changes:
        print(f"    ~ {name}: \"{old}\" -> \"{new}\"")
    for name, val in es_adds:
        print(f"    + {name} = \"{val}\"")
    print(f"\nretroarch-core-options.cfg ({len(co_changes)} changes, {len(co_adds)} additions):")
    for name, old, new in co_changes:
        print(f"    ~ {name}: \"{old}\" -> \"{new}\"")
    for name, val in co_adds:
        print(f"    + {name} = \"{val}\"")
    if not (es_changes or es_adds or co_changes or co_adds):
        print("\n  (no changes — already in sync)")


def cmd_apply(profiles: list[Profile], target_id: str | None):
    selected = profiles
    if target_id:
        selected = [p for p in profiles if p.id == target_id]
        if not selected:
            print(f"[fatal] no profile with id '{target_id}'")
            sys.exit(1)

    # Tier-2 auto-snapshot before any writes (DECISIONS.md #5). Failures
    # are logged but do not block apply — the .bak.rbcf.<date> daily
    # backups still run inside apply_es_settings / apply_core_options.
    snap_id = None
    try:
        from backups import snapshot as _snapshot
        snap = _snapshot(
            "working",
            description=f"auto-snap before apply ({len(selected)} profiles)",
        )
        if snap is not None:
            snap_id = snap.id
            print(f"  pre-apply snapshot: {snap_id}")
        else:
            print("  pre-apply snapshot: skipped (see warning above)")
    except Exception as e:  # broad: never let snapshot break apply
        print(f"[warn] pre-apply snapshot failed: {e}", file=sys.stderr)

    print(f"Applying {len(selected)} profile(s)...")
    es_changes, es_adds = apply_es_settings(planned_es_changes(selected))
    co_changes, co_adds = apply_core_options(planned_core_changes(selected))
    print(f"  es_settings.cfg: {len(es_changes)} updated, {len(es_adds)} added")
    print(f"  retroarch-core-options.cfg: {len(co_changes)} updated, {len(co_adds)} added")
    if es_changes or es_adds or co_changes or co_adds:
        print(f"  backups tagged: {BACKUP_TAG}")
        if snap_id:
            print(f"  revert with: rbcf backup restore {snap_id} --apply")


def cmd_revert(profiles: list[Profile], target_id: str):
    matches = [p for p in profiles if p.id == target_id]
    if not matches:
        print(f"[fatal] no profile with id '{target_id}'")
        sys.exit(1)
    p = matches[0]
    removed = revert_profile(p)
    print(f"Reverted {p.id}: removed {len(removed)} key(s) from es_settings.cfg")
    for r in removed:
        print(f"  - {r}")


# ------------------------------ guid alias commands ------------------------------

def _format_vidpid(vid: str, pid: str) -> str:
    return f"{vid.lower()}:{pid.lower()}"


def cmd_guid_status(es_input_path: Path = ES_INPUT):
    """Read es_input.cfg, group aliases, print a table of alias groups."""
    if not es_input_path.exists():
        print(f"[info] {es_input_path} not found.")
        print("       (no controllers configured yet, or RetroBat not installed)")
        return
    aliases = parse_es_input(es_input_path)
    groups = group_aliases(aliases)
    if not aliases:
        print("[info] no <inputConfig type=\"joystick\"> blocks found.")
        return

    multi = {k: v for k, v in groups.items() if len(v) > 1}
    singles = {k: v for k, v in groups.items() if len(v) == 1}

    print(f"\nFound {len(aliases)} <inputConfig> joystick block(s) in {es_input_path}\n")
    print(f"{'[vid:pid]':<14} pads in alias group")
    # Order: alias groups first (most actionable), then singletons.
    for key in sorted(multi):
        entries = multi[key]
        label = _format_vidpid(*key)
        for i, a in enumerate(entries):
            tag = "  (canonical)" if i == 0 else ""
            prefix = label if i == 0 else " " * len(label)
            name = a.device_name or "(no name)"
            print(f"{prefix:<14} {name:<32}  GUID={a.guid}{tag}")
        print()
    for key in sorted(singles):
        a = singles[key][0]
        label = _format_vidpid(*key)
        name = a.device_name or "(no name)"
        print(f"{label:<14} {name:<32}  GUID={a.guid}  (singleton)")
    print()
    print(f"Summary: {len(multi)} alias group(s), {len(singles)} singleton(s), "
          f"{len(aliases)} total device(s).")


def cmd_guid_fold(target_id: str | None, dry: bool, es_input_path: Path = ES_INPUT):
    """Fold every multi-alias group (or one matching --id <vid:pid>) into es_input.cfg."""
    if not es_input_path.exists():
        print(f"[fatal] {es_input_path} not found.")
        sys.exit(1)
    aliases = parse_es_input(es_input_path)
    groups = group_aliases(aliases)
    multi = {k: v for k, v in groups.items() if len(v) > 1}
    if target_id:
        try:
            v, p = target_id.lower().split(":")
        except ValueError:
            print(f"[fatal] --id must be of form 'vid:pid' (got '{target_id}')")
            sys.exit(1)
        key = (v, p)
        if key not in multi:
            print(f"[info] no multi-alias group for {target_id} "
                  f"(have {len(multi)} group(s); use 'rbcf guid status' to list).")
            return
        multi = {key: multi[key]}
    if not multi:
        print("[info] no alias groups need folding "
              "(all VID:PIDs are singletons).")
        return

    mode = "DRY-RUN" if dry else "APPLY"
    print(f"\nguid fold ({mode}) — {len(multi)} group(s) to process\n")
    total_added = 0
    total_kept = 0
    for key in sorted(multi):
        group = multi[key]
        label = _format_vidpid(*key)
        added, kept = expand_inputconfig(es_input_path, group, dry=dry)
        total_added += added
        total_kept += kept
        print(f"  [{label}] canonical='{group[0].device_name or '(no name)'}' "
              f"-> +{added} added, ={kept} kept")
    print()
    if dry:
        print(f"Would add {total_added} <inputConfig> block(s), "
              f"keep {total_kept} existing.")
        print("Re-run with --apply to actually write.")
    else:
        print(f"Wrote {total_added} new <inputConfig> block(s) "
              f"({total_kept} existing kept).")
        if total_added:
            print(f"Backup tag: .bak.rbcf.{datetime.now():%Y%m%d}")


def cmd_guid_help():
    print("""
rbcf guid — SDL controller GUID alias management

Subcommands:
  status                Read es_input.cfg, list alias groups + singletons.
  fold [opts]           Duplicate <inputConfig> blocks across all GUIDs in
                        an alias group, mirroring the canonical block's
                        button mapping. Defaults to --dry-run.
    --id <vid:pid>      Fold only the named group (e.g. '2dc8:3106').
    --dry-run           Preview only (default).
    --apply             Actually rewrite es_input.cfg.
  help                  This message.

Background: a single physical pad can present under multiple SDL GUIDs
(USB vs Bluetooth, driver swap, etc.) — RetroBat treats each as a fresh
device and 'forgets' the mapping. 'fold' writes the same mapping under
every known alias GUID so any reconnect path resolves cleanly.
See docs/GUID_DRIFT_DESIGN.md for the full design.
""".strip())


# ------------------------------ backup commands ------------------------------

def _format_snapshot_row(s) -> str:
    # s is a backups.Snapshot; we keep this loose to avoid a hard import
    # at module level (so rbcf can still load if backups.py is missing).
    created = s.created_at or "(unknown)"
    # Trim ISO microsecond fractions for the table; keep YYYY-MM-DD HH:MM.
    if "T" in created:
        date_part, _, time_part = created.partition("T")
        created = f"{date_part} {time_part[:5]}"
    desc = (s.description or "").replace("\n", " ")
    if len(desc) > 50:
        desc = desc[:47] + "..."
    return f"{s.id:<19} {s.kind:<8} {created:<20} {desc}"


def cmd_backup_factory():
    from backups import snapshot as _snapshot, factory_exists, _read_manifest
    if factory_exists():
        existing = _read_manifest("factory")
        when = existing.created_at if existing else "(unknown date)"
        print(f"Factory snapshot already taken on {when}.")
        print("It is permanent and never overwritten — no action.")
        return
    snap = _snapshot("factory", description="pre-install factory snapshot")
    if snap is None:
        print("[fatal] could not capture factory snapshot.")
        sys.exit(1)
    print(f"Factory snapshot captured: {snap.id}")
    print(f"  created_at: {snap.created_at}")
    print(f"  files:      {len(snap.files)}")
    for f in snap.files:
        print(f"    - {f}")


def cmd_backup_snapshot(description: str):
    from backups import snapshot as _snapshot
    snap = _snapshot("working", description=description or "manual snapshot")
    if snap is None:
        print("[fatal] could not capture working snapshot.")
        sys.exit(1)
    print(f"Working snapshot captured: {snap.id}")
    print(f"  description: {snap.description}")
    print(f"  files:       {len(snap.files)}")


def cmd_backup_list():
    from backups import list_snapshots, factory_exists
    snaps = list_snapshots()
    if not snaps:
        print("(no snapshots — capture one with `rbcf backup snapshot` "
              "or `rbcf backup factory`)")
        return
    print(f"{'ID':<19} {'KIND':<8} {'CREATED':<20} DESCRIPTION")
    for s in snaps:
        print(_format_snapshot_row(s))
    print()
    print(f"Total: {len(snaps)} snapshot(s)"
          f"{' (incl. factory)' if factory_exists() else ''}.")


def cmd_backup_restore(snapshot_id: str, dry: bool):
    from backups import restore as _restore, _read_manifest
    snap = _read_manifest(snapshot_id)
    if snap is None:
        print(f"[fatal] no such snapshot: {snapshot_id}")
        sys.exit(1)
    mode = "DRY-RUN" if dry else "APPLY"
    print(f"\nbackup restore ({mode}) — snapshot {snapshot_id}")
    print(f"  kind:        {snap.kind}")
    print(f"  created_at:  {snap.created_at}")
    print(f"  description: {snap.description}")
    print(f"  files in snapshot: {len(snap.files)}")
    if dry:
        print()
        print("  Will first auto-capture a working snapshot of the CURRENT")
        print("  state (description: \"auto-snap before restoring "
              f"{snapshot_id}\") so the restore is itself revertible.")
    print()

    restored, skipped = _restore(snapshot_id, dry=dry)
    label = "Would restore" if dry else "Restored"
    print(f"{label} {len(restored)} file(s):")
    for r in restored:
        print(f"  + {r}")
    if skipped:
        print(f"\nSkipped {len(skipped)}:")
        for path, reason in skipped:
            print(f"  ! {path}: {reason}")
    if dry:
        print()
        print("Re-run with --apply to actually write.")


def cmd_backup_help():
    print("""
rbcf backup — two-tier backup / snapshot management

Subcommands:
  factory               Capture the tier-1 pre-install snapshot. One-shot:
                        if already taken, prints the existing date and exits.
                        Stored at %APPDATA%/RB-Controller_fix/factory/.
  snapshot [opts]       Capture a tier-2 working snapshot manually.
    --description TEXT  Free-text label written into the manifest.
  list                  Show all snapshots in a table. Most-recent working
                        first; factory pinned to the bottom (last-resort).
  restore <id> [opts]   Restore a snapshot back to RetroBat. Defaults to a
                        dry-run preview; pass --apply to actually write.
                        ALWAYS auto-captures a working snapshot of the
                        current state first so the restore is revertible.
    --dry-run           Preview only (default).
    --apply             Actually copy files back to RetroBat.
  help                  This message.

Storage:
  %APPDATA%/RB-Controller_fix/factory/         (tier 1, permanent)
  %APPDATA%/RB-Controller_fix/snapshots/<id>/  (tier 2, capped at 30)

Tier-2 snapshots are taken automatically before every `rbcf apply` and
before every restore — see the snapshot id printed at the top of those
commands' output.
""".strip())


# ------------------------------ pull-community ------------------------------

def cmd_pull_community(args):
    """Fetch community/ from the GitHub repo into profiles/community/.

    Uses GitHub's Contents API to recursively traverse the community folder.
    Writes profiles to profiles/community/<system>/<rom>.yaml so they sit
    alongside (but separate from) the user's own authored profiles. The GUI
    surfaces these with a [community] tag.

    No auth required for public repos (60 req/hr unauthenticated, plenty for
    a normal pull). Pass --token to lift the limit.
    """
    import urllib.request, urllib.error, urllib.parse

    ROOT = Path(__file__).resolve().parent
    PROFILES_DIR = ROOT / "profiles"
    COMM_DIR = PROFILES_DIR / "community"
    USER_AGENT = "RB-Controller_fix/0.1.3 pull-community"

    repo = args.repo
    ref = args.ref
    token = args.token
    api_base = f"https://api.github.com/repos/{repo}/contents"

    def gh_get_json(path):
        url = f"{api_base}/{urllib.parse.quote(path)}?ref={urllib.parse.quote(ref)}"
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None  # path doesn't exist upstream
            raise

    def gh_get_raw(download_url):
        req = urllib.request.Request(download_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read()

    print(f"Pulling community profiles from {repo}@{ref} ...")
    if not args.token:
        print("  (no --token given; subject to 60 requests/hr rate limit)")
    root_listing = gh_get_json("community")
    if root_listing is None:
        print(f"[info] no community/ folder at {repo}@{ref} — nothing to pull")
        return
    if not isinstance(root_listing, list):
        print(f"[fatal] expected directory listing at community/, got {type(root_listing).__name__}")
        sys.exit(1)

    # Recursively walk: returns list of (rel_path, download_url, sha)
    def walk(listing, prefix):
        items = []
        for entry in listing:
            ename = entry.get("name", "")
            etype = entry.get("type", "")
            epath = entry.get("path", "")
            if etype == "dir":
                sub = gh_get_json(epath)
                if isinstance(sub, list):
                    items.extend(walk(sub, prefix + (ename,)))
            elif etype == "file" and ename.endswith(".yaml"):
                items.append({
                    "rel": "/".join(prefix + (ename,)),
                    "url": entry.get("download_url"),
                    "sha": entry.get("sha"),
                    "size": entry.get("size", 0),
                })
        return items

    upstream = walk(root_listing, ())
    print(f"  Upstream: {len(upstream)} profile file(s)")
    if not upstream:
        return

    # Sort for deterministic output
    upstream.sort(key=lambda x: x["rel"])

    written = 0
    skipped = 0
    failed = 0
    upstream_rels = set(x["rel"] for x in upstream)
    for entry in upstream:
        local = COMM_DIR / entry["rel"]
        if args.dry_run:
            mark = "diff" if not local.exists() else "noop"
            print(f"  [{mark:>4}] {entry['rel']}  ({entry['size']} bytes)")
            continue
        # Compare SHA to skip unchanged files (cheap optimisation)
        if local.exists() and entry["sha"]:
            try:
                # GitHub blob SHA: sha1("blob <size>\0<content>")
                import hashlib
                content = local.read_bytes()
                blob_sha = hashlib.sha1(
                    f"blob {len(content)}\0".encode("utf-8") + content
                ).hexdigest()
                if blob_sha == entry["sha"]:
                    skipped += 1
                    continue
            except OSError:
                pass
        try:
            data = gh_get_raw(entry["url"])
        except Exception as e:
            print(f"  [fail] {entry['rel']} — {e}")
            failed += 1
            continue
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(data)
        written += 1
        print(f"  [done] {entry['rel']}  ({len(data)} bytes)")

    # Optional: prune local files that are no longer upstream
    pruned = 0
    if args.prune and not args.dry_run and COMM_DIR.exists():
        for local_yaml in COMM_DIR.rglob("*.yaml"):
            rel = local_yaml.relative_to(COMM_DIR).as_posix()
            if rel not in upstream_rels:
                local_yaml.unlink()
                pruned += 1
                print(f"  [prune] {rel}")
        # Clean up empty dirs
        for d in sorted([p for p in COMM_DIR.rglob("*") if p.is_dir()],
                        key=lambda p: -len(p.parts)):
            try:
                d.rmdir()
            except OSError:
                pass

    if args.dry_run:
        print(f"\nDry run summary: {len(upstream)} upstream file(s)")
    else:
        print(f"\nSummary: {written} written, {skipped} unchanged, "
              f"{failed} failed, {pruned} pruned")
        if written:
            print(f"  Local: {COMM_DIR}")
            print("  Run `py rbcf.py list` to see them; community profiles get a [community] badge.")


# ------------------------------ submit-controller ------------------------------

def cmd_submit_controller(args):
    """Process a community-supplied controller photo and stage it for a PR.

    Flow:
      1. Validate VID/PID format (4-char hex, normalised uppercase).
      2. Pick a cleanup mode (auto = inspect image, choose silhouette /
         remove-bg / crop based on background lightness + uniformity).
      3. Invoke clean_controller_photo.py via subprocess to produce
         gui/img/known/<VID>_<PID>.<ext>.
      4. Update controller_catalog.yaml — append a new entry or update
         the existing one. Mark wiki_file: "" (community image, not
         from Wikimedia, so the sync tool won't touch it).
      5. Print git-add / commit / push / PR-URL hints.
    """
    import subprocess
    from PIL import Image

    ROOT = Path(__file__).resolve().parent
    CATALOG = ROOT / "controller_catalog.yaml"
    KNOWN_DIR = ROOT / "gui" / "img" / "known"
    CLEAN_PY = ROOT / "clean_controller_photo.py"
    GITHUB_REPO = "ITViking-FIN/RetroControlMapper"

    # 1. VID/PID validation
    vid = (args.vid or "").upper().strip()
    pid = (args.pid or "").upper().strip()
    if not re.fullmatch(r"[0-9A-F]{4}", vid):
        print(f"[fatal] --vid must be 4 hex chars (got {vid!r})"); sys.exit(2)
    if not re.fullmatch(r"[0-9A-F]{4}", pid):
        print(f"[fatal] --pid must be 4 hex chars (got {pid!r})"); sys.exit(2)
    key = f"{vid}:{pid}"

    src = args.image
    if not src.exists():
        print(f"[fatal] image not found: {src}"); sys.exit(2)
    if not CLEAN_PY.exists():
        print(f"[fatal] clean_controller_photo.py missing: {CLEAN_PY}"); sys.exit(2)

    # 2. Pick mode
    mode = args.mode
    if mode == "auto":
        with Image.open(src) as im:
            rgb = im.convert("RGB")
            w, h = rgb.size
            # Sample corners — same heuristic as clean_controller_photo
            corners = [rgb.getpixel((0, 0)), rgb.getpixel((w-1, 0)),
                       rgb.getpixel((0, h-1)), rgb.getpixel((w-1, h-1))]
            avg = tuple(sum(c[i] for c in corners) // 4 for i in range(3))
            bg_brightness = sum(avg) / 3
            # Sample centre for object brightness
            cx, cy = w // 2, h // 2
            mid = rgb.getpixel((cx, cy))
            obj_brightness = sum(mid) / 3
        if bg_brightness > 200 and obj_brightness < 100:
            mode = "silhouette"
            print(f"[auto] dark-on-light photo (bg={bg_brightness:.0f} obj={obj_brightness:.0f}) -> silhouette mode")
        elif bg_brightness > 200:
            mode = "remove-bg"
            print(f"[auto] uniform light bg (bg={bg_brightness:.0f}) -> remove-bg mode")
        else:
            mode = "crop"
            print(f"[auto] heterogeneous bg (bg={bg_brightness:.0f}) -> tight-crop mode")

    # 3. Invoke cleaner
    out_ext = ".png" if mode == "silhouette" else ".jpg"
    out_path = KNOWN_DIR / f"{vid}_{pid}{out_ext}"
    cmd = [sys.executable, str(CLEAN_PY), str(src), "--out", str(out_path)]
    if mode == "silhouette":
        cmd.append("--silhouette")
        cmd += ["--threshold", str(args.threshold)]
        if args.no_keep_colors:
            cmd.append("--no-keep-colors")
    elif mode == "remove-bg":
        cmd.append("--remove-bg")
        cmd += ["--tolerance", str(args.tolerance)]
    # else: tight crop (default behaviour, no flag)

    print(f"[run] {' '.join(str(x) for x in cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        print(f"[fatal] cleaner exited rc={result.returncode}"); sys.exit(result.returncode)
    if not out_path.exists():
        print(f"[fatal] expected output not found: {out_path}"); sys.exit(1)

    # 4. Update controller_catalog.yaml
    if not CATALOG.exists():
        print(f"[fatal] catalog missing: {CATALOG}"); sys.exit(1)
    catalog = yaml.safe_load(CATALOG.read_text(encoding="utf-8")) or {}
    entries = catalog.get("controllers") or []
    matched = None
    for e in entries:
        if (e.get("vid", "").upper() == vid and e.get("pid", "").upper() == pid):
            matched = e; break
    name = args.name or (matched.get("name") if matched else f"Controller {key}")
    if matched is None:
        new_entry = {
            "vid": vid,
            "pid": pid,
            "name": name,
            "wiki_file": "",
            "pc_support": args.pc_support,
            "notes": "Community-supplied image (gui/img/known/). Not on Wikimedia.",
        }
        entries.append(new_entry)
        catalog["controllers"] = entries
        action = "added"
    else:
        if not matched.get("name"): matched["name"] = name
        if not matched.get("pc_support"): matched["pc_support"] = args.pc_support
        existing_notes = matched.get("notes", "")
        if "community-supplied" not in existing_notes.lower():
            matched["notes"] = (existing_notes + ("\n" if existing_notes else "")
                                + "Community-supplied image (gui/img/known/).").strip()
        action = "updated"

    CATALOG.write_text(
        yaml.safe_dump(catalog, sort_keys=False, allow_unicode=True, width=120),
        encoding="utf-8",
    )
    print(f"[catalog] {action} entry for {key} ({name})")
    print(f"[image]   wrote {out_path}")

    # 5. Print next-step hints
    rel_img = out_path.relative_to(ROOT).as_posix()
    rel_cat = CATALOG.relative_to(ROOT).name
    print()
    print("Next steps:")
    print(f"  1. Review the cleaned image:  start {out_path}")
    print(f"  2. Stage:                     git add {rel_img} {rel_cat}")
    print(f"  3. Commit:                    git commit -m \"controller: add {key} ({name})\"")
    print(f"  4. Push:                      git push origin <your-branch>")
    print(f"  5. Open PR using template:    https://github.com/{GITHUB_REPO}/pulls/new")
    print()
    print("If the cleanup looks off, re-run with a different --mode "
          "(silhouette / remove-bg / crop) or tune --threshold / --tolerance.")


def cmd_validate(profiles: list[Profile]):
    issues = 0
    for p in profiles:
        if not p.system:
            print(f"[err] {p.file}: missing 'system'"); issues += 1
        if not p.is_system_default:
            if "[" in (p.rom or "") or "]" in (p.rom or ""):
                print(f"[warn] {p.file}: rom contains brackets — may need escaping")
        for k in p.es_settings:
            if not re.fullmatch(r"[A-Za-z0-9_\-]+", k):
                print(f"[warn] {p.file}: es_settings key '{k}' has unusual characters")
        for k in p.core_options:
            if not re.fullmatch(r"[A-Za-z0-9_\-]+", k):
                print(f"[warn] {p.file}: core_options key '{k}' has unusual characters")
    if issues == 0:
        print(f"OK — {len(profiles)} profile(s) validated, no errors.")


# ------------------------------ entrypoint ------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list",     help="Show all profiles")
    sub.add_parser("status",   help="Compare profiles against current RetroBat config")
    sub.add_parser("diff",     help="Preview what `apply` would change")
    a = sub.add_parser("apply",    help="Apply all profiles, or one with --id")
    a.add_argument("--id", help="Apply only this profile id (e.g. 'c64/Boulder Dash.crt')")
    r = sub.add_parser("revert",   help="Remove one profile's es_settings entries")
    r.add_argument("--id", required=True)
    sub.add_parser("validate", help="Lint profiles for issues")

    b = sub.add_parser("backup", help="Two-tier snapshot / restore subsystem")
    b_sub = b.add_subparsers(dest="backup_cmd", required=True)
    b_sub.add_parser("factory",
                     help="Capture the one-shot pre-install (tier 1) snapshot")
    bs = b_sub.add_parser("snapshot",
                          help="Capture a working (tier 2) snapshot manually")
    bs.add_argument("--description", default="",
                    help="Free-text label stored in the snapshot manifest")
    b_sub.add_parser("list", help="List all snapshots in a table")
    br = b_sub.add_parser("restore", help="Restore a snapshot")
    br.add_argument("id", help="Snapshot id (e.g. '20260504-120030' or 'factory')")
    bmode = br.add_mutually_exclusive_group()
    bmode.add_argument("--dry-run", action="store_true",
                       help="Preview only (default).")
    bmode.add_argument("--apply", action="store_true",
                       help="Actually restore.")
    b_sub.add_parser("help", help="Show backup subcommand help")

    pc = sub.add_parser("pull-community",
                        help="Fetch community-curated profiles from the GitHub repo")
    pc.add_argument("--repo", default="ITViking-FIN/RetroControlMapper",
                    help="GitHub repo to pull from (owner/name)")
    pc.add_argument("--ref", default="main",
                    help="Branch / tag / commit to pull (default: main)")
    pc.add_argument("--token",
                    help="Optional GitHub PAT to lift the 60/hr rate limit")
    pc.add_argument("--dry-run", action="store_true",
                    help="List what would be fetched, don't write")
    pc.add_argument("--prune", action="store_true",
                    help="Remove local community profiles that no longer exist upstream")

    sc = sub.add_parser("submit-controller",
                        help="Process & catalog a community-supplied controller photo")
    sc.add_argument("--vid", required=True, help="USB VID, 4-char hex (e.g. 2DC8)")
    sc.add_argument("--pid", required=True, help="USB PID, 4-char hex (e.g. 310B)")
    sc.add_argument("--image", required=True, type=Path,
                    help="Path to the source image (will be cleaned + cached)")
    sc.add_argument("--name", help="Friendly controller name (default: prompt or 'Controller VID:PID')")
    sc.add_argument("--mode", choices=("auto", "silhouette", "remove-bg", "crop"),
                    default="auto",
                    help="Cleanup mode. 'auto' picks silhouette for dark-on-light, "
                         "remove-bg for uniform light bg, crop otherwise.")
    sc.add_argument("--threshold", type=int, default=200,
                    help="--mode silhouette: pixels darker than this count as silhouette.")
    sc.add_argument("--tolerance", type=int, default=18,
                    help="--mode remove-bg: how close-to-bg counts as background.")
    sc.add_argument("--no-keep-colors", action="store_true",
                    help="--mode silhouette: drop the coloured-letter overlay.")
    sc.add_argument("--pc-support", choices=("native", "shim"), default="native")

    g = sub.add_parser("guid", help="Manage SDL controller GUID aliases (es_input.cfg)")
    g_sub = g.add_subparsers(dest="guid_cmd", required=True)
    g_sub.add_parser("status", help="List alias groups in es_input.cfg")
    g_sub.add_parser("help",   help="Show guid subcommand help")
    gf = g_sub.add_parser("fold", help="Fold alias groups into es_input.cfg")
    gf.add_argument("--id", help="Fold only this VID:PID group (e.g. '2dc8:3106')")
    mode = gf.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="Preview only (default).")
    mode.add_argument("--apply", action="store_true",
                      help="Actually rewrite es_input.cfg.")

    args = ap.parse_args()

    # `backup` commands don't need profiles loaded — handle early.
    if args.cmd == "backup":
        if args.backup_cmd == "factory":
            cmd_backup_factory()
        elif args.backup_cmd == "snapshot":
            cmd_backup_snapshot(args.description)
        elif args.backup_cmd == "list":
            cmd_backup_list()
        elif args.backup_cmd == "restore":
            dry = not args.apply
            cmd_backup_restore(args.id, dry=dry)
        else:  # help
            cmd_backup_help()
        return

    # `submit-controller` doesn't need profiles loaded — handle early.
    if args.cmd == "submit-controller":
        cmd_submit_controller(args)
        return

    # `pull-community` doesn't need local profiles loaded — handle early.
    if args.cmd == "pull-community":
        cmd_pull_community(args)
        return

    # `guid` commands don't need profiles loaded — handle early.
    if args.cmd == "guid":
        if args.guid_cmd == "status":
            cmd_guid_status()
        elif args.guid_cmd == "fold":
            # default: dry-run unless --apply
            dry = not args.apply
            cmd_guid_fold(args.id, dry=dry)
        else:  # help
            cmd_guid_help()
        return

    profiles = load_profiles()
    if not profiles:
        print(f"[info] no profiles found in {PROFILES_DIR}")
        sys.exit(0)

    {
        "list":     lambda: cmd_list(profiles),
        "status":   lambda: cmd_status(profiles),
        "diff":     lambda: cmd_diff(profiles),
        "apply":    lambda: cmd_apply(profiles, args.id),
        "revert":   lambda: cmd_revert(profiles, args.id),
        "validate": lambda: cmd_validate(profiles),
    }[args.cmd]()


if __name__ == "__main__":
    main()
