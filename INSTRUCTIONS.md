# RetroControlMapper — Instruction Manual

Welcome. This is the long-form manual. If you just want to get started in three minutes, the [README](README.md) covers that. This document walks you through everything.

<!-- screenshot: gui/img/icon/RetroControlMapper_512.png -->

---

## Table of contents

1. [Getting started](#getting-started)
2. [The main UI](#the-main-ui)
3. [Suggestions, PDF drop, and community submit](#suggestions-pdf-drop-and-community-submit)
4. [Controller management](#controller-management)
5. [Per-game vs. per-system profiles](#per-game-vs-per-system-profiles)
6. [The Save → Apply flow](#the-save--apply-flow)
7. [Backups](#backups)
8. [The GUID drift fix](#the-guid-drift-fix)
9. [Bezel viewport calibration](#bezel-viewport-calibration)
10. [Light / Dark / Auto theme](#light--dark--auto-theme)
11. [Network features (privacy)](#network-features-privacy)
12. [Settings cog reference](#settings-cog-reference)
13. [CLI reference](#cli-reference)
14. [Files we touch](#files-we-touch)
15. [Files we never touch](#files-we-never-touch)
16. [Troubleshooting](#troubleshooting)
17. [FAQ](#faq)
18. [Reporting bugs](#reporting-bugs)

---

## Getting started

### Install

1. Grab `RetroControlMapper_0.1.5_setup.exe` from the [latest release](https://github.com/ITViking-FIN/RetroControlMapper/releases/latest).
2. Run the installer. You'll be asked two things:
   - **"Back up current RetroBat settings?"** — leave this on. It captures a permanent, never-overwritten "factory" snapshot you can fall back to no matter what happens later.
   - **"Run RetroControlMapper at Windows startup?"** — recommended if you want the GUID drift watcher (see below) to fix controller mappings automatically the moment they break. You can change this later from the Settings cog.
3. Click through. The installer drops a Start menu shortcut and (optionally) a desktop icon.

### First run — the onboarding wizard

The first time you launch the app, you'll see a tray icon appear (gamepad-shaped). The configuration UI opens in your browser at `http://localhost:8765/`. The wizard runs once:

1. **RetroBat detection.** The app probes the registry, common install paths (`C:\RetroBat`, `D:\RetroBat`, `E:\RetroBat`, `%USERPROFILE%\RetroBat`, `%APPDATA%\RetroBat`), and any user-supplied override. The first match wins. If we couldn't find it, you'll get a path picker — paste in or browse to the install root.
2. **Summary card.** You'll see a summary like:

   > Found RetroBat at `D:\RetroBat`. 4 systems supported. 47 ROMs found across them. 12 already have profiles, 35 don't.

3. **Scaffold the missing profiles.** Click the big primary button: "Scaffold 35 missing with system defaults". This creates a placeholder profile for every uncovered ROM, copying the system's `_default.yaml` as a starting point. Each scaffold is marked **T** (template) so you remember it hasn't been verified yet.
4. **Bezel cutoff fix.** If we found bezels whose default transparency margins would crop the game image, the wizard offers to rewrite the `.info` sidecars with stricter margins. One click, no fuss.
5. **Apply now or later.** "Apply now" jumps you straight into the preview-and-confirm flow described in [The Save → Apply flow](#the-save--apply-flow). "Apply later" closes the wizard and lands you on the main UI.

You can re-run onboarding any time from the Settings cog → Re-run onboarding.

---

## The main UI

The default view is **sleek by design** — header + source/target controllers side-by-side, and a footer. Everything else (mapping table, overrides, notes, settings, manual-extracted suggestions) lives behind a card-styled icon toolbar in the top-right. Each popover has an "Always keep ___ visible" toggle that pins the panel inline below the controllers if you prefer to see it permanently.

### Header

- **Pad pills** (top-left). One per detected controller. The active pill has a green dot. Click any pill to make it the active source. Click the chevron next to the pills to expand the controller management drawer.
- **Five-icon toolbar** (top-right, card-styled). Left-to-right in workflow order:
  - **💡 Suggestions** — manual-extracted bindings for the loaded game (new in v0.1.5; see the dedicated section below). Count badge shows how many bindings are on offer for the active game.
  - **⌨ Mappings** — pad-button-to-keyboard-key mapping grid (`RETROK_*` codes). Count badge shows how many keys you've bound.
  - **🎚 Overrides** — per-game advanced settings (keyboard pass-through, focus capture, joy-port). Count badge shows how many overrides are set.
  - **📄 Notes** — free-text notes saved into the profile YAML.
  - **⚙ Settings** — global app settings.
- **System and game selectors.** Inside the target pane, below the header. System dropdown lists every system your RetroBat install knows about. Game dropdown lists ROMs from `roms/<system>/`. Profiles you already have are marked.
- **Apply / Save / Test buttons.** At the bottom of the target pane. Apply pushes saved profiles to RetroBat (preview by default — see below). Test launches the current ROM in RetroBat using the saved bindings. Save Profile writes the YAML.
- **Update badge** (occasionally). Appears next to the ⚙ cog if a newer version is available. Click for release notes and the download link. Only appears if you've enabled update checks.
- **Pin toggles.** Each icon's popover has an "Always keep ___ visible" checkbox in its footer. Tick it → the panel renders inline below the controllers, with a small unpin × on its header to fold it back into the icon-bar. Pin state persists across sessions via `localStorage`.

### Source pane (left)

A high-fidelity diagram of your physical controller. As you press buttons, the corresponding shapes light up — useful for sanity-checking a flaky button before you start mapping. The diagram updates in real time at ~60Hz from the browser's Gamepad API.

If we have an image catalogued for your controller's VID:PID, it shows here. Otherwise you'll see a generic XInput/HID placeholder. You can supply your own — see [Adding controller images](#adding-controller-images).

### Target pane (right)

The system + game selectors live at the top. Below them, the target system's controller diagram. **Three rendering tiers**, used in order:

1. **Curated SVG art** — for the 11 most-supported systems we've drawn proper schematics: CD32 pad, Competition Pro 1-button joystick, ColecoVision pad, etc.
2. **Generic-from-descriptor** — for ~15 popular systems we have a *shape* descriptor (face buttons / d-pad / sticks / shoulders / system buttons), the GUI auto-generates a clean schematic. Examples: NES (2-button row), SNES (4-button diamond), Genesis 6-button (2×3 grid), PSX (DualShock with △○✕□), N64 (single stick + 3 face + 4 shoulders), Saturn 6-button, etc.
3. **Generic default fallback** — for any other system in your library (the long tail beyond curated + descriptor), a sensible 1-stick + d-pad + 4 buttons + L/R + Start/Select schema is shown. **Better than blank.** You can still bind via click-across — see below.

The buttons light up in sync with your physical pad, mapped through the active profile — so you can see what a press on your gamepad's "B" actually translates to on the target.

At the bottom, three action buttons:

- **Test** — launches the currently selected ROM in RetroBat (using your saved bindings) so you can verify the mapping live, then come back and tweak. Faster feedback loop than save → apply → manually open RetroBat → manually pick the game.
- **Apply** — pushes saved profiles into RetroBat's config files. Preview by default.
- **Save Profile** — writes the YAML profile under `profiles/<system>/<rom>.yaml`. With "One-Click Save & Apply" on (settings cog), this also runs Apply automatically.

### Mappings popover (⌨)

For buttons the libretro core doesn't already handle (e.g. C64 keyboard keys mapped to a pad face button, MAME service buttons, Amiga F-key shortcuts), click the ⌨ icon to open the mapping grid. The values are RetroArch keystroke codes like `RETROK_F1`, `RETROK_SPACE`, `RETROK_RETURN`. Rows with a bound value get a green-tinted input field so you can scan which buttons are mapped at a glance. A green tip banner at the top reminds you these mappings apply *per system* (via libretro core options), not per game — dismissible.

**Three ways to fill a binding** (any of these works — pick whichever fits):

1. **Press-to-bind keystroke (easiest).** Each row has a small 🎯 listen icon at the right edge. Click it → the row enters a violet pulsing state ("press a key…") → tap the keyboard key you want bound → the field auto-fills with the right `RETROK_*` constant. Escape cancels. Works for letters, digits, F-keys, space, return, tab, arrows, shift/ctrl/alt, all common punctuation. Layout-independent (uses `event.code` not `event.key`).
2. **Click-across (advanced — see below).** Press a physical button on your gamepad → it arms with a violet pulse on the source SVG → click any target button on the right → a per-game RetroArch input remap is written. Only enabled for systems where RetroBat's default mapping is unreliable; the curated set keeps its verified defaults.
3. **Manual typing.** Type `RETROK_F1` etc. directly. Tab moves to the next row.

Live highlight feedback runs at 60Hz: pressing a button on your gamepad lights it up on both the source SVG (left) and — if there's a default route — the target SVG (right). Stick movement translates the analog knob.

### Profile templates

When you start a new profile or switch to a system that has curated templates, a **From template…** button appears next to the Game dropdown. Click it to see the available templates for the current system, each with a description:

- **Menu-heavy C64** — F1/F3/F5/F7 mapped to face buttons (Boulder Dash etc.).
- **Joystick + 1 fire (C64)** — pure 1-button arcade ports.
- **C64 — Joystick on Port 1** — for the rare titles that read CIA-shared port 1.
- **C64 — Keyboard adventure** — GameFocus + physical-keyboard pass-through ON (Last Ninja, Maniac Mansion).
- **Amiga CD32 — CD32 Pad (default)** — system default with all 7 buttons distinct.
- **Amiga CD32 — Mouse-driven** — Cannon Fodder / Lemmings / Beneath a Steel Sky.
- **Amiga 500 — 1-button / CD32-Pad on Amiga / Mouse-driven** — three patterns covering most Amiga 500 games.

Selecting a template **populates the form** with its values; you can then edit any field before saving. Existing values are replaced, so don't pick a template after you've filled in a custom mapping unless you want to start over.

### Click-across binding (advanced)

For systems where RetroBat's default RetroPad → core mapping is unreliable (most of the long tail beyond the 25-or-so curated systems), you can directly assign which physical button does which target action.

**The flow:**
1. Pick the system + game.
2. **Press a physical button** on your gamepad — or click any button on the source SVG. It pulses violet ("ARMED").
3. **Click any button on the target SVG** on the right. A toast confirms the binding (e.g. `Bound A → 1`).
4. The target button gets a persistent violet outline (`has-binding` badge) so you can see what's already wired.

**What's actually written:** a per-game RetroArch input remap at
`emulators/retroarch/config/remaps/<core display name>/<rom>.rmp`
with lines like `input_remap_id_1_btn_a = 0` (meaning: physical A button now produces what RetroPad B normally produces).

**Cancel mid-bind:** press Escape, click outside the source/target panes, or click the same physical button again to disarm.

**Reliable systems (CD32, SNES, Saturn, NeoGeo, etc.) keep their default mapping.** Click-across is intentionally OFF there — the verified default is plug-and-play. A "Customize" affordance for explicit overrides is planned for a future release.

### Overrides popover (🎚)

Settings that survive RetroBat's launch-time config regeneration. Click the 🎚 icon to open:

- **Joystick port assignment** — which port (1–4) this game uses by default. Important for C64 where some games expect joystick on port 2.
- **Game Focus mode** — capture keyboard input for this game so global hotkeys don't interfere.
- **Keyboard pass-through** — for systems where the keyboard is part of the experience (Amiga, Atari ST, ZX Spectrum, C64).
- **Analog mouse** — Amiga / Atari ST games that originally used a mouse.

These are written as per-game keys in `es_settings.cfg` and survive the launcher's regeneration step. The count badge on the 🎚 icon shows how many overrides are active for the loaded game.

### Notes popover (📄)

Free-text notes about a game's controls. Saved into the profile YAML under `notes:`. Click the 📄 icon to open the editor.

---

## Suggestions, PDF drop, and community submit

v0.1.5 ships a bundled bindings database (62 systems, **9,804 mappings** across **4,143 games**) extracted from game-manual PDFs by a hybrid pipeline (heuristic regex passes + local Qwen 2.5 LLM over LAN). Most popular titles now open with suggested mappings pre-populated — no more configuring from scratch.

### Reviewing suggestions (💡)

When you pick a system + game in the target pane, the app auto-fetches matching bindings from the bundled DB. The **💡 Suggestions** icon's count badge shows how many are on offer. Click it to open the popover:

Each suggestion shows:
- **Pad button** (e.g. `A`, `dpad_up`) — what the manual says.
- **Action** — what that button does (e.g. `RETROK_RETURN`, `"Light Punch"`).
- **Confidence chip** — `high` / `medium` / `low` based on extraction certainty.
- **Source chip** — colour-coded by extractor:
  - 🟣 `bundled` — from a manual-extracted source baked into the installer.
  - 🟡 `arcade` — from the community `controls.dat` (MAME / FBNeo / Neo-Geo etc.).
  - 🟣 `llm` — extracted by the local Qwen 2.5 LLM pass.
  - 🔵 `regex` — extracted by a pattern-matching pass.
  - 🟢 `user_pdf` — you just dropped a PDF and this came from it.

Three actions per row:
- **Apply** — pushes the binding into the mapping grid for this game.
- **Reject** — hides this suggestion (doesn't affect the bundled DB).
- The header has **Apply all** to push every visible suggestion at once.

Suggestions persist in `data/bindings_user/<system>.json` once you apply + save, so the next time you load this game your applied bindings come back automatically.

### Drop a PDF for an unknown game

If the suggestions list is empty and you have the game's manual, drag the PDF onto the drop-zone at the bottom of the Suggestions popover (or click "Choose file…").

- **No OCR on your machine.** The dev box pre-OCR'd the bundled DB; your local installation runs only `pypdf` text extraction. Scanned (image-only) PDFs surface a friendly warning explaining we can't auto-extract from them locally — you can still map the controls manually.
- **Native-text PDFs** (most modern manuals, web archive re-typesets, homebrew docs) produce useful suggestions you can review and apply just like bundled ones, with a green `user_pdf` source chip.
- **Size cap:** 50 MiB — manuals over that are rare and the parser chokes anyway.

### Submitting back to the community (MVP)

The Suggestions popover footer has a toggle: **"Submit my approved bindings to the community DB on Save Profile"**. Tick it, then hit Save Profile:

1. Your profile saves locally normally.
2. The app builds a pre-filled **GitHub Issue** with title, labels (`community-binding`, `bindings-submission`), and the binding JSON in the body.
3. Your default browser opens to the GitHub Issue compose page. Review, edit if you want, then submit when ready.
4. The project maintainer triages submissions and folds accepted bindings into the next release's bundled DB.

**No accounts, no OAuth, no upload-on-your-behalf in v0.1.5.** Every submission is a conscious click in your browser. A full OAuth-backed PR flow against a dedicated companion repo lands in v0.1.6.

Schema, field stability guarantees, and the per-system file format are documented in [`docs/COMMUNITY_BINDINGS.md`](docs/COMMUNITY_BINDINGS.md).

**Where the local data lives:**
- Approved bindings → `%APPDATA%\RB-Controller_fix\data\bindings_user\<system>.json` (frozen builds) or `data/bindings_user/<system>.json` (dev runs).
- Submission queue (your local record of what you've submitted) → `%APPDATA%\RB-Controller_fix\data\bindings_user_submission_queue\<timestamp>_<sys>_<rom>.json`.

---

## Controller management

### Pad pills

Each detected gamepad gets a pill in the header. Click to make active. The drawer (chevron) shows full info: friendly name, VID:PID, driver type (XInput / DInput / HID), and the Windows InstanceId.

### Identifying duplicate controllers

If you have two physically identical pads (e.g. two 8BitDo Ultimates), they may report the same VID:PID and the same name to the browser. The Identify flow sorts them out:

1. Click the **Identify…** button on a card.
2. The card switches to "listening" mode. Press any button on the controller you want to label.
3. The card flashes blue and captures the press. You can now type a label like "Player 1 white" or "Player 2 black".

Labels persist locally in your browser's storage, keyed by the Windows InstanceId so they survive reboots.

### Active vs. inactive

The pill with the green dot is the active source — its presses drive the live highlights in both panes. Other pads are still detected, just not bound to the visualisation right now.

### Adding controller images

Your physical pad image is fetched from `gui/img/known/<VID>_<PID>.<ext>`. If we don't have one for your hardware:

1. **Settings cog → Controller images → Manage…**
2. Click **Upload**, pick a PNG or JPG (transparent PNG strongly preferred), and confirm the VID:PID.
3. The image is stored under `gui/img/contrib/`. Reload the page; your card now shows the new image.

The nightly catalog sync also checks Wikimedia Commons for canonical product photos, so for popular controllers you may not need to do this yourself.

### Rescan

If a controller doesn't show up after you plug it in, click **Rescan** at the bottom of the drawer. We re-probe via Windows PnP and redraw the cards.

---

## Per-game vs. per-system profiles

RetroControlMapper organises profiles by system, with two tiers:

### System defaults (`_default.yaml`)

One per system. Lives at `profiles/<system>/_default.yaml`. Applies to every game on that system that doesn't have its own profile. Edit this once per system, get sensible behaviour for everything.

### Per-game overrides (`<rom>.yaml`)

For the one game that needs special treatment. Lives at `profiles/<system>/<rom>.yaml`. Only the keys that *differ* from the system default need to be set here — everything else inherits.

### Inheritance overlay toggle

In the game-detail view, click **Show inheritance** to highlight which fields are inherited from the system default vs. explicitly overridden. Inherited fields show a small grey "= default" tag; overrides show a violet "override" tag. The toggle is sticky — once you turn it on for a system, it stays on until you turn it off.

### Confidence levels (V / K / T)

Every profile carries a confidence pill in the game-detail header:

- **V (Verified)** — green. You've actually run the game with this profile and confirmed it works in your setup.
- **K (Known-good)** — yellow. The bindings are from a trusted source (forum thread, well-known ROM pack, prior install) but you haven't tested them yourself yet.
- **T (Scaffold)** — grey. Placeholder, copied from the system default. Fill in the per-game tweaks when you get a chance.

Click the pill to change the confidence. Marking T → V asks for a quick "are you sure?" so you don't bump it accidentally.

---

## The Save → Apply flow

There are two flavours, and you can switch between them in Settings.

### Default: two-step (preview before write)

1. Click **Save Profile**. This writes the YAML to disk. Fast, no preview — this only changes our local profile, not RetroBat.
2. Click **Apply**. We compute a diff against the current RetroBat config and show you a preview modal:

   > Preview: 2 files would change · 7 lines added · 1 line modified
   >
   > **es_settings.cfg**
   > `+ c64["Boulder Dash.crt"].vice_joyport=2`
   > `+ c64["Boulder Dash.crt"].GameFocus=1`
   > …

3. You click **Apply for real** (or Cancel). Backups are created automatically. The success modal lists every file written and where the backups landed.

### Power-user: One-Click Save & Apply

Settings cog → check **One-Click Save & Apply**. Now Save also applies immediately, no preview. Use this once you're confident in your workflow.

The default is the safer two-step shape. The one-click variant is a deliberate opt-in.

### Apply receipts

After every successful apply, the success modal shows:

- Every file that was written.
- Every backup file that was created (suffix `.bak.rbcf.YYYYMMDD`).
- A **Open RetroBat** button so you can fire it up immediately to test.

If something fails partway (e.g. permissions error because RetroBat is currently running and has a file open), you'll get a partial-failure modal — green checks on what worked, red X on what didn't, and a "Restore from backup" button next to each failure.

---

## Backups

Two tiers. The pre-install snapshot is your nuclear undo; the working snapshots are your everyday safety net.

### Tier 1 — Pre-install (factory) snapshot

- Captured **once**, during install, only if you ticked "Back up current RetroBat settings".
- Stored permanently under `%APPDATA%\RB-Controller_fix\factory\`.
- **Never overwritten.** This is the "nothing else worked, give me my pre-RetroControlMapper RetroBat back" revert.
- Surfaces as the last entry in the snapshot picker, always.

If you skipped this during install, you can capture one at any time from the CLI: `rbcf backup factory`.

### Tier 2 — Working snapshots

- Auto-captured **before every Apply** writes anything.
- Stored under `%APPDATA%\RB-Controller_fix\snapshots\<timestamp>\`.
- Capped at **30 entries**, oldest pruned as new ones arrive.
- Each snapshot has a description (e.g. "Apply: c64/Boulder Dash.crt + 4 others") for context.

### Listing snapshots

```
rbcf backup list
```

Shows a table:

```
ID                 Type      Description                          When
factory            tier-1    Pre-install snapshot                 2026-04-12 09:14
20260503-184022    tier-2    Apply: 35 scaffolded c64 profiles    2026-05-03 18:40
20260503-091205    tier-2    Apply: c64/Boulder Dash.crt          2026-05-03 09:12
…
```

### Restoring a snapshot

```
rbcf backup restore 20260503-184022
```

By default this is a **dry run** — it shows you what would be restored without writing anything. Add `--apply` to actually do it:

```
rbcf backup restore 20260503-184022 --apply
```

The restore itself **takes a snapshot of CURRENT state first**, so even restoring a backup is reversible.

You can also restore from the GUI: Settings cog → Backups → pick a snapshot from the list → Restore.

---

## The GUID drift fix

This is the headline feature. Read this section if you've ever had RetroBat ask you to re-configure your controller for no apparent reason.

### Why your controllers "forget" their settings

RetroBat's EmulationStation keys controller mappings on the **SDL GUID** — a 128-bit hash that includes (among other things) the controller's bus type, name, firmware version, and driver. Every one of those things can change without you doing anything physical to the hardware:

- USB ↔ Bluetooth swap → bus byte changes → fresh GUID.
- USB port hop on certain hubs → version field perturbs → fresh GUID.
- 8BitDo dongle re-pairs after a firmware blip → name string changes → fresh GUID.
- Steam Input or DS4Windows starts hooking the device → driver byte flips → fresh GUID.
- Manufacturer driver update via Windows Update rewrites the HID strings → fresh GUID.

EmulationStation sees the "new" GUID, doesn't recognise it, and dumps you into the input-configure wizard. Your old mapping isn't gone — it's still in `es_input.cfg` under the old GUID — but ES has no way to know they're the same controller.

### How the alias-fold works

We maintain an **alias group** for each physical controller, keyed on `(VID, PID, instance path)`. When you fold an alias group:

1. We parse `es_input.cfg` and pull every `<inputConfig>` block ever recorded.
2. We group them by VID:PID. Each group is a candidate set of aliases for one physical pad (or a small handful, in the dual-identical-pads case).
3. For each alias GUID in the group, we ensure there's an `<inputConfig>` block with the canonical button mapping. Existing blocks are updated in place (preserving their cosmetic device name); missing blocks are synthesised.
4. The result: regardless of which transport / driver permutation Windows hands ES this time, ES finds a matching GUID block and skips the wizard.

You can fold from the GUI (Advanced drawer → GUID drift → Fold) or from the CLI:

```
rbcf guid status         (list alias groups)
rbcf guid fold           (preview)
rbcf guid fold --apply   (write)
```

### The watcher

Folding once is great, but a fresh alias can appear at any time — the moment you un-dock an 8BitDo and pair it over Bluetooth, you've got a new GUID that wasn't in the fold.

The **watcher** handles this. It runs as part of the tray app:

- Polls `es_input.cfg` for changes (no extra background process — it lives in the same binary as the tray icon).
- On change, re-runs the fold pass automatically.
- Backs off for a few seconds after firing to avoid feedback loops with itself.
- Idempotent: if there's nothing new, it does nothing.

To enable: Settings cog → toggle **GUID watcher (auto-fold)**.

To use the watcher, you'll want to also enable "Run RetroControlMapper at Windows startup" so the watcher is alive when ES launches.

### Dual identical-pad case

If you have two physically different pads with the same VID:PID (e.g. two 8BitDo Ultimates), naive grouping would fold them into each other — worse than no fix. We disambiguate via the Windows HID InstanceId, which is unique per physical port-instance even for identical pads. If the disambiguation is ambiguous, the GUI surfaces a "We see two pads with the same VID:PID — confirm which alias set belongs to which" prompt before doing anything.

---

## Bezel viewport calibration

### Why bezels sometimes crop games

RetroBat ships with bezels (decorative borders around the game image — TV cabinets, arcade marquees, etc.) for a lot of systems. The launcher figures out where the "play area" should go inside the bezel by scanning the bezel PNG for transparent pixels: anything more transparent than alpha 235 (out of 255) is considered playable area.

That threshold is too generous. Many bezels have a soft anti-aliased edge that's, say, alpha 220 — RetroBat treats that as still inside the bezel, shrinks the play area accordingly, and parts of the game get cropped behind the artwork.

### The alpha-≤32 fix

We use a much stricter threshold (alpha ≤ 32) when computing the play area, then write the result to a `.info` sidecar next to the bezel PNG. RetroBat respects the explicit `.info`, so it skips its own auto-detect and uses our stricter margins.

### One-click fix in onboarding

The first-run wizard scans every bezel in your install and counts the ones whose RetroBat-default detection would crop the game. If it finds any:

> We found 12 bezels with auto-detect cutoffs. Fix them?

Click **Fix all**. We write the corrected `.info` sidecars; the original PNGs are untouched. You can re-run the scan from Settings cog → Bezels → Scan now.

---

## Light / Dark / Auto theme

Settings cog → Theme. Three states:

- **Light** — frosted-acrylic light theme. Translucent layered panels over an off-white background, candy-coloured accent pills, single-light-source shadows.
- **Dark** — same architecture, dark surfaces.
- **Auto** — follows your OS's `prefers-color-scheme`. Default.

Persisted in your browser's local storage as `rbcf-theme`. Survives reloads but not browser switches.

---

## Network features (privacy)

We make outbound network requests in **two** circumstances. Both are explicitly user-triggered.

### Update check

- **What it does.** Compares the local `__version__` (currently `0.1.5.2`) against the latest release tag of `ITViking-FIN/RetroControlMapper` on GitHub.
- **When it runs.** Only after you click **Check now** in Settings cog → Updates, OR if you've enabled "Auto-check at startup" (default off).
- **Caching.** Result cached for 24h (errors cached for 1h). Stored at `%APPDATA%\RB-Controller_fix\update-check.json`.
- **Source.** Public GitHub releases API only. No auth, no cookies.
- **What we send.** Just an HTTP GET to `https://api.github.com/repos/ITViking-FIN/RetroControlMapper/releases/latest`. No identifying info beyond a standard User-Agent.

### System lookup

- **What it does.** For systems not in our curated bindings list, fetches public reference info (RetroBat wiki, libretro core docs, launcher source) to bootstrap a starting profile.
- **When it runs.** Only when you click the **Search online** button on a system that has no curated diagram. **Asks every time.** Consent is **not** cached — you'll see the prompt on each lookup.
- **Caching.** Once fetched, the result is cached locally so re-opening that system doesn't re-query. Clear from Settings cog → Network → Clear lookup cache.
- **What we send.** Plain HTTP GETs to public documentation URLs. No identifying info.

That's it. Everything else (controller probes, profile reads/writes, configuration apply) is fully local.

---

## Settings cog reference

The settings cog (top-right of the header) opens a popover with these rows:

| Row | What it does | Persisted to |
|-----|--------------|--------------|
| Theme | Light / Dark / Auto | `localStorage['rbcf-theme']` |
| **Accent colour** | Override the theme's primary accent (any colour). Resets to theme default via the Reset button. | `localStorage['rbcf-user-accent']` |
| RetroBat install path | Override the auto-detected install location | `%APPDATA%\RB-Controller_fix\rbcfrc` |
| Re-run onboarding | Reopens the first-run wizard | `localStorage['rbcf-onboarded']` |
| One-Click Save & Apply | Skip preview, apply immediately on save | `localStorage['rbcf-one-click']` |
| GUID watcher (auto-fold) | Background watcher re-folds alias groups when new aliases appear | server-side config |
| Run at Windows startup | Adds/removes the `Run` registry key | Windows registry (HKCU) |
| Auto-check for updates | Run an update check at startup | `localStorage['rbcf-update-autocheck']` |
| Check now | Manual update check | — |
| Bezel scan | Scan + offer to fix bezel cutoffs | — |
| Controller images → Manage | Upload custom controller artwork | `gui/img/contrib/` |
| Inheritance overlay default | Show inheritance tags by default in game-detail | `localStorage['rbcf-show-inheritance']` |
| Clear local UI state | Wipes all `rbcf-*` localStorage keys | — |
| Open profiles folder | Opens `profiles/` in Explorer | — |
| Open backups folder | Opens `%APPDATA%\RB-Controller_fix\` in Explorer | — |
| Sync log | Tail the controller catalog sync log | — |
| About | Version, license, credits | — |

---

## CLI reference

For power users who prefer the terminal. All commands live behind the `rbcf` (and `rbcf_gui`) entry points:

### Profile commands

```
rbcf list                Show every profile in profiles/.
rbcf status              Compare profiles against current RetroBat config.
rbcf diff                Preview what `apply` would change.
rbcf apply               Push every saved profile to RetroBat (with backups).
rbcf apply --id ID       Push only one profile (e.g. --id "c64/Boulder Dash.crt").
rbcf revert --id ID      Remove one profile's es_settings entries from RetroBat.
rbcf validate            Lint every profile YAML for schema issues.
```

### Backup subcommands

```
rbcf backup factory                 Capture (or recapture, with confirmation) the
                                    tier-1 pre-install snapshot.
rbcf backup snapshot                Capture a tier-2 working snapshot manually.
rbcf backup snapshot --description "before MAME tweak"
                                    Same with a label.
rbcf backup list                    Show all snapshots in a table.
rbcf backup restore ID              Dry-run preview of restoring a snapshot.
rbcf backup restore ID --apply      Actually restore (takes a current-state
                                    snapshot first, so it's reversible).
rbcf backup help                    Show help for backup subcommands.
```

### GUID alias subcommands

```
rbcf guid status                    List alias groups detected in es_input.cfg.
rbcf guid fold                      Preview folding all alias groups.
rbcf guid fold --apply              Actually rewrite es_input.cfg with the fold.
rbcf guid fold --id 2dc8:3106       Preview/fold only one VID:PID group.
rbcf guid help                      Show help for guid subcommands.
```

### Community / sharing subcommands

```
rbcf submit-controller              Process a controller photo, drop it in the
    --vid 2DC8 --pid 310B           catalog, and print the PR-creation URL.
    --image path/to/photo.jpg       Auto-picks the cleanup mode based on the
    [--mode auto|silhouette|        photo's background; pass --mode to override.
           remove-bg|crop]
    [--name "8BitDo Ultimate 2"]    Optional friendly name (defaults to existing
                                    catalog entry's name or "Controller VID:PID").

rbcf pull-community                 Fetch curated community profiles from the
    [--repo OWNER/NAME]             GitHub repo's community/ folder via the
    [--ref BRANCH]                  Contents API. Default repo is
    [--token GITHUB_PAT]            ITViking-FIN/RetroControlMapper, default
    [--dry-run]                     branch is main. Pass --token to lift the
    [--prune]                       60req/hr unauthenticated rate limit.
                                    --prune removes local community profiles
                                    that no longer exist upstream.
```

### GUI server

```
rbcf_gui                            Start the local server, open browser.
rbcf_gui --port 8766                Use a different port (default 8765).
rbcf_gui --no-open                  Start server, don't auto-open browser.
```

The local server only ever binds to `localhost`. It's not reachable from other machines on your network.

---

## Files we touch

In your RetroBat install:

| File | What we write | When |
|------|--------------|------|
| `emulationstation/.emulationstation/es_settings.cfg` | Per-game and per-system keys for RetroBat-managed settings (joystick port, GameFocus, keyboard pass-through, model, etc.). | On Apply. |
| `emulators/retroarch/retroarch-core-options.cfg` | Direct edits to keys the RetroBat launcher doesn't manage (e.g. `vice_mapper_*`, `puae_mapper_*`, `vice_analogmouse`). | On Apply. |
| `emulationstation/.emulationstation/es_input.cfg` | Folded `<inputConfig>` alias blocks for known controller GUIDs. | Only when the GUID watcher triggers, or when you run `rbcf guid fold --apply`. |
| `decorations/thebezelproject/systems/<System>.info` | Explicit play-area margins to override RetroBat's too-lenient bezel auto-detect. | When you run the bezel scan + fix. |

Every write is preceded by a backup (suffix `.bak.rbcf.YYYYMMDD`) on the first edit per day.

In our own folders:

| Path | Purpose |
|------|---------|
| `profiles/<system>/<rom>.yaml` | Per-game profile YAMLs you've created/edited. |
| `profiles/<system>/_default.yaml` | System default profile. |
| `%APPDATA%\RB-Controller_fix\rbcfrc` | Persisted RetroBat install path override. |
| `%APPDATA%\RB-Controller_fix\factory\` | Tier-1 pre-install snapshot. |
| `%APPDATA%\RB-Controller_fix\snapshots\` | Tier-2 working snapshots (rolling, capped at 30). |
| `%APPDATA%\RB-Controller_fix\update-check.json` | Cached update-check result (24h TTL). |

---

## Files we never touch

For absolute clarity:

- The **RetroBat launcher itself** (`retrobat.exe`, `emulatorlauncher.exe`).
- **Emulator binaries** (RetroArch, libretro cores, standalone emulators).
- **Your ROM files.**
- **Save states or memory cards.**
- The **bezel PNGs themselves** (we only write the `.info` sidecars next to them).
- Anything outside the four files listed in the previous section.

If something we don't list goes missing or changes, it wasn't us.

---

## Troubleshooting

### 1. "My controllers keep forgetting their settings"

This is the GUID drift bug.

- **Settings cog → toggle GUID watcher (auto-fold).**
- Make sure "Run RetroControlMapper at Windows startup" is also on, so the watcher is alive when EmulationStation starts.
- Run `rbcf guid status` to see the alias groups we've detected; if your pad is listed with multiple GUIDs, run `rbcf guid fold --apply` to fold them once explicitly.

After folding, the next ES launch should pick up your mapping regardless of which transport you connected with.

### 2. "I picked a system in the dropdown but the right pane is empty"

That system doesn't have a curated controller diagram in our bundled set yet.

- Click **Search online** on the system selector. With your consent, we look up reference info from RetroBat's wiki and libretro docs and offer a starting profile. (Asks every time. No consent caching.)
- Or fill in the bindings manually in the mappings section. Save → Apply. It just works.

### 3. "RetroBat install not detected"

We probed the registry, common paths, and any user override.

- **Settings cog → Set RetroBat root manually.** Paste the path to your install root (the folder that contains `emulationstation/`, `emulators/`, `roms/`).
- Click Save. The path is persisted to `%APPDATA%\RB-Controller_fix\rbcfrc`. Restart the server (the cog will offer to do this for you).

### 4. "I made a bad change, how do I revert?"

Two options, in order of severity:

- **Restore a recent working snapshot.** `rbcf backup list` shows the rolling tier-2 snapshots. Pick one and `rbcf backup restore <id> --apply`. The restore itself takes a snapshot of current state first, so it's reversible.
- **Restore the factory snapshot.** `rbcf backup restore factory --apply`. This puts your RetroBat config back to whatever it was right before you installed RetroControlMapper. Last-resort revert.

If neither works, the RetroBat-side `.bak.rbcf.YYYYMMDD` files in the same folders as the originals are also safe to copy back manually.

### 5. "Where do I find the configuration files this tool generates?"

Profiles are at `<install dir>\profiles\<system>\<rom>.yaml` (or `_default.yaml`). They're plain YAML — feel free to edit them by hand. The GUI re-reads them on the next page load.

User-data files (snapshots, caches, the install-path override) are under `%APPDATA%\RB-Controller_fix\`.

The bundled installer extracts the program files to `%LOCALAPPDATA%\Programs\RetroControlMapper\` by default.

---

## FAQ

**Q: Do I need RetroBat installed to use this?**
A: Yes. RetroControlMapper edits RetroBat's configuration; without RetroBat there's nothing to configure. Most read-only commands (`rbcf list`, `rbcf validate`) work without it but the interesting features don't.

**Q: Will this break my existing RetroBat setup?**
A: It edits four files (described in [Files we touch](#files-we-touch)) with a daily backup before every edit. Plus the tier-1 factory snapshot if you opted in during install. You can roll back any change. We don't touch the launcher, the emulators, or your ROMs.

**Q: Does this work with Batocera or Recalbox?**
A: Not officially. The profile schema would translate, but we use RetroBat-specific paths and the alias-fold logic targets EmulationStation as forked by RetroBat. Other forks share the `<inputConfig>` shape but the surrounding launcher behaviour differs.

**Q: Why a local web GUI instead of a native Windows app?**
A: Two reasons. First, the controller-press visualisation uses the browser's Gamepad API, which is the cleanest cross-driver gamepad pipeline on Windows. Second, the layered design language renders crisply with CSS and saves us from rebuilding controls from scratch in a desktop toolkit.

**Q: Does the app phone home?**
A: No. Outbound network requests are limited to update checks (off by default, your call) and system lookups (asks every time). See [Network features (privacy)](#network-features-privacy).

**Q: I have two identical 8BitDo Ultimates. Will the GUID watcher confuse them?**
A: No — we disambiguate via the Windows HID InstanceId, which is unique per physical port-instance even for identical pads. If the disambiguation is ambiguous in any specific case, the GUI surfaces a confirmation prompt before doing anything destructive.

**Q: Can I edit the profile YAMLs by hand?**
A: Yes. The GUI re-reads `profiles/` on every page load. The schema is documented at the top of each generated YAML file and in the validate command (`rbcf validate`).

**Q: What happens if I uninstall?**
A: The app removes its program files. Your profiles, snapshots, and `%APPDATA%\RB-Controller_fix\` user data are left in place by default — uninstaller offers an opt-in "remove all user data" checkbox. RetroBat's config is left in whatever state your last Apply left it; if you want it back to pre-install, restore the factory snapshot **before** uninstalling.

---

## Reporting bugs

Bugs and feature requests: [GitHub issues](https://github.com/ITViking-FIN/RetroControlMapper/issues).

Please include:

- **Version** — found in Settings cog → About. Currently `0.1.5.2`.
- **Windows version** — Windows 10 / 11, build number if you have it.
- **RetroBat version** — found in RetroBat's own About screen.
- **What you expected vs. what happened.**
- **Reproduction steps** if you can pin them down.
- **Logs** if relevant — `controller_sync.log` for catalog issues, the browser console for UI bugs, the terminal output of `rbcf_gui` for backend bugs.

If you're reporting a GUID drift issue specifically, the output of `rbcf guid status` is enormously helpful — it shows us what aliases are in your `es_input.cfg` already.

Thanks for using RetroControlMapper. Happy gaming.
