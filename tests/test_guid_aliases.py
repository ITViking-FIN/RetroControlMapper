"""Smoke tests for guid_aliases.py — run via `py tests/test_guid_aliases.py`.

Exercises:
  * parse_es_input on a 3-block fixture (two aliases + one singleton)
  * group_aliases produces 2 groups (one with 2 entries, one singleton)
  * expand_inputconfig with dry=True returns the right (added, kept) counts
  * extract_vid_pid for the SDL byte layout

No pytest, no third-party deps. Plain `assert` + a `__main__` block.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

# Ensure we can import from the project root regardless of cwd.
THIS = Path(__file__).resolve()
PROJECT_ROOT = THIS.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from guid_aliases import (  # noqa: E402
    expand_inputconfig,
    extract_vid_pid,
    group_aliases,
    parse_es_input,
)

FIXTURE = THIS.parent / "fixtures" / "es_input.sample.cfg"


def test_extract_vid_pid():
    # 8BitDo Ultimate USB: bytes 4-5 = "c8 2d" → 0x2dc8 ; bytes 8-9 = "06 31" → 0x3106
    vid, pid = extract_vid_pid("03000000c82d00000631000011010000")
    assert vid == "2dc8", f"expected vid=2dc8 got {vid!r}"
    assert pid == "3106", f"expected pid=3106 got {pid!r}"

    # Xbox 360 XInput: "5e 04" → 045e ; "8e 02" → 028e
    vid, pid = extract_vid_pid("030000005e0400008e02000014010000")
    assert vid == "045e", f"expected vid=045e got {vid!r}"
    assert pid == "028e", f"expected pid=028e got {pid!r}"

    # Bad input
    assert extract_vid_pid("") == ("", "")
    assert extract_vid_pid("garbage") == ("", "")
    assert extract_vid_pid("not-a-hex-string-of-32-charac") == ("", "")
    print("  extract_vid_pid: ok")


def test_parse_es_input():
    aliases = parse_es_input(FIXTURE)
    assert len(aliases) == 3, f"expected 3 aliases, got {len(aliases)}"
    guids = {a.guid for a in aliases}
    assert "03000000c82d00000631000011010000" in guids
    assert "05000000c82d00000631000017010000" in guids
    assert "030000005e0400008e02000014010000" in guids

    # All VID/PID values populated, lowercase
    for a in aliases:
        assert a.vid and a.vid == a.vid.lower()
        assert a.pid and a.pid == a.pid.lower()

    # Phase-1 invariant: last_seen always None when parsed from disk only
    for a in aliases:
        assert a.last_seen is None
    print(f"  parse_es_input: ok ({len(aliases)} aliases parsed)")


def test_parse_missing_file_returns_empty():
    aliases = parse_es_input(Path("/nonexistent/path/that/does/not/exist.cfg"))
    assert aliases == []
    print("  parse_es_input(missing): ok (empty list)")


def test_group_aliases():
    aliases = parse_es_input(FIXTURE)
    groups = group_aliases(aliases)
    assert len(groups) == 2, f"expected 2 groups, got {len(groups)}"
    # The 8BitDo group: 2 entries
    bitdo = groups.get(("2dc8", "3106"))
    assert bitdo is not None and len(bitdo) == 2, \
        f"expected 2dc8:3106 group of 2, got {bitdo}"
    # Order-of-first-appearance: USB before BT in the fixture
    assert bitdo[0].guid.startswith("03"), \
        "canonical (first) should be the USB block"
    # The Xbox group: singleton
    xbox = groups.get(("045e", "028e"))
    assert xbox is not None and len(xbox) == 1
    print("  group_aliases: ok (2 groups, sizes 2 + 1)")


def test_expand_inputconfig_dry_run_already_satisfied():
    """When the alias group is already fully present (USB + BT both there),
    expand_inputconfig should report (added=0, kept=1)."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "es_input.cfg"
        shutil.copy2(FIXTURE, tmp)
        original_bytes = tmp.read_bytes()
        aliases = parse_es_input(tmp)
        groups = group_aliases(aliases)
        bitdo_group = groups[("2dc8", "3106")]
        added, kept = expand_inputconfig(tmp, bitdo_group, dry=True)
        # canonical is group[0]; group[1] (the BT alias) is already in
        # the file → kept=1, added=0
        assert added == 0, f"expected added=0, got {added}"
        assert kept == 1, f"expected kept=1, got {kept}"
        # dry=True must not have touched the file
        assert tmp.read_bytes() == original_bytes, \
            "dry-run must not modify the file"
    print("  expand_inputconfig(dry, already-folded): ok (added=0, kept=1)")


def test_expand_inputconfig_dry_run_with_synthetic_missing_alias():
    """Inject a fake third 2dc8:3106 alias not in the file → expect added=1, kept=1."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "es_input.cfg"
        shutil.copy2(FIXTURE, tmp)
        aliases = parse_es_input(tmp)
        groups = group_aliases(aliases)
        bitdo_group = list(groups[("2dc8", "3106")])
        # Append a synthetic alias not yet in the file
        from guid_aliases import GuidAlias
        bitdo_group.append(GuidAlias(
            guid="04000000c82d000006310000aabbccdd",
            vid="2dc8",
            pid="3106",
            device_name="8BitDo Ultimate (synthetic)",
        ))
        added, kept = expand_inputconfig(tmp, bitdo_group, dry=True)
        # canonical (USB) is group[0]; group[1] (BT) already in file (kept=1);
        # group[2] (synthetic) not in file (added=1)
        assert added == 1, f"expected added=1, got {added}"
        assert kept == 1, f"expected kept=1, got {kept}"
        # dry=True: file unchanged → still 3 inputConfig blocks
        tree = ET.parse(tmp)
        cfgs = [c for c in tree.getroot().iter("inputConfig")
                if (c.get("type") or "").lower() == "joystick"]
        assert len(cfgs) == 3, f"file shouldn't grow under dry-run; saw {len(cfgs)}"
    print("  expand_inputconfig(dry, missing alias): ok (added=1, kept=1)")


def test_expand_inputconfig_singleton_is_noop():
    """A singleton group should be a no-op even if you pass it in."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "es_input.cfg"
        shutil.copy2(FIXTURE, tmp)
        aliases = parse_es_input(tmp)
        groups = group_aliases(aliases)
        xbox_group = groups[("045e", "028e")]
        added, kept = expand_inputconfig(tmp, xbox_group, dry=True)
        assert added == 0 and kept == 0
    print("  expand_inputconfig(singleton): ok (no-op)")


def main():
    print(f"Running guid_aliases smoke tests against {FIXTURE}\n")
    assert FIXTURE.exists(), f"fixture missing: {FIXTURE}"
    test_extract_vid_pid()
    test_parse_es_input()
    test_parse_missing_file_returns_empty()
    test_group_aliases()
    test_expand_inputconfig_dry_run_already_satisfied()
    test_expand_inputconfig_dry_run_with_synthetic_missing_alias()
    test_expand_inputconfig_singleton_is_noop()
    print("\nAll guid_aliases smoke tests passed.")


if __name__ == "__main__":
    main()
