# RetroControlMapper installer (Inno Setup)

This directory contains the Inno Setup script that produces the Windows
`RetroControlMapper_0.1.0_setup.exe` installer. The installer wraps the
PyInstaller `--onefile` binary built by Stream PI's `..\build.ps1`.

The script implements the locked specs from `..\DECISIONS.md`:

- **Windows installer (Inno Setup)** — license, install location,
  update-check consent, autostart, factory snapshot, shortcuts.
- **Installer maintenance mode (Repair / Uninstall)** — re-running setup on
  a system with an existing install presents a Maintenance page; the
  uninstaller asks before deleting user data.

## Prerequisites

1. **Inno Setup 6+** — download and install from
   <https://jrsoftware.org/isdl.php>. Ensure `iscc.exe` is on `PATH`
   (the installer typically adds it under
   `C:\Program Files (x86)\Inno Setup 6\`).
2. **The application binary** — `..\dist\RetroControlMapper.exe`, produced
   by Stream PI's `..\build.ps1`. The Inno script will fail at compile
   time if this file is missing.
3. **Application icon (`RetroControlMapper.ico`)** — see step 2 below.

## Build steps

### 1. Build the application binary

```powershell
cd ..
.\build.ps1
```

This produces `..\dist\RetroControlMapper.exe`. Stream PI owns this step.

### 2. Generate the installer icon

Inno Setup's `SetupIconFile` directive expects a `.ico` file (multi-size).
The project ships PNGs only, so produce a `.ico` from the 256×256 PNG.

Using ImageMagick (recommended):

```powershell
magick convert ..\gui\img\icon\RetroControlMapper_256.png `
    -define icon:auto-resize=256,128,64,48,32,16 `
    RetroControlMapper.ico
```

Alternatively, any tool that can produce a multi-resolution `.ico` from
the source PNG works. The `.ico` is git-ignored — regenerate per build.

If you skip this step, comment out the `SetupIconFile=` line in
`RetroControlMapper.iss` and Inno will use its default icon.

### 3. Compile the installer

```powershell
.\build-installer.ps1
```

Or invoke `iscc.exe` directly:

```powershell
iscc.exe RetroControlMapper.iss
```

Output lands at `output\RetroControlMapper_0.1.0_setup.exe`.

### 4. Test (recommended on a clean VM)

- Fresh install: run the setup, verify Tasks page checkboxes flow into
  the post-install hooks correctly, verify Start menu + Desktop
  shortcuts, verify the README opens at the end.
- Maintenance mode: re-run the same setup on the same machine; you
  should see the Repair / Uninstall radio page after the welcome page.
- Uninstall: verify the prompt about deleting `%APPDATA%\RB-Controller_fix\`
  appears and respects Yes / No.

## Required-but-not-yet-implemented CLI flags

The `[Code]` section's `CurStepChanged` procedure invokes the .exe with
several CLI flags that **DO NOT YET EXIST** in the application source.
Stream IS (this stream) cannot wire them; this is the punch-list for the
next stream.

The .exe entrypoint is `rbcf_gui.py`. Each flag should be parsed before
the GUI starts, perform its action, and exit (no GUI window).

| Flag | Semantics | Backing call |
|------|-----------|--------------|
| `--capture-factory-snapshot` | Capture the tier-1 "factory" snapshot of current RetroBat settings (one-shot, refused if already exists). Exit 0 on success or "already exists"; non-zero on hard failure (no `RETROBAT_ROOT` etc). Print one-line status to stdout. | `backups.snapshot('factory', description='Captured by installer wizard')` |
| `--set-autostart on` / `off` | Write or remove `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\RetroControlMapper`. Inno also writes this via `[Registry]`, so this flag's job is mainly to record the application's own internal "autostart enabled" state, so the in-app settings UI reflects the right toggle position. | New helper, e.g. `autostart.set_enabled(bool)` (module to be created), or inline in `rbcf_gui.py`. |
| `--set-watcher-mode off` / `detect` / `auto-fold` | Set the GUID drift watcher mode. Persisted to `%APPDATA%\RB-Controller_fix\guid-watcher-state.json` via the existing `guid_watcher.set_mode()`. Validates against `guid_watcher.VALID_MODES`. | `guid_watcher.set_mode(mode)` (already exists). |
| `--set-update-check-consent on` / `off` | Set the "auto-check for updates on startup" consent flag. The GUI's `update_check.py` and the `/api/update-check` endpoint must read this on first auto-check to decide whether to make the network call. **Note**: `update_check.py` does not currently expose a `_set_consent_via_cli()` helper — it must be added (e.g. write a small `update-consent.json` next to `update-check.json`, read on every `check_for_updates(allow_online=...)` call). | `update_check.set_consent(bool)` (helper to be added). |

### Recommended implementation shape

Add to `rbcf_gui.py` near the top of `main()`, before any GUI / Tk / web
server initialization:

```python
def _handle_installer_cli(argv: list[str]) -> int | None:
    """Return an exit code if argv contains an installer CLI flag,
    otherwise None to fall through to normal GUI startup."""
    if not argv:
        return None
    flag = argv[0]
    if flag == "--capture-factory-snapshot":
        from backups import snapshot
        snap = snapshot("factory", description="Captured by installer wizard")
        return 0  # success or already-exists are both fine
    if flag == "--set-autostart" and len(argv) >= 2:
        from autostart import set_enabled  # NEW MODULE
        set_enabled(argv[1] == "on")
        return 0
    if flag == "--set-watcher-mode" and len(argv) >= 2:
        from guid_watcher import set_mode
        try:
            set_mode(argv[1])
            return 0
        except ValueError:
            return 2
    if flag == "--set-update-check-consent" and len(argv) >= 2:
        from update_check import set_consent  # NEW HELPER
        set_consent(argv[1] == "on")
        return 0
    return None  # not an installer flag → normal startup

# In main():
exit_code = _handle_installer_cli(sys.argv[1:])
if exit_code is not None:
    sys.exit(exit_code)
```

The flags are silently best-effort: each `Exec()` call in the Inno script
runs hidden (`SW_HIDE`) and waits for termination but does not check the
return code. The user-visible failure mode is "the option you ticked
didn't take effect" — which the next .exe launch will surface via the
in-app settings UI.

## File inventory

| File | Purpose |
|------|---------|
| `RetroControlMapper.iss` | Main Inno Setup script. |
| `build-installer.ps1` | Tiny PS wrapper that invokes `iscc.exe`. |
| `README.md` | This file. |
| `.gitignore` | Excludes the build output and the generated `.ico`. |
| `RetroControlMapper.ico` | (Generated, git-ignored) installer icon. |
| `output\` | (Generated, git-ignored) compiled installer .exe lands here. |

## Notes on the AppId UUID

The `AppId` in `RetroControlMapper.iss` is the stable UUID
`{8E3A9F2C-7B41-4D6E-9F58-2C1A0B5D8E47}`. **DO NOT change this between
versions** — Inno uses it as the registry key for the installed
application, and changing it breaks in-place upgrades + maintenance-mode
detection (the new installer wouldn't see the old install).

## Concerns / open questions

- **Per-user vs per-machine install**: `PrivilegesRequired=lowest` with
  `PrivilegesRequiredOverridesAllowed=dialog` lets the user choose at
  install time. The default is per-user (no UAC, install under
  `%LOCALAPPDATA%\Programs\` via `{autopf}`). The autostart Run key is
  written to `HKCU` which is correct for per-user. If the user elevates
  to per-machine, the Run key still goes to `HKCU` of whoever ran setup,
  which is probably what's wanted but worth confirming.
- **`PrivilegesRequiredOverridesAllowed=dialog`** combined with
  `{autopf}` may resolve to `Program Files` (per-machine) or
  `%LOCALAPPDATA%\Programs` (per-user) depending on the user's choice.
  If you want to force per-user, drop the `Overrides` line.
- **Repair branch UX**: Inno's default behavior in Repair is to re-run
  through every wizard page including Tasks. This may surprise users
  who expect Repair to be one-click. A future enhancement: in
  `ShouldSkipPage`, skip wpSelectTasks when in maintenance Repair mode
  to make Repair non-interactive.
