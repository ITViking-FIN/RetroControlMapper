# Building RetroControlMapper.exe

Single-binary Windows build, produced by PyInstaller `--onefile`. This
is the artefact Stream IS's installer wraps in the Inno Setup wizard.

## Prerequisites

- **Python 3.14** on Windows 10 / 11 (the `py` launcher must work)
- All runtime deps installed: `py -m pip install -r requirements.txt`
- **Optional**: [UPX](https://upx.github.io/) on `PATH` — shrinks the
  final .exe by ~30%. PyInstaller silently skips UPX if it's missing,
  so this is fully optional.

PyInstaller itself is installed/upgraded by `build.ps1` on every run, so
you don't need to manage it manually.

## Build

```powershell
cd D:\RB-Controller_fix
.\build.ps1
```

This produces `dist\RetroControlMapper.exe` — typically 25–40 MB
without UPX, 18–28 MB with UPX. Build time is ~30s on a warm cache.

## Test

Double-click the .exe (or run it from a terminal). Expected behaviour:

1. The tray icon (the RetroControlMapper diamond) appears in the
   system tray.
2. The default browser opens to `http://localhost:8765/`.
3. The GUI loads with the device list populated.
4. Right-clicking the tray icon shows the context menu (Show, GUID
   watcher mode, Quit).

If the .exe launches but the tray icon never appears, see
*Troubleshooting* below.

## Bundle layout (what's inside the .exe)

PyInstaller `--onefile` packs everything into one binary. At runtime,
the .exe unpacks to a per-process temp dir at
`%LOCALAPPDATA%/Temp/_MEIxxxxxx/`. This dir is read by `sys._MEIPASS`.
The bundle includes:

- `gui/` (HTML, CSS, JS, images, icons) — served by the local HTTP server
- `controller_catalog.yaml`
- `LICENSE`, `README.md`, `INSTRUCTIONS.md`
- `profiles/` — the **factory seed library** (read-only)

User-writable data lives **outside** the .exe, under
`%APPDATA%/RB-Controller_fix/`:

- `profiles/` — the editable user copy
- `sync_manifest.json`
- `controller_sync.log`
- `rbcfrc` — RetroBat root override (see `config.py`)
- `backups/` — daily snapshot archive

## First-run profile-seed handoff (IMPORTANT)

The bundled `profiles/` tree at `sys._MEIPASS/profiles` is **read-only**
(it lives inside the .exe and the unpack dir gets deleted on exit).
The runtime app reads + writes from `%APPDATA%/.../profiles/` instead.

Bridging the two is the **installer's** job, not this build's:

- **Stream IS installer** (Inno Setup) extracts the .exe's bundled
  `profiles/` to `%APPDATA%/RB-Controller_fix/profiles/` at install
  time, only if that directory does not already exist.
- This means the .exe alone, without the installer, will start with
  no editable profiles — that's expected and tracked. Running the
  raw .exe is a developer flow; end users always get the installer.

Future work (post-v0.1.0): teach `rbcf_gui.py` startup to detect
`sys.frozen` and fall back to copying the bundled tree itself, so the
.exe is usable standalone. Tracked in DECISIONS.md.

## Bumping the version

1. Edit `__version__` in `config.py` (e.g. `"0.1.0"` → `"0.1.1"`).
2. Re-run `.\build.ps1`.
3. Tag the git commit and push — `update_check.py` polls GitHub
   releases at `GITHUB_OWNER/GITHUB_REPO` (also defined in `config.py`).

There is no separate version file in the .spec — the .exe doesn't
carry a Windows VERSIONINFO resource yet (that's deferred to v0.1.1
via `version_file=` in the spec).

## Troubleshooting

### The .exe launches but no tray icon appears

Open a terminal and run the .exe — if pystray's win32 backend isn't
bundled, you'll see an `ImportError: pystray._win32` in stderr. The
fix is in `rbcf.spec`'s `hiddenimports` (`pystray._win32` is already
listed there). If the error mentions `PIL.ImageDraw` or
`PIL.ImageFont`, those are also already in `hiddenimports` — verify
they didn't get removed.

### "Failed to load Python DLL" on launch

Stale unpack dir from a previous build. Delete
`%LOCALAPPDATA%/Temp/_MEIxxxxxx*` and try again.

### The bundled `gui/` is missing at runtime

The path resolution in `rbcf_gui.py` needs to use `sys._MEIPASS` when
frozen. If the GUI 404s on assets, this is the bug — file an issue
referencing this section and the `BASE_DIR` definition in
`rbcf_gui.py`.

### Build fails: "no files matched glob 'gui/img/contrib/*'"

PyInstaller errors when a glob matches zero files. If `contrib/` got
emptied (e.g. someone moved the 8BitDo reference images out of source
control), remove that line from `rbcf.spec` — or add a
`.gitkeep`-style placeholder so the glob always matches something.

### The .exe is huge (>100 MB)

Numpy / scipy / matplotlib likely got pulled in transitively. They're
in the `excludes=` list of the spec — verify nothing new in
`requirements.txt` imports them. Run
`py -m PyInstaller --clean rbcf.spec --log-level=DEBUG` and grep the
build log for `numpy`.
