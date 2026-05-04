# Design language — Frosted Acrylic

User-supplied direction (2026-05-04). The current dark-theme github-dark
CSS in `gui/style.css` is to be migrated to this language. This document
is the brief any UI agent (Stream T2/T3 successors, ui-polish, etc.)
reads first before touching CSS.

> **Source**: User dropped a "Frosted Acrylic Kit" reference image showing
> a light-mode glassmorphism component sheet — translucent shell over a
> soft-light background, layered shell → plate → content stack, vibrant
> candy-colored pill buttons, soft scattered shadows, single light source
> from upper-left, "glow above stack" 1px edge highlight.

## Headline traits

1. **Light, not dark.** Off-white / very pale blue background with a
   subtle radial gradient implying a single overhead-left light source.
   Replaces the current `--bg-0: #0b0e13` family.

2. **Translucent surfaces, not opaque.** Every panel uses
   `backdrop-filter: blur(...)` over the page. The plate sits *inside*
   the shell with its own translucency, never opaque.

3. **Layered stack architecture.** Three z-tiers per UI region:
   - **shell** — outermost rounded translucent frame (border-radius
     ~24px, large soft shadow, 1px white inner-top edge highlight = the
     "glow above stack")
   - **plate** — nested panel, slightly more opaque than shell
   - **content** — actual controls, sit on the plate
   The image labels these explicitly. Don't flatten them into a single
   layer.

4. **Soft scattered shadow under every elevated element.** Two-layer
   shadow: a tight 2-6px close shadow + a wider 18-30px diffuse one,
   both very low alpha. Together they imply the element is floating
   above the surface.

5. **Single light source.** All highlights and shadows must be
   consistent — top-left bright, bottom-right dark. Never have an
   element whose highlight is on the bottom-right (would break the
   illusion).

6. **Vibrant candy accents.** Pill buttons in cyan, pink, violet/blue.
   Glossy vertical highlight (top half lighter). Used sparingly — for
   primary actions and status indicators only.

7. **Two border treatments.**
   - **single border (soft)** — 1px translucent white at the top inner
     edge, 1px dark at the bottom outer edge. The default.
   - **double border (sharp)** — 1px hard inner stroke + 1px outer
     stroke with a small gap, used for "selected / active" affordances.

## Color tokens (proposed — adjust during implementation)

```css
:root {
  /* Surface */
  --bg-page:       #eef2f7;                   /* base off-white */
  --bg-page-grad:  radial-gradient(             /* single light source */
                     1200px 800px at 25% -10%,
                     rgba(255,255,255,0.6),
                     transparent 60%
                   );
  --shell-fill:    rgba(255, 255, 255, 0.42);  /* outer panel translucency */
  --plate-fill:    rgba(255, 255, 255, 0.58);  /* inner panel */
  --content-fill:  rgba(255, 255, 255, 0.82);  /* opaque-ish input */

  /* Edges (soft border treatment) */
  --edge-top:      rgba(255, 255, 255, 0.65);  /* glow above stack */
  --edge-bottom:   rgba(20, 24, 38, 0.06);     /* faint dark outer */

  /* Edges (sharp / double border) */
  --edge-inner:    rgba(124, 92, 255, 0.55);   /* selection accent */
  --edge-outer:    rgba(124, 92, 255, 0.15);

  /* Soft scattered shadow (apply to every elevated element) */
  --shadow-soft:   0 1px 2px rgba(20, 24, 38, 0.05),
                   0 8px 28px rgba(20, 24, 38, 0.08);
  --shadow-deep:   0 1px 3px rgba(20, 24, 38, 0.07),
                   0 14px 40px rgba(20, 24, 38, 0.12);

  /* Text */
  --tx-primary:    #1a1d24;
  --tx-secondary:  #4a5160;
  --tx-muted:      #6b7280;
  --tx-on-accent:  #ffffff;

  /* Accents (pill / candy) */
  --acc-cyan:      #4ad8ff;
  --acc-cyan-2:    #6fe0ff;
  --acc-pink:      #ff6cb3;
  --acc-pink-2:    #ff85c0;
  --acc-violet:    #7c5cff;     /* matches the existing brand accent */
  --acc-violet-2:  #9580ff;
  --acc-blue:      #58a6ff;     /* for "active/pressed" — kept */

  /* Accent gradient — used sparingly for primary CTAs */
  --acc-gradient:  linear-gradient(135deg, var(--acc-cyan) 0%, var(--acc-pink) 100%);

  /* State */
  --state-ok:      #3fb950;
  --state-warn:    #d29922;
  --state-err:     #f85149;

  /* Glassmorph blur amounts */
  --blur-low:      blur(12px);
  --blur-med:      blur(20px);
  --blur-high:     blur(30px);

  /* Radii */
  --radius-shell:  24px;
  --radius-plate:  18px;
  --radius-pill:   999px;
  --radius-input:  12px;
}
```

## Component treatments

### Pill button (primary action)

