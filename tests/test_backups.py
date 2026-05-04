"""Smoke tests for backups.py — run via `py tests/test_backups.py`.

Exercises:
  * factory_exists() False on a fresh state
  * snapshot('factory', ...) succeeds, then factory_exists() True
  * second snapshot('factory', ...) returns None
  * snapshot('working', ...) creates a snapshots/<id>/ dir
  * list_snapshots() ordering: most-recent working first, factory at end
  * restore('factory', dry=True) returns the right files without writing
  * cap enforcement: 32 working snapshots → list returns <= 30 (factory
    excluded from the cap)

Isolation strategy: APPDATA is redirected to a tempdir so the
module-level FACTORY_DIR / SNAPSHOTS_DIR resolve there. A fake
RETROBAT_ROOT (with the canonical sub-files populated) is also stood up
in the tempdir, and `backups.RETROBAT_ROOT` is monkey-patched to point
at it. We then re-import backups so its module-level constants pick up
the redirected APPDATA.

No pytest, no third-party deps. Plain `assert` + a `__main__` block.
"""
from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

# Ensure project root on sys.path regardless of cwd.
THIS = Path(__file__).resolve()
PROJECT_ROOT = THIS.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _make_fake_retrobat(root: Path) -> None:
    """Populate ``root`` with the files backups.py knows how to capture."""
    es_dir = root / "emulationstation" / ".emulationstation"
    es_dir.mkdir(parents=True, exist_ok=True)
    (es_dir / "es_settings.cfg").write_text(
        '<?xml version="1.0"?>\n<config>\n'
        '  <string name="example" value="hi" />\n'
        '</config>\n',
        encoding="utf-8",
    )
    (es_dir / "es_input.cfg").write_text(
        "<inputList>\n</inputList>\n", encoding="utf-8",
    )

    ra_dir = root / "emulators" / "retroarch"
    ra_dir.mkdir(parents=True, exist_ok=True)
    (ra_dir / "retroarch-core-options.cfg").write_text(
        'vice_mapper_a = "RETROK_F1"\n', encoding="utf-8",
    )

    bezels = root / "decorations" / "thebezelproject" / "systems"
    bezels.mkdir(parents=True, exist_ok=True)
    (bezels / "c64.info").write_text('{"top":50}\n', encoding="utf-8")
    (bezels / "amiga500.info").write_text('{"top":40}\n', encoding="utf-8")


def _fresh_backups_module(appdata: Path, retrobat: Path):
    """Re-import backups.py after redirecting APPDATA + RETROBAT_ROOT.

    Returns the freshly-imported module. Each test calls this so the
    module-level FACTORY_DIR / SNAPSHOTS_DIR pick up the new APPDATA.
    """
    os.environ["APPDATA"] = str(appdata)
    if "backups" in sys.modules:
        del sys.modules["backups"]
    import backups  # noqa: WPS433 (intentional re-import)
    backups.RETROBAT_ROOT = retrobat
    # Sanity: directory constants must now resolve under our tempdir.
    assert str(backups.FACTORY_DIR).startswith(str(appdata)), (
        f"FACTORY_DIR {backups.FACTORY_DIR} not under tempdir {appdata}"
    )
    assert str(backups.SNAPSHOTS_DIR).startswith(str(appdata)), (
        f"SNAPSHOTS_DIR {backups.SNAPSHOTS_DIR} not under tempdir {appdata}"
    )
    return backups


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

def test_factory_lifecycle():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        appdata = td / "appdata"
        retrobat = td / "RetroBat"
        appdata.mkdir()
        retrobat.mkdir()
        _make_fake_retrobat(retrobat)
        b = _fresh_backups_module(appdata, retrobat)

        assert b.factory_exists() is False, "fresh state: factory should not exist"

        snap = b.snapshot("factory", description="initial install")
        assert snap is not None, "first factory snapshot should succeed"
        assert snap.id == "factory"
        assert snap.kind == "factory"
        assert snap.description == "initial install"
        # Files captured: 3 static + 2 .info = 5 (all populated above)
        assert len(snap.files) == 5, f"expected 5 captured files, got {len(snap.files)}: {snap.files}"
        assert b.factory_exists() is True

        # Second factory call: refused (returns None), and on-disk dir
        # is untouched.
        before_mtime = (b.FACTORY_DIR / "manifest.json").stat().st_mtime
        snap2 = b.snapshot("factory", description="should not happen")
        assert snap2 is None, "second factory snapshot should be refused"
        after_mtime = (b.FACTORY_DIR / "manifest.json").stat().st_mtime
        assert before_mtime == after_mtime, "factory manifest must not be rewritten"

    print("  factory_lifecycle: ok")


