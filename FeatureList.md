# RetroControlMapper — Feature List

Scannable one-liner inventory of what the app does. For the long-form
walkthrough see [`INSTRUCTIONS.md`](INSTRUCTIONS.md); for the marketing
pitch see [`README.md`](README.md).

## Bindings & profiles

- Local bindings DB (4,143 games / 47 systems bundled in installer)
- Online bindings lookup for missing systems (consent-per-call)
- Manual-extraction PDF drop — contribute bindings from any game's manual
- Community DB submissions — pre-filled GitHub Issue from the GUI
- Per-game profiles (`profiles/<system>/<rom>.yaml`)
- Per-system defaults (`_default.yaml`) with inheritance overlay
- Profile templates per genre (Menu-heavy C64, CD32, Mouse-driven Amiga, etc.)
- System/game level notes (free-text, saved into profile YAML)
- Confidence labels per profile — Verified / Known-good / Template
- 30+ pre-curated controller bindings for popular systems

## GUI

- Sleek default — source + target controllers side-by-side, nothing else
- Five-icon top-right toolbar (💡 Suggestions · ⌨ Mappings · 🎚 Overrides · 📄 Notes · ⚙ Settings)
- Per-panel "always keep visible" pin toggles (persisted)
- Live press-indicator feedback at 60 Hz on both source + target SVGs
- Source/target SVG schematic auto-generation for any unmapped system
- Press-to-bind keystrokes — 🎯 listen icon, tap key, done
- Click-across binding for systems without verified defaults
- Count badges on icons (mappings / overrides / suggestions counts)
- Light / Dark / Auto theme
- User-tunable accent colour
- Toast notifications for save / apply / bind events

## Controller management

- Pad pills — one per detected controller, click to make active
- VID:PID-keyed controller image catalog (Wikimedia + community)
- Controller-image submission flow (`rbcf submit-controller`)
- GUID alias detection (fixes "my mappings keep disappearing" bug)
- Multi-pad disambiguation (Identify… flow for duplicate controllers)
- Per-controller image override via Settings cog

## Save / Apply / Test

- Two-step Save → Preview → Apply (or one-click power-user mode)
- Apply receipts (audit trail of what changed)
- Test-launch button — fires up the game in RetroBat with your bindings
- Per-game RetroArch `.rmp` writes for click-across overrides

## Backups & safety

- Tier 1 — Pre-install factory snapshot (permanent, never overwritten)
- Tier 2 — Rolling per-edit working snapshots (auto)
- Restore from any snapshot (Settings cog)
- Apply preview shows diff before writing config

## RetroBat integration

- 200+ system dropdown from your local RetroBat install
- Auto-detect RetroBat root (registry + common paths + manual override)
- ROM scanning per system (counts by config / scanned / missing)
- Bezel viewport calibration (recovers cropped game screens)
- Onboarding wizard with scaffold-missing-profiles step

## Networking & privacy

- No telemetry, no accounts, no phone-home
- Outbound calls gated behind explicit consent (per-call, not cached)
- Auto-update check (opt-in, GitHub-Releases polling)
- Skip-this-version + release-notes links in the update banner
- Community profile pull (`rbcf pull-community`)
- Online bindings lookup via Vimm.net (Flaresolverr-routed)

## System integration

- Tray-resident — closes to system tray, doesn't quit
- Optional "Run at Windows startup" entry
- GUID watcher daemon (background controller-drift fix)
- Installer detects + upgrades-in-place over prior versions
- All user-writable data under `%APPDATA%\RB-Controller_fix\`

## Extraction pipeline (dev-side, off-line)

- Multi-pass regex extraction across 5 specialised passes
- Local LLM hybrid (Qwen 2.5 3B / 7B via Ollama over LAN)
- Per-system few-shot memory pool (quality-scored, auto-evicting)
- Strict output validation (rejects hallucinated buttons, verifies quotes)
- Configurable model via `RBCF_LLM_MODEL` env var
- Retry-mode sweeps for previously-uncertain records
- Auto-skip for single-button joystick systems
