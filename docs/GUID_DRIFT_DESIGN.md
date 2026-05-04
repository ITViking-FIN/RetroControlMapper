# GUID drift — design

Status: draft, Stream B, 2026-05-03
Owner module: `guid_aliases.py` (scaffold only; bodies pending review)
Related: `CLAUDE.md` (headline bug), `rbcf_gui.py::probe_devices()` (HID probe — read-only reference)

---

## 1. Problem statement

The user-reported "RetroBat keeps forgetting controller settings" bug is a
direct consequence of how SDL2 derives the GUID it uses to key autoconfig
entries. EmulationStation persists per-controller mappings to
`es_input.cfg` as `<inputConfig deviceGUID="…" deviceName="…">` blocks,
and the launcher matches a connected pad to its mapping by exact-string
deviceGUID. If the GUID changes for any reason, the controller is treated
as brand-new and the user is dropped into the "Configure Input" wizard.

The SDL2 GUID is **not** a stable hardware identifier. It is a 128-bit
synthesis of HID descriptor fields (see SDL2 source
`src/joystick/SDL_joystick.c` → `SDL_CreateJoystickGUID()`, called from
`src/joystick/hidapi/SDL_hidapijoystick.c::HIDAPI_AddDevice()`). The byte
layout, in little-endian 16-bit words:

| Word | Bytes | Field                          | Stable across reconnect? |
|------|-------|--------------------------------|--------------------------|
| 0    | 0–1   | `bus_type` (USB=`0x03`, BT=`0x05`, etc.) | **No** — flips on USB↔Bluetooth |
| 1    | 2–3   | CRC16 of `"<vendor> <product>"` strings  | **No** — name strings vary by driver / OS pairing |
| 2    | 4–5   | Vendor ID                                | **Yes** (when reported) |
| 3    | 6–7   | `0x0000` padding                          | yes (fixed) |
| 4    | 8–9   | Product ID                                | **Yes** (when reported) |
| 5    | 10–11 | `0x0000` padding                          | yes (fixed) |
| 6    | 12–13 | `release` / firmware version              | **No** — drivers report different versions |
| —    | 14    | driver signature (`'h'` HIDAPI, `'x'` XInput, …) | **No** — flips on driver swap |
| —    | 15    | driver-dependent type byte                | **No** |

Concrete evidence: an Xbox One Elite Series 2 over USB enumerates as
`03005d085e040000000b000011050000`, and the *same physical pad* over
Bluetooth enumerates as `05005d085e040000220b000017050000`. Bytes 4–5
(`5e04` → VID 0x045E, Microsoft) and 8–9 (`0b00` → PID 0x000B) are
identical. Word 0 (bus), word 1 (name CRC), word 6 (version), and the
driver byte all change. (Source: SDL2 commit history "Use the bus in
the HIDAPI joystick guid now that it's available", discourse thread on
libsdl.org.)

This is **by design** in SDL — the GUID is intended to identify a
"capability surface", not a physical device — but it is also exactly
why RetroBat's autoconfig "forgets" the pad on every transport hop.

## 2. Reproduction patterns observed in the wild

All of the following produce a fresh GUID for a previously-configured
pad, triggering the "configure input" prompt on next ES launch:

1. **USB ↔ Bluetooth swap** — bus byte changes (`0x03` ↔ `0x05`).
   Affects every modern wireless pad (DualSense, Xbox Wireless, 8BitDo
   Ultimate dock vs paired BT, Switch Pro, etc.).
2. **USB port hop** — should be GUID-stable, but in practice some hub
   chipsets (especially front-panel USB 3 hubs) re-enumerate the device
   with a different `release` value or a slightly different product
   string, perturbing the name CRC.
3. **Dongle reset / re-pair** — 8BitDo dongles in particular re-issue
   the HID product string after a firmware-internal re-pair, changing
   the CRC.
4. **Steam Input or DS4Windows hooking the device** — these inject a
   virtual XInput device (driver byte `'x'`) alongside or replacing the
   raw HIDAPI device (driver byte `'h'`). The VID:PID often gets rewritten
   to Steam's virtual VID (`28DE`) or ViGEm's emulated Xbox 360
   (`045E:028E`), which is a *different* alias problem — see §6.