```css
.fa-pill {
  border-radius: var(--radius-pill);
  padding: 12px 28px;
  background: var(--acc-gradient);
  color: var(--tx-on-accent);
  font-weight: 600;
  border: 1px solid var(--edge-top);
  box-shadow: var(--shadow-soft),
              inset 0 1px 0 rgba(255,255,255,0.45);  /* top gloss */
}
```

Variants: `.fa-pill-cyan` (solid cyan), `.fa-pill-pink`, `.fa-pill-violet`,
`.fa-pill-gradient` (the cyan→pink combo).

### Shell + plate

```css
.fa-shell {
  background: var(--shell-fill);
  backdrop-filter: var(--blur-med);
  border: 1px solid var(--edge-bottom);
  border-top-color: var(--edge-top);          /* glow above stack */
  border-radius: var(--radius-shell);
  box-shadow: var(--shadow-deep);
  padding: 24px;
}
.fa-plate {
  background: var(--plate-fill);
  backdrop-filter: var(--blur-low);
  border: 1px solid var(--edge-bottom);
  border-top-color: var(--edge-top);
  border-radius: var(--radius-plate);
  box-shadow: var(--shadow-soft);
  padding: 16px;
}
```

### Toggle

Rounded-rect track ~44×24px. Track background: `var(--content-fill)` when
off, `var(--acc-blue)` when on (with a soft glow). Handle: white circle
with `--shadow-soft`, slides on transition.

### Search field

```css
.fa-search {
  border-radius: var(--radius-pill);
  background: var(--content-fill);
  border: 1px solid var(--edge-bottom);
  border-top-color: var(--edge-top);
  box-shadow: inset 0 1px 2px rgba(20,24,38,0.06);
  padding: 10px 14px 10px 40px;
  /* search icon as a separate floating button on the right with a glow on focus */
}
.fa-search:focus-within {
  border-color: var(--acc-violet);
  box-shadow: inset 0 1px 2px rgba(20,24,38,0.06),
              0 0 0 4px rgba(124,92,255,0.15);
}
```

### Slider

Thin track (4px), dark thumb (12px diameter). Track has subtle inner shadow.

### Settings / profile button (chip style)

Lower-key than the pill — neutral fill, no gradient, just a soft chip
with `var(--shadow-soft)`. The image shows these as the muted siblings
of the candy pills.

### "Add user — Pro feature — Upgrade" CTA card

This is the high-emphasis slot. Translucent plate, gradient pill button
inside. Use sparingly — at most one per view.

## Single-light-source rule

Every elevation must follow the same convention:
- Top edge: bright (`--edge-top`)
- Bottom edge: dim (`--edge-bottom`)
- Shadow extends down-right (already encoded in `--shadow-soft` /
  `--shadow-deep` which use positive Y offsets).
- Inner gloss on pill buttons: top half brighter.

If a designer/agent ever writes a `box-shadow` with a *negative* Y, or
an `inset` highlight on the *bottom*, that's a bug.

## What NOT to do

- ❌ Don't make panels opaque. Frosted glass requires the underlying
  page to show through.
- ❌ Don't drop the layered shell-plate-content split into a single
  flat panel. The depth is the brand.
- ❌ Don't use the candy gradient on more than one element per view —
  it loses meaning if it's everywhere.
- ❌ Don't put dark text on dark translucency. Text contrast must stay
  WCAG AA (4.5:1) against the *blurred-through* background, which the
  designer has already validated in the reference image (note the
  "text contrast stable" check).
- ❌ Don't change the `.rbcf-onb-` or `.rbcf-apply-` class prefixes —
  rebrand the styles, not the IDs/classes (JS depends on classes).

## Migration order (when implementation begins)

1. Replace the `:root` token block in `gui/style.css` with the table
   above. Keep both palettes side by side initially via a body class
   `body.theme-frosted` so we can A/B locally.
2. Restyle the **toolbar** + **header** first — most-visible surfaces.
3. Restyle the **onboarding overlay** (`.rbcf-onb-*`) — it's the first
   impression for new users.
4. Restyle the **apply preview modal** (`.rbcf-apply-*`) — the second
   most-load-bearing surface.
5. Restyle the **device cards** + **profile editor** last.
6. Drop the old palette body class once parity is achieved.

Each step should be reviewable as its own commit. Browser-tested before
landing — the backdrop-blur fallbacks and contrast ratios both need
human eyes.

## Migration prerequisites — answered 2026-05-04

- **Light/Dark switch in settings** ✅ — Ship both modes. Toggle lives in
  the existing T3 settings popover (cog icon in the toolbar). Three states:
  Light · Dark · Auto (follows `prefers-color-scheme`). Persisted in
  `localStorage['rbcf-theme']`. Default: Auto.
- **Accent intensity** ✅ — Global. Single set of accent tokens in `:root`,
  no per-surface tuning for now.
- **Animation budget** ✅ — Generous. Hover lift on cards (translateY ~2px,
  shadow deepens), focus glow expand (rgba ring grows 4px→6px), pill press
  depth (translateY +1px + reduced shadow on `:active`). Use `cubic-bezier
  (0.2, 0.8, 0.2, 1)` for a slightly springy feel. Cap individual transitions
  at 220ms; modal entry/exit may be 300ms.
