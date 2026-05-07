# Contributing to RB-Controller_fix

Thanks for considering a contribution! This project is small and
opinionated, so contributions land best when they fit one of the
established lanes:

1. **New controller image** — you own a controller we don't have a photo
   of (or have a better photo of one we do).
2. **New game profile** — you've worked out a button/keystroke mapping
   for a specific game and want to share it.
3. **Bug fix** — something's broken; you can fix it.
4. **New feature** — something not yet shipped that fits the project's
   scope (per `v0.1.3-PLAN.md`, `CLAUDE.md`).

Each lane has a streamlined workflow below. If your contribution doesn't
fit, open a discussion issue first — we'd rather chat about it than have
you spend hours on something we'd ask you to redesign.

---

## Lane 1 — Contributing a controller image

The catalog (`controller_catalog.yaml`) maps USB VID:PID to a controller
name + a Wikimedia Commons file name. When the file is on Wikimedia, the
nightly sync (`controller_sync.py`) fetches it automatically. **When it
isn't** — most 8BitDo, RetroBit, Hori, etc. — we accept community-supplied
images checked directly into `gui/img/known/<VID>_<PID>.{jpg,png}`.

### Quick path (recommended)

```
py rbcf.py submit-controller \
    --vid 2DC8 --pid 310B \
    --image path/to/your/photo.jpg \
    --silhouette
```

What it does:
1. Runs `clean_controller_photo.py` with the chosen mode
   (`--silhouette` for dark-on-light photos, `--remove-bg` for
   uniform backgrounds, default tight-crop otherwise).
2. Saves the output as `gui/img/known/<VID>_<PID>.<ext>`.
3. Updates `controller_catalog.yaml` to add (or update) the entry,
   marked `pc_support: native` and `wiki_file: ""` (community image).
4. Prints next-step instructions (commit, push, open PR).

### Manual path

If you want to do the cleanup yourself:
1. Drop the raw photo in `gui/img/contrib/`.
2. Run `py clean_controller_photo.py <input> --out gui/img/known/<VID>_<PID>.<ext>` with
   whichever mode looks best (try `--silhouette` and `--remove-bg`,
   compare).
3. Edit `controller_catalog.yaml` — add a new entry under `controllers:`
   following the existing format. Set `wiki_file: ""` (we'll only
   sync via Commons if a real Wikimedia file exists).
4. Open a PR using the template under
   `.github/PULL_REQUEST_TEMPLATE/controller-image.md`.

### Image quality bar

- **Top-down view** of the controller, ideally on a clean background.
- At least 600px on the long side (we resize to 800–900px for cache).
- Real photo OR clean product render — both fine. Avoid screenshots
  with watermarks or store overlays.
- Free-license preferred; if it's a manufacturer marketing image,
  note attribution in the PR description.

### Why VID:PID and not just model name?

So the GUI auto-picks the right image when the user plugs in their
controller. Two visually-identical controllers (e.g., 8BitDo Ultimate
v1 vs v2) have different VID:PIDs and benefit from distinct photos.

---

## Lane 2 — Contributing a game profile

(Stub — fully documented in v0.2 when we ship community sharing as a
first-class feature. For now, profile contributions live in your local
`profiles/` and we'll publish a curated `community/` folder in this
repo as part of v0.1.3 Task 6.)

---

## Lane 3 — Bug fixes

1. Open an issue describing the bug + reproducer.
2. Reference the issue in your PR.
3. Add a manual-verification note to your PR — what did you test, on
   which RetroBat / emulator versions.

---

## Lane 4 — New features

Read `CLAUDE.md` and `v0.1.3-PLAN.md` first. If your idea fits an
existing task slot, claim it in an issue and let's chat about scope.

---

## Conventions

- **Vanilla deps only.** Python: stdlib + PyYAML + Pillow. JS: vanilla.
  No frameworks. We're shipping this as a single PyInstaller .exe.
- **No dependencies that don't work on Windows.** This is a Windows tool.
- **Backups before destructive operations.** Anything that touches
  RetroBat's own configs must back up first (see existing `backup`
  CLI).
- **Every PR should leave the project at least as healthy as it found
  it.** If you touch a file that's missing a docstring or tests,
  consider adding them.
- **Schema changes need a migration path.** Profile YAML, catalog YAML,
  manifest JSON — don't break existing user data without a one-shot
  migration.