def test_working_snapshot_creates_dir():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        appdata = td / "appdata"
        retrobat = td / "RetroBat"
        appdata.mkdir()
        retrobat.mkdir()
        _make_fake_retrobat(retrobat)
        b = _fresh_backups_module(appdata, retrobat)

        snap = b.snapshot("working", description="manual #1")
        assert snap is not None
        assert snap.kind == "working"
        snap_dir = b.SNAPSHOTS_DIR / snap.id
        assert snap_dir.is_dir(), f"snapshot dir missing: {snap_dir}"
        assert (snap_dir / "manifest.json").is_file()
        # The captured files must exist at their relative paths inside the dir.
        for rel in snap.files:
            assert (snap_dir / rel).is_file(), f"missing inside snapshot: {rel}"

    print("  working_snapshot_creates_dir: ok")


def test_list_ordering():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        appdata = td / "appdata"
        retrobat = td / "RetroBat"
        appdata.mkdir()
        retrobat.mkdir()
        _make_fake_retrobat(retrobat)
        b = _fresh_backups_module(appdata, retrobat)

        # Capture in a deterministic order; bump mtimes so they differ.
        s1 = b.snapshot("working", description="first")
        assert s1 is not None
        time.sleep(0.05)
        s2 = b.snapshot("working", description="second")
        assert s2 is not None
        time.sleep(0.05)
        s3 = b.snapshot("working", description="third")
        assert s3 is not None
        # Force mtimes to be definitely-distinct in case the FS clock is coarse.
        for offset, snap in [(1.0, s1), (2.0, s2), (3.0, s3)]:
            mp = b.SNAPSHOTS_DIR / snap.id / "manifest.json"
            os.utime(mp, (mp.stat().st_atime, mp.stat().st_mtime + offset))

        b.snapshot("factory", description="emergency revert")

        snaps = b.list_snapshots()
        assert len(snaps) == 4, f"expected 4 snapshots, got {len(snaps)}"
        # Working snapshots first, most-recent-first by mtime.
        assert snaps[0].id == s3.id, f"newest working should be first: got {snaps[0].id}"
        assert snaps[1].id == s2.id
        assert snaps[2].id == s1.id
        # Factory pinned to the END.
        assert snaps[-1].id == "factory", f"factory must be last; got {snaps[-1].id}"
        assert snaps[-1].kind == "factory"

    print("  list_ordering: ok")


def test_restore_dry_run():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        appdata = td / "appdata"
        retrobat = td / "RetroBat"
        appdata.mkdir()
        retrobat.mkdir()
        _make_fake_retrobat(retrobat)
        b = _fresh_backups_module(appdata, retrobat)

        snap = b.snapshot("factory", description="dry-run subject")
        assert snap is not None

        # Mutate the live RetroBat tree so we can prove dry-run does NOT touch it.
        es_settings = retrobat / "emulationstation" / ".emulationstation" / "es_settings.cfg"
        marker = "<!-- LIVE EDIT MARKER -->"
        es_settings.write_text(es_settings.read_text(encoding="utf-8") + marker, encoding="utf-8")

        before_count = (
            len(list(b.SNAPSHOTS_DIR.iterdir())) if b.SNAPSHOTS_DIR.is_dir() else 0
        )
        restored, skipped = b.restore("factory", dry=True)
        after_count = (
            len(list(b.SNAPSHOTS_DIR.iterdir())) if b.SNAPSHOTS_DIR.is_dir() else 0
        )

        assert len(restored) == len(snap.files), (
            f"dry-run should plan to restore all captured files; "
            f"planned {len(restored)}, captured {len(snap.files)}"
        )
        assert skipped == [], f"unexpected skips in dry-run: {skipped}"
        # Live file MUST still bear our marker — dry-run wrote nothing.
        assert marker in es_settings.read_text(encoding="utf-8"), (
            "dry-run unexpectedly overwrote the live RetroBat file"
        )
        # Dry-run must NOT auto-snapshot — no new working entry created.
        assert before_count == after_count, (
            f"dry-run should not create an auto-snapshot; "
            f"working dir grew from {before_count} to {after_count}"
        )

    print("  restore_dry_run: ok")