5. **XInput ↔ DInput driver swap** — pads with a mode toggle (8BitDo's
   X/D switch, the user has two of these) flip driver byte and name
   string simultaneously.
6. **Windows driver update** — a manufacturer driver pushed via Windows
   Update can rewrite the HID name strings, changing the CRC even though
   nothing physical changed.

## 3. Detection strategy

### 3.1 Alias group definition

An **alias group** is a set of SDL GUIDs that we believe map to a single
physical pad. The grouping key is `(VID, PID, instance_path_prefix)`:

- `VID:PID` is taken from bytes 4–5 and 8–9 of the GUID. These are stable
  across all the perturbations in §2 — the only stability anchor SDL
  gives us.
- `instance_path_prefix` is a coarsened form of the Windows HID
  `InstanceId` (already collected by `probe_devices()` in `rbcf_gui.py`,
  e.g. `HID\VID_2DC8&PID_3106&MI_00\7&abcd1234&0&0000`). We coarsen by
  stripping the trailing port-enumeration suffix and keeping the
  bus / VID / PID / collection-index portion. This lets us tell two
  identical 8BitDo Ultimates apart even though their VID:PIDs are
  identical — see §6.

### 3.2 Sources of GUIDs

We have three GUID sources, in order of recency:

1. **Currently-connected** — derived live from `Get-PnpDevice`. The HID
   probe gives us VID:PID and InstanceId; the GUID itself is computed by
   SDL inside ES, so we don't get it directly here. We use VID:PID as
   the join key.
2. **`es_input.cfg` history** — every `<inputConfig deviceGUID="…">` ever
   written by ES is sitting in this file, even ones for now-disconnected
   pads. ES never garbage-collects entries. This is our gold mine: every
   GUID alias the user has ever seen for a given pad is already on disk.
3. **`emulatorlauncher.log`** — RetroBat-Official's launcher logs the
   resolved GUID per launch. This is a fallback for when es_input.cfg
   hasn't yet captured a freshly-drifted alias. (Out of scope for v1;
   v1 reads only `es_input.cfg`.)

### 3.3 Cross-referencing

`parse_es_input()` extracts every `<inputConfig>` with `deviceGUID` and
`deviceName`. For each, we extract VID/PID from GUID bytes 4–5 and 8–9.
We then group by `(VID, PID)` to form candidate alias groups. The
currently-connected pad's VID:PID picks which group is "active".

If two physical pads share VID:PID (the dual-8BitDo case), the
`es_input.cfg` entries are still indistinguishable on GUID alone — but
they are distinguishable at *runtime* via InstanceId. See §6.

## 4. Mitigation A — write-time expansion

Trigger: invoked from the GUI ("Fold aliases for this pad") or after the
user finishes ES's input-configure wizard for a pad we already know.

Algorithm:

1. Parse `es_input.cfg` → `list[GuidAlias]`.
2. Group by `(VID, PID)`. Pick the group containing the just-configured
   GUID.
3. The just-configured `<inputConfig>` block is the source of truth.
4. For every other GUID in the group:
   - if a block already exists for it, replace its `<input …/>` children
     with a deep copy from the source-of-truth block. Keep its existing
     `deviceName` (cosmetic — what the user sees in the ES UI when that
     transport reconnects).
   - if no block exists, synthesise one with the source-of-truth's
     `<input>` children and a placeholder `deviceName="…(alias)"`.
5. Write back atomically (temp + rename), with a `.bak.rbcf.<date>`
   one-shot per day, matching the convention in `CLAUDE.md` §
   Conventions.

The result: regardless of which transport / driver permutation the user
boots into, ES finds a matching `deviceGUID` entry on first lookup and
skips the wizard.

## 5. Mitigation B — read-time watcher

