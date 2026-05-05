# Changelog

All notable changes to RetroControlMapper. Format follows [Keep a
Changelog](https://keepachangelog.com); versioning follows
[SemVer](https://semver.org).

## [v0.1.1] — 2026-05-05

First public release. (v0.1.0 was built and tested locally but never
shipped — its commits are folded into v0.1.1 below.)

Five fixes and two features landed after the initial v0.1.0 setup .exe
was first cut. Cumulatively addresses 4 bugs the user hit while
exercising the fresh install plus the two scaffold-flow improvements.

### Added

- **Scaffold progress bar.** Apply with hundreds of thousands of files
  no longer looks frozen. Two new streaming endpoints
  (`/api/scaffold-{all,defaults}/stream?apply=true`) emit Server-Sent
  Events; the GUI renders a cyan→pink gradient progress bar with
  percentage, done/total counters, and the currently-writing file
  path. Existing non-streaming endpoints stay byte-identical.
- **Per-directory scaffold exclusions.** Each system row in the Step 2
  scan table has an "Exclude folders…" link. The modal lists the
  system's immediate subdirectories with checkboxes; user picks which
  to skip. Excludes persist to `%APPDATA%/RB-Controller_fix/scaffold-
  excludes.json`. Power-user shortcut: drop a `.rbcf-ignore` file in
  any directory and the scaffolder treats that whole tree as excluded
  (gitignore-style). Two endpoints: `GET /api/scaffold-excludes`,
  `POST /api/scaffold-excludes`, plus `GET /api/system-subdirs?
  system=<id>` for the modal's data source.
- **Per-row "(N)" pill** next to the Exclude folders link showing the
  current exclude count for that system.

### Fixed

- **Installer crash on shortcut creation** (`IPersistFile::Save failed;
  0x80070005`). The `[Icons]` section used `{commondesktop}` which
  needs admin elevation, but the installer runs `PrivilegesRequired=
  lowest`. Now `{autodesktop}` — routes to the user's Desktop in
  unprivileged mode.
- **Apply broken in the bundled .exe.** `run_apply()` was spawning a
  subprocess against `rbcf.py`, but PyInstaller compiles .py source
  into the PYZ archive — there's no `rbcf.py` file on disk in the
  bundle. Refactored to call `rbcf.cmd_apply()` in-process via
  `contextlib.redirect_stdout`. Side benefit: no subprocess spawn cost
  per Apply.
- **GUI opened in a browser tab** — was a placeholder during dev. Tray
  menu "Show window" now launches Edge in `--app` mode (no browser
  chrome, looks like a real desktop window). Falls back to the user's
  default browser if Edge isn't found.
- **Empty / non-real systems in the onboarding scan.** `/api/scan` was
  returning entries for `amazon`, `2ship`, `aquarius`, etc. — RetroBat
  systems with zero ROMs in the user's library. Now filtered out
  (`rom_count == 0 && profiles_count == 0`).
- **Stuck-disabled scaffold-defaults toggle.** When defaults were all
  in place but per-game stubs were missing, the mode toggle defaulted
  to "Defaults only (0)" with a disabled primary button — user could
  only proceed by manually flipping to "Every ROM". Now auto-promotes
  to the actionable mode.
- **Mislabelled "Profiles" column in the scan table.** Counted only
  per-game profiles (excluding `_default.yaml`) but read as if it
  meant all YAMLs on disk. Renamed column header to "Per-game" and
  the summary line clarifies "X with per-game profiles".
- **Controller-image upload size cap status code.** Inner branch was
  returning HTTP 200 with `{ok: false, error: "too large"}`; outer
  envelope branch was returning 413. Now both 413 — consistent with
  any downstream tooling that keys off HTTP status.

### Changed

- **HTTP status mapping for `/api/controller-image` errors.** "too
  large" → 413; "missing file" / "unsupported" / "invalid VID" → 400;
  success → 200 (was always 200 + JSON-error body before).

## [v0.1.0] — 2026-05-04

First public release. The full toolset for fixing RetroBat's
controller-config fragility, packaged as a single Windows .exe.

### Highlights

- **GUID alias-fold** — fixes the bug where the same physical pad
  presents under multiple SDL GUIDs (USB-vs-Bluetooth, port hops, driver
  swaps) and RetroBat "forgets" your mapping. Detect-mode default plus
  opt-in silent auto-fold via the tray menu.
- **Tray-resident** — closes to tray, opens in its own desktop window
  (Edge `--app` mode — no browser chrome). Settings cog with theme,
  one-click apply, controller images, update check.
- **Per-system + per-game profile model** with V/K/T confidence
  indicator, inheritance overlay (toggle to see overridden vs.
  inherited values per row).
- **Two-tier backups** — immutable pre-install factory snapshot plus a
  rolling 30-entry working-snapshot history. Auto-snap before every
  Apply. Restore takes a fresh snapshot of current state first, so the
  restore is itself revertible.
- **Out-of-the-box scaffolding** — first-run wizard scans your library
  and offers safe `_default.yaml` scaffolds plus optional per-game stubs
  for every ROM you have.
- **Bezel viewport calibration** — fixes RetroBat's too-lenient
  alpha-235 cutoff that crops the visible play area.
- **Installer with maintenance mode** — re-running the setup .exe
  presents Repair / Uninstall / Cancel. Repair re-extracts files,
  preserves user data; Uninstall removes the app and asks (default No)
  before deleting `%APPDATA%`.

### Features

#### Core

- Auto-detect RetroBat install via `.rbcfrc` override → registry probe
  → env var → common install paths.
- 244 RetroBat systems in the SYSTEM dropdown (parsed from
  `es_systems.cfg`), with curated mapping notes for **52 popular
  systems** including:
  - Major consoles: NES, SNES, Genesis/Mega Drive, Master System, Game
    Gear, GB/GBC/GBA, NDS, N64, PSX, Dreamcast, Saturn, PCE/TG-16
  - Arcade: MAME, FBNeo, NeoGeo, NeoGeo CD, CPS1/2/3, Naomi, Naomi 2,
    Atomiswave, Sega Model 2/3, Chihiro, Triforce, Daphne, Cave,
    Gaelco, Namco System 246/256, HBMAME
  - Handhelds: Lynx, WonderSwan, Neo Geo Pocket
  - Retro home computers: C64, Amiga 500/1200/CD32, Atari ST, ZX
    Spectrum, MSX, Amstrad CPC
  - Personal request: Magnavox Odyssey² / Philips Videopac
- **Search online for missing system mappings** — explicit consent each
  time, fetches from RetroBat wiki / libretro docs / launcher source.
  No consent caching; you'll be prompted on every lookup.
- **252 profile YAMLs** ship with the installer as a seed — copied to
  `%APPDATA%/RB-Controller_fix/profiles/` on first run.

#### UI

- **Frosted Acrylic** design language: layered shell-and-plate depth,
  visible backdrop blur, ambient bokeh, soft scattered shadows, single
  upper-left light source, etched-glass typography.
- **Light / Dark / Auto** theme toggle in the settings cog (Auto
  follows `prefers-color-scheme`).
- **Per-controller pills** in the page header — one candy-styled pill
  per detected pad, only the active one shows the green pulsing dot.
  Click to switch + see that controller's specific details.
- **Game-detail view** with V/K/T confidence pill, inheritance overlay
  (off by default, sticky-once-toggled per system), per-row source
  badges (Override / Inherited / Unset).
- **Apply preview modal** — Save → preview → Apply two-step (default).
  One-Click Save & Apply available as a settings opt-in.
- **Custom controller images** — Manage… in the cog popover. Drag-and-
  drop upload to `gui/img/contrib/`, ≤2 MB, PNG/JPG/WebP/SVG. Contrib
  images take priority over Wikimedia-synced images.

#### Networking (all consent-gated)

- **Update check** — checks GitHub releases API on user request. 24h
  cache, 1h on errors. Default OFF until you click "Check now" the
  first time. Cache + consent persist in `%APPDATA%`.
- **System lookup** — RetroBat wiki + libretro docs + launcher source.
  Asks every time, no consent caching.
- **No telemetry. No accounts.**

#### Distribution

- Single `RetroControlMapper_0.1.0_setup.exe` (~31 MB).
- Inno Setup wizard pages: license (GPL-3.0) → install location →
  tasks (autostart on Windows / back up RetroBat first / enable update
  check / desktop shortcut) → install → launches the app and opens the
  README.
- Per-user install (no UAC required).
- Maintenance mode on re-run: Repair / Uninstall / Cancel.
- Uninstaller stops the tray, removes the autostart Run key, asks
  (default No) about deleting `%APPDATA%/RB-Controller_fix/`.

### CLI

`rbcf.py` (also bundled in the .exe — `RetroControlMapper.exe <flag>`):

- `rbcf list` / `status` / `diff` / `apply` / `revert` / `validate`
- `rbcf guid status` — alias group inventory
- `rbcf guid fold [--id vid:pid] [--apply]` — manual fold
- `rbcf backup factory` / `snapshot` / `list` / `restore <id>`
- Installer-time flags (used by Inno): `--capture-factory-snapshot`,
  `--set-autostart on|off`, `--set-watcher-mode off|detect|auto-fold`,
  `--set-update-check-consent on|off`

### Known caveats (logged for v0.1.1)

- `backups._read_manifest` is a leading-underscore-private helper that
  is imported by name from `rbcf.py` and `rbcf_gui.py`. Cosmetic; no
  user-visible effect.
- `_scan_bezels()` runs synchronously inside `/api/scan`. Sub-second
  for typical libraries; could mtime-cache in a future revision if
  high-bezel-count installs surface a perf concern.
- `system_lookup` `source` response field uses domain-specific values
  (`'retrobat-wiki'` / `'libretro-docs'` / `'launcher-source'`) instead
  of the spec's generic `'live'`. Frontend handles either; cosmetic.
- The path-override "Try anyway without restart" landing on a stale
  `RETROBAT_ROOT` shows the empty-systems panel as "No systems
  detected" rather than the more useful "server needs restart" copy.

### Internals

- **Watcher daemon** — runs as a thread inside the tray app. Three
  modes: `off`, `detect` (logs alias detections, never modifies),
  `auto-fold` (silent re-fold per locked decision). Default after
  install: `detect`.
- **Frontend / backend split** — single-page vanilla HTML/CSS/JS GUI
  served by a stdlib `http.server` on `localhost:8765`. No frameworks.
  Backend is pure Python 3.14 + PyYAML + Pillow + pystray.
- **Single .exe distribution** via PyInstaller `--onefile`. End users
  do not need Python installed. Bundle size ~35 MB unpacked.
- **252 profile YAMLs** copied from the bundle to
  `%APPDATA%/RB-Controller_fix/profiles/` on first run; subsequent
  reads + writes go through `%APPDATA%`. Reinstalls don't clobber user
  edits.

### Verified test suite

- `py rbcf.py validate` — 252 profiles, no errors
- `py tests/test_guid_aliases.py` — 7 smoke tests pass
- `py tests/test_backups.py` — 6 smoke tests pass
- `py tests/test_guid_watcher.py` — 6 smoke tests pass
- `py rbcf_gui.py --no-tray --no-open` — boots cleanly, all endpoints
  respond
- 14 manual QA areas: 58 pass · 6 caveat (above) · 0 fail

### License

GPL-3.0 (see [LICENSE](LICENSE)).

[v0.1.1]: https://github.com/ITViking-FIN/RetroControlMapper/releases/tag/v0.1.1
[v0.1.0]: https://github.com/ITViking-FIN/RetroControlMapper/blob/main/CHANGELOG.md#v010--2026-05-04
