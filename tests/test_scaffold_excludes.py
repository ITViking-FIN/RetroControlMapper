"""Smoke tests for the v0.1.1 scaffold-excludes machinery.

Covers:
  - _validate_exclude_entry — the path-traversal guard accepts simple
    relative subdir names and rejects anything that climbs out of the
    system's ROM dir
  - _load_excludes / _save_excludes — JSON round-trip with the ENV
    redirected to a tempdir so we never touch the real %APPDATA%
  - _is_excluded inputs propagate via _iter_rom_files (top-level subdir
    pruning + .rbcf-ignore drop-in handling)

Plain-`assert`, no pytest. Run via `py tests/test_scaffold_excludes.py`.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Ensure the project root is on sys.path so we can import rbcf_gui.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

# Redirect APPDATA so the import doesn't load (or pollute) the real
# excludes file. Must happen BEFORE importing rbcf_gui.
_TMP_APPDATA = tempfile.mkdtemp(prefix="rbcf_test_excl_")
os.environ["APPDATA"] = _TMP_APPDATA

# Defer import so the module-level SCAFFOLD_EXCLUDES_PATH constant
# resolves under our tempdir.
import importlib  # noqa: E402

if "rbcf_gui" in sys.modules:
    rbcf_gui = importlib.reload(sys.modules["rbcf_gui"])
else:
    import rbcf_gui  # noqa: E402


def _reset_excludes_file():
    """Wipe whatever excludes file currently exists in the tempdir."""
    p = rbcf_gui.SCAFFOLD_EXCLUDES_PATH
    if p.is_file():
        p.unlink()


def test_validate_traversal_guard():
    """The guard rejects anything dangerous and accepts simple names."""
    valid = ["Demos", "Sub-Folder", "abc.def", "a/b", "weird name with spaces"]
    invalid = ["", "  ", ".", "..", "../etc/passwd", "../..\\windows",
               "/abs/path", "./rel", "C:/drive/letter", "D:something"]
    for entry in valid:
        assert rbcf_gui._validate_exclude_entry(entry), f"should accept: {entry!r}"
    for entry in invalid:
        assert not rbcf_gui._validate_exclude_entry(entry), \
            f"should reject: {entry!r}"
    print("  validate_traversal_guard: ok")


def test_load_save_roundtrip():
    """Writing a dict and reading it back yields the same dict."""
    _reset_excludes_file()
    initial = rbcf_gui._load_excludes()
    assert initial == {}, f"empty start expected; got {initial!r}"
    payload = {"amiga4000": ["Demos"], "c64": ["Tools", "Magazines"]}
    rbcf_gui._save_excludes(payload)
    loaded = rbcf_gui._load_excludes()
    assert loaded == payload, f"round-trip failed: {loaded!r} != {payload!r}"
    # Empty system list survives.
    rbcf_gui._save_excludes({"amiga4000": []})
    again = rbcf_gui._load_excludes()
    assert again == {"amiga4000": []}, f"empty-list survives expected; got {again!r}"
    _reset_excludes_file()
    print("  load_save_roundtrip: ok")


def test_load_handles_corrupt_file():
    """Bad JSON / non-dict at the top level → returns {} rather than raising."""
    _reset_excludes_file()
    rbcf_gui.SCAFFOLD_EXCLUDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    rbcf_gui.SCAFFOLD_EXCLUDES_PATH.write_text("not json", encoding="utf-8")
    assert rbcf_gui._load_excludes() == {}
    rbcf_gui.SCAFFOLD_EXCLUDES_PATH.write_text("[1, 2, 3]", encoding="utf-8")
    assert rbcf_gui._load_excludes() == {}, "list at top level should be ignored"
    rbcf_gui.SCAFFOLD_EXCLUDES_PATH.write_text(
        '{"amiga4000": ["ok", 7, true]}', encoding="utf-8")
    out = rbcf_gui._load_excludes()
    assert out == {"amiga4000": ["ok"]}, f"non-string entries should be filtered; got {out!r}"
    _reset_excludes_file()
    print("  load_handles_corrupt_file: ok")


def test_iter_rom_files_honours_excludes():
    """Building a synthetic ROM tree, _iter_rom_files prunes excluded subdirs
    and any directory containing .rbcf-ignore."""
    with tempfile.TemporaryDirectory(prefix="rbcf_roms_") as tmp:
        tmp_root = Path(tmp)
        sys_dir = tmp_root / "amiga4000"
        # Layout:
        #   amiga4000/Real-ROM.lha           ← yielded
        #   amiga4000/Sub/Inner.lha          ← yielded
        #   amiga4000/Demos/Demo1.lha        ← excluded by name
        #   amiga4000/IgnoredTree/.rbcf-ignore + IgnoredTree/X.lha  ← pruned
        #   amiga4000/images/cover.png       ← pruned (reserved asset dir)
        for d in ("Sub", "Demos", "IgnoredTree", "images"):
            (sys_dir / d).mkdir(parents=True, exist_ok=True)
        (sys_dir / "Real-ROM.lha").write_text("rom")
        (sys_dir / "Sub" / "Inner.lha").write_text("rom")
        (sys_dir / "Demos" / "Demo1.lha").write_text("rom")
        (sys_dir / "IgnoredTree" / "X.lha").write_text("rom")
        (sys_dir / "IgnoredTree" / ".rbcf-ignore").write_text("")
        (sys_dir / "images" / "cover.png").write_text("img")

        excludes = {"amiga4000": ["Demos"]}
        names = sorted(p.name for p in
                       rbcf_gui._iter_rom_files(sys_dir, "amiga4000", excludes))
        assert names == ["Inner.lha", "Real-ROM.lha"], \
            f"expected only Real-ROM + Inner; got {names!r}"
    print("  iter_rom_files_honours_excludes: ok")


def test_iter_rom_files_no_excludes_dict():
    """Calling _iter_rom_files without excludes still works (back-compat
    with old call sites that pass system_dir only)."""
    with tempfile.TemporaryDirectory(prefix="rbcf_roms_") as tmp:
        sys_dir = Path(tmp) / "c64"
        sys_dir.mkdir()
        (sys_dir / "Boulder Dash.crt").write_text("rom")
        (sys_dir / "images").mkdir()
        (sys_dir / "images" / "boulder.png").write_text("img")
        names = sorted(p.name for p in rbcf_gui._iter_rom_files(sys_dir))
        assert names == ["Boulder Dash.crt"], f"got {names!r}"
    print("  iter_rom_files_no_excludes_dict: ok")


def test_count_roms_honours_excludes():
    """_count_roms_in_system also prunes via the excludes mechanism."""
    with tempfile.TemporaryDirectory(prefix="rbcf_roms_") as tmp:
        sys_dir = Path(tmp) / "amiga4000"
        sys_dir.mkdir()
        (sys_dir / "a.lha").write_text("rom")
        (sys_dir / "b.lha").write_text("rom")
        demos = sys_dir / "Demos"
        demos.mkdir()
        (demos / "x.lha").write_text("rom")
        (demos / "y.lha").write_text("rom")
        # Without excludes
        assert rbcf_gui._count_roms_in_system(sys_dir) == 4
        # With excludes
        assert rbcf_gui._count_roms_in_system(
            sys_dir, "amiga4000", {"amiga4000": ["Demos"]}
        ) == 2
    print("  count_roms_honours_excludes: ok")


if __name__ == "__main__":
    print("Running scaffold-excludes smoke tests")
    print()
    test_validate_traversal_guard()
    test_load_save_roundtrip()
    test_load_handles_corrupt_file()
    test_iter_rom_files_honours_excludes()
    test_iter_rom_files_no_excludes_dict()
    test_count_roms_honours_excludes()
    print()
    print("All scaffold-excludes smoke tests passed.")
