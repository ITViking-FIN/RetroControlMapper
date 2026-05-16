# Contributing to RB-Controller_fix

Thanks for considering a contribution! This project is small and
opinionated, so contributions land best when they fit one of the
established lanes:

1. **New controller image** — you own a controller we don't have a photo
   of (or have a better photo of one we do).
2. **New game bindings** — you've worked out a button/keystroke mapping
   for a game and want to share it back. v0.1.5 ships an in-app
   submission flow (see Lane 2 below).
3. **Bug fix** — something's broken; you can fix it.
4. **New feature** — something not yet shipped that fits the project's
   scope. Open a discussion issue first — most feature work is
   prioritised against an internal roadmap.

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

## Lane 2 — Contributing game bindings

v0.1.5 ships an in-app submission flow. The fastest path:

1. Open the game in the GUI (system + ROM selectors).
2. Click the **💡 Suggestions** icon in the top-right toolbar.
3. Apply the existing suggestions if any look right; tweak in the
   mapping grid; drop the manual PDF if you have it for more
   coverage.
4. Tick **"Submit my approved bindings to the community DB on Save
   Profile"** in the Suggestions popover footer.
5. Hit **Save Profile**. The app opens a pre-filled GitHub Issue in
   your browser with title, labels (`community-binding`,
   `bindings-submission`), and the binding JSON in the body.
6. Review the Issue body, edit if you want to add context (manual
   source link, why a binding choice was made, etc.), then **Submit
   new issue**.

The maintainer triages submissions and folds accepted bindings into
the next release's bundled DB. **No accounts, no OAuth, no upload-
on-your-behalf** — every submission is a conscious click in your
browser.

### Submission JSON format + field stability

Full schema, validation rules, and which fields are *contract* (we
won't rename) vs *internal* (we may restructure) are documented in
[`docs/COMMUNITY_BINDINGS.md`](docs/COMMUNITY_BINDINGS.md).

### CLI alternative

If you don't want to use the GUI, run the extractor directly:

```
py manual_user_contribution.py path/to/manual.pdf <system_id> <rom_name> --save --submit
```

This produces the same submission record as the GUI flow; copy the
`bindings:` block from the queue file under
`%APPDATA%\RB-Controller_fix\data\bindings_user_submission_queue\`
into a GitHub Issue manually.

### What's coming in v0.1.6

A proper OAuth-backed PR flow against a dedicated companion repo
(`RetroControlMapper-community-bindings`). Auto-merge after CI
validation. Live DB updates without reinstall. The v0.1.5 Issue-
based flow continues working as a fallback for users who prefer
not to authenticate.

---

## Lane 3 — Bug fixes

1. Open an issue describing the bug + reproducer.
2. Reference the issue in your PR.
3. Add a manual-verification note to your PR — what did you test, on
   which RetroBat / emulator versions.

---

## Lane 4 — New features

Open a discussion issue first describing what you want to build and
why. Most feature work is prioritised against an internal roadmap and
some "obvious" features are intentionally deferred for compatibility
or scope reasons — better to chat before you invest hours.

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