def test_restore_apply_takes_auto_snapshot():
    """Real-apply path must auto-snapshot the current state first."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        appdata = td / "appdata"
        retrobat = td / "RetroBat"
        appdata.mkdir()
        retrobat.mkdir()
        _make_fake_retrobat(retrobat)
        b = _fresh_backups_module(appdata, retrobat)

        b.snapshot("factory", description="apply subject")
        before_ids = {s.id for s in b.list_snapshots()}

        # Mutate the live tree so the restore actually writes something.
        es_settings = retrobat / "emulationstation" / ".emulationstation" / "es_settings.cfg"
        es_settings.write_text("<!-- mutated -->\n", encoding="utf-8")

        restored, skipped = b.restore("factory", dry=False)
        assert len(restored) >= 1
        assert skipped == [] or all("missing" not in r for _p, r in skipped)

        after_ids = {s.id for s in b.list_snapshots()}
        new_ids = after_ids - before_ids
        assert len(new_ids) == 1, (
            f"restore should have created exactly one new working snapshot; "
            f"new={new_ids}"
        )
        # The live file should now match the snapshot's content (not "<!-- mutated -->").
        text = es_settings.read_text(encoding="utf-8")
        assert "mutated" not in text, "live file not actually restored"

    print("  restore_apply_takes_auto_snapshot: ok")


def test_cap_enforcement():
    """Working snapshot count must not exceed SNAPSHOT_HISTORY_CAP."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        appdata = td / "appdata"
        retrobat = td / "RetroBat"
        appdata.mkdir()
        retrobat.mkdir()
        _make_fake_retrobat(retrobat)
        b = _fresh_backups_module(appdata, retrobat)
        cap = b.SNAPSHOT_HISTORY_CAP
        assert cap == 30, f"expected cap 30 (DECISIONS.md #5), got {cap}"

        # Fabricate 32 working snapshot dirs by hand with deterministic
        # ordered mtimes — going through snapshot() in a loop would be
        # second-resolution-ambiguous and slow.
        for i in range(32):
            stamp = f"2026010{i // 10}-12{i:02d}00"  # synthetic ids
            sd = b.SNAPSHOTS_DIR / stamp
            sd.mkdir(parents=True, exist_ok=True)
            mp = sd / "manifest.json"
            mp.write_text(
                '{"id":"' + stamp + '","kind":"working","created_at":"2026-01-01T12:00:00",'
                '"description":"synthetic","files":[],"retrobat_root":""}',
                encoding="utf-8",
            )
            # Distinct mtimes so prune order is deterministic.
            os.utime(mp, (1_700_000_000 + i, 1_700_000_000 + i))

        # Now trigger a real working snapshot — this should prune oldest
        # back down to <= cap.
        snap = b.snapshot("working", description="trigger prune")
        assert snap is not None

        snaps = b.list_snapshots()
        working_count = sum(1 for s in snaps if s.kind == "working")
        assert working_count <= cap, (
            f"working snapshot count exceeded cap: {working_count} > {cap}"
        )

        # Add a factory snapshot and verify it's NOT counted against cap.
        b.snapshot("factory", description="last-resort")
        snaps = b.list_snapshots()
        working_count2 = sum(1 for s in snaps if s.kind == "working")
        factory_count = sum(1 for s in snaps if s.kind == "factory")
        assert factory_count == 1
        assert working_count2 <= cap, "factory should be excluded from the cap"

    print(f"  cap_enforcement: ok (capped at {cap}, factory excluded)")


def main():
    print("Running backups smoke tests\n")
    test_factory_lifecycle()
    test_working_snapshot_creates_dir()
    test_list_ordering()
    test_restore_dry_run()
    test_restore_apply_takes_auto_snapshot()
    test_cap_enforcement()
    print("\nAll backups smoke tests passed.")


if __name__ == "__main__":
    main()
