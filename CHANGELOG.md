# Changelog

All notable changes to RetroControlMapper. Format follows [Keep a
Changelog](https://keepachangelog.com); versioning follows
[SemVer](https://semver.org).

## [v0.1.5.2] — 2026-05-16

**Brand consistency.** v0.1.5.1 still surfaced the legacy
`RB-Controller_fix` codename in several user-visible places (GUI brand
title, Settings popover header, tray menu, onboarding wizard text,
outbound User-Agent strings). v0.1.5.2 finishes the renaming pass —
everywhere the user sees the product name, it's now `RetroControlMapper`.

The `%APPDATA%\RB-Controller_fix\` user-data folder stays as-is in
this release: renaming it would migrate existing users' profiles +
settings + snapshots on first launch and that's worth its own
migration step. Slated for v0.1.6.

### Changed

- **GUI brand title** (`<h1>` in header) `RB-Controller_fix` →
  `RetroControlMapper`.
- **Settings popover header** + aria-label + button tooltip.
- **Onboarding wizard greeting** ("RetroControlMapper needs to know
  where RetroBat lives…").
- **Tray menu**: "About RB-Controller_fix" → "About RetroControlMapper";
  tray tooltip title likewise.
- **GUI footer** profile-path example now reads
  `%APPDATA%\RB-Controller_fix\profiles\<system>\<rom>.yaml`
  (was a developer-machine `D:/RB-Controller_fix/...` path).
- **Outbound User-Agent strings** across `update_check.py`,
  `controller_sync.py`, `data_arcade_controls.py`,
  `manual_research_online.py`, `system_lookup.py`, `rbcf.py`:
  rebranded to `RetroControlMapper/<version>` and now derive the
  version from `config.__version__` instead of hardcoded strings
  (so future bumps don't leave stale UAs behind).
- **Settings backup file format**: `app` field now emits
  `"RetroControlMapper"`. Imports still accept the legacy
  `"RB-Controller_fix"` ID so older backups restore cleanly.
- **CONTRIBUTING.md** title + **`docs/UX_FLOWS.md`** prose +
  **`controller_catalog.yaml`** header comment.

### Kept (intentional)

- `%APPDATA%\RB-Controller_fix\` data folder — see TL;DR above.
- Dev workspace path `D:\RB-Controller_fix\` in docs — that's the
  development checkout location; user installs don't see it.
- Internal Python module / file-header comments (low value, no
  user impact).

## [v0.1.5.1] — 2026-05-16

**Hotfix.** Caught during post-release screenshot capture: the v0.1.5
headline feature (bindings DB suggestions in the GUI) was returning
zero hits for real-world ROM filenames because the DB key normalisation
didn't account for the trailing `<year> <publisher>` suffix on bundled
DB keys. Plus a small batch of GUI screenshots added to the repo and
linked from the README.

### Fixed

- **`bindings_lookup`: key normalisation gap (HEADLINE FEATURE).** The
  bundled bindings DB uses keys like `"bionic commando 1988 us gold ltd"`
  (title + year + publisher) but `_candidate_keys()` only generated the
  plain title (`"bionic commando"`). Every user ROM filename was a miss
  → the GUI Suggestions popover was always empty in v0.1.5. Fix: new
  `_match_db_key()` helper does exact-match first then word-boundary
  prefix match where the next DB-key token is a 4-digit year
  (year-shape guard prevents `"impossible mission"` from wrongly
  matching `"impossible mission ii 1988 epyx"`). Verified end-to-end:
  Bruce Lee / Turrican / Wizball / Shadow of the Beast / Spy vs Spy
  / 1943 / Bruce Lee + 9 more c64 ROMs now produce real suggestions.
- **`_candidate_keys`: handle "The" / "A" / "An" article variants.**
  Adds dropped-article candidates so `"Addams Family, The"` and
  `"The Addams Family"` both resolve.

### Added

- **`gui/img/screenshots/` — first batch of v0.1.5 GUI screenshots.**
  Captured live against c64 + Bruce Lee with the patched bindings DB
  reading 5 suggestions through.
  - `01-main.png` — sleek default view with five-icon toolbar
  - `02-suggestions.png` — 💡 Suggestions panel (Bruce Lee bindings)
  - `03-mappings.png` — ⌨ Mappings panel with face-button colour swatches
  - `04-notes.png` — 📄 Notes panel with sample game-controls notes
- **README screenshots link** in the Quick links section.

## [v0.1.5] — 2026-05-16

**From data to delivery.** v0.1.4 *produced* the bindings DB;
v0.1.5 *ships* it. The DB is now bundled into the installer, surfaced
as in-GUI suggestions on every game profile, extensible via user-PDF
drop, and contributable back via a pre-filled GitHub Issue submission
flow. Coverage more than doubled (~1,900 → 4,143 games, +118%; 47
systems with any bindings, up from 33). The v0.1.4 LLM spike got
promoted to a production extractor that now produces 58.6% of all
bindings in the DB. Plus a sleek GUI refresh that strips the
controllers-first view of clutter and tucks everything else behind
a five-icon toolbar. Full notes:
[RELEASE_NOTES_v0.1.5.md](RELEASE_NOTES_v0.1.5.md).

### Added

- **LLM hybrid extraction in production.** `llm_extract.py` +
  `llm_hybrid_feed.py` now contribute 5,741 bindings (58.6% of the
  shipped DB) across 47 systems. Qwen 2.5 3B over local LAN via
  Ollama, system-aware passport prompts, strict output validation
  (drops hallucinated buttons, verifies source quotes verbatim).
- **Per-system few-shot memory pool** (`llm_memory.py`) — quality-
  scored 0-10, capped at 20 examples per system, evicted by score.
  Prompts inject 2 best examples per call → Ollama prompt-cache
  compounds the speedup.
- **Style-guide prompt scaffolding** (`llm_style_guide.py`) — teaches
  the LLM 6 recognised manual variation patterns + 7 explicit
  pitfalls to avoid (cross-references, combos, navigation flavour,
  story text, OCR-garbled input, etc.).
- **Retry-mode sweeps** — `llm_hybrid_feed.py --retry-mode uncertain-only`
  re-attempts records the LLM saw candidates in but didn't commit.
  Final sweep recovered +206 bindings against a now-mature pool.
- **`--skip-single-button` flag** — skip systems where the binding is
  trivially "FIRE → primary action" (Atari 2600, Vectrex, etc.) so
  LLM cycles go to systems that actually benefit.
- **Model selection via env var** — `RBCF_LLM_MODEL=qwen2.5:7b`
  swaps the extractor model without code edits. Provenance tag
  derived from the actual model in use (`extractor: "llm-qwen2.5-3b"`
  etc.) for audit + selective re-runs.
- **GUI icon-bar (13e).** Top-right five-icon toolbar (💡 Suggestions,
  ⌨ Mappings, 🎚 Overrides, 📄 Notes, ⚙ Settings) replaces the bottom
  accordion stack. Each opens a popover; each popover has an "Always
  keep ___ visible" pin checkbox that renders the panel inline below
  the controllers. Pin state persists in localStorage.
- **Tier 1 Task 1: Bindings DB → GUI suggestions.** `bindings_lookup.lookup()`
  is now wired into the profile-load flow via new `/api/suggestions`
  endpoint. Suggestions appear in the 💡 popover with per-row
  Apply / Reject + Apply-all. Source chip distinguishes bundled vs
  arcade vs user_pdf vs LLM vs regex. Count badge on the icon shows
  pending suggestions at-a-glance.
- **Tier 1 Task 2: Bindings DB as installer payload.** `data/bindings_db/`
  (62 systems, 7.2 MB) bundles into the PyInstaller exe via `rbcf.spec`
  datas directive, lands at `_MEIPASS/data/bindings_db/` at runtime
  where `bindings_lookup` finds it automatically. No separate post-
  install copy step needed.
- **Tier 1 Task 5 (BW-8): User PDF drop-zone.** New `/api/contribute-pdf`
  multipart endpoint wires `manual_user_contribution.extract_user_pdf`
  into the GUI. Drag a PDF onto the 💡 popover → pypdf-only extraction
  (no OCR; end-user safe) → results surface in the suggestions list.
  Scanned (image-only) PDFs return a friendly warning.
- **Tier 4 Task 15 MVP: Community submission flow.** Suggestions popover
  footer has "Submit to community DB" toggle. On Save Profile, builds
  a pre-filled GitHub Issue URL with the binding JSON + labels and
  opens it in the user's browser. No OAuth in v0.1.5 — the project
  maintainer triages issues into the next release's bundled DB. Full
  Tier 4 OAuth-backed PR flow lands in v0.1.6. Schema + contract
  documented in `docs/COMMUNITY_BINDINGS.md`.
- **Mapping rows visual polish.** Filled rows get a green-tinted
  input field signalling "this button is bound."
- **Count badges** on Mappings and Overrides icons show currently-set
  binding/override counts at-a-glance.
- **NOTES popover (13b).** Profile notes lifted out of the accordion
  into a document-icon popover. Same textarea element, no data
  migration needed.
- **Overrides popover (13d).** Advanced game overrides lifted out of
  the accordion into the icon-bar (moved from the target-pane h2
  position used during the 13d intermediate stage for symmetry).
- **Controller silhouette tweak (13c first pass).** Extended grips,
  deeper notch, slimmer main body — closer to 8BitDo Ultimate
  proportions. Internal elements (sticks, d-pad, face buttons)
  unchanged.
- **llm_unstick utility.** Detects + resets records stamped
  `llm_attempted=true` with empty bindings + no skip reason + no
  uncertain count (the BW-1 signature) so they re-attempt on the
  next feed run.

### Fixed

- **BW-1: LLMError swallowed on retry exhaustion.** When the Llama
  box was unreachable for the full retry budget, `llm_extract.py`
  returned a `persistent_failure` record stamping the title as
  permanently failed. Records were then skipped on every subsequent
  run, even after the box came back. Fix: `LLMError` now propagates
  up and the orchestrator aborts the run with
  `abort_reason='ollama_unreachable'` instead.
- **Pre-stamping bug.** `llm_attempted=true` was being set
  speculatively before the call resolved. Caught exceptions left
  records stamped as attempted with no real outcome, blocking
  retries. Fix: stamp only on real outcomes
  (success/uncertain/rejected/skipped).
- **Windows cp1252 console Unicode arrows.** `print_summary` in
  `llm_hybrid_feed.py` crashed on Windows cmd.exe when emitting `→`.
  Fix: `sys.stdout.reconfigure(encoding="utf-8")` + ASCII `->`
  fallback when reconfigure fails.

### Changed

- **Bindings DB bundled into installer.** `data/bindings_db/` (62
  per-system JSON files, ~7.2 MB) ships as PyInstaller payload at
  `_MEIPASS/data/bindings_db/`. `bindings_lookup.py` finds it
  automatically via `Path(__file__).parent / "data" / "bindings_db"`.
- **Per-system yield summary** — replaced the misleading
  "bindings/calls × 100" display with two clearer columns: "hit"
  (% calls that produced bindings) and "avg/hit" (bindings per
  successful call).
- **Mappings input placeholder** — restored to `"e.g. RETROK_F1,
  RETROK_SPACE, --- to clear"` (the v0.1.4 working value); the green
  tint signals binding-present without need for an inline prefix label.

### Deferred to v0.1.6

- GitHub-as-database community contribution pool (Tier 4 of the
  original v0.1.5 plan).
- Live bindings_db updates without reinstall.
- Qwen 2.5 7B sweep against the 2,291 still-uncertain records.
- Controller silhouette proper-proportions iteration.
- Tier 1 user-contribution flow (drop a PDF → extract bindings →
  optional submit).

## [v0.1.4] — 2026-05-12

**Intelligence release.** This version starts knowing about your games.
Out of the box, ~1,800 games across 20+ retro systems get suggested
button-to-action bindings — no per-game configuration needed. The
intelligence comes from two sources: the community-maintained MAME/
FBNeo `controls.dat` (canonical arcade button labels for 1,061 titles),
and a heuristic pipeline that reads game-manual PDFs via OCR + a
5-pass cascade of section-detection and pattern-matching regexes.
Plus a v0.2 spike toward LLM-based extraction (Qwen 2.5 3B over LAN)
for the long tail.

### Added

- **Arcade controls dataset.** `data_arcade_controls.py` pulls
  `yo1dog/controls-dat-json` on first arcade-system lookup. 1,061
  canonical titles with rich button labels (`P1_BUTTON1: "Light Punch"`)
  and joystick direction mappings. Cached locally for offline use.
  Covers mame, fbneo, hbmame, neogeo, cps1/2/3.
- **Game manual extraction pipeline.** Multi-tier lookup:
  - Local 7z archive ingestor (`manual_local.py`) — indexes 19,548
    manual entries across 63 systems from a user-supplied
    Manual_Package.7z, on-demand single-PDF extraction.
  - Online research (`manual_research_online.py`) — Flaresolverr-
    routed scraper for Vimm's Lair (fully implemented), GamesDatabase
    and ReplacementDocs (stubbed for future work).
  - PDF → text → bindings extractor (`manual_extract.py`) — pdfplumber
    primary, pypdf fallback with heuristic word-resplit for glyph-
    positioned PDFs.
- **OCR fallback** (`manual_ocr.py`) — tesseract-based OCR for
  scanned bitmap manuals (~80% of the retro corpus). Uses pypdfium2
  for rasterisation, persistent OCR text cache keyed by
  `(pdf_path, psm, lang, dpi, prefer_toc)`.
- **TOC-aware fast-path** — manuals with a Table of Contents get
  OCR'd selectively (TOC pages + target controls page only), cutting
  per-manual OCR from 30 pages to ~3.
- **Multi-pass extraction cascade** (5 passes climbing the yield
  curve — each pass runs only on titles the previous left empty):
  - Pass 1: default tight heuristics
  - Pass 2: extended section headers (sports/RPG/fighter genres)
  - Pass 3: PSM sweep (re-OCR at PSM 6/4/11)
  - Pass 4: looser regex thresholds, low-confidence flag
  - Pass 5: single-fire-button joystick specialist (DE-9 systems)
- **DE-9 compound directions.** Joystick "up and to the left" emits
  TWO bindings (dpad_up + dpad_left) sharing the same action —
  matches how DE-9 joysticks electrically wire (no diagonal switch).
- **OCR vocabulary correction.** Targeted fix-ups for common Tesseract
  mangles in controller words: `ieft`→`left`, `dovvn`→`down`,
  `lire`→`fire`, `loystick`→`joystick`, `buttor`→`button`, etc.
- **Move-sequence rejection.** Fighter-game combo descriptions
  (Hadouken, Fatality, etc.) get explicitly filtered before pattern
  matching so the bindings DB stays clean of game-internal combat
  data.
- **Extractor versioning.** Per-record `extractor_version` stamp +
  `--upgrade-below-version` CLI flag for selective re-extraction
  when heuristics ship.
- **Update notification UI overhaul.** Old "Release notes ↗" link
  replaced with three labelled actions: `Upgrade ↗` (direct installer
  download from GitHub release assets), `Release notes`, and
  `Skip this version` (persists in localStorage).
- **v0.2-spike LLM scaffold.** `llm_extract.py` + `llm_memory.py` +
  `llm_style_guide.py` lay the groundwork for hybrid LLM extraction
  on regex-zero titles. Ollama HTTP client, prompt builder with
  one-shot example + 6 manual-variation patterns + 7 explicit
  pitfalls, per-system few-shot memory pool (quality-scored,
  prompt-cache-friendly), structured uncertainty channel for items
  the LLM should flag rather than guess at. Full protocol documented
  in `docs/LLM_PROTOCOL.md`.

### Fixed

- **pypdfium2 bitmap leak.** Long-running OCR processes accumulated
  ~200KB-13MB per page in C-level bitmap buffers that pypdfium2 keeps
  alive while the PIL Image references them. Fix: explicit
  `bitmap.close()` after `.copy()` detaches the PIL image from the
  underlying buffer. Memory creep on the build run dropped 60×.
- **Early-stop loop no-op.** `manual_ocr.ocr_pdf_pages` had an
  early-stop heuristic that reduced `cap` inside a `for i in
  range(...)` loop — Python's range captures cap at loop creation,
  so cap reductions never took effect. Replaced with a while loop.
  Result on FF7 PSX: 30 pages OCR'd → 11 pages, 85s → 30s.
- **Action-by-verb regex backtracking.** The pass-5 prose pattern's
  optional middle groups were greedy, eating into "the joystick"
  and leaving only "the left or right" for the input phrase →
  losing the primary direction on compound bindings. Made groups
  lazy (`??`) — Bruce Lee LEAP went from 2 cardinals to 3 (full
  up+left+right).

## [v0.1.3] — 2026-05-07

**Feature release.** End-to-end mapping flows: the user can now
configure a controller for any system in their library — curated
target SVGs for the popular set, generic schematics for the long
tail. Plus templates, press-to-bind, click-across (partial), test-
launch, accent picker, controller-image and community workflows.

### Added

- **Generic target SVG generator.** Any system without a curated
  target controller now gets a clean schematic rendered from a
  shape descriptor (face buttons, dpad, sticks, shoulders, system
  buttons). 15 systems shipped with explicit `target_layout`
  descriptors (NES, SNES, Genesis 3+6btn, MD, MS, GG, GB/GBC/GBA,
  NDS, N64, PSX, DC, Saturn, PCE). Anything else falls back to a
  generic 1-stick + 4-button + dpad + L/R + Start/Select default —
  better than blank.
- **Profile templates per genre.** `profile_templates/<system>/<id>.yaml`
  define starter mappings (Menu-heavy C64, joystick-only, joyport-1
  Boulder Dash style, keyboard-adventure, CD32 default,
  mouse-driven, Amiga 1-button / 2-button / mouse-driven). New
  "From template…" affordance in the toolbar; clicking populates
  the form. 9 starter templates ship.
- **Press-to-bind keystrokes.** Each map-row gets a 🎯 listen
  button. Click → row enters listening state → next key pressed
  on the keyboard is captured (via `event.code`, layout-independent),
  converted to the right `RETROK_*` constant, written to the field.
  Escape cancels. Covers all letters/digits/F-keys/specials/punct.
- **Click-across binding (partial scope).** For systems lacking a
  `fixed_mapping_note` (the long tail where RetroBat's
  interpretation is often problematic): press a physical button →
  source SVG arms (violet pulse, distinct from the blue live-press
  highlight) → click any target SVG button → per-game `.rmp`
  written under
  `emulators/retroarch/config/remaps/<corename>/<rom>.rmp`.
  Existing bindings reload as persistent badges on target buttons.
  Curated systems (CD32 / SNES / Saturn / NeoGeo / etc.) keep
  their default mapping; v0.1.4 adds an opt-in Customize button.
- **Launch-test button.** Save profile → click Test → spawns
  RetroBat with the selected ROM via `subprocess.Popen` with
  `CREATE_NEW_PROCESS_GROUP` so the GUI stays responsive. Window-
  docking via `ctypes`/`SetWindowPos` deferred to v0.1.4.
- **User-tunable accent colour.** New row in the existing settings
  cog: HTML5 colour picker overrides `--acc` (and a derived
  `--acc-2` / `--acc-bg` / `--acc-bg-soft`) across whichever theme
  is active. Persists via `localStorage`. Pre-applies before first
  paint so no theme flash. "Reset" button restores the active
  theme's default.
- **Controller graphics sharing workflow.** New
  `rbcf.py submit-controller --vid X --pid Y --image P` CLI
  subcommand: auto-detects the cleanup mode (silhouette /
  remove-bg / tight-crop) by sampling corners + centre, runs
  `clean_controller_photo.py`, saves under
  `gui/img/known/<VID>_<PID>.<ext>`, updates
  `controller_catalog.yaml`. Plus `CONTRIBUTING.md` and a
  `.github/PULL_REQUEST_TEMPLATE/controller-image.md` for the
  community workflow.
- **Community profile pull (lite).** New
  `rbcf.py pull-community [--repo --ref --token --dry-run --prune]`
  fetches profile YAMLs from a `community/` folder in this repo via
  the GitHub Contents API, deduplicates with SHA comparison, drops
  into `profiles/community/`. Sets up the social layer without a
  custom backend.

### Changed

- Settings cog popover now hosts the accent picker between the
  theme switcher and the One-Click toggle.
- `setTargetSVG()` resolution is now: curated SVG → declared
  `target_layout` → generic default. Always renders something.
- Generator-emitted target buttons carry `data-retropad="N"`
  attributes so the click-across binder knows which libretro
  RetroPad index each face/dpad/shoulder/system button maps to.

### Internals

- `LIBRETRO_BUTTON_INDEX`, `core_for_system()`,
  `core_display_name()` (reads `corename` from
  `<core>_libretro.info`), `remap_path()`, `read_remap()`,
  `write_remap()`. The `.rmp` writer preserves non-`btn_` lines
  RetroArch may have written (analog_dpad_mode, device_p1, etc.).
- New `/api/templates`, `/api/template`, `/api/launch-test`,
  `/api/remap` (GET + POST) endpoints.

## [v0.1.2] — 2026-05-05

**Security release.** A post-v0.1.1 audit found three HIGH-severity
issues in the local HTTP server. All fixed; v0.1.1 users should
upgrade. The in-app update check picks this release up automatically.

### Security

- **H1 — DNS rebinding via missing Origin validation.** Any website
  open in the user's browser could `fetch()` to `localhost:8765` and
  trigger config writes. Added an Origin/Host whitelist on every
  state-changing request (POST + DELETE): allowed origins are
  `http://localhost:<port>`, `http://127.0.0.1:<port>`, `http://[::1]:
  <port>` (with or without port), and the empty/missing-Origin case
  for native CLI callers (curl, our own SSE writes). Cross-origin
  requests now return 403.
- **H2 — write-mode endpoints exploitable via `<img>` CSRF.** The
  `?apply=true` path on `/api/scaffold-{all,defaults}` and
  `/api/bezel-cutoffs` was reachable via GET, meaning a malicious
  `<img src="http://localhost:8765/api/scaffold-all/stream?apply=true">`
  on any visited page would silently mass-write profile YAMLs.
  Write-mode endpoints now require POST; GET preserves the read-only
  preview.
- **H3 — unbounded JSON body size.** POSTs read `Content-Length`
  bytes blind, allowing a multi-GB body to exhaust memory. JSON body
  cap of 1 MB enforced; oversize → 413.

### Fixed

- **M4 — XXE / billion-laughs DoS in XML parsing.** Eight `ET.parse`
  call sites (across `guid_aliases`, `rbcf_gui`, `audit_media`,
  `scan_controls`) accepted external XML and processed internal DTD
  entity expansion. New `xml_safe.safe_parse()` helper rejects any
  XML containing DOCTYPE or ENTITY declarations in the prolog. Hand-
  rolled — no `defusedxml` dependency added per user direction.
- **M5 — missing `import sys` in `update_check.py`.** `set_consent()`
  references `sys.stderr` on the OSError path; would have crashed
  with `NameError` if the consent file failed to write.
- **M6 — `_parse_iso` double-corrected UTC.** Cache TTL was off by
  the local DST offset in DST-observing timezones. Now uses
  `datetime.fromisoformat()` with explicit UTC tzinfo.
- **M7 — `BACKUP_TAG` frozen at import.** A tray app running past
  midnight stamped backups with yesterday's date. Now computed lazily
  on every access via a small `_BackupTag` shim that preserves the
  existing call-site syntax.

### Changed

- **Hardcoded path in `audit_media.py`** replaced with `Path(__file__)
  .resolve().parent / "scrape_audit_report.md"` so the report lands
  next to the script regardless of where the project tree lives.
- **Placeholder User-Agent strings** in `system_lookup.py` and
  `controller_sync.py` updated to reference the real GitHub repo and
  current version.
- **Duplicate `Cache-Control: no-store`** removed from `_json()` —
  was being sent twice (once explicitly, once by `end_headers()`).
- **`Pillow>=10.1`** lower bound (was `>=10.0`) so users get the
  CVE-2023-44271 / CVE-2023-50447 fixes by default.

### Internals

The streaming scaffold endpoints (`/api/scaffold-{all,defaults}/stream`)
moved from GET (EventSource) to POST (`fetch()` + ReadableStream + manual
SSE chunk parsing). Wire format unchanged. Frontend updated.

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

[v0.1.2]: https://github.com/ITViking-FIN/RetroControlMapper/releases/tag/v0.1.2
[v0.1.1]: https://github.com/ITViking-FIN/RetroControlMapper/releases/tag/v0.1.1
[v0.1.0]: https://github.com/ITViking-FIN/RetroControlMapper/blob/main/CHANGELOG.md#v010--2026-05-04
