# RB-Controller_fix — UX Flows

> Stream D output. Design-only, no implementation. The UI agent will pick this
> up in a later iteration. **Do not hand-edit the existing GUI based on this
> doc without coordination** — the current GUI is the *baseline*; this doc
> describes the *target*.

---

## Design philosophy

Two values, both from the user, hold rank over everything below:

1. **"Total control, but ONLY when needed and the user asks for it."**
   Progressive disclosure is the spine. The default landing experience
   shows: detected pad, detected systems/games, one big primary action.
   Every knob beyond that lives behind a disclosure (`Advanced…`, "Show
   details", a side drawer, a footer link). Nothing screams. Defaults
   work.

2. **"The more ready-made stuff we can ship with out of the box, the
   better."** Profiles bundled in `profiles/` are first-class assets, not
   examples. The first-run flow assumes the user wants to *consume* them,
   not author them. Authoring is a power-user path.

Translated to UI rules:

- **Empty states are designed, not afterthoughts.** Every "we found
  nothing" path has a single primary action that gets the user to a
  populated state in one click.
- **Pessimistic on writes, optimistic on reads.** Reads (`/api/devices`,
  `/api/games`, `/api/profile`) update the UI immediately and reconcile
  on response. Writes (`/api/save`, `/api/apply`) always show a
  confirmation step (dry-run preview) and a success state with the
  receipt (backup file path, line count, etc).
- **One canonical place for status.** A persistent footer carries: last
  apply, last sync, server-bind health, RetroBat path. Toasts are for
  acknowledging discrete actions; the footer is for ambient state.
- **Keyboard works, but isn't promoted.** Tab order is logical, focus
  rings are visible, `Enter` confirms primary actions in dialogs. No
  global hotkeys (the demo audience here is mouse-driven).
- **No frameworks.** Vanilla HTML/CSS/JS per CLAUDE.md. Disclosures are
  `<details>`/`<summary>` or class-toggled `<section>`s with a chevron.
  Modals are `<dialog>` elements (native, focus-trapped, keyboard-closed
  for free).

---

## Cross-flow vocabulary (used throughout)

| Term | Meaning |
|------|---------|
| **Profile** | A YAML file in `profiles/<system>/<rom>.yaml` (or `_default.yaml`). |
| **System default** | `_default.yaml` — fallback for any ROM without a per-game profile. |
| **Verified (V)** | The user has run the game with this profile and confirmed it works. |
| **Known-good (K)** | Cribbed from a reliable source (forum, ROM-pack, prior install) but not yet confirmed in *this* setup. |
| **Scaffold (T)** | TBD/template — system default copied as a starting point, no game-specific tuning. |
| **Apply** | Run `rbcf.py apply` — push profiles into RetroBat's config files. |
| **Dry-run** | Same as apply but writes nothing; produces a diff. |
| **Sync** | Run `controller_sync.py` — fetch controller catalog images from Wikimedia. |
| **Drift** | Same physical controller surfacing under multiple SDL GUIDs. See Stream B's `docs/GUID_DRIFT_DESIGN.md` (forthcoming). |

---

## 1. First-run onboarding

**Intent.** First time the user opens the GUI, the app should *prove its
value in 10 seconds*. We probe everything we can without asking, present
a single triage summary, and offer one button: "scaffold all missing
with sensible defaults". The user should be able to launch RetroBat
right after, see games working, and only come back if something's wrong.

**Trigger.** No `rbcf-onboarded` key in `localStorage`, OR the user
navigates to `/?onboarding=1`.

### Steps

| # | User | System |
|---|------|--------|
| 1 | Opens `http://localhost:8765/`. | Detects no `rbcf-onboarded`. Shows full-screen onboarding overlay (rest of UI dimmed/disabled behind it). |
| 2 | — | In parallel: hits `/api/devices`, a (new) `/api/scan` that returns systems + ROMs + profile coverage, and reads the resolved RetroBat root. |
| 3 | Reads the summary card. | Renders: "Found RetroBat at `E:\RetroBat`. 4 systems supported. 47 ROMs found across them. 12 already have profiles, 35 don't." |
| 4 | Clicks **[Scaffold 35 missing with system defaults]**. | Shows a confirm modal with the breakdown (12 c64, 18 amiga500, 5 amigacd32). On confirm: POST a (new) `/api/scaffold-all` and stream progress. |
| 5 | Watches a progress list. | Each row flips from "queued" → "wrote" with checkmark. On finish: "35 scaffold profiles created. None verified yet — that's normal." |
| 6 | Clicks **[Apply now]** (primary) or **[Apply later]** (secondary). | If apply now: jumps into Flow 7 (Apply/dry-run) with the scaffolded set pre-loaded. If later: closes the overlay, sets `rbcf-onboarded=1`, lands on the main GUI with the toolbar pre-populated to the first system. |

### Empty-state language

If RetroBat **isn't found** at step 2 → see Flow 9, error 9.1. Onboarding
hands off to that flow and resumes once a path is captured.

If RetroBat is found but **0 systems** are recognised (es_systems.cfg
empty/malformed) → see Flow 9, error 9.2.

If RetroBat is found, systems exist, but **0 ROMs** in any of them:

> "**Nothing to do yet.**
> RetroBat sees these systems but no ROMs in any of them. Drop ROMs into
> `E:\RetroBat\roms\<system>\` and click Rescan."
>
> [Rescan] [Open ROMs folder]

### Wireframe

```
┌─────────────────────────────────────────────────────────────────┐
│  Welcome to RB-Controller_fix                            [skip] │
│                                                                 │
│  We had a quick look around your machine.                       │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  RetroBat   E:\RetroBat                            [edit] │  │
│  │  Systems    4 supported (c64, amiga500, amiga1200, cd32)  │  │
│  │  ROMs       47 across all systems                         │  │
│  │  Profiles   12 already have one  ·  35 don't              │  │
│  │  Pad        8BitDo Ultimate (1 connected)                 │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  We can drop a sensible default profile on each of those 35     │
│  ROMs right now. They use the system default mapping — you can  │
│  customise any of them later.                                   │
│                                                                 │
│            [Scaffold 35 missing with defaults]   ← primary      │
│                                                                 │
│            [Skip — I'll set up profiles myself]                 │
│                                                                 │
│  Advanced…   ← opens disclosure with manual paths, etc.         │
└─────────────────────────────────────────────────────────────────┘
```

### Microinteraction notes

- The detection card animates in chunk by chunk as `/api/scan` data
  arrives — no spinner-on-blank-card. Each row shows "…" while pending,
  then snaps to its value with a 100 ms ease-in.
- The primary CTA label is computed live; if N changes between mount and
  click (e.g. user added ROMs), it updates without re-render.
- "Skip" sets `rbcf-onboarded=1` so we don't re-prompt; the user can
  re-open onboarding from `Advanced… → Re-run onboarding`.

### Success state

Two-line green toast in lower-right after step 5:

> **35 profiles scaffolded.** Open any game from the toolbar above to
> tune it.

The toolbar's System dropdown now defaults to whichever system received
the most new scaffolds (visual nudge: "you probably want to look here
first").

### Open questions

- ❓ When the user has *both* an existing pre-rbcf profile collection
  and a fresh ROM library, do we offer "import from existing
  install" as a third onboarding path? (Stream B may surface this via
  the catalog work.)
- ❓ Should "Scaffold all" also write `_default.yaml` for systems that
  don't have one? Currently the seed profiles ship with one for c64,
  amiga500, amigacd32 — but not amiga1200.

---

## 2. Device picker — the dual-8BitDo case

**Intent.** The user owns two 8BitDo Ultimates that present identically
to the browser Gamepad API (per CLAUDE.md). The current GUI lets them
click a device card to pick the active source, but if both report the
same `pad.id` the user has no way to tell which is which from the card
labels alone. We add a "press a button to identify" flow on top.

### Steps

| # | User | System |
|---|------|--------|
| 1 | Opens the device drawer (already in the GUI; click the chevron). | Renders a card per detected `pad.index`. Two identical-looking 8BitDo cards. |
| 2 | Hovers either card → tooltip shows `pad.index`, VID:PID, instance ID. | — |
| 3 | Clicks **[Identify…]** on a card (new affordance). | Card enters "listening" state: dim the other cards, big inline text "**Press any button on this controller now.**" |
| 4 | Presses A on the controller they want to label. | The system records the `pad.index` whose `buttons[*].pressed` fires first (50 ms debounce). Card flashes blue, exits listening, shows the captured timestamp + button index. |
| 5 | Optionally, types a label ("Player 1 white" / "Player 2 black") into the inline label field. | Persists to `localStorage` keyed by `instance_id` (more stable than `pad.index`). |
| 6 | Clicks the card to make it the active source. | Existing flow — `setActivePad()`. |

### Wireframe (drawer expanded)

```
▾ 2 controllers detected · 2 XInput
  ┌───────────────────────────────────┐  ┌───────────────────────────────────┐
  │ [img] 8BitDo Ultimate              │  │ [img] 8BitDo Ultimate              │
  │       2DC8:3106 · XInput           │  │       2DC8:3106 · XInput           │
  │       label: "Player 1 white" ✎   │  │       label: (none)               │
  │       [Active]   [Identify…]       │  │       [Use this]  [Identify…]      │
  └───────────────────────────────────┘  └───────────────────────────────────┘
                                  [Rescan]
```

### Listening state (step 3)

```
▾ 2 controllers detected · 2 XInput
  ┌──────────────────────── L I S T E N I N G ──────────────┐
  │  Press any button on the controller you want to label.  │
  │                                                          │
  │  …waiting (timeout in 8s)         [Cancel]              │
  └──────────────────────────────────────────────────────────┘
  ┌─ dimmed second card ─────────────┐
  │ [img] 8BitDo Ultimate            │
  │ … (greyed out)                   │
  └──────────────────────────────────┘
```

### Microinteractions

- 8-second timeout. On timeout: show "Didn't catch a press — try again",
  re-enable both cards, no destructive change.
- Debounce: ignore button events fired within 50 ms of entering the
  listening state, in case the user already had the button down from
  clicking [Identify…]. (Realistically they clicked with mouse, but
  some users may have clicked using the gamepad's nav.)
- After the first press, capture all currently-pressed buttons in the
  same frame and pick the *lowest* index. (Avoids picking up "L1+R1"
  when the user is gripping aggressively.)
- The label is the only thing persisted server-side optionally (we'd
  want a follow-up endpoint), but for v1 it's fine to live in
  `localStorage` keyed by the device's `instance_id`.
- Use `gamepadbuttondown`-style polling we already have in `app.js` —
  no new event plumbing.

### Error states

- **No controllers connected** at app open: device drawer header shows
  "No HID gamepads detected. Connect one and click Rescan." Button to
  rescan is sticky-visible.
- **Active pad disconnected mid-session**: drawer collapses to summary,
  the source SVG goes dim, footer shows red "Pad disconnected". On
  reconnect, the GUI tries to restore the previously-active pad by
  matching `instance_id`; if it can't, it falls back to "first
  connected" and surfaces a passive toast.
- **`probe_devices()` returns an `{error: ...}` shape**: surface the
  error text in the drawer summary rather than swallowing it (current
  behaviour swallows, see `loadDevices()` lines 568-578). Add a "Retry
  probe" button.

### Open questions

- ❓ Should "Identify…" *also* persist to a server-side store so the
  label survives across machines / reinstalls? Probably not — the
  `instance_id` won't match between machines anyway, so localStorage
  is the right scope. Confirm.
- ❓ When two cards have the same VID:PID and one is labelled but the
  other isn't, should we sort the labelled one first? (Predictability
  vs alphabetical/index order.)

---

## 3. "Your N games have no profile" empty state

**Intent.** When the user picks a system in the toolbar and it has ROMs
but few/no profiles, surface that prominently so the next step is
obvious. Don't make them notice it themselves.

### Trigger

The user changes the System dropdown. After `loadGames()` returns, count
`games.filter(g => !g.has_profile).length`. If non-zero, show a banner
above the side-by-side panes (between the toolbar and the source/target
view).

### Banner content

If **all** games are unprofiled:

```
┌─────────────────────────────────────────────────────────────────┐
│  ⓘ  18 ROMs in amiga500 · 0 have a profile yet.                 │
│                                                                 │
│     [Scaffold all 18 with system default]   [Pick one to start] │
│                                                                 │
│     System default uses RetroPad mode, button B as fire.        │
│     [What does that mean?]                                      │
└─────────────────────────────────────────────────────────────────┘
```

If **some** games are unprofiled:

```
┌─────────────────────────────────────────────────────────────────┐
│  12 of 18 ROMs in amiga500 have profiles · 6 don't.             │
│  [Scaffold the 6 missing]   [Show only unprofiled in dropdown]  │
└─────────────────────────────────────────────────────────────────┘
```

If **all** games are profiled, the banner is suppressed entirely.

### Steps for "scaffold all N missing"

| # | User | System |
|---|------|--------|
| 1 | Clicks [Scaffold all 6]. | Modal: "Create 6 profile YAMLs from the system default? Each gets confidence=T. You can edit any of them later." [Confirm] / [Cancel]. |
| 2 | Confirms. | POST to (new) `/api/scaffold-system` with the system ID. Backend reads `_default.yaml`, copies it for each missing ROM with `rom:` filled in, `confidence: T`, `notes: "Scaffold from system default."` |
| 3 | — | Banner updates: "All 18 games have profiles." Game dropdown gets refreshed; previously-empty entries now have the leading `*` marker. |
| 4 | Picks one of the now-scaffolded games. | Profile loads (T confidence is shown in the game-detail header — see Flow 4). |

### Per-game manual flow

Same as today's flow: pick game from dropdown, fill in mappings, save.
The empty-state banner is just a shortcut.

### "Skip and use system default" path

Don't write a profile at all. Make this explicit: a third button in the
banner labelled `[Skip — let the system default cover everything]`.
Sets `localStorage["rbcf-skip-empty-banner-amiga500"] = 1` so the
banner stays hidden for that system. Banner re-appears on next visit
*if* the user has since added new unprofiled ROMs (we compare counts).

### Microinteractions

- Banner uses the accent violet at low alpha, dismissible (`×` in
  upper-right) but dismissal only hides it for the session unless they
  used the "Skip" button.
- Scaffold writes are pessimistic: button shows spinner, disabled,
  until backend confirms. On error, banner stays, error toast shown.

### Open questions

- ❓ Should "Show only unprofiled in dropdown" persist across system
  switches, or reset every time? Suggest: per-system, in localStorage.
- ❓ Should we offer to scaffold during system change (auto-prompt) or
  always wait for the user to click? Suggest: never auto-prompt mid-
  session; only auto-prompt during onboarding (Flow 1).

---

## 4. Game-detail view

**Intent.** When the user picks a game from the dropdown, they should
immediately see: what profile is loaded, what its confidence is, which
fields are inherited from the system default vs explicitly overridden,
and one click to edit each.

### Layout

This replaces nothing — it augments the existing `<section>`s with a
header strip just under the toolbar:

```
┌─────────────────────────────────────────────────────────────────┐
│  [V] Boulder Dash.crt · c64                       Last edited:  │
│      title: Boulder Dash · year: 1984              2026-04-30   │
│                                                                 │
│  Inherits from c64/_default.yaml — 3 fields overridden.         │
│  [Show inheritance]                                             │
└─────────────────────────────────────────────────────────────────┘
```

The `[V]` is a coloured pill: green for V (verified), yellow for K
(known-good unverified), grey for T (scaffold). Click the pill →
bottom-sheet/popover with confidence definitions and a "Mark as
Verified" button.

### Inheritance overlay

Click `[Show inheritance]` → toggles a class on the form sections that
shows, next to each input:

| Source | Visual | Notes |
|--------|--------|-------|
| System default | small grey "= default" tag | input is blank, placeholder shows the inherited value |
| Game profile (override) | small violet "override" tag | input contains the override value |
| Backend-managed (RetroBat owns this key) | locked/disabled, "🔒 RetroBat" tag | not editable, see CLAUDE.md `Configurevice()` discipline |

When the inheritance overlay is active, hovering a "= default" tag shows
a tooltip with the system default value. Clicking a "= default" tag
copies that value into the input as a starting override.

### Edit affordances

- `core_options` keys (mapping rows): plain text input as today, with
  the inheritance/override tag on the right.
- `es_settings` keys (game-options section): existing select/checkbox
  inputs as today, with same tags.
- Confidence pill: clickable, opens menu `[V] Verified · [K] Known-good
  unverified · [T] Scaffold (default)`. Selection writes back on save.
- Notes textarea: as today.

### Read-only "summary" mode

When the user lands on a fresh game without intent to edit, the form
sections are visually de-emphasised (slightly muted background, smaller
font on labels). Clicking anywhere into a section "wakes" that section
into edit mode (border brightens, label colours saturate). Saves are
still per the existing Save button — this is purely visual cueing that
"you're browsing, not editing yet".

### Wireframe

```
[ V ]  Boulder Dash.crt   c64                            edited 4d ago
       title Boulder Dash · year 1984
       Inherits c64/_default.yaml · 3 overrides     [Show inheritance]
─────────────────────────────────────────────────────────────────────
▾ Custom button → keystroke mappings
   Face buttons          A · B · X · Y
     A  [           ]  = default (vice_mapper_a = ---)
     B  [SPACE      ]  override
     X  [F1         ]  override
     Y  [           ]  = default
   D-pad …
   Shoulders …

▾ Per-game settings
     Game Focus                  ☐  = default
     C64 model         [C64 PAL auto ▾]  = default
     Joystick port     [2            ▾]  override

▾ Notes
     Original Boulder Dash, NTSC has weird timing. Use PAL.
```

### Microinteractions

- Inheritance toggle is sticky: the user's preference (overlay on/off)
  persists in localStorage.
- Clicking the confidence pill is a menu, not a toggle — confidence is
  three-valued.
- "Mark as Verified" requires the user to type their initials (or just
  press Enter on a no-op confirm) — micro-friction so they don't
  accidentally bump T → V on a profile they haven't tested.

### Open questions

- ❓ Should the inheritance overlay be on by default? Argument for:
  shows the most info up front. Argument against: noisier. Suggest:
  off by default, sticky once toggled, with a header tooltip pointing
  at the toggle.
- ❓ When the user *clears* an override (empties the input), do we ask
  "revert to default?" or just save it as cleared? The save normalizer
  currently drops empty values, so silently reverting is the right
  call.

---

## 5. Advanced controls

**Intent.** Hide the dragons. The vast majority of users should never
see this surface. Power users should be one click away from raw config
editing, dry-run preview, backup browsing, and conflict resolution.

### Entry points

- Footer link: `Advanced…` (right-aligned, muted colour).
- Each section header has a small `⋯` menu when there's something
  advanced to do (e.g. "Edit raw es_settings.cfg snippet" or "View
  backup history for this section").

Clicking either lands the user in a side drawer (slides in from the
right; existing GUI already has the device drawer on top, so this is a
full-height right drawer for parity).

### Drawer contents

```
┌── ADVANCED ──────────────────────────────────────────[×]┐
│                                                         │
│  ▾ Apply / dry-run                                      │
│       Always preview before write.                      │
│       [Run dry-run now]                                 │
│       [Apply (with preview)]                            │
│                                                         │
│  ▾ Backups                                              │
│       Last 7 days of .bak.rbcf.YYYYMMDD files.          │
│       [view list]   [open backup folder]                │
│                                                         │
│  ▾ Raw config edit                                      │
│       Edit es_settings.cfg snippet                      │
│       Edit retroarch-core-options.cfg snippet           │
│       (Both pop modal editors with diff preview before  │
│        write. See "Apply/dry-run flow" — Flow 7.)       │
│                                                         │
│  ▾ Conflict resolution                                  │
│       2 core_options conflicts detected.                │
│       [Review them]                                     │
│                                                         │
│  ▾ GUID drift                                           │
│       3 GUIDs for what looks like 1 controller.         │
│       [Review them]   [Open Stream-B doc]               │
│                                                         │
│  ▾ Profiles                                             │
│       [Validate all profiles]                           │
│       [Open profiles folder]                            │
│                                                         │
│  ▾ Reset                                                │
│       [Re-run onboarding]                               │
│       [Clear local UI state]                            │
│                                                         │
│  ▾ Server                                               │
│       Bound to localhost:8765 ✓                         │
│       Sync log: 1,247 lines · last sync 14 hours ago    │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### Conflict resolution UI (sub-flow)

`core_options` apply globally per-core. If two profiles set
`puae_mapper_a` to different values, last-wins with a `[warn]` (per
CLAUDE.md "Profile schema"). The conflict resolution panel surfaces
these:

```
┌── CORE_OPTIONS CONFLICTS ────────────────────────────────┐
│                                                          │
│  vice_mapper_y                                           │
│    ┌─ Boulder Dash.crt    → "RETROK_F1"                 │
│    └─ IK+.crt              → "RETROK_F3"                │
│                                                          │
│    Last to apply wins. Currently last-applied:          │
│    IK+.crt → RETROK_F3                                  │
│                                                          │
│    [Pick winner: Boulder Dash]                          │
│    [Pick winner: IK+]                                   │
│    [Mark as 'intentional — silence warning']            │
│                                                          │
│  puae_mapper_l2                                          │
│    …                                                     │
└──────────────────────────────────────────────────────────┘
```

"Pick winner" doesn't change the *other* profile silently — it changes
this profile's value to match the chosen one and notes in the YAML
that the conflict was resolved by the user. (The other profile is
left alone; the conflict goes away because they now agree.)

### Microinteractions

- Drawer animates in (200 ms cubic-bezier) and traps focus.
- All advanced actions have *some* friction: typed confirmation, dry-run
  preview, or both.
- "Clear local UI state" wipes all `rbcf-*` localStorage keys; toast
  shows the count cleared.

### Open questions

- ❓ Should conflict resolution also offer "split the conflict by
  scoping one of them to a different system"? Probably out of scope —
  the conflict is structural (libretro doesn't honour per-game core
  options through RetroBat). Document this in the panel rather than
  build the affordance.
- ❓ Does the user want a "Lock raw config" toggle that hides even the
  Advanced drawer (e.g. for kiosk-style setups)? Defer.

---

## 6. GUID drift surfacing

**Intent.** Cross-references Stream B's design doc
(`docs/GUID_DRIFT_DESIGN.md`, forthcoming). The bug from CLAUDE.md:
"the same physical controller can present under multiple SDL GUIDs
depending on USB enumeration. RetroBat keys autoconfig on GUID, so the
same pad 'loses' its mapping at random." Stream D's contribution is the
*UI* surface for this: detection notice → user choice to fold the
GUIDs together, dismiss, or see details.

### Trigger

When `/api/devices` (or a Stream-B-introduced sibling endpoint) returns
data that includes a "drift suspected" flag for the connected pad — i.e.
multiple GUIDs in the catalog match the same VID:PID and look like the
same controller (same friendly name, same `instance_id` minus the
unstable suffix, etc).

### Banner

Non-modal, sits below the device drawer (top of main content):

```
┌─────────────────────────────────────────────────────────────────┐
│  ⓘ  Looks like Windows is seeing your 8BitDo Ultimate under     │
│     3 different SDL GUIDs. RetroBat keys per-GUID, so your       │
│     mappings might "vanish" between sessions.                    │
│                                                                  │
│     [Fold them into one mapping]  [Show details]  [Dismiss]      │
└─────────────────────────────────────────────────────────────────┘
```

### "Show details"

Drops the banner into an expanded view (still inline, no modal):

```
┌─ DRIFT DETAILS ─────────────────────────────────────────────────┐
│                                                                 │
│  Device: 8BitDo Ultimate · 2DC8:3106                            │
│                                                                 │
│  Seen under these GUIDs:                                        │
│   ☐  030000007e0500000620000000000000  (last seen 2026-05-02)  │
│   ☐  030000007e0500000620000010010000  (last seen 2026-05-01)  │
│   ☐  030000007e0500000620000011010000  (last seen 2026-04-29)  │
│                                                                 │
│  Recommended: pick one as canonical and fold the others into    │
│  it. RetroBat will then accept any of the three GUIDs as the    │
│  same controller for autoconfig purposes.                       │
│                                                                 │
│  Canonical: [first one ▾]                                       │
│  [Fold]   [Cancel]                                              │
└─────────────────────────────────────────────────────────────────┘
```

### Steps

| # | User | System |
|---|------|--------|
| 1 | Sees the banner. | Banner appears once per session per VID:PID with drift. |
| 2 | Clicks **[Fold them into one mapping]**. | Confirm modal: "This will write a unified GUID mapping. Backup: `…\.bak.rbcf.20260503`. [Confirm fold] / [Cancel]." |
| 3 | Confirms. | POST to (new) `/api/fold-guids` (Stream B's endpoint name). Backend writes the unified mapping; banner replaced with success state. |
| 4 | (Alternative) Clicks **[Show details]**. | Inline expansion as wireframed above. |
| 5 | (Alternative) Clicks **[Dismiss]**. | Sets `localStorage["rbcf-dismissed-drift-2DC8:3106"] = <YYYY-MM-DD>` — banner suppressed for that VID:PID for 30 days. After 30 days or on new GUID detection, banner reappears. |

### Microinteractions

- Banner is *not* modal; the user can keep using the GUI while it sits.
- "Fold" is destructive-ish (writes RetroBat config), so it gets the
  full Apply/dry-run treatment (Flow 7).
- "Dismiss" is silent. The footer's "Drift status" indicator (see Flow
  8) still shows the count, so dismissing doesn't lose the info.

### Open questions

- ❓ Should we offer "fold permanently — silence drift detection for
  this VID:PID" as an option in addition to dismiss? Probably yes —
  some users will want this explicit. Stream B may already have this
  in their backend design.
- ❓ When the user has *two* physical 8BitDos AND drift is suspected,
  the heuristic might over-fold. Stream B should expose a confidence
  score; the UI should refuse to auto-suggest fold below some
  threshold and just say "we're not sure — review manually".

---

## 7. Apply/dry-run flow

**Intent.** Never apply without preview. The user always sees a diff
against the current `es_settings.cfg` and `retroarch-core-options.cfg`
before any write happens. Confirmation is unambiguous; success state
shows the receipt.

### Steps

| # | User | System |
|---|------|--------|
| 1 | Clicks [Apply] in the toolbar (or any other "apply" affordance — e.g. from Flow 1, Flow 6). | Toolbar Apply button label changes to "Previewing…" with spinner. POST to `/api/apply` with `{dry_run: true}` (new flag — currently `/api/apply` does no dry-run mode). |
| 2 | — | Backend runs `rbcf.py apply --dry-run` and returns the would-be-written diff. |
| 3 | Sees a modal preview. | Diff shown as side-by-side with line numbers. Header: "Preview: 2 files would change · 7 lines added · 1 line modified". |
| 4 | Clicks **[Apply for real]** (primary). | Modal locks (no close), POST `/api/apply` (no dry_run). Spinner. |
| 5 | — | Backend writes, makes backups (`.bak.rbcf.YYYYMMDD`), returns success with `{paths_written: [...], backup_paths: [...]}`. |
| 6 | Sees success state. | Modal becomes "Applied successfully" with the receipt: 2 file paths, 2 backup file paths, "Open RetroBat" / "Close" buttons. |

### Modal wireframe

```
┌── PREVIEW: APPLY ───────────────────────────────────────────[×]┐
│                                                                │
│  2 files would change · 7 additions · 1 modification           │
│                                                                │
│  ▾ es_settings.cfg                                             │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  + c64["Boulder Dash.crt"].vice_joyport=2               │  │
│  │  + c64["Boulder Dash.crt"].GameFocus=1                  │  │
│  │  + c64["IK+.crt"].vice_joyport=2                        │  │
│  │  …                                                       │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  ▾ retroarch-core-options.cfg                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  - vice_mapper_y = "---"                                │  │
│  │  + vice_mapper_y = "RETROK_F1"                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                │
│  Backups will be created:                                      │
│   E:\…\es_settings.cfg.bak.rbcf.20260503                       │
│   E:\…\retroarch-core-options.cfg.bak.rbcf.20260503            │
│                                                                │
│            [Apply for real]      [Cancel]                      │
└────────────────────────────────────────────────────────────────┘
```

### Success state

```
┌── APPLIED ──────────────────────────────────────────────────[×]┐
│                                                                │
│  ✓ 2 files written                                             │
│                                                                │
│  Wrote:                                                        │
│   E:\RetroBat\emulationstation\.emulationstation\es_settings.cfg │
│   E:\RetroBat\emulators\retroarch\retroarch-core-options.cfg   │
│                                                                │
│  Backups:                                                      │
│   …\es_settings.cfg.bak.rbcf.20260503                          │
│   …\retroarch-core-options.cfg.bak.rbcf.20260503               │
│                                                                │
│  Next: launch any game in RetroBat and the new mappings        │
│  will pick up. RetroBat regenerates emulator config on each    │
│  launch — that's expected.                                     │
│                                                                │
│            [Open RetroBat]      [Close]                        │
└────────────────────────────────────────────────────────────────┘
```

### Microinteractions

- Diff coloration: additions green, modifications yellow, removals red,
  unchanged context muted. Standard.
- "Apply for real" is the modal's primary, but it's *not* selected by
  default — the user must move focus to it. Prevents accidental Enter.
- If apply fails partway (e.g. permissions error on the second file),
  the success modal becomes a partial-failure modal: green check on
  written files, red X on failed, "Restore from backup" button next to
  failed entries.
- The current Save-then-apply auto-flow in `app.js` (`apply: true` in
  `collectProfile()`) should keep its behaviour but invoke this preview
  modal between save and apply. The existing one-click Save still
  saves the YAML; the apply portion goes through dry-run preview first.

### Open questions

- ❓ Do we want a "skip preview for the rest of this session"
  per-power-user toggle? Likely no — keeps the discipline. The
  Advanced drawer offers a "Run apply without preview" escape hatch
  if they really need it.
- ❓ How big can a diff get? If a user scaffolded 200 ROMs in one go,
  the modal's diff view needs scrolling and ideally collapsible
  per-section. Default to collapsed sections when total >50 lines.

---

## 8. Sync status (footer indicator)

**Intent.** `controller_sync.py` runs nightly via Task Scheduler. The
GUI surfaces this as a passive footer indicator — never interrupts —
so the user knows the catalog is fresh.

### Footer layout (sticky, full-width, low contrast)

```
┌────────────────────────────────────────────────────────────────────────┐
│  ● synced 14h ago  ·  12 controllers  ·  +1 this week     Advanced…   │
└────────────────────────────────────────────────────────────────────────┘
```

- Green dot: synced within last 48 h
- Yellow dot: synced 48 h–7 d ago
- Red dot: never synced or older than 7 d
- "+1 this week" is shown only when a new entry was added since last
  visit (we compare `entry_count` from `/api/sync-status` against
  `localStorage["rbcf-last-seen-sync-count"]`).

### Click behaviour

Click anywhere on the indicator: pops a small detail card

```
┌─────────────────────────────────────────────────────┐
│  Last sync   2026-05-03 03:00 (Task Scheduler)      │
│  Catalog     12 controllers (10 PC-native, 2 shim)  │
│  Added       8BitDo Ultimate 2 (this week)          │
│                                                     │
│  [Sync now]   [View log]   [Open task scheduler]    │
└─────────────────────────────────────────────────────┘
```

`Sync now` triggers `/api/sync` (already exists). Spinner replaces the
footer indicator while running. On success, indicator updates with
the new timestamp; on failure, indicator turns red with hover tooltip
"sync failed at HH:MM — view log".

### Microinteractions

- Footer never scrolls out of view — sticky bottom.
- Hover tooltip on the dot summarises the same info as the popover.
- The popover's `[View log]` opens a modal with the last 100 lines of
  `controller_sync.log` (tail behavior, scrollable, monospaced).

### Open questions

- ❓ Should "+N new this week" be more visible — e.g. a subtle pulse
  animation on the dot? Suggest: yes, but only for the first 24 h
  after detection.
- ❓ Open task scheduler — Windows-only path. On non-Windows (future-
  proofing), this button hides. Acceptable.

---

## 9. Error states catalogue

Exhaustive list. Each entry: trigger, surface, message, recovery.

### 9.1 RetroBat install not found

- **Trigger.** First-run probe + on every boot of the GUI we check that
  `RETROBAT_ROOT` from `config.py` exists and contains `emulationstation/`.
- **Surface.** Full-screen blocking onboarding panel (replaces normal
  onboarding overlay). User can't proceed without resolving.
- **Message.**

  > **We couldn't find RetroBat.**
  > We looked in `E:\RetroBat\` (default) and the registry, but came up
  > empty. If you have RetroBat installed somewhere else, point us at
  > the install root.
  >
  > [ E:\RetroBat\           ] [ Browse… ] [ Use this path ]
  >
  > [I don't have RetroBat installed yet — show me the download page]

- **Recovery.** Path persists to a new dotfile `.rbcfrc` in the project
  root (or `%APPDATA%/RB-Controller_fix/rbcfrc.json` post-packaging).
  On next launch, the resolved path is read first and the error is
  suppressed if the path now exists.

### 9.2 `es_settings.cfg` missing or malformed

- **Trigger.** `/api/scan` (or any read that touches `es_settings.cfg`)
  fails to parse it / file doesn't exist / `<systemList>` empty.
- **Surface.** Inline error banner at top of main content (not modal —
  the user might want to fix it externally and rescan).
- **Message.**

  > **es_settings.cfg looks broken.**
  > We expected `E:\RetroBat\emulationstation\.emulationstation\es_settings.cfg`
  > but it's `<reason>`. RetroBat regenerates this on first launch — try
  > launching RetroBat at least once, then [Rescan].
  >
  > [Rescan] [Open the file] [Show parse error]

- **Recovery.** On rescan, if it now reads, banner clears.

### 9.3 YAML profile invalid

- **Trigger.** `/api/profile` or `rbcf.py validate` returns a parse error
  (the `_error` field in `load_profile()` / a non-zero exit from validate).
- **Surface.** When loading a specific profile: in-line error in the
  game-detail header, replaces the title strip.
- **Message.**

  > **This profile won't parse.** `c64/Bruce Lee.crt.yaml` line 14:
  > "expected mapping value, found block end".
  > [Open file in editor] [Reset to system default] [Skip]

- **Recovery.** If the user picks "Reset to system default", we copy
  `_default.yaml` over the broken file *with backup* (write a
  `.bak.rbcf.broken.YYYYMMDD` first). On reload, profile parses.

### 9.4 SVG controller image missing for VID:PID

- **Trigger.** `controller_catalog.yaml` has no entry for VID:PID, OR
  the `gui/img/known/<vid>_<pid>.<ext>` file is missing despite a
  catalog entry.
- **Surface.** Device card thumbnail falls back to the existing "XI" /
  "HID" placeholder (already implemented in `loadDevices()`). Add: a
  small `[contribute]` link in the card's tooltip.
- **Message** (in tooltip).

  > No image catalogued for `2DC8:310B`. The nightly sync will try
  > Wikimedia next; if you have an image, drop it in `gui/img/contrib/`.

- **Recovery.** None required; the GUI works fine without the image.
  If sync grabs an image later, it appears on next reload.

### 9.5 HTTP server can't bind port 8765

- **Trigger.** `rbcf_gui.py` startup; `OSError: [Errno 10048]` (Windows
  port-in-use) or similar.
- **Surface.** This is a server-side error, not GUI. The browser will
  fail to connect at all. We instrument the launcher (`rbcf_gui.py`):

  > `[fatal] could not bind localhost:8765 — already in use.`
  > `Try: py rbcf_gui.py --port 8766`

- **Recovery.** Default-port fallback on next launch: if 8765 is taken,
  try 8766..8770 in order, log the chosen port to console + a
  `last_port.txt` so the auto-open `webbrowser` call uses the right
  URL. (Existing code does `--port` arg only — augmenting this is a
  small backend change. Out of scope for Stream D, but flag it.)

### 9.6 Permissions error writing backup or config

- **Trigger.** Any write into `E:\RetroBat\…` fails with `PermissionError`.
- **Surface.** Apply/dry-run modal goes into partial-failure state
  (see Flow 7). Toast: red, sticky (no auto-dismiss) until the user
  clicks it.
- **Message.**

  > **Couldn't write to RetroBat.** Permission denied on
  > `E:\RetroBat\…\es_settings.cfg`. RetroBat may be running, or the
  > file may be read-only.
  >
  > [Try again] [Open file properties] [Show what would have changed]

- **Recovery.** "Try again" reruns just the failed write, not the
  whole apply. If RetroBat is running and the file is locked, this
  matters — we want the user to close RetroBat and retry without
  losing any of the rest of the apply's progress.

### 9.7 (Bonus) Probe failure on Windows

- **Trigger.** `probe_devices()` returns `[{"error": ...}]` (existing
  shape). Currently the GUI silently shows "probe error: …" in the
  drawer summary.
- **Surface.** Promote: device drawer expands (overrides collapsed
  default just for this case), shows a structured error panel, with a
  retry button.
- **Message.**

  > **Couldn't enumerate HID devices.** PowerShell exited with `<rc>`.
  > We use `Get-PnpDevice` to list controllers — if PowerShell is
  > restricted by Group Policy, this can fail.
  >
  > [Retry] [Show command] [Documentation]

- **Recovery.** Retry button reruns `/api/devices`.

---

## 10. Accessibility / keyboard nav notes

The GUI is a single-page tool used primarily with mouse + gamepad
(ironically). Keyboard nav is "minimal but non-zero" per the task brief.

### Tab order

1. Header brand (focusable but not actionable — no tabstop)
2. Pad status pill (focusable, opens device drawer on Enter — pseudo-link)
3. Device drawer toggle (chevron)
4. Inside device drawer (when expanded): each device card, then Rescan
5. System dropdown
6. Game dropdown
7. Apply
8. Save profile
9. Inside source pane: nothing focusable (purely visual)
10. Inside target pane: nothing focusable
11. Inside mappings section: each text input, in region order
12. Inside game-options section: each select/checkbox, in declaration order
13. Notes textarea
14. Footer: Advanced link, sync indicator

### Focus rings

Visible 2px outline using `--blue` at 60 % alpha, never removed. Buttons
get a slightly inset variant; inputs get the standard outline.

### Keyboard shortcuts (very limited)

- `Esc` closes any open modal / drawer.
- `Enter` confirms primary action in modals (but never the destructive
  one — user must Tab to "Apply for real" / "Confirm fold" / etc).
- `Ctrl+S` (when a profile is loaded): triggers Save profile. This is a
  power-user nicety; advertise only via tooltip.
- No global hotkeys beyond that.

### Screen reader

- Every SVG icon used decoratively has `aria-hidden="true"` (already
  the case in current `index.html`).
- Buttons have descriptive titles where the visible label is short
  (already done: "Push all saved profiles to RetroBat" on Apply).
- Toasts use `aria-live="polite"` (need to add — current toast div
  doesn't declare it). Errors use `aria-live="assertive"`.
- The diff preview modal has a heading like "Preview of changes — 2
  files, 7 lines" announced first so SR users get context before
  diving in.

### Reduced-motion

`@media (prefers-reduced-motion: reduce)`: drawer slide-in becomes
instantaneous, banner pulses are removed, modal fade is instantaneous.
Microinteractions described above as "200 ms cubic-bezier" all collapse
to 0 ms.

### Open questions

- ❓ Is there demand for full keyboard-only operation (every flow
  reachable without mouse)? The mappings input forms work fine with
  Tab; the dual-8BitDo identify flow is gamepad-driven by definition;
  the diff preview is read-only. So basically yes by default. Confirm
  with user.
- ❓ Do we need a high-contrast theme? The current dark theme is fine
  for most users but `--bd-1` and `--bd-2` are quite close. Could
  ship a high-contrast variant behind a localStorage toggle.

---

## Appendix A — Endpoints we want (names only)

Backend stream picks these up later. Stream D references these by name
across the flows above; no request/response spec here on purpose.

- `GET /api/scan` — combined first-run summary: RetroBat root, systems,
  ROM counts, profile coverage, pad summary. Replaces the four parallel
  calls the current `init()` makes when the user lands fresh.
- `POST /api/scaffold-all` — write a scaffold profile (T confidence)
  for every ROM that doesn't have one across all systems.
- `POST /api/scaffold-system` — same, scoped to one system.
- `POST /api/apply` (extend existing) — accept `{dry_run: true}`.
  Response should include diff data for the modal.
- `POST /api/fold-guids` — Stream B owns this. Accept canonical GUID +
  list of GUIDs to fold.
- `GET /api/conflicts` — return list of `core_options` keys with
  conflicting values across profiles.
- `GET /api/backups` — list `.bak.rbcf.*` files in the RetroBat dirs we
  touch.
- `GET /api/validate-profile?system&rom` — wraps the relevant
  `rbcf.py validate` slice for a single profile.
- `POST /api/retrobat-root` — persist a user-provided RetroBat root to
  `.rbcfrc` / `%APPDATA%`.

---

## Appendix B — localStorage keys

All under `rbcf-` prefix per CLAUDE.md.

| Key | Purpose | Set in |
|-----|---------|--------|
| `rbcf-onboarded` | "1" once user has been through Flow 1 | Flow 1 |
| `rbcf-active-pad-index` | which `pad.index` drives the source SVG | exists today |
| `rbcf-device-bar-expanded` | drawer state | exists today |
| `rbcf-collapsed` | which `<section>`s are collapsed | exists today |
| `rbcf-pad-label-<instance_id>` | user's name for a specific pad | Flow 2 |
| `rbcf-skip-empty-banner-<system>` | suppress "no profiles" banner per system | Flow 3 |
| `rbcf-show-inheritance` | inheritance overlay on/off | Flow 4 |
| `rbcf-dismissed-drift-<vidpid>` | drift banner dismiss date | Flow 6 |
| `rbcf-last-seen-sync-count` | for "+N new this week" | Flow 8 |

---

## Open questions consolidated (for the user)

The riskiest ones first. Marked `❓` so they're greppable.

**Top 3 — please weigh in before UI implementation begins:**

1. ❓ **Inheritance overlay default state (Flow 4).** On by default
   gives more information up front but is visually noisier. Off by
   default is cleaner but novice users may not realise it exists.
   Suggest: off by default, sticky once toggled, with a one-time
   tooltip hint pointing at the toggle on first profile open. Confirm?

2. ❓ **Should "Scaffold all" auto-create `_default.yaml` for systems
   that don't have one (Flow 1)?** Currently amiga1200 has no default
   shipped. Auto-creating it from amiga500's would be safe (same core,
   puae) but maybe over-stepping. Suggest: yes, copy from amiga500 with
   a note, but ask the user every time. Confirm?

3. ❓ **GUID drift fold confidence threshold (Flow 6).** Stream B will
   provide a confidence score; below what threshold does the UI refuse
   to auto-suggest fold? Suggest: 0.85+ for the banner, 0.65+ for "Show
   details" exposing the fold action, below 0.65 we just log and don't
   surface anything.

**Lower-priority:**

4. ❓ Onboarding option for "import from existing install" (Flow 1).
5. ❓ Persist pad labels server-side or localStorage-only (Flow 2)?
6. ❓ Show-only-unprofiled toggle persistence scope (Flow 3).
7. ❓ Confidence pill: should clearing an override prompt for revert?
   (Flow 4). Suggest: silent, since save normaliser drops empties.
8. ❓ Conflict resolution: scope-by-system option (Flow 5)?
9. ❓ Skip-preview escape hatch for power users (Flow 7)? Suggest no.
10. ❓ Pulse animation on sync footer dot when "+N this week" (Flow 8)?
11. ❓ Full keyboard-only operation as a goal (Flow 10)?
12. ❓ High-contrast theme variant (Flow 10)?
13. ❓ Auto-fold permanently option vs dismiss-30-days (Flow 6)?
14. ❓ Diff preview default-collapse threshold (Flow 7) — 50 lines?

---

*End of document.*
