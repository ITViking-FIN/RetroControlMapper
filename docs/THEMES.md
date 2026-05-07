# Themes

The GUI's design language (`docs/DESIGN_LANGUAGE.md`) defines the
**Frosted Acrylic** baseline — light, dark, and `auto` (follows
`prefers-color-scheme`). All driven by CSS custom properties on
`:root` / `[data-theme="..."]`, so swapping themes is a single
attribute change on `<html>`.

This file logs additional **shipping themes** planned for v0.1.4+,
plus the user-tunable accent feature that applies across all themes.

---

## Currently shipped (v0.1.2)

| Theme key | Mood | Status |
|---|---|---|
| `light` (default `:root`) | Bright frosted acrylic; cyan/violet candy accents | ✅ |
| `dark` (`[data-theme="dark"]`) | Deep navy + frosted; same candy accents | ✅ |
| `auto` (`[data-theme="auto"]`) | Follows OS preference | ✅ |

---

## Planned for v0.1.4

Currently scoped: **`tactical` only.** `hifi` is filed away as a
later-backlog idea (see "Backlog" section below) — its skeuomorphic
language fights the Frosted Acrylic baseline and the brushed-metal /
textured-control work is meaningfully bigger than a normal theme.
Better to revisit once we've shipped one additional theme cleanly.

### Theme: `tactical` (HUD / sci-fi command interface)

Inspired by spaceship-cockpit / military-HUD aesthetics — angular
brackets, scanlines, hexagonal map elements, mint primary, orange
warning. Reads like Helldivers / Mass Effect / Destiny.

**Palette:**

| Token | Value | Use |
|---|---|---|
| `--bg-page` | `#0A1F2A` | Deep marine teal, near-black |
| `--bg-page-grad` | `radial-gradient` of `rgba(94, 230, 188, 0.05)` | Subtle teal vignette |
| `--shell-fill` | `rgba(94, 230, 188, 0.04)` | Translucent panels |
| `--plate-fill` | `rgba(94, 230, 188, 0.06)` | |
| `--content-fill` | `rgba(15, 35, 45, 0.85)` | Solid command surface |
| `--edge-top` | `#5EE6BC` solid | Sharp mint border tops |
| `--edge-bottom` | `rgba(94, 230, 188, 0.4)` | |
| `--tx-primary` | `#D7F5E8` | Cool off-white |
| `--tx-secondary` | `#9DDFC4` | Mint-tinged secondary |
| `--tx-muted` | `#5E8B7E` | Dim mint |
| `--acc` | `#5EE6BC` | Mint green (primary action) |
| `--acc-2` | `#3FCBA0` | Mint pressed state |
| `--state-warn` | `#FF7A2D` | Bright orange — warnings |
| `--state-err` | `#FF4040` | Red alert |
| `--state-ok` | `#5EE6BC` | Same as accent |

**Distinctive elements** (need component-level CSS, not just tokens):
- Angular bracket-style borders on plates (`clip-path` cuts)
- Subtle scanline overlay on backgrounds (`background-image:
  linear-gradient(...)` at 2px stripes, very low alpha)
- Hexagonal grid pattern on map / device-list backgrounds
- Mono+condensed typography (uppercase labels, large readouts)

**Effort:** M — palette is a 30-line `[data-theme="tactical"]`
block. Bracket borders + scanlines + hex grid are ~150 lines of
shared component CSS. Two days well-spent.

---

---

## Backlog (revisit after `tactical` ships)

### Theme: `hifi` (Hi-Fi audio gear)

Inspired by skeuomorphic studio rack equipment — brushed-metal knobs,
chiselled buttons, textured noise backgrounds, glowing LED segments.
Very tactile, photo-real, "expensive equipment" vibe.

**Status (2026-05-04):** filed for later by user request. Reasons:
- The skeuomorphic language fights Frosted Acrylic's flat minimalism;
  shipping it well means designing tactile controls that don't look
  like outliers.
- The brushed-metal knob / slider work is meaningfully bigger than a
  normal palette swap (4–5 days for a polished result).
- The user-tunable accent (already shipped) covers the most-requested
  colour-customisation use case without a full skeuomorphic theme.

When we revisit this, start with: a **simplified** version that uses
heavier shadows + slight bevels but keeps the existing flat
component shapes. Skip the noise-texture backgrounds and full
brushed-metal knobs unless we're ready to commit to a separate
visual language.

**Palette sketch (preserved for later):**

| Token | Value | Use |
|---|---|---|
| `--bg-page` | `#1A2530` | Dark slate-blue |
| `--shell-fill` | brushed-metal gradient | |
| `--tx-primary` | `#E8F0F5` | Cool white (LED-like) |
| `--acc` | user-tunable; defaults cyan/teal | Slider track / glow |

**Distinctive elements** (would need building from scratch):
- Noise/grain background texture (SVG filter, baked PNG, or CSS stipple)
- Brushed-metal knobs / sliders for `<input type="range">`
- Beveled buttons with light-from-above shading
- Monospace 7-segment display for numeric readouts

---

## User-tunable accent (cross-theme)

Idea (per user request 2026-05-03): let users override the primary
accent colour without picking a whole theme. So someone running
`hifi` or `tactical` who prefers blue or purple sliders/highlights
can do so.

**Mechanism:**
- New section in the GUI's settings: "Accent colour" — colour input
  (HTML5 `<input type="color">`) defaulting to the theme's `--acc`
  value
- On change: write to `localStorage` as `rbcf-user-accent`
- On page load: if a user accent is set, override `--acc` and
  `--acc-2` (derived: brighter or via HSL shift) on
  `document.documentElement.style.setProperty('--acc', value)`

**Caveats:**
- Need a "reset to theme default" button
- Some themes (`tactical`) reuse the accent for `--state-ok`; user
  override must keep state colours consistent (don't change `--state-ok`
  to red just because the user picked red as their accent)
- Some accents reused inside gradients — those need to read from `--acc`
  via `var()` already (audit needed)

**Effort:** S — once the theming infrastructure is there, this is
~30 lines of JS + a settings panel entry. Could ship as part of any
v0.1.4 theme PR.

---

## Implementation conventions

When adding a new theme:

1. Define ONLY the tokens that change. Inherit everything else from
   the default `:root`.
2. Don't use literal colours in component CSS — go through tokens.
   If a token doesn't exist for what you need, add it to `:root`
   first, then override per-theme.
3. Theme keys are lowercase ASCII, `data-theme="<key>"`.
4. Add a row to the table at the top of this file.
5. If a theme needs extra component-level styles (scanlines, brushed
   metal, etc.), put them in a `@layer theme.<key>` block at the
   bottom of `style.css` so they don't pollute the default cascade.

---

## Theme switcher UI (deferred)

Currently the theme is fixed to `auto`. v0.1.4 should add:
- Settings menu entry "Appearance" with three (or more) buttons
- Selected theme persisted to `localStorage` as `rbcf-theme`
- Applied on page load before first paint to avoid theme flash
- Whatever new themes are shipped get added to the picker
