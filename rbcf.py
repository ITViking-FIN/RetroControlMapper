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

from config import ES_SETTINGS, RA_CORE_OPTS

ROOT = Path(__file__).resolve().parent
PROFILES_DIR = ROOT / "profiles"
BACKUP_TAG = f".bak.rbcf.{datetime.now():%Y%m%d}"


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
    print(f"Applying {len(selected)} profile(s)...")
    es_changes, es_adds = apply_es_settings(planned_es_changes(selected))
    co_changes, co_adds = apply_core_options(planned_core_changes(selected))
    print(f"  es_settings.cfg: {len(es_changes)} updated, {len(es_adds)} added")
    print(f"  retroarch-core-options.cfg: {len(co_changes)} updated, {len(co_adds)} added")
    if es_changes or es_adds or co_changes or co_adds:
        print(f"  backups tagged: {BACKUP_TAG}")


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
    args = ap.parse_args()

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