Mitigation A only covers GUIDs we've already seen. A new alias can
appear mid-session (user un-docks an 8BitDo and pairs over Bluetooth,
new bus byte → new GUID, ES auto-configures it from its internal
gamecontrollerdb on next launch and writes a fresh inputConfig block
**without** the user's per-pad customisations).

Mitigation B is a watcher that:

1. Polls `es_input.cfg` mtime (or uses `ReadDirectoryChangesW` via a
   tiny PowerShell helper — no new Python deps; matches CLAUDE.md
   constraint).
2. On change, re-runs the alias-fold pass (§4) — but only fires if a
   *new* GUID has appeared in a known alias group. Idempotent: re-fold
   on no-op is a no-op.
3. Backs off for N seconds after firing to avoid an mtime feedback loop
   with itself.

Two delivery options for the watcher (❓ user decision):

- **Desktop daemon**: launched at login via the existing
  `setup_schedule.ps1` Task Scheduler entry pattern. Pro: shares a
  process with our nightly Wikimedia sync; con: invisible if it
  crashes.
- **GUI-attached**: only runs while `rbcf_gui.py` is open. Pro:
  visible, easy to debug; con: doesn't help the headline bug if the
  user closes the GUI before launching ES.

## 6. Disambiguating the dual-pad case

The user has two 8BitDo Ultimates of the same model (`2DC8:3106`) per
`CLAUDE.md`. Naive `(VID, PID)` grouping would fold both pads' aliases
into one group, then write each pad's mapping over the other's on every
launch — worse than no fix.

Disambiguation hierarchy:

1. **Windows HID `InstanceId`** is unique per physical-port-instance,
   even for two identical pads. Format
   `HID\VID_2DC8&PID_3106&MI_00\<bus-prefix>&<rng>&<port>&<col>`. The
   `<rng>` segment is generated at first-enumeration and persists in
   the registry across reboots for as long as the pad is plugged into
   the same port; it rotates on port hop. This is our best-available
   disambiguator. We persist `(GUID → InstanceId)` observations to a
   small sidecar file (`%APPDATA%/RB-Controller_fix/guid_aliases.json`)
   so we can match on next reconnect even if the live HID enumeration
   is in a different order.
2. **deviceName fallback**: if the live probe shows two pads with the
   same VID:PID, and `es_input.cfg` has two different deviceNames for
   that VID:PID (e.g. "8BitDo Ultimate" vs "8BitDo Ultimate (P2)"
   because the user renamed one), use deviceName as the secondary key.
3. **User confirmation in GUI**: when grouping is ambiguous and we
   can't disambiguate from data alone, surface a "We see 2 pads with
   the same VID:PID — confirm which alias set belongs to which" UI.
   ❓ See §8 for UX.

## 7. Risks

- **False fold** between two physically different pads with identical
  VID:PID — see §6. Mitigated, but never zero, because Windows can
  rotate the InstanceId rng segment under us. The watcher must
  *never* silently overwrite a deviceGUID block whose deviceName
  doesn't match what we recorded; it must surface the conflict.
- **es_input.cfg corruption** — we are now writing to a file ES owns.
  Atomic rename + daily `.bak.rbcf.<date>` is the floor, plus a
  schema sanity-check before write (don't proceed if the file fails
  to round-trip parse).
- **Schema drift in EmulationStation** — the `<inputConfig>` element
  shape is stable across ES forks (vanilla, RetroBat, Batocera,
  Recalbox all share it) but RetroBat-Official could in principle
  add attributes. Round-trip the XML preserving all unknown
  attributes / children verbatim.
- **Double-fire with ES's own write** — Mitigation B sees ES write
  the file; Mitigation B writes it; ES isn't running at write time so
  there's no read race, but if the user re-launches ES before our
  rewrite settles, ES reads stale content. Use `os.replace` for
  atomicity and back off ≥ 1 s after detected mtime change before
  acting.
- **Steam Input / DS4Windows alias** (§2.4) — these inject *virtual*
  pads with a different VID:PID. Folding them into the physical pad's
  group is **wrong** because the button capability surface differs
  (virtual pads always present as Xbox 360). Detect and exclude
  Steam (VID `28DE`) and ViGEm (`045E:028E` with no matching real
  Xbox InstanceId) from grouping.

## 8. Decision points (❓ for user)

1. **❓ Watcher delivery**: Task Scheduler login-daemon, or
   GUI-attached only? See §5.
2. **❓ Block strategy**: duplicate `<inputConfig>` block per alias
   GUID (current proposal — explicit, ES-native), or a single block
   with a `deviceGUIDs="g1,g2,g3"` extension (cleaner, but requires
   teaching ES to parse it — non-starter unless we patch ES, which we
   won't).
3. **❓ GUI surfacing**: when fold opportunity is detected
   ("I found 3 aliases for your pad — fold them?"), is this a passive
   banner the user can dismiss, or a modal that interrupts? Suggest
   passive banner + an explicit action button on the device card.
4. **❓ Dual-pad UX**: when two physical pads share VID:PID and we
   need user confirmation, do we ask once and persist, or every time
   the InstanceId rotates? Suggest: ask once, persist to
   `guid_aliases.json`, re-ask only if the persisted mapping is
   contradicted by live evidence.
5. **❓ `bak` retention**: CLAUDE.md says one bak per file per day.
   For `es_input.cfg`, where the watcher could rewrite many times in
   one session, do we want one bak per actual mutation instead?
   Suggest: keep the daily bak as the user-facing rollback, but also
   ring-buffer the last N mutations to a hidden `.bak.history/` for
   debugging.

## 9. API sketch (`guid_aliases.py`)

```python
@dataclass
class GuidAlias:
    guid: str            # 32-hex-char SDL GUID, lowercase
    vid: str             # 4-hex-char, uppercase, e.g. "2DC8"
    pid: str             # 4-hex-char, uppercase, e.g. "3106"
    instance_id: str | None   # Windows HID InstanceId if known
    last_seen: str | None     # ISO-8601 timestamp from sidecar history

def parse_es_input(path: Path) -> list[GuidAlias]: ...
def group_aliases(aliases: list[GuidAlias]) -> dict[tuple[str, str], list[GuidAlias]]: ...
def expand_inputconfig(es_input_path: Path,
                       group: list[GuidAlias],
                       dry: bool) -> tuple[int, int]: ...
```

`expand_inputconfig` returns `(added, kept)`: number of new
`<inputConfig>` blocks synthesised, number of existing ones updated
in-place. `dry=True` returns the same counts without writing.

Future additions (post-review):

- `extract_vid_pid(guid: str) -> tuple[str, str]` — helper that pulls
  bytes 4–5 and 8–9. Trivial; deferred to keep scaffold minimal.
- `disambiguate(group, live_devices) -> list[list[GuidAlias]]` — split
  a VID:PID group into per-physical-pad subgroups using §6 logic.
- `watch(es_input_path, on_change)` — Mitigation B entrypoint.

---

## References

- SDL2 source — `src/joystick/SDL_joystick.c::SDL_CreateJoystickGUID`,
  `src/joystick/hidapi/SDL_hidapijoystick.c::HIDAPI_AddDevice`.
- SDL discourse thread "Use the bus in the HIDAPI joystick guid now
  that it's available" (libsdl-org commit history) — concrete proof
  that bus byte differs USB vs BT for the same pad.
- Game Controller Collective wiki, "SDL Joystick GUID" — canonical
  byte-layout breakdown.
- RetroBat wiki, "Controllers Configuration" — confirms es_input.cfg
  location and SDL-GUID-keyed match.
- RetroBat-Official/emulatorlauncher
  `emulatorLauncher/Generators/LibRetro.Generator.cs` — the wider
  controller-config regeneration story (referenced from CLAUDE.md);
  note: this file does *not* itself touch es_input.cfg, which is owned
  by EmulationStation proper, not the launcher. The launcher consumes
  the deviceGUID via its `Common/Joysticks/` helpers (filenames
  unverified at write time — to be confirmed when integrating).
- `rbcf_gui.py::probe_devices()` (this repo) — read-only reference for
  the HID enumeration strategy, including the `&IG_` XInput marker
  and InstanceId VID:PID extraction.
