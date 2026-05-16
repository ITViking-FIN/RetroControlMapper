// app.js — RB-Controller_fix step 2 with inline SVGs.
// Depends on controllers.js (loaded before this).

const $  = (id) => document.getElementById(id);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

// ============================================================
// Theme (Frosted Acrylic — Light / Dark / Auto)
// Runs *before* init() so the page never flashes the wrong theme.
// localStorage 'rbcf-theme' = 'light' | 'dark' | 'auto'  (default: 'auto').
// The body's data-theme attribute drives the CSS token cascade.
// ============================================================

const THEME_STORAGE_KEY = 'rbcf-theme';
const THEME_VALUES = ['light', 'dark', 'auto'];

function getTheme() {
  try {
    const v = localStorage.getItem(THEME_STORAGE_KEY);
    return THEME_VALUES.includes(v) ? v : 'auto';
  } catch (e) { return 'auto'; }
}
function setTheme(value) {
  const v = THEME_VALUES.includes(value) ? value : 'auto';
  try { localStorage.setItem(THEME_STORAGE_KEY, v); } catch (e) { /* ignore */ }
  document.body.setAttribute('data-theme', v);
  return v;
}
// Apply immediately (body always exists by the time app.js runs since the
// script tag is at the end of <body>).
setTheme(getTheme());

// Header pad-list: a container holding one .pad-pill button per detected
// controller, plus a standalone Rescan icon button. Rendered by renderPadList().
const padList   = $('pad-list');
const padName   = $('pad-name');             // source pane subtitle ("17 buttons · 4 axes")
const targetName = $('target-name');
const fixedNote = $('fixed-mapping-note');
const fixedNoteWrap = $('fixed-mapping-note-wrap');
const srcHost   = $('src-host');
const tgtHost   = $('tgt-host');
const selSystem = $('sel-system');
const selGame   = $('sel-game');
const mapGrid   = $('mappings-grid');
const gameOpts  = $('game-options');
const notesEl   = $('notes');
const toast     = $('toast');
const statusLine = $('status-line');

let SYSTEMS = [];
let SYSTEM_OPTIONS = {};
let CORE_MAPPER_PREFIX = {};
let PAD_BUTTONS = [];
let currentTargetController = null;  // e.g. "cd32_pad" or "joystick_1btn"

// ============================================================
// Toasts
// ============================================================

const TOAST_ICONS = {
  success: '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
  error:   '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
  info:    '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
};

let toastTimer = null;
function showToast(msg, kind = 'info', ms = 3500) {
  const icon = TOAST_ICONS[kind] || TOAST_ICONS.info;
  toast.innerHTML = `${icon}<span class="toast-msg"></span>`;
  toast.querySelector('.toast-msg').textContent = msg;
  toast.className = `toast ${kind}`;
  toast.classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.add('hidden'), ms);
}

// ============================================================
// SVG injection
// ============================================================

function setSourceSVG() {
  // Single source SVG for now (XInput layout matches every modern pad)
  srcHost.innerHTML = SRC_XINPUT;
}

// Default descriptor for systems we know nothing specific about — gives
// the user a generic XInput-shaped target with d-pad / 4 face buttons /
// L+R / Start+Select. Better than an empty state because the
// click-across binding flow still works, and the user can refine the
// layout per-system later (Phase B in v0.1.4).
const GENERIC_TARGET_LAYOUT = {
  face: { layout: 'diamond', count: 4, labels: ['1', '2', '3', '4'] },
  dpad: true,
  sticks: 1,
  shoulders: 2,
  start: true,
  select: true,
  label: 'Generic — 1 stick + d-pad + 4 buttons + L/R',
};

function setTargetSVG(targetCtrl, layout) {
  currentTargetController = targetCtrl;
  const svg = TARGET_SVGS[targetCtrl];
  if (svg) {
    tgtHost.innerHTML = svg;
    return;
  }
  // Fallback chain: explicit layout from system config → generic default.
  // Either way, the user gets a working schematic, never an empty pane.
  if (typeof generateTargetSvg === 'function') {
    const desc = layout || GENERIC_TARGET_LAYOUT;
    const generated = generateTargetSvg(desc);
    if (generated) {
      tgtHost.innerHTML = generated;
      // Mark the wrapper so we can style/hint generic vs curated differently
      tgtHost.classList.toggle('is-generic', !layout);
      tgtHost.classList.toggle('is-layout-derived', !!layout);
      return;
    }
  }
  tgtHost.innerHTML = `
    <div class="empty-state">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg>
      <span>No target controller diagram for this system yet.</span>
    </div>`;
}

// ============================================================
// Live highlights
// ============================================================

// User-selected pad index — clicking a pad-pill (or "Use as active source"
// inside the pad-pill popover) switches which gamepad drives the live
// highlights. Persisted across reloads.
let activePadIndex = parseInt(localStorage.getItem('rbcf-active-pad-index') || '0', 10);

function pickGamepad() {
  const pads = navigator.getGamepads ? navigator.getGamepads() : [];
  // Honour the user's selection if that index is currently connected.
  const sel = pads[activePadIndex];
  if (sel && sel.connected) return sel;
  // The user explicitly picked an index. Don't silently flip to a different
  // pad — on Windows the XInput slot for an active pad can briefly read
  // null during driver / Bluetooth churn, and the old fallback used to
  // overwrite activePadIndex on those frames, so "switch back to controller
  // #1" never stuck. Return null and let the caller render a "no pad" state.
  // The user will see it and pick again, or wait for the slot to come back.
  if (activePadIndex !== 0 || localStorage.getItem('rbcf-active-pad-index') !== null) {
    return null;
  }
  // First-run case — no explicit user pick yet — fall back to first connected.
  for (let i = 0; i < pads.length; i++) {
    if (pads[i] && pads[i].connected) {
      return pads[i];
    }
  }
  return null;
}

function setActivePad(index) {
  activePadIndex = index;
  localStorage.setItem('rbcf-active-pad-index', String(index));
  // Repaint the header pad-list so the green dot moves to the new active pill.
  // (The old loop that toggled `.active` on `.device-card` chips was removed
  // when Stream Z2 retired the device-bar; the pad-list now owns active state.)
  renderPadList();
}

// ---- Pad-list: one candy pill per detected controller --------------------
//
// The header now holds N pills — one per probed device — plus a standalone
// Rescan icon button at the right. Every pill uses the candy-gradient style;
// the active one prepends a green status dot via the .is-active class.
//
// Triggered by: every successful loadDevices(), setActivePad(),
// gamepadconnected / gamepaddisconnected.

let LAST_DEVICES = [];

function deviceFriendlyName(d) {
  if (!d) return '(no controller)';
  return d.name || d.friendly_name || `${d.vid}:${d.pid}` || '(no controller)';
}

function pickFriendlyName() {
  if (!LAST_DEVICES || !LAST_DEVICES.length) return '(no controller)';
  const dev = LAST_DEVICES[activePadIndex] || LAST_DEVICES[0];
  return deviceFriendlyName(dev);
}

// Truncate a friendly name to ~24 chars (CSS handles ellipsis on overflow,
// but a hard cap keeps the pill from ballooning before measurement).
function truncateName(name, max = 24) {
  if (!name) return '';
  return name.length > max ? name.slice(0, max - 1) + '…' : name;
}

// Inline SVGs reused by pill rendering.
const _PAD_CHEVRON_SVG = '<svg class="pad-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 12 15 18 9"/></svg>';
const _RESCAN_SVG = '<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 0 1 15.5-6.3L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15.5 6.3L3 16"/><path d="M3 21v-5h5"/></svg>';

// Build one .pad-pill button for the given device (or a placeholder if dev is null).
function _buildPadPill(dev, idx) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'pad-pill';
  btn.setAttribute('aria-haspopup', 'dialog');
  btn.setAttribute('aria-expanded', 'false');
  if (dev) {
    btn.dataset.padIndex = String(idx);
    btn.dataset.key = dev.key || `${dev.vid}:${dev.pid}`;
    if (idx === activePadIndex) btn.classList.add('is-active');
    const friendly = deviceFriendlyName(dev);
    btn.title = idx === activePadIndex
      ? `${friendly} — active source. Click to view details.`
      : `${friendly} — click to make active and view details.`;
    btn.innerHTML =
      `<span class="pad-name-short">${rbcfEsc(truncateName(friendly))}</span>${_PAD_CHEVRON_SVG}`;
  } else {
    // Empty-state placeholder pill.
    btn.classList.add('is-placeholder');
    btn.dataset.padIndex = '-1';
    btn.title = 'No controllers detected — click to rescan';
    btn.innerHTML =
      '<span class="pad-name-short">No controllers · Rescan</span>' + _PAD_CHEVRON_SVG;
  }
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    onPadPillClick(btn, dev, idx);
  });
  return btn;
}

// Render the standalone header Rescan icon button.
function _buildRescanQuick() {
  const btn = document.createElement('button');
  btn.id = 'btn-rescan-quick';
  btn.type = 'button';
  btn.className = 'rescan-quick';
  btn.title = 'Rescan controllers';
  btn.setAttribute('aria-label', 'Rescan controllers');
  btn.innerHTML = _RESCAN_SVG;
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    loadDevices();
  });
  return btn;
}

// Re-render the header pad-list from LAST_DEVICES + activePadIndex.
function renderPadList() {
  if (!padList) return;
  // Preserve aria-expanded state from any existing open popover so we can
  // restore it on the matching new pill (popover stays open across re-renders).
  const openPadIdx = (() => {
    const pop = $('rbcf-device-popover');
    return pop ? parseInt(pop.dataset.padIdx ?? '-1', 10) : -2;
  })();

  padList.innerHTML = '';
  if (!LAST_DEVICES.length) {
    padList.appendChild(_buildPadPill(null, -1));
  } else {
    LAST_DEVICES.forEach((d, i) => {
      const pill = _buildPadPill(d, i);
      if (i === openPadIdx) pill.setAttribute('aria-expanded', 'true');
      padList.appendChild(pill);
    });
  }
  padList.appendChild(_buildRescanQuick());
}

// Click dispatch from a pill.
function onPadPillClick(pillEl, dev, idx) {
  // Empty-state placeholder → just trigger a rescan and open empty popover.
  if (!dev) {
    if ($('rbcf-device-popover')) {
      dismissDevicePopover();
    } else {
      showDevicePopover(-1, pillEl);
    }
    return;
  }
  // Toggle if this same pill's popover is already open.
  const pop = $('rbcf-device-popover');
  if (pop && parseInt(pop.dataset.padIdx ?? '-2', 10) === idx) {
    dismissDevicePopover();
    return;
  }
  // Switch active source if the user picked a different pill.
  if (idx !== activePadIndex) {
    setActivePad(idx);
    // setActivePad re-rendered the pad-list — find the freshly-rendered pill
    // at the same index so the popover anchors to the live DOM node.
    const refreshed = padList.querySelector(`.pad-pill[data-pad-index="${idx}"]`);
    showDevicePopover(idx, refreshed || pillEl);
  } else {
    showDevicePopover(idx, pillEl);
  }
}

// Track previous-frame button state so we can detect release→press
// transitions (for click-across arm-on-press, which should fire once
// per discrete button press, not every frame the button is held).
let _prevButtonState = {};

function updateGamepad() {
  const pad = pickGamepad();

  if (!pad) {
    // Pill rendering is driven by loadDevices() / setActivePad() / connect
    // events, not by this 60Hz polling loop. Just clear the source-pane label.
    padName.textContent = '—';
    $$('.src-btn.pressed, .tgt-btn.pressed, .map-row.pressed').forEach(el => el.classList.remove('pressed'));
    _prevButtonState = {};
    // Keep the live-counts line in any open popover fresh (it reads from pad).
    refreshPopoverLiveCounts();
    return;
  }
  padName.textContent = `${pad.buttons.length} buttons · ${pad.axes.length} axes`;
  refreshPopoverLiveCounts();

  const sysId = selSystem.value;
  const tgtMap = TARGET_MAPPINGS[sysId] || {};

  // Clear all pressed states first
  $$('.src-btn.pressed, .tgt-btn.pressed, .map-row.pressed').forEach(el => el.classList.remove('pressed'));

  // Buttons
  const newState = {};
  for (let i = 0; i < pad.buttons.length; i++) {
    const btn = pad.buttons[i];
    const isPressed = !!(btn && btn.pressed);
    newState[i] = isPressed;
    // Click-across arm-on-press: fire only on release→press transition,
    // and only when click-across is active for this system.
    if (_clickAcrossEnabled && isPressed && !_prevButtonState[i]) {
      const name = PAD_INDEX_TO_NAME[i];
      if (name) armSource(name);
    }
    if (!isPressed) continue;
    const name = PAD_INDEX_TO_NAME[i];
    if (!name) continue;
    // Source SVG
    const srcEl = document.getElementById(`src-btn-${name}`);
    if (srcEl) srcEl.classList.add('pressed');
    // Target SVG
    const tgtName = tgtMap[name];
    if (tgtName) {
      const tgtEl = document.getElementById(`tgt-btn-${tgtName}`);
      if (tgtEl) tgtEl.classList.add('pressed');
    }
    // Mapping row
    const row = document.querySelector(`.map-row[data-pad-btn="${name}"]`);
    if (row) row.classList.add('pressed');
  }

  // Axes — highlight the STICK on source (not d-pad) and the equivalent
  // direction on TARGET (since libretro analog_dpad_mode=1 routes stick→d-pad).
  const stickThreshold = 0.4;
  handleStick('l3', 'src-l3-knob', pad.axes[0] || 0, pad.axes[1] || 0, stickThreshold, tgtMap);
  handleStick('r3', 'src-r3-knob', pad.axes[2] || 0, pad.axes[3] || 0, stickThreshold, tgtMap);

  _prevButtonState = newState;
}

function handleStick(srcId, knobId, ax, ay, threshold, tgtMap) {
  const stickEl = document.getElementById(`src-btn-${srcId}`);
  const knob = document.getElementById(knobId);
  const moved = Math.abs(ax) > threshold || Math.abs(ay) > threshold;
  if (stickEl) {
    if (moved) stickEl.classList.add('moved');
    else       stickEl.classList.remove('moved');
  }
  if (knob) {
    // Translate the knob in SVG user units (~10 units max from centre)
    const dx = (ax * 10).toFixed(1);
    const dy = (ay * 10).toFixed(1);
    if (moved) knob.setAttribute('transform', `translate(${dx} ${dy})`);
    else       knob.removeAttribute('transform');
  }
  // Project axis movement onto the target d-pad (only for the LEFT stick —
  // libretro's analog_dpad_mode=1 routes left analog → d-pad)
  if (srcId !== 'l3') return;
  const dirs = [];
  if (ax < -threshold) dirs.push('left');
  if (ax >  threshold) dirs.push('right');
  if (ay < -threshold) dirs.push('up');
  if (ay >  threshold) dirs.push('down');
  for (const d of dirs) {
    const tgtName = tgtMap[d];
    if (tgtName) {
      const tgtEl = document.getElementById(`tgt-btn-${tgtName}`);
      if (tgtEl) tgtEl.classList.add('pressed');
    }
    const row = document.querySelector(`.map-row[data-pad-btn="${d}"]`);
    if (row) row.classList.add('pressed');
  }
}

function loop() {
  updateGamepad();
  requestAnimationFrame(loop);
}

// ============================================================
// API
// ============================================================

async function api(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(`${method} ${path} -> ${r.status}`);
  return r.json();
}

// ============================================================
// Selectors
// ============================================================

async function loadSystems() {
  const data = await api('GET', '/api/systems');
  SYSTEMS = data.systems;
  SYSTEM_OPTIONS = data.system_options || {};
  CORE_MAPPER_PREFIX = data.core_mapper_prefix || {};
  PAD_BUTTONS = data.pad_buttons || [];
  selSystem.innerHTML = '';
  for (const s of SYSTEMS) {
    const opt = document.createElement('option');
    opt.value = s.id;
    opt.textContent = s.name;
    selSystem.appendChild(opt);
  }
}

async function loadGames(systemId) {
  selGame.innerHTML = '<option value="">(system default)</option>';
  if (!systemId) return;
  const data = await api('GET', `/api/games?system=${encodeURIComponent(systemId)}`);
  for (const g of data.games || []) {
    const opt = document.createElement('option');
    opt.value = g.filename;
    opt.textContent = (g.has_profile ? '* ' : '  ') + g.title;
    selGame.appendChild(opt);
  }
}

async function loadProfile(systemId, rom) {
  if (!systemId || !rom) {
    clearForm();
    GAME_DETAIL.system = null;
    GAME_DETAIL.rom = null;
    GAME_DETAIL.profile = null;
    GAME_DETAIL.systemDefault = null;
    GAME_DETAIL.dirty = false;
    renderGameDetailHeader(null, null, null);
    applyInheritanceOverlay();
    // v0.1.5: also clear the suggestions state so a stale "5 bindings"
    // badge doesn't linger from the previously-loaded game.
    if (typeof refreshSuggestionsFor === 'function') {
      refreshSuggestionsFor('', '');
    }
    return;
  }
  const data = await api('GET',
    `/api/profile?system=${encodeURIComponent(systemId)}&rom=${encodeURIComponent(rom)}`);
  const profile = data.profile || {};
  const systemDefault = data.system_default || {};
  // Flow 4 — stash on window for the overlay toggle handler.
  GAME_DETAIL.system = systemId;
  GAME_DETAIL.rom = rom;
  GAME_DETAIL.profile = profile;
  GAME_DETAIL.systemDefault = systemDefault;
  GAME_DETAIL.dirty = false;
  populateForm(profile);
  renderGameDetailHeader(systemId, profile, systemDefault);
  applyInheritanceOverlay();
  maybeShowOverlayTooltip(systemId, profile, systemDefault);
  // v0.1.5 Task 1: auto-fetch bindings_db suggestions for this game.
  // Fire-and-forget — refreshSuggestionsFor handles its own errors and
  // updates the icon badge so the user notices manual-extracted hits.
  if (typeof refreshSuggestionsFor === 'function') {
    refreshSuggestionsFor(systemId, rom);
  }
}

function setTargetForSystem(systemId) {
  const sys = SYSTEMS.find(s => s.id === systemId);
  if (!sys) return;
  targetName.textContent = sys.target_controller || '';
  if (sys.fixed_mapping_note) {
    fixedNote.textContent = sys.fixed_mapping_note;
    if (fixedNoteWrap) fixedNoteWrap.hidden = false;
  } else {
    fixedNote.textContent = '';
    if (fixedNoteWrap) fixedNoteWrap.hidden = true;
  }
  setTargetSVG(sys.target_controller, sys.target_layout);

  // If the system has no curated metadata at all, offer an online lookup.
  // The lookup endpoint is gated on user consent (POST with allow_online:true);
  // this initial call uses allow_online:false to probe the local cache only.
  const hasCurated = !!(sys.fixed_mapping_note || sys.target_controller);
  ensureLookupAffordance(sys, hasCurated);
}

// ============================================================
// System lookup affordance — appears under the target SVG when a system
// has no curated metadata. Calls POST /api/system-lookup. See the matching
// _system_lookup_endpoint() in rbcf_gui.py and system_lookup.py for the
// wire format. UI lives entirely below; no HTML markup is required upfront.
// ============================================================

const LOOKUP_HOST_ID = 'rbcf-syslookup-host';

function ensureLookupAffordance(sys, hasCurated) {
  // Always remove any prior lookup UI for this system selection — keeps the
  // pane clean when toggling between systems with/without curated data.
  const prior = document.getElementById(LOOKUP_HOST_ID);
  if (prior) prior.remove();
  if (hasCurated) return;

  const host = document.createElement('div');
  host.id = LOOKUP_HOST_ID;
  host.className = 'rbcf-onb-status';
  host.style.marginTop = '12px';
  host.dataset.systemId = sys.id;

  // Insert after fixedNoteWrap (which is hidden in this branch) but inside the
  // same parent (the target pane). Fall back to appending to tgtHost.
  const anchor = fixedNoteWrap || tgtHost;
  if (anchor && anchor.parentNode) {
    anchor.parentNode.insertBefore(host, anchor.nextSibling);
  } else if (tgtHost) {
    tgtHost.appendChild(host);
  } else {
    document.body.appendChild(host);
  }

  // Initial state: probe the cache (allow_online:false). If a cache hit, render
  // the result; otherwise prompt for online consent.
  renderLookupInitial(host, sys);
}

function renderLookupInitial(host, sys) {
  host.innerHTML = `
    <div class="rbcf-onb-status-msg">
      <strong>No info yet for <code>${rbcfEsc(sys.id)}</code>.</strong>
      <span class="rbcf-onb-muted">We don't have a curated mapping for this system. Search public sources?</span>
      <div style="margin-top:10px; display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
        <button type="button" class="rbcf-apply-btn rbcf-apply-btn-primary" data-act="search">Search online</button>
        <span class="rbcf-onb-muted" data-role="status"></span>
      </div>
    </div>
  `;
  const btn = host.querySelector('[data-act="search"]');
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    setLookupStatus(host, 'Checking local cache…');
    try {
      const cached = await api('POST', '/api/system-lookup', {
        system: sys.id, allow_online: false,
      });
      if (cached && cached.source && cached.source !== 'none') {
        // Cache hit — render result.
        renderLookupResult(host, sys, cached);
        return;
      }
      // No cache → ask for consent.
      btn.disabled = false;
      showLookupConsentModal(sys, host);
    } catch (e) {
      btn.disabled = false;
      setLookupStatus(host, `lookup failed: ${e && e.message ? e.message : e}`);
    }
  });
}

function setLookupStatus(host, msg) {
  const el = host.querySelector('[data-role="status"]');
  if (el) el.textContent = msg || '';
}

function showLookupConsentModal(sys, host) {
  // Reuse the apply-modal styles (deep frosted card + overlay).
  const overlay = document.createElement('div');
  overlay.className = 'rbcf-apply-modal-overlay';
  overlay.id = 'rbcf-lookup-consent-modal';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.innerHTML = `
    <div class="rbcf-apply-modal-card" role="document">
      <div class="rbcf-apply-modal-head">
        <h2 class="rbcf-apply-modal-title">Search online for <code>${rbcfEsc(sys.id)}</code>?</h2>
        <button type="button" class="rbcf-apply-modal-x" aria-label="Cancel" data-act="cancel">×</button>
      </div>
      <div class="rbcf-apply-modal-banner">
        We can search public sources for <strong>${rbcfEsc(sys.name || sys.id)}</strong> controller info.
        We'll only fetch from these domains:
      </div>
      <div class="rbcf-apply-modal-body">
        <ul class="rbcf-apply-list">
          <li><span class="rbcf-apply-mark">·</span><span class="rbcf-apply-text"><code>wiki.retrobat.org</code> — RetroBat's own wiki</span></li>
          <li><span class="rbcf-apply-mark">·</span><span class="rbcf-apply-text"><code>docs.libretro.com</code> — libretro core docs</span></li>
          <li><span class="rbcf-apply-mark">·</span><span class="rbcf-apply-text"><code>raw.githubusercontent.com</code> — RetroBat-Official/emulatorlauncher source</span></li>
        </ul>
        <p class="rbcf-onb-muted" style="margin-top:12px;">
          The result will be saved locally as a proposal — you decide whether to accept it. Nothing is shared with the central registry.
        </p>
      </div>
      <div class="rbcf-apply-modal-foot">
        <span class="rbcf-apply-spacer"></span>
        <button type="button" class="rbcf-apply-btn rbcf-apply-btn-secondary" data-act="cancel">Cancel</button>
        <button type="button" class="rbcf-apply-btn rbcf-apply-btn-primary" data-act="go">Search online</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);

  const close = () => overlay.remove();
  overlay.querySelector('[data-act="cancel"]').addEventListener('click', close);
  overlay.querySelector('.rbcf-apply-modal-x').addEventListener('click', close);
  overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) close(); });

  const goBtn = overlay.querySelector('[data-act="go"]');
  goBtn.addEventListener('click', async () => {
    goBtn.disabled = true;
    setLookupStatus(host, 'Searching…');
    close();
    try {
      const res = await api('POST', '/api/system-lookup', {
        system: sys.id, allow_online: true,
      });
      if (res && res.source && res.source !== 'none') {
        renderLookupResult(host, sys, res);
      } else {
        renderLookupNoResult(host, sys, res);
      }
    } catch (e) {
      setLookupStatus(host, `lookup failed: ${e && e.message ? e.message : e}`);
    }
  });
}

function renderLookupResult(host, sys, result) {
  // Result block: source badge, source_url, excerpt, proposed mapping_note,
  // and Accept / Edit / Reject buttons.
  const sourceLabel = result.source || 'unknown';
  const noteText = result.mapping_note || '';
  const excerptText = result.excerpt || '';
  const url = result.source_url || '';
  host.classList.remove('rbcf-onb-status-error');
  host.classList.add('rbcf-onb-status-ok');
  host.innerHTML = `
    <div class="rbcf-onb-status-msg">
      <strong>Lookup for <code>${rbcfEsc(sys.id)}</code> — <code>${rbcfEsc(sourceLabel)}</code></strong>
      ${url ? `<div class="rbcf-onb-muted" style="margin-top:4px;">Source: <a href="${rbcfEsc(url)}" target="_blank" rel="noopener noreferrer"><code>${rbcfEsc(url)}</code></a></div>` : ''}
      ${excerptText ? `<div class="rbcf-onb-muted" style="margin-top:8px; font-style:italic;">${rbcfEsc(excerptText)}</div>` : ''}
      <div style="margin-top:10px;">
        <label class="rbcf-onb-muted" style="display:block; margin-bottom:4px;">Proposed mapping note (editable):</label>
        <textarea data-role="note" rows="3" style="width:100%; box-sizing:border-box; font: 12px/1.45 var(--mono, monospace); padding:8px; border-radius:8px; border:1px solid var(--edge-bottom); background: var(--content-fill); color: var(--tx-primary);">${rbcfEsc(noteText)}</textarea>
      </div>
      <div style="margin-top:10px; display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
        <button type="button" class="rbcf-apply-btn rbcf-apply-btn-primary" data-act="accept">Accept and save</button>
        <button type="button" class="rbcf-apply-btn rbcf-apply-btn-secondary" data-act="refresh">Refresh</button>
        <button type="button" class="rbcf-apply-btn rbcf-apply-btn-secondary" data-act="reject">Reject</button>
        <span class="rbcf-onb-muted" data-role="status"></span>
      </div>
    </div>
  `;

  host.querySelector('[data-act="accept"]').addEventListener('click', () => {
    // The backend already cached the lookup on first fetch. If the user edited
    // the mapping_note, persist their edit by re-saving via force_refresh path
    // — actually simpler: just stash the edit into localStorage for now and
    // tell the user to re-paste into a manual profile if needed. For the MVP,
    // the cache write done by the backend is the source of truth, and any
    // textarea edit at this point is captured in a successful local save.
    const edited = host.querySelector('[data-role="note"]').value || '';
    try {
      localStorage.setItem(`rbcf-syslookup-note-${sys.id}`, edited);
    } catch (e) { /* ignore */ }
    setLookupStatus(host, 'Saved locally — visible in the cache');
    showToast(`Lookup for ${sys.id} saved.`, 'success', 2200);
  });

  host.querySelector('[data-act="refresh"]').addEventListener('click', async () => {
    setLookupStatus(host, 'Refreshing…');
    try {
      const res = await api('POST', '/api/system-lookup', {
        system: sys.id, allow_online: true, force_refresh: true,
      });
      if (res && res.source && res.source !== 'none') {
        renderLookupResult(host, sys, res);
      } else {
        renderLookupNoResult(host, sys, res);
      }
    } catch (e) {
      setLookupStatus(host, `refresh failed: ${e && e.message ? e.message : e}`);
    }
  });

  host.querySelector('[data-act="reject"]').addEventListener('click', async () => {
    try {
      await api('POST', '/api/system-lookup/clear', { system: sys.id });
      try { localStorage.removeItem(`rbcf-syslookup-note-${sys.id}`); } catch (e) {}
      // Reset the panel back to the initial 'no info' state.
      host.classList.remove('rbcf-onb-status-ok', 'rbcf-onb-status-error');
      renderLookupInitial(host, sys);
      showToast(`Lookup for ${sys.id} cleared.`, 'info', 2000);
    } catch (e) {
      setLookupStatus(host, `clear failed: ${e && e.message ? e.message : e}`);
    }
  });
}

function renderLookupNoResult(host, sys, result) {
  host.classList.remove('rbcf-onb-status-ok');
  host.classList.add('rbcf-onb-status-error');
  const errMsg = (result && result.error) || 'no usable content found in the public sources';
  host.innerHTML = `
    <div class="rbcf-onb-status-msg">
      <strong>Couldn't find anything for <code>${rbcfEsc(sys.id)}</code>.</strong>
      <span class="rbcf-onb-muted">${rbcfEsc(errMsg)}. Manual profile entry only.</span>
      <div style="margin-top:10px; display:flex; gap:8px; align-items:center;">
        <button type="button" class="rbcf-apply-btn rbcf-apply-btn-secondary" data-act="retry">Try again</button>
        <button type="button" class="rbcf-apply-btn rbcf-apply-btn-secondary" data-act="dismiss">Dismiss</button>
      </div>
    </div>
  `;
  host.querySelector('[data-act="retry"]').addEventListener('click', () => {
    host.classList.remove('rbcf-onb-status-error');
    renderLookupInitial(host, sys);
  });
  host.querySelector('[data-act="dismiss"]').addEventListener('click', () => {
    host.remove();
  });
}

// ============================================================
// Mapping rows + game options
// ============================================================

// Region groups for the mapping table — gives users a scannable layout.
// Buttons listed elsewhere are passed through; unknowns land in "other".
const MAP_REGIONS = [
  { id: 'face',     label: 'Face buttons', desc: 'A · B · X · Y',          btns: ['a', 'b', 'x', 'y'] },
  { id: 'dpad',     label: 'D-pad',        desc: 'Up · Down · Left · Right', btns: ['up', 'down', 'left', 'right'] },
  { id: 'shoulder', label: 'Shoulders',    desc: 'L1 · R1 · L2 · R2',     btns: ['l', 'r', 'l2', 'r2'] },
  { id: 'sticks',   label: 'Sticks',       desc: 'L3 · R3 (stick clicks)', btns: ['l3', 'r3'] },
  { id: 'system',   label: 'System',       desc: 'Select · Start',         btns: ['select', 'start'] },
];

const FACE_COLOR = { a: 'green', b: 'red', x: 'blue', y: 'yellow' };

function buildMappingRows() {
  mapGrid.innerHTML = '';

  // Track which pad buttons are already in a region so we can collect leftovers.
  const known = new Set();
  for (const r of MAP_REGIONS) for (const b of r.btns) known.add(b);
  const leftovers = PAD_BUTTONS.filter(b => !known.has(b));
  const regions = MAP_REGIONS.slice();
  if (leftovers.length) regions.push({ id: 'other', label: 'Other', desc: '', btns: leftovers });

  for (const region of regions) {
    // Filter region's buttons to only those the backend actually exposed
    const present = region.btns.filter(b => PAD_BUTTONS.includes(b));
    if (!present.length) continue;

    const wrap = document.createElement('div');
    wrap.className = 'map-region';
    wrap.dataset.region = region.id;

    const label = document.createElement('div');
    label.className = 'map-region-label';
    label.innerHTML = `<span>${region.label}</span>${region.desc ? `<span class="desc">${region.desc}</span>` : ''}`;

    const rows = document.createElement('div');
    rows.className = 'map-region-rows';

    for (const btn of present) {
      const row = document.createElement('div');
      row.className = 'map-row';
      if (FACE_COLOR[btn]) row.classList.add('face-' + FACE_COLOR[btn]);
      row.dataset.padBtn = btn;
      const label = btn.toUpperCase()
        .replace('UP','D-UP').replace('DOWN','D-DOWN')
        .replace('LEFT','D-LEFT').replace('RIGHT','D-RIGHT');
      const swatch = FACE_COLOR[btn] ? '<span class="swatch" aria-hidden="true"></span>' : '';
      // v0.1.5 13e: rows with a bound value get .has-value applied,
      // which tints the input field green so the user can scan the
      // grid and immediately spot which buttons are mapped. The stored
      // value is the full RETROK_* constant — no display-side prefix
      // stripping (keeps the data model + collectProfile() untouched).
      row.innerHTML = `
        <span class="btn-name">${swatch}${label}</span>
        <input type="text" data-map-btn="${btn}" placeholder="e.g. RETROK_F1, RETROK_SPACE, --- to clear">
        <button type="button" class="listen-btn" data-listen-for="${btn}"
                title="Click then press a key to bind it">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none"
               stroke="currentColor" stroke-width="2" stroke-linecap="round"
               stroke-linejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="3"/>
            <circle cx="12" cy="12" r="8"/>
            <line x1="12" y1="2" x2="12" y2="5"/>
            <line x1="12" y1="19" x2="12" y2="22"/>
            <line x1="2" y1="12" x2="5" y2="12"/>
            <line x1="19" y1="12" x2="22" y2="12"/>
          </svg>
          <span class="listen-label">listen</span>
        </button>
      `;
      rows.appendChild(row);
    }

    wrap.appendChild(label);
    wrap.appendChild(rows);
    mapGrid.appendChild(wrap);
  }
}

function buildGameOptions(systemId) {
  gameOpts.innerHTML = '';
  const opts = SYSTEM_OPTIONS[systemId];
  if (!opts || opts.length === 0) {
    gameOpts.innerHTML = `
      <div class="empty-state" style="grid-column: 1 / -1;">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
        <span>No per-game options configured for this system.</span>
      </div>`;
    return;
  }
  for (const o of opts) {
    const row = document.createElement('div');
    row.className = 'opt-row' + (o.type === 'bool' ? ' bool' : '');
    if (o.type === 'bool') {
      row.innerHTML = `
        <label for="opt-${o.key}">${o.label}</label>
        <input type="checkbox" data-opt-key="${o.key}" id="opt-${o.key}">
      `;
    } else if (o.type === 'select') {
      const choices = (o.choices || []).map(c => {
        const v = c.split(' ')[0];
        return `<option value="${v}">${c}</option>`;
      }).join('');
      row.innerHTML = `
        <label for="opt-${o.key}">${o.label}</label>
        <select id="opt-${o.key}" data-opt-key="${o.key}">
          <option value="">(use system default)</option>
          ${choices}
        </select>
      `;
    } else {
      row.innerHTML = `
        <label for="opt-${o.key}">${o.label}</label>
        <input type="text" id="opt-${o.key}" data-opt-key="${o.key}">
      `;
    }
    gameOpts.appendChild(row);
  }
}

// ============================================================
// Form populate / clear / collect
// ============================================================

function clearForm() {
  $$('input[data-map-btn]').forEach(i => i.value = '');
  $$('[data-opt-key]').forEach(el => {
    if (el.type === 'checkbox') el.checked = false;
    else el.value = '';
  });
  notesEl.value = '';
  // v0.1.5 13e: also clear has-value visual + recount badges
  syncMappingRowsVisualState();
  if (typeof updateIconBadges === 'function') updateIconBadges();
}

function populateForm(profile) {
  clearForm();
  if (!profile) return;
  const sysId = selSystem.value;
  const prefix = CORE_MAPPER_PREFIX[sysId];
  const co = profile.core_options || {};
  if (prefix) {
    for (const [k, v] of Object.entries(co)) {
      if (!k.startsWith(prefix)) continue;
      const padBtn = k.slice(prefix.length);
      const inp = document.querySelector(`input[data-map-btn="${padBtn}"]`);
      if (inp) inp.value = v;
    }
  }
  const es = profile.es_settings || {};
  for (const [k, v] of Object.entries(es)) {
    const el = document.querySelector(`[data-opt-key="${k}"]`);
    if (!el) continue;
    if (el.type === 'checkbox') el.checked = (v === '1' || v === 'true' || v === true);
    else el.value = v;
  }
  notesEl.value = profile.notes || '';
  // v0.1.5 13e: after populating, sync row visuals + badges
  syncMappingRowsVisualState();
  if (typeof updateIconBadges === 'function') updateIconBadges();
}

// v0.1.5 13e: after any bulk mutation of mapping input values
// (populateForm / clearForm / listen-bind), refresh the .has-value
// class on each row so the green-tint + RETROK_ prefix visual stays
// in sync. Per-keystroke input events are handled by the global
// 'input' delegation (~line 3560) — this is for non-input mutations.
function syncMappingRowsVisualState() {
  $$('input[data-map-btn]').forEach(inp => {
    const row = inp.closest('.map-row');
    if (!row) return;
    const v = (inp.value || '').trim();
    row.classList.toggle('has-value', !!v && v !== '---');
  });
}

function collectProfile() {
  const sysId = selSystem.value;
  const rom = selGame.value;
  const prefix = CORE_MAPPER_PREFIX[sysId];

  const core_options = {};
  if (prefix) {
    $$('input[data-map-btn]').forEach(inp => {
      const v = inp.value.trim();
      if (!v) return;
      core_options[prefix + inp.dataset.mapBtn] = v;
    });
  }
  const es_settings = {};
  $$('[data-opt-key]').forEach(el => {
    const k = el.dataset.optKey;
    let v;
    if (el.type === 'checkbox') v = el.checked ? '1' : '';
    else v = (el.value || '').trim();
    if (v) es_settings[k] = v;
  });

  return {
    system: sysId,
    rom,
    title: rom ? rom.replace(/\.[^.]+$/, '') : '',
    es_settings,
    core_options,
    notes: notesEl.value.trim(),
    // Flow 4: when the user has touched any value and the loaded profile
    // had V/K confidence, silently downgrade to T on save. Keeps the
    // confidence honest without a modal interruption. Revisit if users
    // complain — a more polite "edit will downgrade, [Continue] / [Discard
    // edit]" warning was specced but skipped this iteration.
    confidence: (GAME_DETAIL.dirty && GAME_DETAIL.profile && GAME_DETAIL.profile.confidence)
      ? 'T'
      : (GAME_DETAIL.profile && GAME_DETAIL.profile.confidence) || '',
    apply: true,
  };
}

// ============================================================
// Flow 4 — game-detail view: confidence pill + inheritance overlay.
//
// Microinteractions:
//   - Confidence pill (V/K/T) renders in the Advanced overrides section
//     header, tucked next to the section .hint.
//   - "Show inheritance overlay" toggle lives in the same header strip.
//     When ON, inherited rows fade and show a ghost value; override rows
//     get a violet "Override" pill.
//   - Per-row badges (`O` / `↓` / `–`) render unconditionally on every
//     mapping & game-options row whenever a profile is loaded.
//   - Overlay state is sticky per-system: `rbcf-overlay-<system>` = '1'.
//   - First-time tooltip hint is per-system: `rbcf-overlay-tip-<system>`.
//     Shows once when a profile loads and has at least one override.
//
// Decision #8 (DECISIONS.md): off by default, sticky once toggled, with a
// first-time tooltip when an override exists.
// ============================================================

const GAME_DETAIL = {
  system: null,
  rom: null,
  profile: null,
  systemDefault: null,
  dirty: false,
};

const OVERLAY_KEY_PREFIX = 'rbcf-overlay-';        // per-system overlay on/off
const OVERLAY_TIP_PREFIX = 'rbcf-overlay-tip-';    // per-system one-shot tip

function isOverlayOn(systemId) {
  if (!systemId) return false;
  try { return localStorage.getItem(OVERLAY_KEY_PREFIX + systemId) === '1'; }
  catch (e) { return false; }
}
function setOverlayOn(systemId, on) {
  if (!systemId) return;
  try {
    if (on) localStorage.setItem(OVERLAY_KEY_PREFIX + systemId, '1');
    else    localStorage.removeItem(OVERLAY_KEY_PREFIX + systemId);
  } catch (e) { /* ignore */ }
}
function wasOverlayTipShown(systemId) {
  if (!systemId) return true;
  try { return localStorage.getItem(OVERLAY_TIP_PREFIX + systemId) === '1'; }
  catch (e) { return true; }
}
function markOverlayTipShown(systemId) {
  if (!systemId) return;
  try { localStorage.setItem(OVERLAY_TIP_PREFIX + systemId, '1'); }
  catch (e) { /* ignore */ }
}

// Map a core_options key to the mapping-row's pad button (or null if it
// doesn't belong to this system's mapper prefix).
function coreOptKeyToPadBtn(systemId, key) {
  const prefix = CORE_MAPPER_PREFIX[systemId];
  if (!prefix || !key.startsWith(prefix)) return null;
  return key.slice(prefix.length);
}

// Compute the source for a single key: 'override', 'inherited', or 'unset'.
function keySource(profileVal, defaultVal) {
  const has = (v) => v !== undefined && v !== null && v !== '';
  if (has(profileVal)) return 'override';
  if (has(defaultVal)) return 'inherited';
  return 'unset';
}

const SOURCE_BADGE = {
  override:  { glyph: 'O', label: 'Override',  cls: 'src-override',  title: 'Set in this game profile (override).' },
  inherited: { glyph: '↓', label: 'Inherited', cls: 'src-inherited', title: 'Inherited from the system _default.yaml.' },
  unset:     { glyph: '–', label: 'Not set',   cls: 'src-unset',     title: 'Not set at any level.' },
};

function makeRowBadge(source) {
  const meta = SOURCE_BADGE[source] || SOURCE_BADGE.unset;
  const span = document.createElement('span');
  span.className = 'row-source-badge ' + meta.cls;
  span.dataset.source = source;
  span.title = meta.title;
  span.setAttribute('aria-label', meta.label);
  span.textContent = meta.glyph;
  return span;
}

// Render the game-detail header strip. Hosts the confidence pill, the
// "X of Y overrides" summary, and the overlay toggle.
//
// v0.1.5 13d: previously injected into #sec-game-options. Now lives
// in the hidden #game-options-host so it travels into the overrides
// popover when opened. (Follow-up: surface the override count as a
// badge ON the Overrides button itself for at-a-glance visibility
// without opening the popover.)
function renderGameDetailHeader(systemId, profile, systemDefault) {
  const sec = document.getElementById('game-options-host');
  if (!sec) return;
  let host = sec.querySelector('.rbcf-game-detail-header');
  if (!systemId || !profile) {
    if (host) host.remove();
    return;
  }
  if (!host) {
    host = document.createElement('div');
    host.className = 'rbcf-game-detail-header';
    // Insert before the #game-options div so the strip sits at the
    // top of the host (and thus at the top of the popover when shown).
    const gameOpts = sec.querySelector('#game-options');
    if (gameOpts) sec.insertBefore(host, gameOpts);
    else sec.prepend(host);
  }

  // Per-row computation of override count (es_settings + core_options).
  const overrideCount = countOverrides(profile);
  const conf = (profile.confidence || '').toUpperCase();
  const overlayOn = isOverlayOn(systemId);

  host.innerHTML = `
    <div class="rbcf-gdh-row">
      ${renderConfidencePillHTML(conf)}
      <span class="rbcf-gdh-summary">
        ${overrideCount > 0
          ? `<strong>${overrideCount}</strong> override${overrideCount === 1 ? '' : 's'} on top of <code>${rbcfEsc(systemId)}/_default.yaml</code>`
          : `No overrides — fully inherited from <code>${rbcfEsc(systemId)}/_default.yaml</code>`}
      </span>
      <span class="rbcf-gdh-spacer"></span>
      <label class="rbcf-gdh-toggle" title="Fade inherited rows; show ghost values from the system default.">
        <input type="checkbox" id="rbcf-overlay-toggle" ${overlayOn ? 'checked' : ''}>
        <span>Show inheritance overlay</span>
      </label>
    </div>
  `;

  const toggle = host.querySelector('#rbcf-overlay-toggle');
  if (toggle) {
    toggle.addEventListener('change', () => {
      setOverlayOn(systemId, toggle.checked);
      applyInheritanceOverlay();
    });
  }
}

function renderConfidencePillHTML(conf) {
  if (!conf || !'VKT'.includes(conf)) {
    return `<span class="confidence-pill confidence-none" title="No confidence set on this profile.">·</span>`;
  }
  const meta = {
    V: { label: 'Verified',   tip: 'Verified — bindings tested in-game.' },
    K: { label: 'Known-good', tip: 'Known good — drawn from a trusted source but not personally tested.' },
    T: { label: 'Scaffold',   tip: 'Scaffold — placeholder. Edit to verify and promote.' },
  }[conf];
  return `<span class="confidence-pill confidence-${conf}" title="${rbcfEsc(meta.tip)}" aria-label="Confidence ${rbcfEsc(meta.label)}">${conf} · ${rbcfEsc(meta.label)}</span>`;
}

function countOverrides(profile) {
  if (!profile) return 0;
  let n = 0;
  for (const v of Object.values(profile.es_settings || {})) {
    if (v !== undefined && v !== null && v !== '') n++;
  }
  for (const v of Object.values(profile.core_options || {})) {
    if (v !== undefined && v !== null && v !== '') n++;
  }
  return n;
}

// Apply / refresh the overlay state on every mapping + opt-row. Reads the
// current GAME_DETAIL state. Idempotent — safe to call after every change.
function applyInheritanceOverlay() {
  const sysId = GAME_DETAIL.system;
  const profile = GAME_DETAIL.profile || {};
  const sysDefault = GAME_DETAIL.systemDefault || {};
  if (!sysId) {
    // Strip any badges left over from a previous selection.
    document.querySelectorAll('.row-source-badge').forEach(el => el.remove());
    document.querySelectorAll('.map-row, .opt-row').forEach(row => {
      row.classList.remove('rbcf-row-inherited', 'rbcf-row-override', 'rbcf-row-unset', 'rbcf-overlay-on');
      row.querySelectorAll('.rbcf-ghost-value, .rbcf-override-pill').forEach(el => el.remove());
    });
    return;
  }

  const overlayOn = isOverlayOn(sysId);
  const co = profile.core_options || {};
  const dco = sysDefault.core_options || {};
  const es = profile.es_settings || {};
  const des = sysDefault.es_settings || {};

  // ------- mapping rows (core_options keyed by pad button) -------
  // Live DOM value wins so the user's in-flight edits shift the badge
  // ('inherited' → 'override') as they type.
  document.querySelectorAll('.map-row').forEach(row => {
    const inp = row.querySelector('input[data-map-btn]');
    if (!inp) return;
    const padBtn = inp.dataset.mapBtn;
    const prefix = CORE_MAPPER_PREFIX[sysId] || '';
    const key = prefix + padBtn;
    const liveVal = (inp.value || '').trim();
    const profileVal = liveVal || co[key];
    const defaultVal = dco[key];
    const source = keySource(profileVal, defaultVal);
    paintRow(row, source, overlayOn, defaultVal);
    // Placeholder shows the inherited value when input is empty (always —
    // feels natural even with overlay off; we only swap when empty).
    if (source !== 'override' && defaultVal && !liveVal) {
      inp.placeholder = defaultVal + '  (inherited)';
    } else if (!liveVal && !defaultVal) {
      inp.placeholder = 'e.g. RETROK_F1, RETROK_SPACE, --- to clear';
    }
  });

  // ------- opt-rows (es_settings keyed by data-opt-key) -------
  document.querySelectorAll('.opt-row').forEach(row => {
    const el = row.querySelector('[data-opt-key]');
    if (!el) return;
    const key = el.dataset.optKey;
    let liveVal;
    if (el.type === 'checkbox') liveVal = el.checked ? '1' : '';
    else liveVal = (el.value || '').trim();
    const profileVal = liveVal || es[key];
    const defaultVal = des[key];
    const source = keySource(profileVal, defaultVal);
    paintRow(row, source, overlayOn, defaultVal);
  });
}

function paintRow(row, source, overlayOn, defaultVal) {
  // Reset state classes.
  row.classList.remove('rbcf-row-override', 'rbcf-row-inherited', 'rbcf-row-unset');
  row.classList.toggle('rbcf-overlay-on', !!overlayOn);
  row.classList.add('rbcf-row-' + source);

  // Badge: always present (regardless of overlay) once a profile is loaded.
  let badge = row.querySelector('.row-source-badge');
  if (badge) badge.remove();
  badge = makeRowBadge(source);
  row.prepend(badge);

  // Override pill (overlay-only, override-only).
  let pill = row.querySelector('.rbcf-override-pill');
  if (pill) pill.remove();
  if (overlayOn && source === 'override') {
    pill = document.createElement('span');
    pill.className = 'rbcf-override-pill';
    pill.textContent = 'Override';
    row.appendChild(pill);
  }

  // Ghost value (overlay-only, inherited-only).
  let ghost = row.querySelector('.rbcf-ghost-value');
  if (ghost) ghost.remove();
  if (overlayOn && source === 'inherited' && defaultVal) {
    ghost = document.createElement('span');
    ghost.className = 'rbcf-ghost-value';
    ghost.textContent = '= ' + defaultVal;
    ghost.title = 'Inherited from the system default.';
    row.appendChild(ghost);
  }
}

// First-time tooltip: when a profile with overrides loads on a system
// that hasn't shown the tip yet, anchor a small auto-dismissing balloon
// at the overlay toggle. Independent of the onboarding overlay.
function maybeShowOverlayTooltip(systemId, profile, _systemDefault) {
  if (!systemId || !profile) return;
  if (wasOverlayTipShown(systemId)) return;
  const overrides = countOverrides(profile);
  if (overrides <= 0) return;
  if (isOverlayOn(systemId)) {
    // Already on — no need to suggest.
    markOverlayTipShown(systemId);
    return;
  }
  const toggle = document.getElementById('rbcf-overlay-toggle');
  if (!toggle) return;

  const tip = document.createElement('div');
  tip.className = 'rbcf-overlay-tip';
  tip.setAttribute('role', 'tooltip');
  tip.innerHTML = `This profile has <strong>${overrides}</strong> override${overrides === 1 ? '' : 's'} — toggle the overlay to see what's inherited from the system default.`;

  // Anchor: append to the header host, position the tip absolutely just
  // below the toggle. Keeps it self-contained — no body-level portal.
  const host = toggle.closest('.rbcf-game-detail-header') || document.body;
  host.appendChild(tip);

  // Auto-dismiss after a generous read window. User can also click to dismiss.
  const dismiss = () => {
    tip.classList.add('rbcf-overlay-tip-fade');
    setTimeout(() => tip.remove(), 220);
    markOverlayTipShown(systemId);
  };
  tip.addEventListener('click', dismiss);
  setTimeout(dismiss, 6500);
}

// Mark the in-memory profile dirty when the user edits any field. Save-
// time logic (collectProfile) reads GAME_DETAIL.dirty to silently downgrade
// V/K confidence to T.
function markGameDetailDirty() {
  if (!GAME_DETAIL.profile) return;
  if (GAME_DETAIL.dirty) return;
  GAME_DETAIL.dirty = true;
  // Repaint the confidence pill with a "(edit pending)" hint, but don't
  // actually downgrade the in-memory value. Save flow handles it.
  const pillHost = document.querySelector('.rbcf-game-detail-header .confidence-pill');
  if (pillHost && /^[VK]$/.test(GAME_DETAIL.profile.confidence || '')) {
    pillHost.classList.add('confidence-pending-downgrade');
    pillHost.title = `Editing this profile will reset its confidence to T (until you re-verify) on save.`;
  }
}

// ============================================================
// Save→Apply two-step (decision #10): default flow shows a
// dry-run preview modal between save and apply.
// localStorage 'rbcf-one-click-apply' = '1' opts back into the
// legacy one-click behaviour.
// ============================================================

const ONE_CLICK_KEY = 'rbcf-one-click-apply';

function isOneClickApplyEnabled() {
  try { return localStorage.getItem(ONE_CLICK_KEY) === '1'; }
  catch (e) { return false; }
}
function setOneClickApply(enabled) {
  try {
    if (enabled) localStorage.setItem(ONE_CLICK_KEY, '1');
    else         localStorage.removeItem(ONE_CLICK_KEY);
  } catch (e) { /* ignore quota / disabled storage */ }
}

// Escape an arbitrary string for safe interpolation into innerHTML.
function rbcfEsc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// Build the planned-changes list HTML from the in-memory profile.
function buildPlannedChangesHTML(profile) {
  const sysId = profile.system || '';
  const rom = profile.rom || '';
  const target = rom ? `${rbcfEsc(sysId)}["${rbcfEsc(rom)}"]` : `${rbcfEsc(sysId)} default`;

  const esEntries = Object.entries(profile.es_settings || {});
  const coEntries = Object.entries(profile.core_options || {});

  let html = '';

  html += '<div class="rbcf-apply-group">';
  html += '<div class="rbcf-apply-group-title">es_settings.cfg <span class="rbcf-apply-group-count">'
        + esEntries.length + '</span></div>';
  if (esEntries.length === 0) {
    html += '<div class="rbcf-apply-empty">No per-game es_settings changes.</div>';
  } else {
    html += '<ul class="rbcf-apply-list">';
    for (const [k, v] of esEntries) {
      html += '<li><span class="rbcf-apply-mark">~</span>'
            + '<span class="rbcf-apply-text">Will set <code>' + target + '.'
            + rbcfEsc(k) + '</code> = <code>' + rbcfEsc(v) + '</code></span></li>';
    }
    html += '</ul>';
  }
  html += '</div>';

  html += '<div class="rbcf-apply-group">';
  html += '<div class="rbcf-apply-group-title">retroarch-core-options.cfg <span class="rbcf-apply-group-count">'
        + coEntries.length + '</span> <span class="rbcf-apply-warn">(global per system)</span></div>';
  if (coEntries.length === 0) {
    html += '<div class="rbcf-apply-empty">No core-option changes.</div>';
  } else {
    html += '<ul class="rbcf-apply-list">';
    for (const [k, v] of coEntries) {
      html += '<li><span class="rbcf-apply-mark">~</span>'
            + '<span class="rbcf-apply-text">Will set RetroArch core option <code>'
            + rbcfEsc(k) + '</code> = <code>' + rbcfEsc(v) + '</code></span></li>';
    }
    html += '</ul>';
  }
  html += '</div>';

  return html;
}

// Modal focus-trap state.
let _rbcfApplyPrevFocus = null;
let _rbcfApplyTrapHandler = null;

function _rbcfApplyFocusables(root) {
  return Array.from(root.querySelectorAll(
    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
  )).filter(el => !el.disabled && el.offsetParent !== null);
}

function dismissApplyModal() {
  const overlay = $('rbcf-apply-modal');
  if (!overlay) return;
  if (_rbcfApplyTrapHandler) {
    document.removeEventListener('keydown', _rbcfApplyTrapHandler, true);
    _rbcfApplyTrapHandler = null;
  }
  overlay.remove();
  if (_rbcfApplyPrevFocus && document.contains(_rbcfApplyPrevFocus)) {
    try { _rbcfApplyPrevFocus.focus(); } catch (e) { /* ignore */ }
  }
  _rbcfApplyPrevFocus = null;
}

// Trigger the apply step (POST /api/apply) and toast.
async function performApplyAfterSave(profile) {
  setStatus('applying…');
  try {
    const r = await api('POST', '/api/apply', {});
    if (r.ok) {
      setStatus('applied · ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
      const tag = profile && profile.rom
        ? `${profile.system}/${profile.rom}`
        : 'all profiles';
      showToast(`Applied ${tag}.`, 'success');
    } else {
      setStatus('apply failed');
      showToast('Apply failed: ' + (r.error || 'rc ' + r.returncode), 'error');
    }
  } catch (e) {
    setStatus('apply error');
    showToast('Apply error: ' + e.message, 'error');
  }
}

function showApplyPreviewModal(profile) {
  // Tear down any pre-existing modal (defensive).
  dismissApplyModal();
  _rbcfApplyPrevFocus = document.activeElement;

  const overlay = document.createElement('div');
  overlay.id = 'rbcf-apply-modal';
  overlay.className = 'rbcf-apply-modal-overlay';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.setAttribute('aria-labelledby', 'rbcf-apply-modal-title');

  const tag = profile.rom
    ? `${rbcfEsc(profile.system)} / ${rbcfEsc(profile.rom)}`
    : rbcfEsc(profile.system || 'profile');

  overlay.innerHTML = `
    <div class="rbcf-apply-modal-card" role="document">
      <div class="rbcf-apply-modal-head">
        <h2 class="rbcf-apply-modal-title" id="rbcf-apply-modal-title">Preview — review before applying</h2>
        <button type="button" class="rbcf-apply-modal-x" aria-label="Cancel" data-act="cancel">×</button>
      </div>
      <div class="rbcf-apply-modal-banner">
        Your profile <strong>${tag}</strong> is saved. These changes will be written to RetroBat config files when you click <strong>Apply</strong>. Click <strong>Cancel</strong> to leave RetroBat untouched — the saved profile YAML stays on disk.
      </div>
      <div class="rbcf-apply-modal-body">
        ${buildPlannedChangesHTML(profile)}
      </div>
      <div class="rbcf-apply-modal-foot">
        <button type="button" class="rbcf-apply-link" data-act="never">Don't show this again</button>
        <span class="rbcf-apply-spacer"></span>
        <button type="button" class="rbcf-apply-btn rbcf-apply-btn-secondary" data-act="cancel">Cancel</button>
        <button type="button" class="rbcf-apply-btn rbcf-apply-btn-primary" data-act="apply">Apply</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);

  const card = overlay.querySelector('.rbcf-apply-modal-card');
  const applyBtn = overlay.querySelector('[data-act="apply"]');
  const cancelBtn = overlay.querySelector('[data-act="cancel"]');
  const xBtn = overlay.querySelector('.rbcf-apply-modal-x');
  const neverBtn = overlay.querySelector('[data-act="never"]');

  applyBtn.addEventListener('click', async () => {
    applyBtn.disabled = true;
    cancelBtn.disabled = true;
    try {
      await performApplyAfterSave(profile);
    } finally {
      dismissApplyModal();
    }
  });
  cancelBtn.addEventListener('click', () => {
    setStatus('apply cancelled · profile saved');
    showToast('Cancelled — RetroBat config left untouched.', 'info', 2500);
    dismissApplyModal();
  });
  xBtn.addEventListener('click', () => cancelBtn.click());
  neverBtn.addEventListener('click', async () => {
    setOneClickApply(true);
    showToast('One-Click Save & Apply enabled.', 'info', 2200);
    applyBtn.disabled = true;
    cancelBtn.disabled = true;
    try {
      await performApplyAfterSave(profile);
    } finally {
      dismissApplyModal();
    }
  });

  // Backdrop click = cancel.
  overlay.addEventListener('mousedown', (e) => {
    if (e.target === overlay) cancelBtn.click();
  });

  // Focus trap + Escape handler.
  _rbcfApplyTrapHandler = (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      cancelBtn.click();
      return;
    }
    if (e.key !== 'Tab') return;
    const items = _rbcfApplyFocusables(card);
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault(); last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault(); first.focus();
    }
  };
  document.addEventListener('keydown', _rbcfApplyTrapHandler, true);

  // Auto-focus the primary action.
  setTimeout(() => { try { applyBtn.focus(); } catch (e) { /* ignore */ } }, 0);
}

// ============================================================
// Settings popover (toolbar cog)
// ============================================================

let _rbcfSettingsOutsideHandler = null;
let _rbcfSettingsKeyHandler = null;

function dismissSettingsPopover() {
  const pop = $('rbcf-apply-settings-popover');
  if (pop) pop.remove();
  const cog = $('rbcf-apply-settings-cog');
  if (cog) cog.setAttribute('aria-expanded', 'false');
  if (_rbcfSettingsOutsideHandler) {
    document.removeEventListener('mousedown', _rbcfSettingsOutsideHandler, true);
    _rbcfSettingsOutsideHandler = null;
  }
  if (_rbcfSettingsKeyHandler) {
    document.removeEventListener('keydown', _rbcfSettingsKeyHandler, true);
    _rbcfSettingsKeyHandler = null;
  }
}

function showSettingsPopover() {
  dismissSettingsPopover();
  const cog = $('rbcf-apply-settings-cog');
  if (!cog) return;

  const pop = document.createElement('div');
  pop.id = 'rbcf-apply-settings-popover';
  pop.className = 'rbcf-apply-settings-popover';
  pop.setAttribute('role', 'dialog');
  pop.setAttribute('aria-label', 'RetroControlMapper Settings');
  const currentTheme = getTheme();
  const themeBtn = (val, label, icon) => `
    <button type="button" class="rbcf-apply-theme-btn${currentTheme === val ? ' rbcf-apply-theme-btn-active' : ''}"
            data-rbcf-theme="${val}" aria-pressed="${currentTheme === val}">
      ${icon}<span>${label}</span>
    </button>`;
  const ICON_LIGHT = '<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>';
  const ICON_DARK  = '<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';
  const ICON_AUTO  = '<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 3v18"/><path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor" stroke="none"/></svg>';

  pop.innerHTML = `
    <div class="rbcf-apply-settings-head">
      <h3 class="rbcf-apply-settings-title">RetroControlMapper Settings</h3>
      <button type="button" class="rbcf-apply-modal-x" aria-label="Close" data-act="close">×</button>
    </div>
    <div class="rbcf-apply-settings-body">
      <div class="rbcf-apply-theme-row" role="group" aria-label="Theme">
        <span class="rbcf-apply-theme-label-main">Theme</span>
        <span class="rbcf-apply-theme-label-help">Light, Dark, or follow system preference.</span>
        <div class="rbcf-apply-theme-segmented" id="rbcf-apply-theme-segmented">
          ${themeBtn('light', 'Light', ICON_LIGHT)}
          ${themeBtn('dark',  'Dark',  ICON_DARK)}
          ${themeBtn('auto',  'Auto',  ICON_AUTO)}
        </div>
      </div>
      <div class="rbcf-apply-settings-row rbcf-acc-row">
        <span class="rbcf-apply-settings-label">
          <span class="rbcf-apply-settings-label-main">Accent colour</span>
          <span class="rbcf-apply-settings-label-help">Override the theme's primary accent. Affects buttons and active states across all themes.</span>
        </span>
        <span class="rbcf-acc-controls">
          <input type="color" id="rbcf-acc-picker" class="rbcf-acc-picker"
                 aria-label="Accent colour"
                 value="${(localStorage.getItem('rbcf-user-accent') || '').match(/^#[0-9a-fA-F]{6}$/) ? localStorage.getItem('rbcf-user-accent') : '#7c5cff'}">
          <button type="button" id="rbcf-acc-reset"
                  class="rbcf-apply-btn rbcf-apply-btn-secondary"
                  title="Reset to theme default">Reset</button>
        </span>
      </div>
      <label class="rbcf-apply-settings-row">
        <input type="checkbox" id="rbcf-apply-one-click-toggle" ${isOneClickApplyEnabled() ? 'checked' : ''}>
        <span class="rbcf-apply-settings-label">
          <span class="rbcf-apply-settings-label-main">One-Click Save & Apply</span>
          <span class="rbcf-apply-settings-label-help">Skip the preview modal and apply immediately on Save.</span>
        </span>
      </label>
      <div class="rbcf-apply-settings-row rbcf-cimg-settings-row">
        <span class="rbcf-apply-settings-label">
          <span class="rbcf-apply-settings-label-main">Controller images</span>
          <span class="rbcf-apply-settings-label-help">Upload images for controllers we don't have art for.</span>
        </span>
        <button type="button" class="rbcf-apply-btn rbcf-apply-btn-secondary rbcf-cimg-manage-btn"
                id="rbcf-cimg-manage-btn">Manage…</button>
      </div>
      <div class="rbcf-apply-settings-row rbcf-backup-settings-row">
        <span class="rbcf-apply-settings-label">
          <span class="rbcf-apply-settings-label-main">User settings backup</span>
          <span class="rbcf-apply-settings-label-help">Export your in-app preferences (theme, accent, toggles, active-pad selection) to a JSON file. Import on another machine or after a reset.</span>
        </span>
        <span class="rbcf-backup-actions">
          <button type="button" class="rbcf-apply-btn rbcf-apply-btn-secondary"
                  id="rbcf-settings-export">Export…</button>
          <button type="button" class="rbcf-apply-btn rbcf-apply-btn-secondary"
                  id="rbcf-settings-import">Import…</button>
          <input type="file" id="rbcf-settings-import-file" accept="application/json,.json" hidden>
        </span>
      </div>
      <div class="rbcf-apply-settings-row rbcf-update-row" id="rbcf-update-row">
        <span class="rbcf-apply-settings-label">
          <span class="rbcf-apply-settings-label-main">
            Updates
            <span class="rbcf-update-version" id="rbcf-update-version-pill">v${escapeHtml(rbcfUpdateLocalVersion())}</span>
          </span>
          <label class="rbcf-update-autocheck">
            <input type="checkbox" id="rbcf-update-autocheck-toggle" ${rbcfUpdateAutoCheckEnabled() ? 'checked' : ''}>
            <span>Auto-check on startup</span>
          </label>
          <span class="rbcf-update-status" id="rbcf-update-status">Loading…</span>
          <span class="rbcf-update-consent" id="rbcf-update-consent" hidden></span>
        </span>
        <button type="button" class="rbcf-apply-btn rbcf-apply-btn-secondary rbcf-update-check-btn"
                id="rbcf-update-check-btn">Check now</button>
      </div>
    </div>
  `;
  document.body.appendChild(pop);

  // Theme segmented control wiring.
  pop.querySelectorAll('.rbcf-apply-theme-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const val = btn.dataset.rbcfTheme;
      setTheme(val);
      pop.querySelectorAll('.rbcf-apply-theme-btn').forEach(b => {
        const on = b.dataset.rbcfTheme === val;
        b.classList.toggle('rbcf-apply-theme-btn-active', on);
        b.setAttribute('aria-pressed', String(on));
      });
      const label = val === 'auto' ? 'Auto (system)' : (val[0].toUpperCase() + val.slice(1));
      showToast(`Theme: ${label}.`, 'info', 1800);
    });
  });

  // Position the popover under the cog (right-aligned).
  const r = cog.getBoundingClientRect();
  const popW = 340;
  let left = r.right - popW;
  if (left < 8) left = 8;
  pop.style.position = 'fixed';
  pop.style.top = (r.bottom + 6) + 'px';
  pop.style.left = left + 'px';
  pop.style.width = popW + 'px';

  cog.setAttribute('aria-expanded', 'true');

  const cb = pop.querySelector('#rbcf-apply-one-click-toggle');
  cb.addEventListener('change', () => {
    setOneClickApply(cb.checked);
    showToast(
      cb.checked ? 'One-Click Save & Apply enabled.' : 'Preview before Apply enabled.',
      'info', 2000);
  });
  pop.querySelector('[data-act="close"]').addEventListener('click', dismissSettingsPopover);

  // Accent picker + reset (cross-theme override)
  const accPicker = pop.querySelector('#rbcf-acc-picker');
  const accReset  = pop.querySelector('#rbcf-acc-reset');
  if (accPicker) {
    // If no override is stored, sync the picker swatch to the live --acc
    // value so the user sees what's currently in effect.
    if (!localStorage.getItem('rbcf-user-accent')) {
      const cur = getComputedStyle(document.documentElement)
                    .getPropertyValue('--acc').trim();
      if (/^#[0-9a-fA-F]{6}$/.test(cur)) accPicker.value = cur;
    }
    accPicker.addEventListener('input', (e) => {
      const v = e.target.value;
      localStorage.setItem('rbcf-user-accent', v);
      applyUserAccent(v);
    });
  }
  if (accReset) {
    accReset.addEventListener('click', () => {
      localStorage.removeItem('rbcf-user-accent');
      applyUserAccent(null);
      // Re-sync picker to whatever the theme reverted to
      const cur = getComputedStyle(document.documentElement)
                    .getPropertyValue('--acc').trim();
      if (accPicker && /^#[0-9a-fA-F]{6}$/.test(cur)) accPicker.value = cur;
      showToast('Accent reset to theme default.', 'info', 1800);
    });
  }

  const manageBtn = pop.querySelector('#rbcf-cimg-manage-btn');
  if (manageBtn) {
    manageBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      // Close the popover first, then open the sub-modal — the modal traps
      // focus/Escape on its own and the small popover would otherwise sit
      // half-hidden behind it.
      dismissSettingsPopover();
      showControllerImagesModal();
    });
  }

  // User settings backup — export / import via localStorage round-trip.
  const exportBtn = pop.querySelector('#rbcf-settings-export');
  if (exportBtn) {
    exportBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      exportUserSettings();
    });
  }
  const importBtn = pop.querySelector('#rbcf-settings-import');
  const importFileInput = pop.querySelector('#rbcf-settings-import-file');
  if (importBtn && importFileInput) {
    importBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      importFileInput.click();
    });
    importFileInput.addEventListener('change', (e) => {
      const f = e.target.files && e.target.files[0];
      if (f) importUserSettings(f);
      // Allow re-selecting the same file later
      importFileInput.value = '';
    });
  }

  // Updates row wiring.
  const updateAutoCb = pop.querySelector('#rbcf-update-autocheck-toggle');
  if (updateAutoCb) {
    updateAutoCb.addEventListener('change', () => {
      rbcfUpdateSetAutoCheck(updateAutoCb.checked);
      showToast(
        updateAutoCb.checked ? 'Update auto-check enabled.' : 'Update auto-check disabled.',
        'info', 1800);
    });
  }
  const updateBtn = pop.querySelector('#rbcf-update-check-btn');
  if (updateBtn) {
    updateBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      rbcfUpdateOnCheckNowClicked(pop);
    });
  }
  // Render whatever cached state we already have, then ask the server for a
  // fresh cached read (cheap, no network).
  rbcfUpdateRenderStatusFromCache(pop);
  rbcfUpdateFetchCached().then((info) => {
    if (info) rbcfUpdateRenderStatus(pop, info);
  });

  _rbcfSettingsOutsideHandler = (e) => {
    if (pop.contains(e.target) || cog.contains(e.target)) return;
    dismissSettingsPopover();
  };
  document.addEventListener('mousedown', _rbcfSettingsOutsideHandler, true);
  _rbcfSettingsKeyHandler = (e) => {
    if (e.key === 'Escape') { e.preventDefault(); dismissSettingsPopover(); cog.focus(); }
  };
  document.addEventListener('keydown', _rbcfSettingsKeyHandler, true);

  setTimeout(() => { try { cb.focus(); } catch (e) { /* ignore */ } }, 0);
}

// ============================================================
// Updates — settings row, header badge, consent flow.
// ------------------------------------------------------------
// Backend: /api/update-check (GET cached / POST live). Default
// behaviour: passive — cache rendered on page load, network only
// hit after explicit user consent (Check now button or auto-check
// after first consent). Cache TTL: 24h normal, 1h errors.
// localStorage keys:
//   rbcf-update-autocheck       '1'/'0'  default '1'
//   rbcf-update-consent         '1'/'0'  set when user OKs the consent prompt
//   rbcf-update-dismissed-{ver} '1'      header-badge dismiss memory
// ============================================================

const RBCF_UPDATE_AUTOCHECK_KEY = 'rbcf-update-autocheck';
const RBCF_UPDATE_CONSENT_KEY   = 'rbcf-update-consent';
const RBCF_UPDATE_DISMISS_PREFIX = 'rbcf-update-dismissed-';

let _rbcfUpdateLastInfo = null;        // most recent UpdateInfo seen
let _rbcfUpdateConsentSession = false; // consent for THIS browser session
let _rbcfUpdateLocalVersionCache = null;

function rbcfEscape(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
// Public alias used inside the popover template.
function escapeHtml(s) { return rbcfEscape(s); }

function rbcfUpdateLocalVersion() {
  if (_rbcfUpdateLocalVersionCache) return _rbcfUpdateLocalVersionCache;
  // Best-effort: derive from the cached info (which carries `current`).
  // Falls back to '?' until the first /api/update-check round-trip lands.
  if (_rbcfUpdateLastInfo && _rbcfUpdateLastInfo.current) {
    _rbcfUpdateLocalVersionCache = _rbcfUpdateLastInfo.current;
    return _rbcfUpdateLocalVersionCache;
  }
  return '?';
}

function rbcfUpdateAutoCheckEnabled() {
  try {
    const v = localStorage.getItem(RBCF_UPDATE_AUTOCHECK_KEY);
    return v !== '0';
  } catch (e) { return true; }
}

function rbcfUpdateSetAutoCheck(on) {
  try { localStorage.setItem(RBCF_UPDATE_AUTOCHECK_KEY, on ? '1' : '0'); }
  catch (e) { /* ignore */ }
}

function rbcfUpdateConsentEverGiven() {
  try { return localStorage.getItem(RBCF_UPDATE_CONSENT_KEY) === '1'; }
  catch (e) { return false; }
}

function rbcfUpdateRecordConsent() {
  try { localStorage.setItem(RBCF_UPDATE_CONSENT_KEY, '1'); }
  catch (e) { /* ignore */ }
  _rbcfUpdateConsentSession = true;
}

function rbcfUpdateBadgeDismissed(version) {
  if (!version) return false;
  try { return localStorage.getItem(RBCF_UPDATE_DISMISS_PREFIX + version) === '1'; }
  catch (e) { return false; }
}

function rbcfUpdateMarkBadgeDismissed(version) {
  if (!version) return;
  try { localStorage.setItem(RBCF_UPDATE_DISMISS_PREFIX + version, '1'); }
  catch (e) { /* ignore */ }
}

async function rbcfUpdateFetchCached() {
  try {
    const res = await fetch('/api/update-check', { method: 'GET' });
    if (!res.ok) return null;
    const data = await res.json();
    if (data && data.ok) {
      _rbcfUpdateLastInfo = data;
      _rbcfUpdateLocalVersionCache = data.current || _rbcfUpdateLocalVersionCache;
      rbcfUpdateRenderHeaderBadge(data);
      return data;
    }
  } catch (e) { /* ignore — offline-friendly */ }
  return null;
}

async function rbcfUpdatePostCheck(allowOnline, force) {
  try {
    const res = await fetch('/api/update-check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ allow_online: !!allowOnline, force: !!force }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    if (data && data.ok) {
      _rbcfUpdateLastInfo = data;
      _rbcfUpdateLocalVersionCache = data.current || _rbcfUpdateLocalVersionCache;
      rbcfUpdateRenderHeaderBadge(data);
      return data;
    }
  } catch (e) { /* ignore */ }
  return null;
}

function rbcfUpdateRenderStatusFromCache(pop) {
  if (_rbcfUpdateLastInfo) rbcfUpdateRenderStatus(pop, _rbcfUpdateLastInfo);
  else {
    const el = pop.querySelector('#rbcf-update-status');
    if (el) {
      el.className = 'rbcf-update-status rbcf-update-status-muted';
      el.textContent = 'Not yet checked.';
    }
  }
}

function rbcfUpdateRenderStatus(pop, info) {
  const statusEl = pop.querySelector('#rbcf-update-status');
  const verPill  = pop.querySelector('#rbcf-update-version-pill');
  if (verPill && info && info.current) {
    verPill.textContent = 'v' + info.current;
  }
  if (!statusEl || !info) return;

  // Determine which state to render.
  const src = info.source;
  const upd = !!info.update_available;
  const latest = info.latest;

  let html = '';
  let cls = 'rbcf-update-status';

  if (src === 'error') {
    cls += ' rbcf-update-status-error';
    html = `Last check failed: ${rbcfEscape(info.error || 'unknown')}. ` +
      `<button type="button" class="rbcf-update-link-btn" data-act="retry">Retry</button>`;
  } else if (src === 'unreleased') {
    cls += ' rbcf-update-status-muted';
    html = `No releases yet — dev build.`;
  } else if (upd && latest) {
    cls += ' rbcf-update-status-update';
    const notesUrl = info.release_url || '#';
    const installUrl = info.installer_url || info.release_url || '#';
    // Three action affordances:
    //   Upgrade       — direct installer download (or release page if
    //                   no .exe asset is attached to the release)
    //   Release notes — what the link used to be by itself
    //   Skip          — dismiss for this version only (same as the
    //                   header badge ×), persists in localStorage
    html = `<strong>v${rbcfEscape(latest)}</strong> available · ` +
      `<a class="rbcf-update-link rbcf-update-link-cta" href="${rbcfEscape(installUrl)}" target="_blank" rel="noopener">Upgrade ↗</a> · ` +
      `<a class="rbcf-update-link" href="${rbcfEscape(notesUrl)}" target="_blank" rel="noopener">Release notes</a> · ` +
      `<button type="button" class="rbcf-update-link rbcf-update-link-skip" data-skip-version="${rbcfEscape(latest)}">Skip this version</button>`;
  } else if (src === 'cache' && (!info.checked_at || !info.has_cache)) {
    cls += ' rbcf-update-status-muted';
    html = `Not yet checked.`;
  } else {
    cls += ' rbcf-update-status-ok';
    html = `Up to date.`;
  }

  statusEl.className = cls;
  statusEl.innerHTML = html;

  // Wire any inline buttons we just rendered.
  const retry = statusEl.querySelector('[data-act="retry"]');
  if (retry) {
    retry.addEventListener('click', (e) => {
      e.preventDefault();
      // Already consented at least once if we have any cached state at all,
      // but be safe: route through the same path Check-now uses.
      rbcfUpdateOnCheckNowClicked(pop);
    });
  }
  // Wire the "Skip this version" button. Persists the dismissal in
  // localStorage and re-renders the status row in muted "Up to date
  // (skipped vX)" state so the user can tell it took effect.
  const skipBtn = statusEl.querySelector('.rbcf-update-link-skip');
  if (skipBtn) {
    skipBtn.addEventListener('click', (e) => {
      e.preventDefault();
      const ver = skipBtn.getAttribute('data-skip-version');
      if (ver) {
        rbcfUpdateMarkBadgeDismissed(ver);
        // Hide the header badge if it's still visible
        const hdrBadge = document.getElementById('rbcf-update-badge');
        if (hdrBadge && hdrBadge.parentNode) {
          hdrBadge.parentNode.removeChild(hdrBadge);
        }
        // Update the status row to reflect the skipped state
        statusEl.className = 'rbcf-update-status rbcf-update-status-muted';
        statusEl.innerHTML = `Skipped v${rbcfEscape(ver)}. Will re-prompt when a newer release ships.`;
      }
    });
  }
}

function rbcfUpdateRenderHeaderBadge(info) {
  // Remove any existing badge first.
  const existing = document.getElementById('rbcf-update-badge');
  if (existing && existing.parentNode) existing.parentNode.removeChild(existing);

  if (!info || !info.update_available || !info.latest) return;
  if (rbcfUpdateBadgeDismissed(info.latest)) return;

  // Place inside .page-actions, just before the cog so order is
  // [pad-pills…] [update-badge] [cog].
  const actions = document.querySelector('.page-actions');
  if (!actions) return;
  const cog = document.getElementById('rbcf-apply-settings-cog');

  const badge = document.createElement('div');
  badge.id = 'rbcf-update-badge';
  badge.className = 'rbcf-update-badge';
  const notesUrl = info.release_url || '#';
  const installUrl = info.installer_url || info.release_url || '#';
  const ver = info.latest;
  badge.title = `Update available: v${ver}. Click 'Upgrade' to download the installer, or × to skip this version.`;
  // Two affordances on the header pill: the version label still leads
  // to release notes (low-friction information), an explicit "Upgrade"
  // CTA opens the installer, and × skips this version. Three icons in
  // a compact 16px-tall pill is a tight fit — kept short.
  badge.innerHTML = `
    <a class="rbcf-update-badge-link" href="${rbcfEscape(notesUrl)}" target="_blank" rel="noopener"
       aria-label="Update available: v${rbcfEscape(ver)} — release notes">v${rbcfEscape(ver)}</a>
    <a class="rbcf-update-badge-upgrade" href="${rbcfEscape(installUrl)}" target="_blank" rel="noopener"
       aria-label="Upgrade to v${rbcfEscape(ver)}">Upgrade</a>
    <button type="button" class="rbcf-update-badge-x" aria-label="Skip this version">×</button>
  `;
  if (cog) actions.insertBefore(badge, cog);
  else actions.appendChild(badge);

  badge.querySelector('.rbcf-update-badge-x').addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    rbcfUpdateMarkBadgeDismissed(ver);
    if (badge.parentNode) badge.parentNode.removeChild(badge);
  });
}

function rbcfUpdateOnCheckNowClicked(pop) {
  // Decide whether we need consent: first time AND no cache means we must
  // ask before hitting the network. If consent was previously given OR
  // we already have any cached entry (even an "online check not authorised"
  // stub means the user has at least seen this row before), we proceed.
  const haveCache = !!(_rbcfUpdateLastInfo && _rbcfUpdateLastInfo.has_cache);
  const consented = _rbcfUpdateConsentSession || rbcfUpdateConsentEverGiven();

  if (!consented && !haveCache) {
    rbcfUpdateShowConsentPrompt(pop);
    return;
  }
  rbcfUpdateRunCheck(pop);
}

function rbcfUpdateShowConsentPrompt(pop) {
  const consentEl = pop.querySelector('#rbcf-update-consent');
  if (!consentEl) return;
  consentEl.hidden = false;
  consentEl.innerHTML = `
    <span class="rbcf-update-consent-text">
      We'll fetch the latest release from
      <span class="rbcf-update-consent-host">github.com/ITViking-FIN/RetroControlMapper</span>.
      OK to proceed?
    </span>
    <span class="rbcf-update-consent-actions">
      <button type="button" class="rbcf-apply-btn rbcf-apply-btn-secondary" data-act="ok">Yes, check</button>
      <button type="button" class="rbcf-apply-btn rbcf-apply-btn-secondary" data-act="cancel">Cancel</button>
    </span>
  `;
  consentEl.querySelector('[data-act="ok"]').addEventListener('click', (e) => {
    e.preventDefault();
    rbcfUpdateRecordConsent();
    consentEl.hidden = true;
    consentEl.innerHTML = '';
    rbcfUpdateRunCheck(pop);
  });
  consentEl.querySelector('[data-act="cancel"]').addEventListener('click', (e) => {
    e.preventDefault();
    consentEl.hidden = true;
    consentEl.innerHTML = '';
  });
}

async function rbcfUpdateRunCheck(pop) {
  const btn = pop.querySelector('#rbcf-update-check-btn');
  const statusEl = pop.querySelector('#rbcf-update-status');
  if (btn) { btn.disabled = true; btn.textContent = 'Checking…'; }
  if (statusEl) {
    statusEl.className = 'rbcf-update-status rbcf-update-status-muted';
    statusEl.textContent = 'Checking…';
  }
  const info = await rbcfUpdatePostCheck(true, true);
  if (btn) { btn.disabled = false; btn.textContent = 'Check now'; }
  if (info) {
    rbcfUpdateRenderStatus(pop, info);
  } else if (statusEl) {
    statusEl.className = 'rbcf-update-status rbcf-update-status-error';
    statusEl.textContent = 'Check failed (network error).';
  }
}

// Page-load hook: read cached state, then optionally do a quiet refresh
// IF (a) auto-check is enabled, (b) consent has been given previously,
// and (c) cache is missing or stale (>24h). Without prior consent we just
// render whatever is cached and wait for the user to click Check now.
async function rbcfUpdateInit() {
  const cached = await rbcfUpdateFetchCached();
  if (!rbcfUpdateAutoCheckEnabled()) return;
  if (!rbcfUpdateConsentEverGiven()) return;
  // If we have a fresh-ish cache (any cache that was just served), the
  // backend already handles staleness via TTL — POST with force=false
  // will just return the cached entry if still fresh, or hit the net if not.
  // Either way it's a single round-trip and a non-issue.
  await rbcfUpdatePostCheck(true, false);
}

function injectSettingsCog() {
  // Slot the cog into the page header's action group (next to the pad-pill).
  // The cog is global UI — it doesn't belong inside the per-target panel where
  // the system/game selectors and Apply/Save buttons now live.
  let actions = document.querySelector('.page-actions');
  if (!actions) {
    // New-installation fallback: create the container inside <header>.
    const header = document.querySelector('header');
    if (!header) return;
    actions = document.createElement('div');
    actions.className = 'page-actions';
    header.appendChild(actions);
  }
  if ($('rbcf-apply-settings-cog')) return;
  const btn = document.createElement('button');
  btn.id = 'rbcf-apply-settings-cog';
  btn.type = 'button';
  btn.className = 'secondary rbcf-apply-settings-toggle';
  btn.title = 'RetroControlMapper Settings';
  btn.setAttribute('aria-label', 'Settings');
  btn.setAttribute('aria-haspopup', 'dialog');
  btn.setAttribute('aria-expanded', 'false');
  btn.innerHTML = `
    <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <circle cx="12" cy="12" r="3"/>
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
    </svg>
  `;
  actions.appendChild(btn);
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    if ($('rbcf-apply-settings-popover')) dismissSettingsPopover();
    else showSettingsPopover();
  });
}

// ============================================================
// v0.1.5 13b — NOTES popover (lifted from accordion section)
// ============================================================
// Doc icon sits in .page-actions, just before the settings cog. Click
// opens a popover with a textarea bound to the existing #notes element
// (hidden in the DOM via #notes-host). Existing notesEl.value accessors
// in profile load/save continue to work — the textarea is the same
// element regardless of where it's currently rendered.
//
// Pattern mirrors injectSettingsCog + showSettingsPopover.

let _rbcfNotesOutsideHandler = null;
let _rbcfNotesKeyHandler = null;

function injectNotesIcon() {
  let actions = document.querySelector('.page-actions');
  if (!actions) {
    const header = document.querySelector('header');
    if (!header) return;
    actions = document.createElement('div');
    actions.className = 'page-actions';
    header.appendChild(actions);
  }
  if ($('rbcf-notes-icon')) return;
  const btn = document.createElement('button');
  btn.id = 'rbcf-notes-icon';
  btn.type = 'button';
  btn.className = 'secondary rbcf-apply-settings-toggle';
  btn.title = 'Game notes';
  btn.setAttribute('aria-label', 'Game notes');
  btn.setAttribute('aria-haspopup', 'dialog');
  btn.setAttribute('aria-expanded', 'false');
  btn.innerHTML = `
    <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
      <polyline points="14 2 14 8 20 8"/>
      <line x1="9" y1="13" x2="15" y2="13"/>
      <line x1="9" y1="17" x2="13" y2="17"/>
    </svg>
  `;
  // Insert BEFORE the settings cog so order is [...badge, notes, cog].
  const cog = $('rbcf-apply-settings-cog');
  if (cog) actions.insertBefore(btn, cog);
  else actions.appendChild(btn);
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    if ($('rbcf-notes-popover')) dismissNotesPopover();
    else showNotesPopover();
  });
}

function dismissNotesPopover() {
  const pop = $('rbcf-notes-popover');
  if (pop) {
    // v0.1.5 13e: route the textarea to the inline pinned host (if
    // user ticked "Always keep visible") or back to the hidden host.
    // Either way it stays in the DOM and notesEl accessors keep working.
    const dest = getPinned('notes')
      ? document.querySelector('.rbcf-pinned-notes-host')
      : $('notes-host');
    _moveNotesContent(dest);
    pop.remove();
  }
  const icon = $('rbcf-notes-icon');
  if (icon) icon.setAttribute('aria-expanded', 'false');
  if (_rbcfNotesOutsideHandler) {
    document.removeEventListener('mousedown', _rbcfNotesOutsideHandler, true);
    _rbcfNotesOutsideHandler = null;
  }
  if (_rbcfNotesKeyHandler) {
    document.removeEventListener('keydown', _rbcfNotesKeyHandler, true);
    _rbcfNotesKeyHandler = null;
  }
}

function showNotesPopover() {
  dismissNotesPopover();
  const icon = $('rbcf-notes-icon');
  if (!icon) return;

  const pop = document.createElement('div');
  pop.id = 'rbcf-notes-popover';
  pop.className = 'rbcf-apply-settings-popover rbcf-notes-popover';
  pop.setAttribute('role', 'dialog');
  pop.setAttribute('aria-label', 'Game notes');
  pop.innerHTML = `
    <div class="rbcf-apply-settings-head">
      <h3 class="rbcf-apply-settings-title">Notes</h3>
      <button type="button" class="rbcf-apply-modal-x" aria-label="Close" data-act="close">×</button>
    </div>
    <div class="rbcf-apply-settings-body">
      <p class="rbcf-notes-help">Free-text notes about this game's controls. Kept in the profile YAML.</p>
      <div class="rbcf-notes-textarea-host"></div>
    </div>
    <div class="rbcf-pin-foot">
      <label class="rbcf-pin-toggle">
        <input type="checkbox" data-pin-panel="notes">
        Always keep notes visible
        <span class="rbcf-pin-note">renders inline below the controllers</span>
      </label>
    </div>
  `;
  document.body.appendChild(pop);

  // v0.1.5 13e: move the textarea into the popover, from wherever it
  // currently lives (hidden host or inline pinned host).
  const taHost = pop.querySelector('.rbcf-notes-textarea-host');
  _moveNotesContent(taHost);
  const ta = $('notes');
  if (ta) setTimeout(() => ta.focus(), 0);

  // Pin checkbox
  const pinChk = pop.querySelector('input[data-pin-panel="notes"]');
  if (pinChk) {
    pinChk.checked = getPinned('notes');
    pinChk.addEventListener('change', () => {
      setPinned('notes', pinChk.checked);
      applyPinnedStates();
    });
  }

  // Anchor below the icon, right-aligned to the page-actions edge.
  const r = icon.getBoundingClientRect();
  pop.style.position = 'absolute';
  pop.style.top = (r.bottom + 8 + window.scrollY) + 'px';
  pop.style.right = (window.innerWidth - r.right) + 'px';

  icon.setAttribute('aria-expanded', 'true');

  pop.querySelector('[data-act="close"]').addEventListener('click', dismissNotesPopover);
  _rbcfNotesOutsideHandler = (e) => {
    if (pop.contains(e.target)) return;
    if (icon.contains(e.target)) return;
    dismissNotesPopover();
  };
  _rbcfNotesKeyHandler = (e) => {
    if (e.key === 'Escape') dismissNotesPopover();
  };
  document.addEventListener('mousedown', _rbcfNotesOutsideHandler, true);
  document.addEventListener('keydown', _rbcfNotesKeyHandler, true);
}

// ============================================================
// v0.1.5 13d — Advanced game overrides popover
// ============================================================
// "Overrides" button sits in the target pane header (right of the
// target-name hint). Click → popover containing the #game-options
// div (same DOM element the existing renderers populate). Pattern
// mirrors the notes popover.
//
// Why not in the page-actions header strip: the overrides are
// per-target-system, not global. They belong WITH the target system
// the user is configuring, not in the global app chrome.

let _rbcfOverridesOutsideHandler = null;
let _rbcfOverridesKeyHandler = null;

function dismissOverridesPopover() {
  const pop = $('rbcf-overrides-popover');
  if (pop) {
    // v0.1.5 13e: route content to either the inline pinned host or
    // back to the hidden host. Keeps renderers + gameOpts ref intact.
    const dest = getPinned('overrides')
      ? document.querySelector('.rbcf-pinned-overrides-host')
      : $('game-options-host');
    _moveOverridesContent(dest);
    pop.remove();
  }
  // Reflect collapsed state on the icon-bar trigger (the legacy
  // btn-target-overrides stub is hidden; the real toggle is the icon).
  const icon = $('rbcf-overrides-icon');
  if (icon) icon.setAttribute('aria-expanded', 'false');
  const legacy = $('btn-target-overrides');
  if (legacy) legacy.setAttribute('aria-expanded', 'false');
  if (_rbcfOverridesOutsideHandler) {
    document.removeEventListener('mousedown', _rbcfOverridesOutsideHandler, true);
    _rbcfOverridesOutsideHandler = null;
  }
  if (_rbcfOverridesKeyHandler) {
    document.removeEventListener('keydown', _rbcfOverridesKeyHandler, true);
    _rbcfOverridesKeyHandler = null;
  }
}

function showOverridesPopover() {
  dismissOverridesPopover();
  // v0.1.5 13e: the trigger is now the icon-bar icon, not target-h2.
  const icon = $('rbcf-overrides-icon');
  if (!icon) return;

  const pop = document.createElement('div');
  pop.id = 'rbcf-overrides-popover';
  pop.className = 'rbcf-apply-settings-popover rbcf-overrides-popover';
  pop.setAttribute('role', 'dialog');
  pop.setAttribute('aria-label', 'Per-game overrides');
  pop.innerHTML = `
    <div class="rbcf-apply-settings-head">
      <h3 class="rbcf-apply-settings-title">Advanced game overrides</h3>
      <button type="button" class="rbcf-apply-modal-x" aria-label="Close" data-act="close">×</button>
    </div>
    <div class="rbcf-apply-settings-body">
      <p class="rbcf-overrides-help">Keyboard pass-through, focus capture, joy-port — writes <code>es_settings.cfg</code> per-game keys.</p>
      <div class="rbcf-overrides-host"></div>
    </div>
    <div class="rbcf-pin-foot">
      <label class="rbcf-pin-toggle">
        <input type="checkbox" data-pin-panel="overrides">
        Always keep overrides visible
        <span class="rbcf-pin-note">renders inline below the controllers</span>
      </label>
    </div>
  `;
  document.body.appendChild(pop);

  // v0.1.5 13e: move overrides content into the popover, from wherever
  // it currently lives (hidden host or inline pinned host).
  const host = pop.querySelector('.rbcf-overrides-host');
  _moveOverridesContent(host);

  // Anchor below the icon, right-aligned to the page-actions edge.
  const r = icon.getBoundingClientRect();
  pop.style.position = 'absolute';
  pop.style.top = (r.bottom + 8 + window.scrollY) + 'px';
  pop.style.right = (window.innerWidth - r.right) + 'px';

  icon.setAttribute('aria-expanded', 'true');

  // Pin checkbox
  const pinChk = pop.querySelector('input[data-pin-panel="overrides"]');
  if (pinChk) {
    pinChk.checked = getPinned('overrides');
    pinChk.addEventListener('change', () => {
      setPinned('overrides', pinChk.checked);
      applyPinnedStates();
    });
  }

  pop.querySelector('[data-act="close"]').addEventListener('click', dismissOverridesPopover);
  _rbcfOverridesOutsideHandler = (e) => {
    if (pop.contains(e.target)) return;
    if (icon.contains(e.target)) return;
    dismissOverridesPopover();
  };
  _rbcfOverridesKeyHandler = (e) => {
    if (e.key === 'Escape') dismissOverridesPopover();
  };
  document.addEventListener('mousedown', _rbcfOverridesOutsideHandler, true);
  document.addEventListener('keydown', _rbcfOverridesKeyHandler, true);
}

// v0.1.5 13e: legacy stub. The btn-target-overrides element is now an
// inert <button hidden> placeholder in index.html (backwards-compat).
// The real Overrides trigger lives in the .page-actions icon-bar via
// injectOverridesIcon(). Kept as a no-op so any old callers don't crash.
function wireTargetOverridesButton() { /* no-op — see injectOverridesIcon */ }

// ============================================================
// v0.1.5 13e — Overrides icon in the page-actions icon-bar
// ============================================================
// Lifts the per-game overrides trigger out of the target-h2 button
// and into the global icon-bar alongside Mappings / Notes / Settings.
// All four panels now share the same entry-point pattern and the same
// "Always keep visible" pin toggle.

function injectOverridesIcon() {
  let actions = document.querySelector('.page-actions');
  if (!actions) {
    const header = document.querySelector('header');
    if (!header) return;
    actions = document.createElement('div');
    actions.className = 'page-actions';
    header.appendChild(actions);
  }
  if ($('rbcf-overrides-icon')) return;
  const btn = document.createElement('button');
  btn.id = 'rbcf-overrides-icon';
  btn.type = 'button';
  btn.className = 'secondary rbcf-apply-settings-toggle';
  btn.title = 'Advanced game overrides';
  btn.setAttribute('aria-label', 'Game overrides');
  btn.setAttribute('aria-haspopup', 'dialog');
  btn.setAttribute('aria-expanded', 'false');
  btn.innerHTML = `
    <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <line x1="4" y1="21" x2="4" y2="14"/>
      <line x1="4" y1="10" x2="4" y2="3"/>
      <line x1="12" y1="21" x2="12" y2="12"/>
      <line x1="12" y1="8" x2="12" y2="3"/>
      <line x1="20" y1="21" x2="20" y2="16"/>
      <line x1="20" y1="12" x2="20" y2="3"/>
      <line x1="1" y1="14" x2="7" y2="14"/>
      <line x1="9" y1="8" x2="15" y2="8"/>
      <line x1="17" y1="16" x2="23" y2="16"/>
    </svg>
    <span class="rbcf-icon-badge" hidden></span>
  `;
  // Workflow ordering: Mappings → Overrides → Notes → Settings.
  // Insert before notes (if present), else before settings cog, else append.
  const notes = $('rbcf-notes-icon');
  const cog = $('rbcf-apply-settings-cog');
  if (notes) actions.insertBefore(btn, notes);
  else if (cog) actions.insertBefore(btn, cog);
  else actions.appendChild(btn);
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    if ($('rbcf-overrides-popover')) dismissOverridesPopover();
    else showOverridesPopover();
  });
}

// ============================================================
// v0.1.5 13e — Mappings icon + popover
// ============================================================
// Lifts the "Custom button → keystroke mappings" grid out of the
// removed <section id="sec-mappings"> into a popover anchored to
// the ⌨ icon in the page-actions icon-bar. The #mappings-grid div
// reparents between #mappings-host (hidden), .rbcf-mappings-host
// (popover), and .rbcf-pinned-mappings-host (inline pinned).
// buildMappingRows() doesn't care where the grid currently lives.

let _rbcfMappingsOutsideHandler = null;
let _rbcfMappingsKeyHandler = null;

function injectMappingsIcon() {
  let actions = document.querySelector('.page-actions');
  if (!actions) {
    const header = document.querySelector('header');
    if (!header) return;
    actions = document.createElement('div');
    actions.className = 'page-actions';
    header.appendChild(actions);
  }
  if ($('rbcf-mappings-icon')) return;
  const btn = document.createElement('button');
  btn.id = 'rbcf-mappings-icon';
  btn.type = 'button';
  btn.className = 'secondary rbcf-apply-settings-toggle';
  btn.title = 'Button → keystroke mappings';
  btn.setAttribute('aria-label', 'Button mappings');
  btn.setAttribute('aria-haspopup', 'dialog');
  btn.setAttribute('aria-expanded', 'false');
  btn.innerHTML = `
    <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <rect x="2" y="4" width="20" height="16" rx="2"/>
      <path d="M6 8h.01M10 8h.01M14 8h.01M18 8h.01M8 12h.01M12 12h.01M16 12h.01M7 16h10"/>
    </svg>
    <span class="rbcf-icon-badge" hidden></span>
  `;
  // Mappings is first in workflow order — insert before everything else.
  const overrides = $('rbcf-overrides-icon');
  const notes = $('rbcf-notes-icon');
  const cog = $('rbcf-apply-settings-cog');
  const anchor = overrides || notes || cog;
  if (anchor) actions.insertBefore(btn, anchor);
  else actions.appendChild(btn);
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    if ($('rbcf-mappings-popover')) dismissMappingsPopover();
    else showMappingsPopover();
  });
}

function dismissMappingsPopover() {
  const pop = $('rbcf-mappings-popover');
  if (pop) {
    // Route the grid back to either the inline pinned host (if pinned)
    // or the hidden host. Either way it stays in the DOM.
    const dest = getPinned('mappings')
      ? document.querySelector('.rbcf-pinned-mappings-host')
      : $('mappings-host');
    _moveMappingsContent(dest);
    pop.remove();
  }
  const icon = $('rbcf-mappings-icon');
  if (icon) icon.setAttribute('aria-expanded', 'false');
  if (_rbcfMappingsOutsideHandler) {
    document.removeEventListener('mousedown', _rbcfMappingsOutsideHandler, true);
    _rbcfMappingsOutsideHandler = null;
  }
  if (_rbcfMappingsKeyHandler) {
    document.removeEventListener('keydown', _rbcfMappingsKeyHandler, true);
    _rbcfMappingsKeyHandler = null;
  }
}

function showMappingsPopover() {
  dismissMappingsPopover();
  const icon = $('rbcf-mappings-icon');
  if (!icon) return;

  const pop = document.createElement('div');
  pop.id = 'rbcf-mappings-popover';
  pop.className = 'rbcf-apply-settings-popover rbcf-mappings-popover';
  pop.setAttribute('role', 'dialog');
  pop.setAttribute('aria-label', 'Button mappings');
  pop.innerHTML = `
    <div class="rbcf-apply-settings-head">
      <h3 class="rbcf-apply-settings-title">Button mappings</h3>
      <button type="button" class="rbcf-apply-modal-x" aria-label="Close" data-act="close">×</button>
    </div>
    <div class="rbcf-apply-settings-body">
      <p class="rbcf-mappings-help">Map a pad button to a keyboard key. Writes <code>core_options</code> to <code>retroarch-core-options.cfg</code>.</p>
      <div class="rbcf-kbd-tip" data-rbcf-tip="mappings-intro">
        <svg class="rbcf-kbd-tip-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <rect x="2" y="6" width="20" height="14" rx="2"/>
          <path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M8 14h.01M12 14h.01M16 14h.01M7 18h10"/>
        </svg>
        <span>
          Click <strong>listen</strong> on a row, then press the key you want bound to that pad button.
          <span class="rbcf-kbd-tip-note">Mappings apply <strong>per system</strong> (libretro core options), not per game.</span>
        </span>
        <button type="button" class="rbcf-kbd-tip-dismiss" title="Dismiss this tip" aria-label="Dismiss">×</button>
      </div>
      <div class="rbcf-mappings-host"></div>
    </div>
    <div class="rbcf-pin-foot">
      <label class="rbcf-pin-toggle">
        <input type="checkbox" data-pin-panel="mappings">
        Always keep mappings visible
        <span class="rbcf-pin-note">renders inline below the controllers</span>
      </label>
    </div>
  `;
  document.body.appendChild(pop);

  // Move the grid into the popover (from wherever it currently lives).
  const host = pop.querySelector('.rbcf-mappings-host');
  _moveMappingsContent(host);

  // Honour any dismissed-tip preference
  if (localStorage.getItem('rbcf-tip-mappings-intro-dismissed') === '1') {
    const tip = pop.querySelector('[data-rbcf-tip="mappings-intro"]');
    if (tip) tip.hidden = true;
  }

  // Anchor below the icon, right-aligned to the page-actions edge.
  const r = icon.getBoundingClientRect();
  pop.style.position = 'absolute';
  pop.style.top = (r.bottom + 8 + window.scrollY) + 'px';
  pop.style.right = (window.innerWidth - r.right) + 'px';

  icon.setAttribute('aria-expanded', 'true');

  // Initialise pin checkbox + wire its handler
  const pinChk = pop.querySelector('input[data-pin-panel="mappings"]');
  if (pinChk) {
    pinChk.checked = getPinned('mappings');
    pinChk.addEventListener('change', () => {
      setPinned('mappings', pinChk.checked);
      applyPinnedStates();
    });
  }

  // Tip dismiss
  const tipDismiss = pop.querySelector('.rbcf-kbd-tip-dismiss');
  if (tipDismiss) {
    tipDismiss.addEventListener('click', (e) => {
      e.stopPropagation();
      localStorage.setItem('rbcf-tip-mappings-intro-dismissed', '1');
      const tip = pop.querySelector('[data-rbcf-tip="mappings-intro"]');
      if (tip) tip.hidden = true;
    });
  }

  pop.querySelector('[data-act="close"]').addEventListener('click', dismissMappingsPopover);
  _rbcfMappingsOutsideHandler = (e) => {
    if (pop.contains(e.target)) return;
    if (icon.contains(e.target)) return;
    dismissMappingsPopover();
  };
  _rbcfMappingsKeyHandler = (e) => {
    if (e.key === 'Escape') dismissMappingsPopover();
  };
  document.addEventListener('mousedown', _rbcfMappingsOutsideHandler, true);
  document.addEventListener('keydown', _rbcfMappingsKeyHandler, true);
}

// ============================================================
// v0.1.5 Task 1 + 5 + 15 — Suggestions / contribution / community
// ============================================================
// Three flows live behind the 💡 icon:
//   1. Auto-load: when a (system, rom) pair selects, fetch the
//      bindings_db hit and surface it as per-row Apply / Reject.
//   2. PDF contribution: drag a PDF onto the popover → backend runs
//      pypdf-only extraction (no OCR on end-user machine) → results
//      render in the same suggestions list.
//   3. Community submit: ticking "submit to community" on Save Profile
//      builds a pre-filled GitHub Issue URL and opens it. No OAuth in
//      this MVP — the project owner triages issues into bindings_db
//      manually until the full Task-15 PR flow lands.

let _rbcfSuggestionsOutsideHandler = null;
let _rbcfSuggestionsKeyHandler = null;
// Most-recent successful hit. Drives the count badge + the suggestions
// list rendering. Cleared on system/game change before re-fetching.
let _rbcfSuggestionsState = { system: '', rom: '', hit: null, source: '' };

function injectSuggestionsIcon() {
  let actions = document.querySelector('.page-actions');
  if (!actions) {
    const header = document.querySelector('header');
    if (!header) return;
    actions = document.createElement('div');
    actions.className = 'page-actions';
    header.appendChild(actions);
  }
  if ($('rbcf-suggestions-icon')) return;
  const btn = document.createElement('button');
  btn.id = 'rbcf-suggestions-icon';
  btn.type = 'button';
  btn.className = 'secondary rbcf-apply-settings-toggle';
  btn.title = 'Suggested bindings from the game manual';
  btn.setAttribute('aria-label', 'Suggestions');
  btn.setAttribute('aria-haspopup', 'dialog');
  btn.setAttribute('aria-expanded', 'false');
  btn.innerHTML = `
    <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      <path d="M9 18h6"/>
      <path d="M10 22h4"/>
      <path d="M12 2a7 7 0 0 0-7 7c0 3 2 5 3 6.5.7 1 .9 1.7 1 2.5h6c.1-.8.3-1.5 1-2.5 1-1.5 3-3.5 3-6.5a7 7 0 0 0-7-7z"/>
    </svg>
    <span class="rbcf-icon-badge" hidden></span>
  `;
  // Suggestions is the FIRST icon (upstream of mappings — the
  // suggestions feed the mapping work). Insert before everything else.
  const mappings = $('rbcf-mappings-icon');
  const overrides = $('rbcf-overrides-icon');
  const notes = $('rbcf-notes-icon');
  const cog = $('rbcf-apply-settings-cog');
  const anchor = mappings || overrides || notes || cog;
  if (anchor) actions.insertBefore(btn, anchor);
  else actions.appendChild(btn);
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    if ($('rbcf-suggestions-popover')) dismissSuggestionsPopover();
    else showSuggestionsPopover();
  });
}

function dismissSuggestionsPopover() {
  const pop = $('rbcf-suggestions-popover');
  if (pop) {
    const dest = getPinned('suggestions')
      ? document.querySelector('.rbcf-pinned-suggestions-host')
      : $('suggestions-host');
    _moveSuggestionsContent(dest);
    pop.remove();
  }
  const icon = $('rbcf-suggestions-icon');
  if (icon) icon.setAttribute('aria-expanded', 'false');
  if (_rbcfSuggestionsOutsideHandler) {
    document.removeEventListener('mousedown', _rbcfSuggestionsOutsideHandler, true);
    _rbcfSuggestionsOutsideHandler = null;
  }
  if (_rbcfSuggestionsKeyHandler) {
    document.removeEventListener('keydown', _rbcfSuggestionsKeyHandler, true);
    _rbcfSuggestionsKeyHandler = null;
  }
}

function showSuggestionsPopover() {
  dismissSuggestionsPopover();
  const icon = $('rbcf-suggestions-icon');
  if (!icon) return;

  const pop = document.createElement('div');
  pop.id = 'rbcf-suggestions-popover';
  pop.className = 'rbcf-apply-settings-popover rbcf-suggestions-popover';
  pop.setAttribute('role', 'dialog');
  pop.setAttribute('aria-label', 'Suggested bindings');
  pop.innerHTML = `
    <div class="rbcf-apply-settings-head">
      <h3 class="rbcf-apply-settings-title">Suggestions from manual</h3>
      <button type="button" class="rbcf-apply-modal-x" aria-label="Close" data-act="close">×</button>
    </div>
    <div class="rbcf-apply-settings-body">
      <p class="rbcf-mappings-help">
        Bindings the manual extraction found for this game. Review each one,
        apply what looks right, edit or reject the rest. Saved choices land
        in your local profile and the per-machine user DB.
      </p>
      <div class="rbcf-suggestions-host"></div>
      <div class="rbcf-pdf-drop" data-rbcf-pdf-drop>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="17 8 12 3 7 8"/>
          <line x1="12" y1="3" x2="12" y2="15"/>
        </svg>
        <div>
          <strong>Got the manual?</strong> Drop the PDF here.
          <div class="rbcf-pdf-drop-note">Text-PDFs only (no OCR on your machine). Scanned manuals will surface a warning.</div>
        </div>
        <input type="file" accept="application/pdf,.pdf" data-rbcf-pdf-input hidden>
        <button type="button" class="rbcf-pdf-pick" data-rbcf-pdf-pick>Choose file…</button>
      </div>
      <div class="rbcf-community-foot">
        <label class="rbcf-pin-toggle">
          <input type="checkbox" data-rbcf-submit-toggle>
          Submit my approved bindings to the community DB on Save Profile
          <span class="rbcf-pin-note">opens a pre-filled GitHub Issue in your browser</span>
        </label>
      </div>
    </div>
    <div class="rbcf-pin-foot">
      <label class="rbcf-pin-toggle">
        <input type="checkbox" data-pin-panel="suggestions">
        Always keep suggestions visible
        <span class="rbcf-pin-note">renders inline below the controllers</span>
      </label>
    </div>
  `;
  document.body.appendChild(pop);

  // Move the suggestions body into the popover (from hidden or pinned host).
  const host = pop.querySelector('.rbcf-suggestions-host');
  _moveSuggestionsContent(host);

  // Re-render the body in case state changed while the popover was closed.
  renderSuggestions();

  // Anchor below the icon, right-aligned to the page-actions edge.
  const r = icon.getBoundingClientRect();
  pop.style.position = 'absolute';
  pop.style.top = (r.bottom + 8 + window.scrollY) + 'px';
  pop.style.right = (window.innerWidth - r.right) + 'px';
  icon.setAttribute('aria-expanded', 'true');

  // Pin checkbox
  const pinChk = pop.querySelector('input[data-pin-panel="suggestions"]');
  if (pinChk) {
    pinChk.checked = getPinned('suggestions');
    pinChk.addEventListener('change', () => {
      setPinned('suggestions', pinChk.checked);
      applyPinnedStates();
    });
  }
  // Restore "submit to community" pref from localStorage
  const submitChk = pop.querySelector('input[data-rbcf-submit-toggle]');
  if (submitChk) {
    submitChk.checked = localStorage.getItem('rbcf-community-submit') === '1';
    submitChk.addEventListener('change', () => {
      localStorage.setItem('rbcf-community-submit', submitChk.checked ? '1' : '0');
    });
  }
  // PDF drop wiring
  wirePdfDropZone(pop);

  pop.querySelector('[data-act="close"]').addEventListener('click', dismissSuggestionsPopover);
  _rbcfSuggestionsOutsideHandler = (e) => {
    if (pop.contains(e.target)) return;
    if (icon.contains(e.target)) return;
    dismissSuggestionsPopover();
  };
  _rbcfSuggestionsKeyHandler = (e) => {
    if (e.key === 'Escape') dismissSuggestionsPopover();
  };
  document.addEventListener('mousedown', _rbcfSuggestionsOutsideHandler, true);
  document.addEventListener('keydown', _rbcfSuggestionsKeyHandler, true);
}

function _moveSuggestionsContent(toHost) {
  if (!toHost) return;
  const body = $('suggestions-body');
  if (body && body.parentElement !== toHost) toHost.appendChild(body);
}

// Render the current state into #suggestions-body wherever it lives
// (hidden host / popover / inline pinned card).
function renderSuggestions() {
  const body = $('suggestions-body');
  if (!body) return;
  const state = _rbcfSuggestionsState;
  if (!state.system || !state.rom) {
    body.innerHTML = `
      <div class="rbcf-suggestions-empty" data-rbcf-empty>
        Pick a system + game above. If we have manual-extracted
        bindings for it, they'll appear here.
      </div>`;
    return;
  }
  const hit = state.hit;
  const bindings = (hit && hit.bindings) || [];
  if (!bindings.length) {
    body.innerHTML = `
      <div class="rbcf-suggestions-empty" data-rbcf-empty>
        No manual bindings on file for <strong>${rbcfEsc(state.rom)}</strong>
        (<code>${rbcfEsc(state.system)}</code>). You can drop a PDF below
        to extract some, or map controls manually.
      </div>`;
    return;
  }
  const title = rbcfEsc(hit.title || state.rom);
  const src   = (hit.source || state.source || 'bundled');
  const hdr = `
    <div class="rbcf-suggestions-head">
      <strong>${title}</strong>
      <span class="rbcf-suggestion-src-chip src-${rbcfEsc(src)}">${rbcfEsc(src)}</span>
      <button type="button" class="rbcf-apply-all" data-rbcf-apply-all>Apply all</button>
    </div>`;
  const rows = bindings.map((b, i) => {
    const btn  = rbcfEsc(b.button || '?');
    const act  = rbcfEsc(b.action || '');
    const conf = (b.confidence || 'medium').toLowerCase();
    const ext  = (b.extractor || b.matched_by || 'unknown').toLowerCase();
    let kind = 'regex';
    if (ext.includes('llm')) kind = 'llm';
    else if (ext.includes('controls.dat') || ext.includes('arcade')) kind = 'arcade';
    else if (ext.includes('user')) kind = 'user';
    return `
      <div class="rbcf-suggestion-row" data-i="${i}">
        <span class="rbcf-suggestion-btn">${btn}</span>
        <span class="rbcf-suggestion-action">${act}</span>
        <span class="rbcf-suggestion-chips">
          <span class="rbcf-conf-chip conf-${rbcfEsc(conf)}">${rbcfEsc(conf)}</span>
          <span class="rbcf-kind-chip kind-${kind}">${kind}</span>
        </span>
        <span class="rbcf-suggestion-actions">
          <button type="button" class="rbcf-apply-row" data-rbcf-apply-row="${i}" title="Apply this binding">apply</button>
          <button type="button" class="rbcf-reject-row" data-rbcf-reject-row="${i}" title="Reject (hide)">reject</button>
        </span>
      </div>`;
  }).join('');
  body.innerHTML = hdr + `<div class="rbcf-suggestion-rows">${rows}</div>`;
  // Update inline pinned-card count hint
  document.querySelectorAll('[data-rbcf-suggestions-count]').forEach(el => {
    el.textContent = `${bindings.length} ${bindings.length === 1 ? 'binding' : 'bindings'}`;
  });
  // Wire row buttons
  body.querySelectorAll('[data-rbcf-apply-row]').forEach(b => {
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      const idx = +b.getAttribute('data-rbcf-apply-row');
      applySuggestion(idx);
    });
  });
  body.querySelectorAll('[data-rbcf-reject-row]').forEach(b => {
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      const idx = +b.getAttribute('data-rbcf-reject-row');
      rejectSuggestion(idx);
    });
  });
  const allBtn = body.querySelector('[data-rbcf-apply-all]');
  if (allBtn) allBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    applyAllSuggestions();
  });
}

// Apply a single suggestion to the live mapping grid. The binding's
// "button" maps to a PAD button; the "action" is the keyboard key
// (RETROK_*) we'll write into the input. If "action" doesn't start
// with RETROK_, we coerce — the validator on the server accepts
// either form for now.
function applySuggestion(i) {
  const hit = _rbcfSuggestionsState.hit;
  if (!hit) return;
  const b = (hit.bindings || [])[i];
  if (!b) return;
  const padBtn = (b.button || '').toLowerCase();
  let act = (b.action || '').trim();
  if (act && !/^RETROK_/i.test(act)) act = `RETROK_${act.toUpperCase().replace(/[^A-Z0-9_]+/g,'_')}`;
  const inp = document.querySelector(`input[data-map-btn="${padBtn}"]`);
  if (!inp) {
    showToast(`No row for pad button '${padBtn}' — skipped.`, 'warn', 2400);
    return;
  }
  inp.value = act;
  inp.dispatchEvent(new Event('input', { bubbles: true }));
  inp.dispatchEvent(new Event('change', { bubbles: true }));
  showToast(`Applied ${padBtn.toUpperCase()} → ${act}`, 'success', 1800);
}
function applyAllSuggestions() {
  const hit = _rbcfSuggestionsState.hit;
  if (!hit) return;
  let n = 0;
  (hit.bindings || []).forEach((_, i) => {
    const b = hit.bindings[i];
    if (!b) return;
    const padBtn = (b.button || '').toLowerCase();
    let act = (b.action || '').trim();
    if (!act || !padBtn) return;
    if (!/^RETROK_/i.test(act)) act = `RETROK_${act.toUpperCase().replace(/[^A-Z0-9_]+/g,'_')}`;
    const inp = document.querySelector(`input[data-map-btn="${padBtn}"]`);
    if (!inp) return;
    inp.value = act;
    inp.dispatchEvent(new Event('input', { bubbles: true }));
    inp.dispatchEvent(new Event('change', { bubbles: true }));
    n++;
  });
  showToast(`Applied ${n} suggestion${n === 1 ? '' : 's'} to the mapping grid.`, 'success', 2200);
}
function rejectSuggestion(i) {
  const hit = _rbcfSuggestionsState.hit;
  if (!hit || !hit.bindings) return;
  hit.bindings.splice(i, 1);
  renderSuggestions();
  updateIconBadges();
}

// Fetch suggestions for the current (system, game) pair and re-render.
// Safe to call repeatedly — uses the cached _rbcfSuggestionsState so
// no-op when nothing changed.
async function refreshSuggestionsFor(system, rom) {
  system = (system || '').trim();
  rom    = (rom || '').trim();
  // Reset if pair changed
  if (system !== _rbcfSuggestionsState.system || rom !== _rbcfSuggestionsState.rom) {
    _rbcfSuggestionsState = { system, rom, hit: null, source: '' };
  }
  if (!system || !rom) {
    renderSuggestions();
    updateIconBadges();
    return;
  }
  try {
    const r = await fetch(`/api/suggestions?system=${encodeURIComponent(system)}&rom=${encodeURIComponent(rom)}`);
    const j = await r.json();
    _rbcfSuggestionsState.hit    = (j && j.hit) || null;
    _rbcfSuggestionsState.source = (j && j.hit && j.hit.source) || '';
  } catch (e) {
    _rbcfSuggestionsState.hit = null;
  }
  renderSuggestions();
  updateIconBadges();
}

// PDF drop / click-to-pick — multipart POST to /api/contribute-pdf
function wirePdfDropZone(scope) {
  const dz = scope.querySelector('[data-rbcf-pdf-drop]');
  const inp = scope.querySelector('[data-rbcf-pdf-input]');
  const pick = scope.querySelector('[data-rbcf-pdf-pick]');
  if (!dz || !inp || !pick) return;
  pick.addEventListener('click', (e) => { e.preventDefault(); inp.click(); });
  inp.addEventListener('change', () => {
    if (inp.files && inp.files[0]) uploadPdf(inp.files[0]);
  });
  ['dragenter','dragover'].forEach(ev => dz.addEventListener(ev, (e) => {
    e.preventDefault(); e.stopPropagation();
    dz.classList.add('drag-over');
  }));
  ['dragleave','drop'].forEach(ev => dz.addEventListener(ev, (e) => {
    e.preventDefault(); e.stopPropagation();
    dz.classList.remove('drag-over');
  }));
  dz.addEventListener('drop', (e) => {
    const f = (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]);
    if (f) uploadPdf(f);
  });
}
async function uploadPdf(file) {
  const system = (selSystem && selSystem.value) || _rbcfSuggestionsState.system;
  const rom    = (selGame && selGame.value)    || _rbcfSuggestionsState.rom;
  if (!system || !rom) {
    showToast('Pick a system + game first, then drop the PDF.', 'warn', 2600);
    return;
  }
  if (!/\.pdf$/i.test(file.name) && file.type !== 'application/pdf') {
    showToast('That doesn\'t look like a PDF.', 'error', 2400);
    return;
  }
  const fd = new FormData();
  fd.append('pdf', file, file.name);
  fd.append('system_id', system);
  fd.append('rom_name', rom);
  showToast(`Extracting bindings from ${file.name}…`, 'info', 1400);
  try {
    const r = await fetch('/api/contribute-pdf', { method: 'POST', body: fd });
    const j = await r.json();
    if (!j.ok) {
      showToast(`Extraction failed: ${j.error || 'unknown error'}`, 'error', 3000);
      return;
    }
    const res = j.result || {};
    const warn = res.extra && res.extra.warning;
    const nb = (res.bindings || []).length;
    if (warn) {
      showToast(warn, 'warn', 4200);
    }
    if (nb === 0) {
      showToast(`No bindings auto-extracted from ${file.name}.`, 'info', 2400);
      return;
    }
    // Merge into the current state so the suggestions panel shows them.
    _rbcfSuggestionsState.hit = {
      source: 'user_pdf',
      title:  res.title || rom,
      bindings: res.bindings,
    };
    _rbcfSuggestionsState.source = 'user_pdf';
    renderSuggestions();
    updateIconBadges();
    showToast(`Extracted ${nb} binding${nb === 1 ? '' : 's'} from ${file.name}. Review and apply.`, 'success', 2800);
  } catch (e) {
    showToast(`Upload failed: ${e.message || e}`, 'error', 2800);
  }
}

// Build a pre-filled GitHub Issue URL with the user's confirmed
// bindings as the body. No OAuth — opens the user's browser to a
// GitHub Issue compose page with title + body + labels prefilled.
// The project owner triages issues into bindings_db manually until
// the full Task-15 OAuth-backed PR flow lands.
function buildCommunitySubmitUrl(system, rom, bindings) {
  const owner = (window.RBCF_GH_OWNER || 'ITViking-FIN');
  const repo  = (window.RBCF_GH_REPO  || 'RetroControlMapper');
  const title = `[bindings] ${system}: ${rom}`;
  const body  = [
    '<!-- Auto-generated by RetroControlMapper. Paste any context after this block. -->',
    '',
    `**System:** \`${system}\``,
    `**Game:** \`${rom}\``,
    `**Submitted:** ${new Date().toISOString()}`,
    `**Client version:** v0.1.5`,
    '',
    '## Bindings',
    '',
    '```json',
    JSON.stringify({ system_id: system, rom_name: rom, bindings }, null, 2),
    '```',
    '',
    '<!-- Optional: please describe the manual source (link, archive, etc.) -->',
  ].join('\n');
  const url = `https://github.com/${owner}/${repo}/issues/new`
            + `?labels=community-binding,bindings-submission`
            + `&title=${encodeURIComponent(title)}`
            + `&body=${encodeURIComponent(body)}`;
  return url;
}
// Called by save flow when user ticked "Submit to community DB on save".
async function submitBindingsToCommunity() {
  const hit = _rbcfSuggestionsState.hit;
  const system = _rbcfSuggestionsState.system || (selSystem && selSystem.value) || '';
  const rom    = _rbcfSuggestionsState.rom    || (selGame && selGame.value)    || '';
  if (!system || !rom) return false;
  // Also collect any user-edited keystroke bindings from the mapping grid
  // so the submission reflects the user's final state, not just the
  // suggestions snapshot.
  const collected = [];
  $$('input[data-map-btn]').forEach(inp => {
    const v = (inp.value || '').trim();
    if (!v || v === '---') return;
    collected.push({
      button: inp.dataset.mapBtn,
      action: v,
      confidence: 'high',
      matched_by: 'user',
      extractor:  'rbcf-gui-v0.1.5',
    });
  });
  if (!collected.length && !(hit && hit.bindings && hit.bindings.length)) {
    showToast('No bindings to submit yet — apply or enter some first.', 'warn', 2600);
    return false;
  }
  const url = buildCommunitySubmitUrl(system, rom, collected.length ? collected : hit.bindings);
  // Also persist a local queue copy via the backend (idempotent — backend
  // is the source of truth for the local copy).
  try {
    await fetch('/api/contribute-save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        system_id: system, rom_name: rom, title: rom,
        bindings: collected.length ? collected : hit.bindings,
        submit: true,
      }),
    });
  } catch (e) { /* non-fatal — the GH issue is the primary submit path */ }
  window.open(url, '_blank', 'noopener');
  showToast('Opened a pre-filled GitHub Issue in your browser. Submit when you\'re ready.', 'info', 3200);
  return true;
}

// ============================================================
// v0.1.5 13e — Pin state + reparent helpers
// ============================================================
// Each tuckable panel has three possible homes:
//   1. hidden host (in DOM, hidden)        — default state
//   2. popover (transient, body element)   — when icon clicked
//   3. inline pinned card (visible card)   — when user ticked "Always keep visible"
// Pin state is global (localStorage), not per-system. Persists across
// sessions. getPinned/setPinned + applyPinnedStates drive the toggle.

const RBCF_PIN_KEY = 'rbcf-pinned-panels';

function getPinned(panel) {
  try {
    const raw = localStorage.getItem(RBCF_PIN_KEY) || '{}';
    const map = JSON.parse(raw);
    return !!map[panel];
  } catch (e) { return false; }
}

function setPinned(panel, value) {
  let map = {};
  try { map = JSON.parse(localStorage.getItem(RBCF_PIN_KEY) || '{}'); } catch (e) {}
  if (value) map[panel] = true;
  else delete map[panel];
  try { localStorage.setItem(RBCF_PIN_KEY, JSON.stringify(map)); } catch (e) {}
}

// Per-panel content-mover. Each finds the panel's body wherever it
// currently is (hidden host, popover, or inline pinned host) and
// moves it to the destination element. If already there, noop.
function _moveMappingsContent(toHost) {
  if (!toHost) return;
  const grid = $('mappings-grid');
  if (grid && grid.parentElement !== toHost) toHost.appendChild(grid);
}
function _moveNotesContent(toHost) {
  if (!toHost) return;
  const ta = $('notes');
  if (ta && ta.parentElement !== toHost) {
    toHost.appendChild(ta);
    ta.hidden = false;
    ta.style.display = '';
  }
}
function _moveOverridesContent(toHost) {
  if (!toHost) return;
  // Overrides has multiple children (game-detail header + #game-options).
  // Collect from any host they might currently be in.
  const sources = [
    $('game-options-host'),
    document.querySelector('.rbcf-overrides-host'),
    document.querySelector('.rbcf-pinned-overrides-host'),
  ].filter(Boolean);
  for (const src of sources) {
    if (src === toHost) continue;
    while (src.firstChild) toHost.appendChild(src.firstChild);
  }
}

// Apply pin state to DOM: show/hide pinned cards, route content to
// correct host. Called on init and whenever pin state changes.
function applyPinnedStates() {
  const panels = [
    { name: 'suggestions', cardId: 'suggestions-pinned-card', pinnedHost: '.rbcf-pinned-suggestions-host', hiddenHostId: 'suggestions-host',  move: _moveSuggestionsContent, popoverOpen: () => !!$('rbcf-suggestions-popover'), popoverHost: '.rbcf-suggestions-host' },
    { name: 'mappings',    cardId: 'mappings-pinned-card',    pinnedHost: '.rbcf-pinned-mappings-host',    hiddenHostId: 'mappings-host',     move: _moveMappingsContent,    popoverOpen: () => !!$('rbcf-mappings-popover'),    popoverHost: '.rbcf-mappings-host' },
    { name: 'overrides',   cardId: 'overrides-pinned-card',   pinnedHost: '.rbcf-pinned-overrides-host',   hiddenHostId: 'game-options-host', move: _moveOverridesContent,   popoverOpen: () => !!$('rbcf-overrides-popover'),   popoverHost: '.rbcf-overrides-host' },
    { name: 'notes',       cardId: 'notes-pinned-card',       pinnedHost: '.rbcf-pinned-notes-host',       hiddenHostId: 'notes-host',        move: _moveNotesContent,       popoverOpen: () => !!$('rbcf-notes-popover'),       popoverHost: '.rbcf-notes-textarea-host' },
  ];
  for (const p of panels) {
    const pinned = getPinned(p.name);
    const card = $(p.cardId);
    if (card) card.hidden = !pinned;
    // Reflect pinned state on the icon (small dot indicator)
    const iconId = p.name === 'suggestions' ? 'rbcf-suggestions-icon'
                : p.name === 'mappings'     ? 'rbcf-mappings-icon'
                : p.name === 'overrides'    ? 'rbcf-overrides-icon'
                : p.name === 'notes'        ? 'rbcf-notes-icon' : null;
    if (iconId) {
      const icon = $(iconId);
      if (icon) {
        if (pinned) icon.setAttribute('data-pinned', '1');
        else icon.removeAttribute('data-pinned');
      }
    }
    // Route content. If a popover is open, leave the content there —
    // it'll be re-routed correctly on dismiss. Otherwise: pinned →
    // inline host, unpinned → hidden host.
    if (!p.popoverOpen()) {
      const dest = pinned
        ? document.querySelector(p.pinnedHost)
        : $(p.hiddenHostId);
      if (dest) p.move(dest);
    }
  }
  // Hide the whole slot wrapper if nothing pinned (the :has() CSS
  // already does this, but belt-and-braces for older browsers).
  const slot = $('rbcf-pinned-slot');
  if (slot) {
    const anyVisible = Array.from(slot.querySelectorAll('.pinned-card')).some(c => !c.hidden);
    slot.style.display = anyVisible ? '' : 'none';
  }
}

// Wire the × buttons on inline pinned cards to unpin the panel.
function wirePinnedUnpinButtons() {
  document.querySelectorAll('.pinned-unpin').forEach(btn => {
    if (btn._rbcfWired) return;
    btn._rbcfWired = true;
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const panel = btn.getAttribute('data-unpin');
      if (!panel) return;
      setPinned(panel, false);
      applyPinnedStates();
      updateIconBadges();
    });
  });
}

// ============================================================
// v0.1.5 13e — Icon count badges
// ============================================================
// Mappings badge = number of populated #mappings-grid inputs.
// Overrides badge = number of [data-opt-key] controls with non-default values.

function _countMappings() {
  let n = 0;
  document.querySelectorAll('#mappings-grid input[data-map-btn]').forEach(i => {
    const v = (i.value || '').trim();
    if (v && v !== '---') n++;
  });
  return n;
}
function _countOverrides() {
  let n = 0;
  document.querySelectorAll('[data-opt-key]').forEach(el => {
    if (el.type === 'checkbox') { if (el.checked) n++; }
    else { if ((el.value || '').trim() !== '') n++; }
  });
  return n;
}
function _renderBadge(iconId, count) {
  const icon = $(iconId);
  if (!icon) return;
  const badge = icon.querySelector('.rbcf-icon-badge');
  if (!badge) return;
  if (count > 0) {
    badge.textContent = String(count);
    badge.hidden = false;
  } else {
    badge.textContent = '';
    badge.hidden = true;
  }
}
function updateIconBadges() {
  _renderBadge('rbcf-mappings-icon',  _countMappings());
  _renderBadge('rbcf-overrides-icon', _countOverrides());
  // Suggestions badge — count of pending (not-yet-applied) bindings
  // from the currently-loaded game's manual hit.
  const hit = (typeof _rbcfSuggestionsState !== 'undefined' && _rbcfSuggestionsState) ? _rbcfSuggestionsState.hit : null;
  const sn = (hit && hit.bindings) ? hit.bindings.length : 0;
  _renderBadge('rbcf-suggestions-icon', sn);
}

// ============================================================
// Controller-images sub-modal (opened from the settings cog)
// ------------------------------------------------------------
// Lets the user upload a custom image for any detected controller
// (one that's missing art, or to override the synced "known" image).
// Backend: POST/DELETE /api/controller-image. UX is intentionally
// scoped to the cog only — no per-controller upload affordance lives
// on the pad-pill detail popover.
// ============================================================

let _rbcfCimgPrevFocus = null;
let _rbcfCimgTrapHandler = null;
let _rbcfCimgDragTarget = -1;       // padIndex currently highlighted by drag

function _rbcfCimgFocusables(root) {
  return Array.from(root.querySelectorAll(
    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
  )).filter(el => !el.disabled && el.offsetParent !== null);
}

function dismissControllerImagesModal() {
  const overlay = $('rbcf-cimg-modal');
  if (!overlay) return;
  if (_rbcfCimgTrapHandler) {
    document.removeEventListener('keydown', _rbcfCimgTrapHandler, true);
    _rbcfCimgTrapHandler = null;
  }
  overlay.remove();
  // Restore focus to whatever launched the modal — typically the cog.
  if (_rbcfCimgPrevFocus && document.contains(_rbcfCimgPrevFocus)) {
    try { _rbcfCimgPrevFocus.focus(); } catch (e) { /* ignore */ }
  } else {
    const cog = $('rbcf-apply-settings-cog');
    if (cog) { try { cog.focus(); } catch (e) { /* ignore */ } }
  }
  _rbcfCimgPrevFocus = null;
  _rbcfCimgDragTarget = -1;
}

// Tag any device URL with where the image came from. Indexed off the
// /api/devices `image` field (which load_catalog populates per the
// contrib-then-known preference order).
function _rbcfCimgSourceFor(dev) {
  const img = (dev && dev.image) || '';
  if (img.startsWith('/img/contrib/')) return 'contrib';
  if (img.startsWith('/img/known/'))   return 'known';
  return 'none';
}

function _rbcfCimgRowHTML(dev, idx) {
  const friendly = rbcfEsc(deviceFriendlyName(dev));
  const vid = rbcfEsc(dev.vid || '');
  const pid = rbcfEsc(dev.pid || '');
  const xinput = dev.xinput ? 'XInput' : 'HID';
  const src = _rbcfCimgSourceFor(dev);
  const srcLabel = src === 'contrib' ? 'contrib image'
                : src === 'known'   ? 'known image'
                : 'no image';
  const img = dev.image
    ? `<img src="${rbcfEsc(dev.image)}" alt="" loading="lazy">`
    : '<span class="rbcf-cimg-placeholder">·</span>';
  const removeBtn = (src === 'contrib')
    ? '<button type="button" class="rbcf-apply-btn rbcf-apply-btn-secondary rbcf-cimg-remove-btn" data-act="remove">Remove</button>'
    : '';
  return `
    <li class="rbcf-cimg-row" data-pad-index="${idx}" data-vid="${vid}" data-pid="${pid}">
      <span class="rbcf-cimg-thumb">${img}</span>
      <span class="rbcf-cimg-info">
        <span class="rbcf-cimg-name">${friendly}</span>
        <span class="rbcf-cimg-meta">
          <code>${vid}:${pid}</code> · ${xinput} ·
          <span class="rbcf-cimg-src rbcf-cimg-src-${src}">${srcLabel}</span>
        </span>
      </span>
      <span class="rbcf-cimg-actions">
        <button type="button" class="rbcf-apply-btn rbcf-apply-btn-secondary rbcf-cimg-upload-btn" data-act="upload">Upload…</button>
        ${removeBtn}
      </span>
    </li>
  `;
}

function _rbcfCimgRenderList() {
  const body = document.querySelector('#rbcf-cimg-modal .rbcf-cimg-list-host');
  if (!body) return;
  if (!LAST_DEVICES || !LAST_DEVICES.length) {
    body.innerHTML = `
      <div class="rbcf-cimg-empty">
        <p><strong>No controllers detected.</strong></p>
        <p class="rbcf-cimg-empty-hint">Connect a controller and click <strong>Rescan</strong>.</p>
      </div>
    `;
    return;
  }
  const rows = LAST_DEVICES.map((d, i) => _rbcfCimgRowHTML(d, i)).join('');
  body.innerHTML = `<ul class="rbcf-cimg-list" role="list">${rows}</ul>`;
}

async function _rbcfCimgPostUpload(vid, pid, file) {
  if (!file) return;
  if (file.size > 2_000_000) {
    showToast('Image is too large (max 2 MB).', 'error');
    return;
  }
  const fd = new FormData();
  fd.append('vid', vid);
  fd.append('pid', pid);
  fd.append('file', file);
  try {
    const r = await fetch('/api/controller-image', { method: 'POST', body: fd });
    const data = await r.json();
    if (!data.ok) {
      showToast('Upload failed: ' + (data.error || 'unknown error'), 'error');
      return;
    }
    showToast('Image saved.', 'success', 2200);
    await loadDevices();        // refresh LAST_DEVICES with new image URL
    _rbcfCimgRenderList();
  } catch (e) {
    showToast('Upload error: ' + e.message, 'error');
  }
}

async function _rbcfCimgDelete(vid, pid) {
  try {
    const r = await fetch(
      `/api/controller-image?vid=${encodeURIComponent(vid)}&pid=${encodeURIComponent(pid)}`,
      { method: 'DELETE' }
    );
    const data = await r.json();
    if (!data.ok) {
      showToast('Remove failed: ' + (data.error || 'unknown error'), 'error');
      return;
    }
    showToast(data.removed ? 'Image removed.' : 'No contrib image on file.', 'info', 2000);
    await loadDevices();
    _rbcfCimgRenderList();
  } catch (e) {
    showToast('Remove error: ' + e.message, 'error');
  }
}

function _rbcfCimgPickFile(vid, pid) {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/png,image/jpeg,image/webp,image/svg+xml,.png,.jpg,.jpeg,.webp,.svg';
  input.style.display = 'none';
  input.addEventListener('change', () => {
    const f = input.files && input.files[0];
    if (f) _rbcfCimgPostUpload(vid, pid, f);
    input.remove();
  });
  document.body.appendChild(input);
  input.click();
}

function showControllerImagesModal() {
  // Tear down any existing instance defensively.
  dismissControllerImagesModal();
  _rbcfCimgPrevFocus = document.activeElement;

  const overlay = document.createElement('div');
  overlay.id = 'rbcf-cimg-modal';
  overlay.className = 'rbcf-apply-modal-overlay';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.setAttribute('aria-labelledby', 'rbcf-cimg-modal-title');

  overlay.innerHTML = `
    <div class="rbcf-apply-modal-card rbcf-cimg-card" role="document">
      <div class="rbcf-apply-modal-head">
        <h2 class="rbcf-apply-modal-title" id="rbcf-cimg-modal-title">Controller images</h2>
        <button type="button" class="rbcf-apply-modal-x" aria-label="Close" data-act="close">×</button>
      </div>
      <div class="rbcf-apply-modal-banner">
        Upload an image for any detected controller. PNG, JPG, WebP, or SVG · 2 MB max. Drag a file onto a row, or use the row's <strong>Upload…</strong> button.
      </div>
      <div class="rbcf-apply-modal-body rbcf-cimg-drop">
        <div class="rbcf-cimg-list-host"></div>
      </div>
      <div class="rbcf-apply-modal-foot">
        <button type="button" class="rbcf-apply-btn rbcf-apply-btn-secondary" data-act="rescan">Rescan</button>
        <span class="rbcf-apply-spacer"></span>
        <button type="button" class="rbcf-apply-btn rbcf-apply-btn-primary" data-act="close-primary">Close</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);

  const card = overlay.querySelector('.rbcf-apply-modal-card');
  const closeBtn = overlay.querySelector('[data-act="close"]');
  const closePrimary = overlay.querySelector('[data-act="close-primary"]');
  const rescanBtn = overlay.querySelector('[data-act="rescan"]');
  const dropZone = overlay.querySelector('.rbcf-cimg-drop');

  // Initial render uses whatever is in LAST_DEVICES; kick a refresh in the
  // background so the list reflects newly-connected pads.
  _rbcfCimgRenderList();
  loadDevices().then(_rbcfCimgRenderList);

  // Backdrop click = close (only when clicking the overlay itself).
  overlay.addEventListener('mousedown', (e) => {
    if (e.target === overlay) dismissControllerImagesModal();
  });
  closeBtn.addEventListener('click', dismissControllerImagesModal);
  closePrimary.addEventListener('click', dismissControllerImagesModal);
  rescanBtn.addEventListener('click', async () => {
    rescanBtn.disabled = true;
    try {
      await loadDevices();
      _rbcfCimgRenderList();
    } finally {
      rescanBtn.disabled = false;
    }
  });

  // Per-row Upload/Remove via event delegation on the body.
  dropZone.addEventListener('click', (e) => {
    const btn = e.target.closest('button');
    if (!btn) return;
    const row = btn.closest('.rbcf-cimg-row');
    if (!row) return;
    const vid = row.dataset.vid || '';
    const pid = row.dataset.pid || '';
    if (!vid || !pid) return;
    if (btn.dataset.act === 'upload') _rbcfCimgPickFile(vid, pid);
    else if (btn.dataset.act === 'remove') _rbcfCimgDelete(vid, pid);
  });

  // Drag-and-drop. Highlight the row under the cursor; drop on a specific
  // row to upload to that controller. Drop in empty space = hint.
  const rowAt = (el) => el && el.closest('.rbcf-cimg-row');
  dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    const r = rowAt(e.target);
    dropZone.querySelectorAll('.rbcf-cimg-row.rbcf-cimg-row-drop').forEach(n => {
      if (n !== r) n.classList.remove('rbcf-cimg-row-drop');
    });
    if (r) {
      r.classList.add('rbcf-cimg-row-drop');
      _rbcfCimgDragTarget = parseInt(r.dataset.padIndex || '-1', 10);
    } else {
      _rbcfCimgDragTarget = -1;
    }
  });
  dropZone.addEventListener('dragleave', (e) => {
    if (e.target === dropZone) {
      dropZone.querySelectorAll('.rbcf-cimg-row-drop').forEach(n => n.classList.remove('rbcf-cimg-row-drop'));
      _rbcfCimgDragTarget = -1;
    }
  });
  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.querySelectorAll('.rbcf-cimg-row-drop').forEach(n => n.classList.remove('rbcf-cimg-row-drop'));
    const r = rowAt(e.target);
    const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (!file) return;
    if (!r) {
      showToast('Drop the file directly on a controller row.', 'info', 2400);
      return;
    }
    const vid = r.dataset.vid || '';
    const pid = r.dataset.pid || '';
    if (vid && pid) _rbcfCimgPostUpload(vid, pid, file);
  });

  // Focus-trap + Escape.
  _rbcfCimgTrapHandler = (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      dismissControllerImagesModal();
      return;
    }
    if (e.key !== 'Tab') return;
    const items = _rbcfCimgFocusables(card);
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault(); last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault(); first.focus();
    }
  };
  document.addEventListener('keydown', _rbcfCimgTrapHandler, true);

  // Auto-focus the primary action (Close — destructive ops are per-row,
  // so the safest landing spot is the modal's exit).
  setTimeout(() => { try { closePrimary.focus(); } catch (e) { /* ignore */ } }, 0);
}

// ============================================================
// Save / apply
// ============================================================

function setStatus(msg) {
  if (statusLine) statusLine.textContent = msg || '';
}

async function onSave() {
  if (!selSystem.value) { showToast('Pick a system first.', 'error'); return; }
  if (!selGame.value) {
    showToast('Per-system defaults: edit profiles/<system>/_default.yaml manually.', 'error'); return;
  }
  const btn = $('btn-save');
  const profile = collectProfile();
  // Decision #10: default flow saves YAML only and then prompts via a
  // dry-run preview modal before applying. Opt-in one-click skips it.
  const oneClick = isOneClickApplyEnabled();
  profile.apply = oneClick;
  btn.disabled = true;
  setStatus('saving…');
  try {
    const r = await api('POST', '/api/save', profile);
    if (!r.ok) {
      setStatus('save failed');
      showToast('Save failed: ' + (r.error || 'unknown'), 'error');
      return;
    }
    if (oneClick) {
      // Legacy one-click behaviour — server already attempted apply.
      let msg = `Saved ${profile.system}/${profile.rom}`;
      if (r.apply && r.apply.ok) msg += ' · applied';
      else if (r.apply) msg += ' · apply failed (' + (r.apply.error || 'rc ' + r.apply.returncode) + ')';
      setStatus('saved · ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
      showToast(msg, 'success');
    } else {
      setStatus('saved · review preview to apply');
      showToast(`Saved ${profile.system}/${profile.rom} — review preview.`, 'info', 2200);
      showApplyPreviewModal(profile);
    }
    await loadGames(profile.system);
    selGame.value = profile.rom;
    // v0.1.5 Task 15: if the user ticked "Submit my approved bindings
    // to the community DB" in the Suggestions popover footer, kick off
    // the GitHub-Issue submit flow now that the local save has landed.
    if (localStorage.getItem('rbcf-community-submit') === '1'
        && typeof submitBindingsToCommunity === 'function') {
      try { await submitBindingsToCommunity(); } catch (e) { /* non-fatal */ }
    }
  } catch (e) {
    setStatus('save error');
    showToast('Save error: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
  }
}

async function onApply() {
  const btn = $('btn-apply');
  btn.disabled = true;
  setStatus('applying…');
  try {
    const r = await api('POST', '/api/apply', {});
    if (r.ok) {
      setStatus('applied · ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
      showToast('Applied all profiles.', 'success');
    } else {
      setStatus('apply failed');
      showToast('Apply failed: ' + (r.error || 'rc ' + r.returncode), 'error');
    }
  } catch (e) {
    setStatus('apply error');
    showToast('Apply error: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
  }
}

// ============================================================
// Wiring
// ============================================================

// ============================================================
// Click-across binding (v0.1.3-stretch — partial scope)
// Only enabled for systems WITHOUT fixed_mapping_note (the long tail
// where RetroBat's interpretation is unreliable). Curated systems
// keep their default mapping; v0.1.4 will ship a Customize option.
//
// Flow:
//   1. User clicks a source SVG button (or presses one) → ARMED
//   2. User clicks a target SVG button → POST /api/remap, .rmp written
//   3. Toast confirms; both sides flash; armed clears
//   4. Escape / outside click disarms
// ============================================================

let _armedSourceBtn = null;     // string like 'a' / 'b' / 'l2' / 'up'
let _clickAcrossEnabled = false;

function isClickAcrossEnabledForSystem(systemId) {
  const sys = (SYSTEMS || []).find(s => s.id === systemId);
  if (!sys) return false;
  // "Reliable" = has fixed_mapping_note. Click-across stays off there
  // until v0.1.4's Customize flow ships.
  return !sys.fixed_mapping_note;
}

function disarmSource() {
  if (!_armedSourceBtn) return;
  const el = document.getElementById(`src-btn-${_armedSourceBtn}`);
  if (el) el.classList.remove('armed');
  _armedSourceBtn = null;
}

function armSource(name) {
  if (!_clickAcrossEnabled) return;
  if (_armedSourceBtn === name) {
    disarmSource();
    return;
  }
  disarmSource();
  const el = document.getElementById(`src-btn-${name}`);
  if (!el) return;
  _armedSourceBtn = name;
  el.classList.add('armed');
}

async function bindArmedToTarget(targetEl) {
  if (!_armedSourceBtn) return;
  if (!_clickAcrossEnabled) return;
  const idxStr = targetEl.getAttribute('data-retropad');
  if (idxStr === null) {
    showToast('That target button has no libretro mapping defined.', 'error');
    return;
  }
  const targetIdx = parseInt(idxStr, 10);
  const sysId = selSystem.value;
  const rom = selGame.value;
  if (!rom) {
    showToast('Pick a game first — remaps are per-game.', 'error');
    disarmSource();
    return;
  }
  const source = _armedSourceBtn;
  // Optimistic visual: brief flash on the target
  targetEl.classList.add('bind-flash');
  setTimeout(() => targetEl.classList.remove('bind-flash'), 500);

  try {
    const r = await api('POST', '/api/remap', {
      system: sysId,
      rom,
      source,
      target_index: targetIdx,
    });
    if (r.ok) {
      const labelNode = targetEl.querySelector('text');
      const targetLabel = labelNode ? labelNode.textContent : `idx${targetIdx}`;
      showToast(`Bound ${source.toUpperCase()} → ${targetLabel}`, 'success', 2400);
      // Mark target as "has-binding" persistently
      targetEl.classList.add('has-binding');
    } else {
      showToast('Remap failed: ' + (r.error || 'unknown'), 'error', 4000);
    }
  } catch (e) {
    showToast('Remap error: ' + e.message, 'error', 4000);
  }
  disarmSource();
}

function setupClickAcross() {
  // Click delegation on the source SVG host — manual arm via mouse
  if (srcHost) {
    srcHost.addEventListener('click', (e) => {
      if (!_clickAcrossEnabled) return;
      const g = e.target.closest('[id^="src-btn-"]');
      if (!g) return;
      const id = g.id.replace(/^src-btn-/, '');
      armSource(id);
    });
  }
  // Click delegation on the target SVG host — bind when armed
  if (tgtHost) {
    tgtHost.addEventListener('click', (e) => {
      if (!_clickAcrossEnabled) return;
      if (!_armedSourceBtn) {
        showToast('Press or click a source button to arm a binding first.', 'info', 2400);
        return;
      }
      const g = e.target.closest('[id^="tgt-btn-"]');
      if (!g) return;
      bindArmedToTarget(g);
    });
  }
  // Escape disarms; outside-click disarms
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && _armedSourceBtn) {
      e.preventDefault();
      disarmSource();
      showToast('Binding cancelled.', 'info', 1500);
    }
  });
  document.addEventListener('mousedown', (e) => {
    if (!_armedSourceBtn) return;
    const inSource = srcHost && srcHost.contains(e.target);
    const inTarget = tgtHost && tgtHost.contains(e.target);
    if (!inSource && !inTarget) disarmSource();
  }, true);
}

async function refreshClickAcrossForSystem(systemId, rom) {
  _clickAcrossEnabled = isClickAcrossEnabledForSystem(systemId);
  // Mark the target host so CSS can dim/customize visuals if click-across
  // is off (e.g. fade out hover states).
  if (tgtHost) {
    tgtHost.classList.toggle('click-across-on',  _clickAcrossEnabled);
    tgtHost.classList.toggle('click-across-off', !_clickAcrossEnabled);
  }
  // Clear any "has-binding" badges; we'll re-fetch and re-apply
  if (tgtHost) {
    tgtHost.querySelectorAll('.has-binding').forEach(el => el.classList.remove('has-binding'));
  }
  if (!_clickAcrossEnabled || !rom) {
    disarmSource();
    return;
  }
  // Fetch current remap and badge target buttons that have bindings
  try {
    const data = await api('GET',
      `/api/remap?system=${encodeURIComponent(systemId)}&rom=${encodeURIComponent(rom)}`);
    const bindings = (data && data.bindings) || {};
    if (!Object.keys(bindings).length) return;
    // For each source bound, find the target with that retropad index and
    // mark it. Multiple sources can map to the same target — that's fine.
    const usedIndices = new Set(Object.values(bindings));
    tgtHost.querySelectorAll('[data-retropad]').forEach(el => {
      const idx = parseInt(el.getAttribute('data-retropad'), 10);
      if (usedIndices.has(idx)) el.classList.add('has-binding');
    });
  } catch (_) { /* missing .rmp is fine — nothing to badge */ }
}


// ============================================================
// Press-to-bind (Task 3 — Mapping UX Level 2)
// Click the listen icon on any map-row → row enters listening state →
// next keydown is captured, converted to RETROK_*, written into the
// row's input. Escape cancels. Click outside cancels.
// ============================================================

let _listeningRow = null;
let _listeningKeyHandler = null;
let _listeningOutsideHandler = null;

// event.code → RETROK_* mapping. Uses event.code (physical key) so layout
// shifts (AZERTY etc.) don't garble the mnemonic. Fallback to event.key.
const CODE_TO_RETROK = (() => {
  const m = {};
  // Letters
  for (let c = 65; c <= 90; c++) {
    const ch = String.fromCharCode(c);
    m['Key' + ch] = 'RETROK_' + ch.toLowerCase();
  }
  // Number row
  for (let n = 0; n <= 9; n++) {
    m['Digit' + n] = 'RETROK_' + n;
  }
  // Numpad digits
  for (let n = 0; n <= 9; n++) {
    m['Numpad' + n] = 'RETROK_KP' + n;
  }
  // F-keys
  for (let n = 1; n <= 15; n++) {
    m['F' + n] = 'RETROK_F' + n;
  }
  // Specials
  Object.assign(m, {
    'Space':        'RETROK_SPACE',
    'Enter':        'RETROK_RETURN',
    'NumpadEnter':  'RETROK_KP_ENTER',
    'Tab':          'RETROK_TAB',
    'Backspace':    'RETROK_BACKSPACE',
    'Delete':       'RETROK_DELETE',
    'Insert':       'RETROK_INSERT',
    'Home':         'RETROK_HOME',
    'End':          'RETROK_END',
    'PageUp':       'RETROK_PAGEUP',
    'PageDown':     'RETROK_PAGEDOWN',
    'ArrowUp':      'RETROK_UP',
    'ArrowDown':    'RETROK_DOWN',
    'ArrowLeft':    'RETROK_LEFT',
    'ArrowRight':   'RETROK_RIGHT',
    'ShiftLeft':    'RETROK_LSHIFT',
    'ShiftRight':   'RETROK_RSHIFT',
    'ControlLeft':  'RETROK_LCTRL',
    'ControlRight': 'RETROK_RCTRL',
    'AltLeft':      'RETROK_LALT',
    'AltRight':     'RETROK_RALT',
    'MetaLeft':     'RETROK_LMETA',
    'MetaRight':    'RETROK_RMETA',
    'CapsLock':     'RETROK_CAPSLOCK',
    'NumLock':      'RETROK_NUMLOCK',
    'ScrollLock':   'RETROK_SCROLLOCK',
    'Pause':        'RETROK_PAUSE',
    'PrintScreen':  'RETROK_PRINT',
    // Punctuation (US layout — fallback uses event.key for non-US)
    'Minus':        'RETROK_MINUS',
    'Equal':        'RETROK_EQUALS',
    'BracketLeft':  'RETROK_LEFTBRACKET',
    'BracketRight': 'RETROK_RIGHTBRACKET',
    'Backslash':    'RETROK_BACKSLASH',
    'Semicolon':    'RETROK_SEMICOLON',
    'Quote':        'RETROK_QUOTE',
    'Backquote':    'RETROK_BACKQUOTE',
    'Comma':        'RETROK_COMMA',
    'Period':       'RETROK_PERIOD',
    'Slash':        'RETROK_SLASH',
    'NumpadAdd':       'RETROK_KP_PLUS',
    'NumpadSubtract':  'RETROK_KP_MINUS',
    'NumpadMultiply':  'RETROK_KP_MULTIPLY',
    'NumpadDivide':    'RETROK_KP_DIVIDE',
    'NumpadDecimal':   'RETROK_KP_PERIOD',
  });
  return m;
})();

function keyEventToRetrok(e) {
  if (CODE_TO_RETROK[e.code]) return CODE_TO_RETROK[e.code];
  // Fallback: try a sensible guess from event.key
  const k = e.key;
  if (k && k.length === 1) {
    if (/[a-zA-Z]/.test(k)) return 'RETROK_' + k.toLowerCase();
    if (/[0-9]/.test(k))    return 'RETROK_' + k;
  }
  return null;
}

function stopListening(commit) {
  if (!_listeningRow) return;
  _listeningRow.classList.remove('listening');
  const lbl = _listeningRow.querySelector('.listen-label');
  if (lbl) lbl.textContent = 'listen';
  if (_listeningKeyHandler) {
    document.removeEventListener('keydown', _listeningKeyHandler, true);
    _listeningKeyHandler = null;
  }
  if (_listeningOutsideHandler) {
    document.removeEventListener('mousedown', _listeningOutsideHandler, true);
    _listeningOutsideHandler = null;
  }
  _listeningRow = null;
}

function startListening(row) {
  if (_listeningRow === row) { stopListening(false); return; }
  if (_listeningRow) stopListening(false);
  _listeningRow = row;
  row.classList.add('listening');
  const lbl = row.querySelector('.listen-label');
  if (lbl) lbl.textContent = 'press a key…';

  _listeningKeyHandler = (e) => {
    if (e.key === 'Escape') {
      e.preventDefault(); e.stopPropagation();
      stopListening(false);
      showToast('Binding cancelled.', 'info', 1500);
      return;
    }
    // Don't let the key reach the input (we'll write the value ourselves)
    e.preventDefault();
    e.stopPropagation();
    const retrok = keyEventToRetrok(e);
    if (!retrok) {
      showToast(`Unrecognised key (event.code "${e.code}"). Try another.`, 'error', 2400);
      return;  // keep listening
    }
    const inp = row.querySelector('input[data-map-btn]');
    if (inp) {
      inp.value = retrok;
      inp.dispatchEvent(new Event('input', { bubbles: true }));
      inp.dispatchEvent(new Event('change', { bubbles: true }));
    }
    stopListening(true);
    const padBtn = row.dataset.padBtn || '';
    showToast(`Bound ${padBtn.toUpperCase()} → ${retrok}`, 'success', 2200);
  };
  _listeningOutsideHandler = (e) => {
    if (!row.contains(e.target)) stopListening(false);
  };

  // Defer attaching the outside handler so the click that started us
  // doesn't immediately stop us
  setTimeout(() => {
    document.addEventListener('keydown', _listeningKeyHandler, true);
    document.addEventListener('mousedown', _listeningOutsideHandler, true);
  }, 0);
}

// Event delegation — buildMappingRows() rebuilds rows; using delegation
// avoids re-binding click handlers each time.
mapGrid.addEventListener('click', (e) => {
  const btn = e.target.closest('.listen-btn');
  if (!btn) return;
  const row = btn.closest('.map-row');
  if (!row) return;
  e.stopPropagation();
  startListening(row);
});


// ============================================================
// Profile templates (Task 2 — "Start from template" affordance)
// ============================================================

let _availableTemplates = [];
let _templatePopover = null;

async function refreshTemplateButton(systemId) {
  const btn = document.getElementById('btn-from-template');
  if (!btn) return;
  _availableTemplates = [];
  try {
    const data = await api('GET', `/api/templates?system=${encodeURIComponent(systemId)}`);
    _availableTemplates = data.templates || [];
  } catch (e) {
    console.warn('templates fetch failed:', e);
  }
  btn.hidden = _availableTemplates.length === 0;
}

function dismissTemplatePopover() {
  if (_templatePopover) {
    _templatePopover.remove();
    _templatePopover = null;
    document.removeEventListener('mousedown', onTemplateOutsideClick, true);
    document.removeEventListener('keydown', onTemplateKey, true);
  }
}

function onTemplateOutsideClick(e) {
  if (!_templatePopover) return;
  if (!_templatePopover.contains(e.target) &&
      !document.getElementById('btn-from-template').contains(e.target)) {
    dismissTemplatePopover();
  }
}
function onTemplateKey(e) {
  if (e.key === 'Escape') dismissTemplatePopover();
}

function showTemplatePopover() {
  dismissTemplatePopover();
  if (!_availableTemplates.length) return;
  const btn = document.getElementById('btn-from-template');
  if (!btn) return;

  const pop = document.createElement('div');
  pop.id = 'rbcf-tpl-popover';
  pop.className = 'rbcf-tpl-popover';
  pop.setAttribute('role', 'dialog');
  pop.setAttribute('aria-label', 'Start from template');

  const items = _availableTemplates.map(t => `
    <button type="button" class="rbcf-tpl-item" data-tpl-id="${escapeHtml(t.id)}">
      <span class="rbcf-tpl-name">${escapeHtml(t.name)}</span>
      ${t.description ? `<span class="rbcf-tpl-desc">${escapeHtml(t.description)}</span>` : ''}
    </button>
  `).join('');

  pop.innerHTML = `
    <div class="rbcf-tpl-head">
      <h3 class="rbcf-tpl-title">Start from template</h3>
      <button type="button" class="rbcf-tpl-close" data-act="close" aria-label="Close">×</button>
    </div>
    <p class="rbcf-tpl-hint">
      Pick a template to populate the form. You can still customise
      every field before saving. Existing values will be replaced.
    </p>
    <div class="rbcf-tpl-list">${items}</div>
  `;
  document.body.appendChild(pop);
  _templatePopover = pop;

  // Position under the button, right-aligned
  const r = btn.getBoundingClientRect();
  const popW = 360;
  let left = r.right - popW;
  if (left < 8) left = 8;
  pop.style.position = 'fixed';
  pop.style.top = (r.bottom + 6) + 'px';
  pop.style.left = left + 'px';
  pop.style.width = popW + 'px';

  pop.querySelector('[data-act="close"]').addEventListener('click', dismissTemplatePopover);
  pop.querySelectorAll('.rbcf-tpl-item').forEach(item => {
    item.addEventListener('click', async () => {
      const id = item.dataset.tplId;
      await applyTemplate(selSystem.value, id);
      dismissTemplatePopover();
    });
  });

  // Close on outside click / Escape
  setTimeout(() => {
    document.addEventListener('mousedown', onTemplateOutsideClick, true);
    document.addEventListener('keydown', onTemplateKey, true);
  }, 0);
}

async function applyTemplate(systemId, templateId) {
  try {
    const data = await api('GET',
      `/api/template?system=${encodeURIComponent(systemId)}&id=${encodeURIComponent(templateId)}`);
    const tpl = data.template || {};
    if (tpl._error) {
      showToast('Template error: ' + tpl._error, 'error');
      return;
    }
    // Reuse the form populator — it accepts the same shape
    populateForm(tpl);
    const tplName = tpl.template || templateId;
    showToast(`Loaded: ${tplName}`, 'success', 2200);
  } catch (e) {
    showToast('Failed to load template: ' + e.message, 'error');
  }
}

// (escapeHtml is already defined elsewhere in this file — reusing it)

// Hook the button click — the button itself is in the markup, hidden
// until refreshTemplateButton() finds templates for the selected system.
document.addEventListener('DOMContentLoaded', () => {
  const btn = document.getElementById('btn-from-template');
  if (btn) {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (_templatePopover) dismissTemplatePopover();
      else showTemplatePopover();
    });
  }
});


selSystem.addEventListener('change', async () => {
  const id = selSystem.value;
  setTargetForSystem(id);
  buildGameOptions(id);
  await loadGames(id);
  selGame.value = '';
  clearForm();
  await refreshTemplateButton(id);
  await refreshClickAcrossForSystem(id, '');
});

selGame.addEventListener('change', async () => {
  await loadProfile(selSystem.value, selGame.value);
  await refreshClickAcrossForSystem(selSystem.value, selGame.value);
});

// Flow 4 — silently downgrade V/K profiles to T when the user edits any
// mapped value or per-game option. Listener uses event delegation so we
// don't have to re-bind after buildMappingRows() / buildGameOptions().
document.addEventListener('input', (e) => {
  const t = e.target;
  if (!t) return;
  if (t.matches('input[data-map-btn]') || t.matches('[data-opt-key]') || t === notesEl) {
    markGameDetailDirty();
    // Recompute badges live so the user sees their edit shift a row from
    // 'inherited' to 'override' (and vice versa when cleared).
    if (GAME_DETAIL.system) applyInheritanceOverlay();
    // v0.1.5 13e: toggle .has-value on the map-row for green-tint + RETROK_
    // prefix visual, and refresh icon-bar count badges.
    if (t.matches('input[data-map-btn]')) {
      const row = t.closest('.map-row');
      if (row) {
        const v = (t.value || '').trim();
        row.classList.toggle('has-value', !!v && v !== '---');
      }
    }
    if (typeof updateIconBadges === 'function') updateIconBadges();
  }
});
document.addEventListener('change', (e) => {
  const t = e.target;
  if (!t) return;
  if (t.matches('[data-opt-key]')) {
    markGameDetailDirty();
    if (GAME_DETAIL.system) applyInheritanceOverlay();
    if (typeof updateIconBadges === 'function') updateIconBadges();
  }
});

$('btn-save').addEventListener('click', onSave);
$('btn-apply').addEventListener('click', onApply);

// Task 4 — Launch-test button: spawn RetroBat with the selected ROM
// for live mapping verification.
async function onLaunchTest() {
  const sysId = selSystem.value;
  const rom = selGame.value;
  if (!sysId) { showToast('Pick a system first.', 'error'); return; }
  if (!rom)   { showToast('Pick a game first — Test launches the selected ROM.', 'error'); return; }
  const btn = $('btn-launch-test');
  if (btn) btn.disabled = true;
  try {
    const r = await api('POST', '/api/launch-test', { system: sysId, rom });
    if (r.ok) {
      showToast(`Launching ${rom} in RetroBat (pid ${r.pid})…`, 'success', 3000);
    } else {
      showToast('Launch failed: ' + (r.error || 'unknown'), 'error', 4000);
    }
  } catch (e) {
    showToast('Launch error: ' + e.message, 'error', 4000);
  } finally {
    if (btn) setTimeout(() => { btn.disabled = false; }, 1500);
  }
}
const btnLaunchTest = $('btn-launch-test');
if (btnLaunchTest) btnLaunchTest.addEventListener('click', onLaunchTest);

// Pad-list pill clicks are wired per-pill inside renderPadList(); the
// standalone Rescan icon button is wired there too. Nothing to wire here.

window.addEventListener('gamepadconnected', e => {
  console.log('connected:', e.gamepad.id);
  showToast(`Gamepad connected: ${e.gamepad.id}`, 'success', 2500);
  loadDevices();  // refresh probe when a new pad attaches
});
window.addEventListener('gamepaddisconnected', e => {
  console.log('disconnected:', e.gamepad.id);
  showToast(`Gamepad disconnected: ${e.gamepad.id}`, 'error', 2500);
  loadDevices();
});

// ============================================================
// Device popover (anchored to the .pad-pill in the page header).
// Replaces the old standalone .device-bar section. Mirrors the
// settings-cog popover's a11y (outside-click + Escape dismiss,
// previous-focus restoration, focus management).
// ============================================================

let _rbcfDevicePopOutsideHandler = null;
let _rbcfDevicePopKeyHandler = null;
let _rbcfDevicePopPrevFocus = null;

// Track the anchor element so we can re-position the popover after a
// re-render swaps DOM nodes (setActivePad() rebuilds the pad-list).
let _rbcfDevicePopAnchor = null;

function dismissDevicePopover(opts) {
  const pop = $('rbcf-device-popover');
  if (pop) pop.remove();
  // Clear aria-expanded on every pill (only one was true at a time).
  if (padList) {
    padList.querySelectorAll('.pad-pill').forEach(p =>
      p.setAttribute('aria-expanded', 'false'));
  }
  if (_rbcfDevicePopOutsideHandler) {
    document.removeEventListener('mousedown', _rbcfDevicePopOutsideHandler, true);
    _rbcfDevicePopOutsideHandler = null;
  }
  if (_rbcfDevicePopKeyHandler) {
    document.removeEventListener('keydown', _rbcfDevicePopKeyHandler, true);
    _rbcfDevicePopKeyHandler = null;
  }
  _rbcfDevicePopAnchor = null;
  // Only restore focus when explicitly requested (Escape key, close button).
  if (opts && opts.restoreFocus
      && _rbcfDevicePopPrevFocus
      && document.contains(_rbcfDevicePopPrevFocus)) {
    try { _rbcfDevicePopPrevFocus.focus(); } catch (e) { /* ignore */ }
  }
  _rbcfDevicePopPrevFocus = null;
}

function _rbcfDevicePopFocusables(root) {
  return Array.from(root.querySelectorAll(
    'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
  )).filter(el => !el.disabled && el.offsetParent !== null);
}

// Position an open popover under its anchor pill (or center-ish if anchor
// is gone). Called on first show and after window resize / re-renders.
function _positionDevicePopover(pop, anchor) {
  const popW = 360;
  pop.style.position = 'fixed';
  pop.style.width = popW + 'px';
  if (anchor && document.contains(anchor)) {
    const r = anchor.getBoundingClientRect();
    let left = r.left;
    if (left + popW > window.innerWidth - 8) left = window.innerWidth - popW - 8;
    if (left < 8) left = 8;
    pop.style.top = (r.bottom + 6) + 'px';
    pop.style.left = left + 'px';
  } else {
    // Fallback — anchor under the pad-list container.
    const r = padList ? padList.getBoundingClientRect() : { left: 8, bottom: 60 };
    pop.style.top = (r.bottom + 6) + 'px';
    pop.style.left = Math.max(8, r.left) + 'px';
  }
}

// Open a popover for the controller at `idx` in LAST_DEVICES, anchored
// under `anchorEl` (the pill that was clicked). Pass idx === -1 for the
// empty-state placeholder.
function showDevicePopover(idx, anchorEl) {
  dismissDevicePopover();
  _rbcfDevicePopPrevFocus = document.activeElement;
  _rbcfDevicePopAnchor = anchorEl || null;

  const pop = document.createElement('div');
  pop.id = 'rbcf-device-popover';
  pop.className = 'pad-pill-popover';
  pop.setAttribute('role', 'dialog');
  pop.setAttribute('aria-label', 'Controller details');
  pop.dataset.padIdx = String(idx);

  pop.innerHTML = `
    <div class="pad-pill-popover-head">
      <h3 class="pad-pill-popover-title" id="pad-pill-popover-title">—</h3>
      <span class="pad-pill-popover-sub" id="pad-pill-popover-sub">—</span>
      <button type="button" class="rbcf-apply-modal-x" aria-label="Close" data-act="close">×</button>
    </div>
    <div class="pad-pill-popover-body">
      <div id="pad-detail" class="pad-detail"></div>
    </div>
    <div class="pad-pill-popover-foot">
      <button id="btn-use-active" class="primary tiny-btn pad-detail-primary" type="button"
              hidden>Use as active source</button>
      <span class="rbcf-apply-spacer"></span>
      <button id="btn-rescan" class="secondary tiny-btn" type="button"
              title="Re-probe Windows for connected controllers">
        <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M3 12a9 9 0 0 1 15.5-6.3L21 8"/>
          <path d="M21 3v5h-5"/>
          <path d="M21 12a9 9 0 0 1-15.5 6.3L3 16"/>
          <path d="M3 21v-5h5"/>
        </svg>
        Rescan
      </button>
    </div>
  `;
  document.body.appendChild(pop);

  _positionDevicePopover(pop, anchorEl);

  if (anchorEl) anchorEl.setAttribute('aria-expanded', 'true');

  // Wire close + rescan + use-as-active.
  pop.querySelector('[data-act="close"]').addEventListener('click', () => {
    dismissDevicePopover({ restoreFocus: true });
  });
  pop.querySelector('#btn-rescan').addEventListener('click', (e) => {
    e.stopPropagation();
    loadDevices();
  });
  pop.querySelector('#btn-use-active').addEventListener('click', (e) => {
    e.stopPropagation();
    const targetIdx = parseInt(pop.dataset.padIdx ?? '-1', 10);
    if (targetIdx < 0) return;
    const dev = LAST_DEVICES[targetIdx];
    if (!dev) return;
    setActivePad(targetIdx);
    showToast(`Active source: ${deviceFriendlyName(dev)}`, 'info', 2000);
    // Re-anchor onto the freshly-rendered pill and refresh the body.
    const refreshed = padList && padList.querySelector(`.pad-pill[data-pad-index="${targetIdx}"]`);
    if (refreshed) {
      _rbcfDevicePopAnchor = refreshed;
      refreshed.setAttribute('aria-expanded', 'true');
      _positionDevicePopover(pop, refreshed);
    }
    paintDevicePopover();
  });

  // Render the body for this specific controller (or empty state).
  paintDevicePopover();
  // Background refresh the device list — useful for the empty state and to
  // pick up any newly-connected pad without leaving the popover.
  loadDevices();

  // Outside-click dismiss — but ignore clicks on any pill in the pad-list
  // (their own handlers manage open/close).
  _rbcfDevicePopOutsideHandler = (e) => {
    if (pop.contains(e.target)) return;
    if (padList && padList.contains(e.target)) return;
    dismissDevicePopover();
  };
  document.addEventListener('mousedown', _rbcfDevicePopOutsideHandler, true);

  // Escape closes; Tab traps focus inside the popover.
  _rbcfDevicePopKeyHandler = (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      const restoreTarget = _rbcfDevicePopAnchor;
      dismissDevicePopover({ restoreFocus: false });
      if (restoreTarget && document.contains(restoreTarget)) {
        try { restoreTarget.focus(); } catch (err) { /* ignore */ }
      }
      return;
    }
    if (e.key !== 'Tab') return;
    const items = _rbcfDevicePopFocusables(pop);
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault(); last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault(); first.focus();
    }
  };
  document.addEventListener('keydown', _rbcfDevicePopKeyHandler, true);

  // Auto-focus the primary action if visible, else Rescan.
  setTimeout(() => {
    const useBtn = pop.querySelector('#btn-use-active');
    const target = (useBtn && !useBtn.hidden) ? useBtn : pop.querySelector('#btn-rescan');
    if (target) { try { target.focus(); } catch (e) { /* ignore */ } }
  }, 0);
}

// Build a one-row entry for the detail table.
function _detailRow(label, value) {
  return `<div class="pad-detail-row"><span class="pad-detail-k">${rbcfEsc(label)}</span><span class="pad-detail-v">${value}</span></div>`;
}

// Render the body of the open popover for whichever controller it's tracking.
// No-op if popover is closed.
function paintDevicePopover() {
  const pop = $('rbcf-device-popover');
  if (!pop) return;
  const idx = parseInt(pop.dataset.padIdx ?? '-1', 10);
  const titleEl = pop.querySelector('#pad-pill-popover-title');
  const subEl   = pop.querySelector('#pad-pill-popover-sub');
  const body    = pop.querySelector('#pad-detail');
  const useBtn  = pop.querySelector('#btn-use-active');

  // Empty-state placeholder popover (no controllers connected).
  if (idx < 0 || !LAST_DEVICES.length) {
    if (titleEl) titleEl.textContent = 'No controllers detected';
    if (subEl) subEl.textContent = 'Connect a controller and click Rescan.';
    if (body) {
      body.innerHTML =
        '<div class="device-empty">Plug in or pair a controller, then press Rescan.</div>';
    }
    if (useBtn) useBtn.hidden = true;
    // Re-anchor to whichever pill the popover originally launched from (the
    // pad-list re-rendered when devices probed → anchor may be stale).
    if (_rbcfDevicePopAnchor && !document.contains(_rbcfDevicePopAnchor) && padList) {
      _rbcfDevicePopAnchor = padList.querySelector('.pad-pill') || null;
      _positionDevicePopover(pop, _rbcfDevicePopAnchor);
    }
    return;
  }

  // Specific-controller popover.
  const dev = LAST_DEVICES[idx];
  if (!dev) {
    // Index drifted out of bounds (device unplugged). Close the popover.
    dismissDevicePopover();
    return;
  }
  const friendly = deviceFriendlyName(dev);
  const isActive = (idx === activePadIndex);
  const live = isActive ? pickGamepad() : null;

  if (titleEl) titleEl.textContent = friendly;
  if (subEl) {
    const btnCount = live ? live.buttons.length : '—';
    const axCount  = live ? live.axes.length : '—';
    subEl.textContent = `${btnCount} buttons · ${axCount} axes · ${dev.vid}:${dev.pid}`;
  }
  if (useBtn) useBtn.hidden = isActive;

  if (body) {
    let html = '';
    // Optional thumb up top.
    if (dev.image) {
      html += `<div class="pad-detail-thumb"><img src="${rbcfEsc(dev.image)}" alt="${rbcfEsc(dev.name || '')}" referrerpolicy="no-referrer"></div>`;
    }
    html += '<div class="pad-detail-table">';
    html += _detailRow('Name', rbcfEsc(dev.name || dev.friendly_name || 'Unknown device'));
    if (dev.friendly_name && dev.friendly_name !== dev.name) {
      html += _detailRow('Friendly', rbcfEsc(dev.friendly_name));
    }
    html += _detailRow('VID', `<code>${rbcfEsc(dev.vid)}</code>`);
    html += _detailRow('PID', `<code>${rbcfEsc(dev.pid)}</code>`);
    html += _detailRow('XInput', dev.xinput ? 'Yes' : 'No');
    if (dev.instance_id) {
      const tail = dev.instance_id.length > 24
        ? '…' + dev.instance_id.slice(-24)
        : dev.instance_id;
      html += _detailRow('InstanceId',
        `<code title="${rbcfEsc(dev.instance_id)}">${rbcfEsc(tail)}</code>`);
    }
    html += '</div>';
    body.innerHTML = html;
  }
}

// Light helper called from the 60Hz polling loop so live button/axis counts
// stay fresh in an open popover (only matters for the active controller).
function refreshPopoverLiveCounts() {
  const pop = $('rbcf-device-popover');
  if (!pop) return;
  const idx = parseInt(pop.dataset.padIdx ?? '-1', 10);
  if (idx < 0 || idx !== activePadIndex) return;
  const subEl = pop.querySelector('#pad-pill-popover-sub');
  const dev = LAST_DEVICES[idx];
  if (!subEl || !dev) return;
  const live = pickGamepad();
  const btnCount = live ? live.buttons.length : '—';
  const axCount  = live ? live.axes.length : '—';
  subEl.textContent = `${btnCount} buttons · ${axCount} axes · ${dev.vid}:${dev.pid}`;
}

// ============================================================
// Device probe (Windows VID:PID via PowerShell). The pill text
// is driven from this; the popover (if open) is repainted from
// the cache.
// ============================================================

async function loadDevices() {
  try {
    const data = await api('GET', '/api/devices');
    const devs = data.devices || [];
    // Tag each device with its render index — useful for friendly-name lookup.
    devs.forEach((d, i) => { d.padIndex = i; });
    LAST_DEVICES = devs;
  } catch (e) {
    LAST_DEVICES = [];
    // Surface the error inside the popover if it's open.
    const body = document.querySelector('#rbcf-device-popover #pad-detail');
    if (body) {
      body.innerHTML = `<div class="device-empty">probe error: ${rbcfEsc(e.message)}</div>`;
    }
  }
  // Always refresh derived UI: the header pad-list + (if open) popover body.
  // After a probe, anchors in the pad-list are new DOM nodes — re-anchor any
  // open popover onto the freshly-rendered pill matching its tracked padIdx.
  renderPadList();
  const pop = $('rbcf-device-popover');
  if (pop && padList) {
    const idx = parseInt(pop.dataset.padIdx ?? '-1', 10);
    let anchor = null;
    if (idx >= 0) {
      anchor = padList.querySelector(`.pad-pill[data-pad-index="${idx}"]`);
    } else {
      // Empty-state popover — re-anchor onto the placeholder pill (or the
      // first pill if devices just appeared).
      anchor = padList.querySelector('.pad-pill');
    }
    if (anchor) {
      anchor.setAttribute('aria-expanded', 'true');
      _rbcfDevicePopAnchor = anchor;
      _positionDevicePopover(pop, anchor);
    }
  }
  paintDevicePopover();
}

// ============================================================
// Collapsible sections
// ============================================================
// Click an .collapsible <h2> to toggle the .collapsed class on its
// parent <section>. State persists in localStorage as a JSON array
// of section IDs. All remaining accordions start open on first load.
// (v0.1.5 13b: #sec-notes was lifted out into a header popover; the
//  default-closed list is empty until another section needs it.)

const COLLAPSE_STORAGE_KEY = 'rbcf-collapsed';
const COLLAPSE_DEFAULT_CLOSED = [];

function readCollapsedState() {
  try {
    const raw = localStorage.getItem(COLLAPSE_STORAGE_KEY);
    if (raw === null) return null;  // distinguish "never set" from "set to []"
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr : null;
  } catch (e) {
    return null;
  }
}

function writeCollapsedState() {
  const ids = $$('section.collapsible.collapsed').map(s => s.id).filter(Boolean);
  try {
    localStorage.setItem(COLLAPSE_STORAGE_KEY, JSON.stringify(ids));
  } catch (e) { /* ignore quota / disabled storage */ }
}

function setSectionCollapsed(section, collapsed) {
  section.classList.toggle('collapsed', collapsed);
  const chev = section.querySelector(':scope > h2 .chev');
  if (chev) chev.textContent = collapsed ? '▸' : '▾';
}

// ============================================================
// User-tunable accent (cross-theme)
// Persists via localStorage 'rbcf-user-accent'; overrides --acc
// (and a derived --acc-2) on document.documentElement at runtime.
// Reset clears the override and falls back to whatever the active
// theme defines.
// ============================================================

const USER_ACCENT_KEY = 'rbcf-user-accent';

function applyUserAccent(value) {
  const root = document.documentElement;
  if (value) {
    root.style.setProperty('--acc', value);
    // Derive a brighter --acc-2 by blending toward white in HSL space
    root.style.setProperty('--acc-2', deriveLighter(value, 0.18));
    // Update the gradient + the picker swatch
    root.style.setProperty('--acc-bg',      hexToRgba(value, 0.18));
    root.style.setProperty('--acc-bg-soft', hexToRgba(value, 0.10));
  } else {
    // Clear all overrides — fall back to theme-defined values
    for (const k of ['--acc', '--acc-2', '--acc-bg', '--acc-bg-soft']) {
      root.style.removeProperty(k);
    }
  }
}

function hexToRgba(hex, alpha) {
  const m = hex.match(/^#?([0-9a-fA-F]{6})$/);
  if (!m) return hex;
  const v = parseInt(m[1], 16);
  return `rgba(${(v>>16)&255}, ${(v>>8)&255}, ${v&255}, ${alpha})`;
}

function deriveLighter(hex, mix) {
  // Blend `hex` toward white by `mix` (0..1)
  const m = hex.match(/^#?([0-9a-fA-F]{6})$/);
  if (!m) return hex;
  const v = parseInt(m[1], 16);
  const r = (v>>16)&255, g = (v>>8)&255, b = v&255;
  const lr = Math.round(r + (255 - r) * mix);
  const lg = Math.round(g + (255 - g) * mix);
  const lb = Math.round(b + (255 - b) * mix);
  return '#' + ((1<<24) | (lr<<16) | (lg<<8) | lb).toString(16).slice(1);
}

// The picker + reset live INSIDE the existing settings popover render —
// see showSettingsPopover() above. They're wired there, not via a
// separate setup function, because the popover is dynamically rendered
// each time it opens.

// ============================================================
// User settings backup (v0.1.4 — export / import localStorage)
// ============================================================
//
// All in-app preferences live in localStorage under keys prefixed
// `rbcf-`. Plus a couple of `data-theme` HTML attributes (theme +
// any future similar). This pair of helpers serialises the lot to
// a JSON blob the user can save off-machine, and restores from one.
//
// The .rmp / profile / catalog state on the RetroBat side is NOT
// included here — that's covered by the `rbcf backup` snapshot
// system, which is a separate (much heavier) thing. This is just
// the GUI-side preferences. Lightweight, fast, single click.

const SETTINGS_BACKUP_VERSION = 1;
const SETTINGS_BACKUP_PREFIX  = 'rbcf-';

function collectUserSettings() {
  const out = {};
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (k && k.startsWith(SETTINGS_BACKUP_PREFIX)) {
      out[k] = localStorage.getItem(k);
    }
  }
  return out;
}

function exportUserSettings() {
  try {
    const payload = {
      schema:    SETTINGS_BACKUP_VERSION,
      app:       'RetroControlMapper',
      app_version: (typeof rbcfUpdateLocalVersion === 'function')
                     ? rbcfUpdateLocalVersion() : 'unknown',
      exported:  new Date().toISOString(),
      data_theme: document.documentElement.getAttribute('data-theme') || null,
      localStorage: collectUserSettings(),
    };
    const stamp = payload.exported.replace(/[:T]/g, '-').slice(0, 16);
    const fname = `rbcf-settings-${stamp}.json`;
    const blob = new Blob([JSON.stringify(payload, null, 2)],
                          { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = fname;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }, 0);
    const count = Object.keys(payload.localStorage).length;
    showToast(`Exported ${count} setting(s) → ${fname}`, 'success', 2400);
  } catch (e) {
    showToast('Export failed: ' + e.message, 'error', 4000);
  }
}

function importUserSettings(file) {
  const reader = new FileReader();
  reader.onload = (e) => {
    try {
      const payload = JSON.parse(e.target.result);
      if (!payload || typeof payload !== 'object') {
        throw new Error('not a JSON object');
      }
      // Accept either the legacy 'RB-Controller_fix' (pre-v0.1.5.2) or
      // the new 'RetroControlMapper' app ID — backwards-compat for users
      // restoring older settings backups.
      const validApp = (payload.app === 'RetroControlMapper'
                     || payload.app === 'RB-Controller_fix');
      if (!validApp) {
        if (!confirm(
          'This file does not look like a RetroControlMapper settings backup '
          + `(app field = ${JSON.stringify(payload.app)}). Import anyway?`)) {
          return;
        }
      }
      if (payload.schema !== SETTINGS_BACKUP_VERSION) {
        if (!confirm(
          `Schema version mismatch (file=${payload.schema}, expected `
          + `${SETTINGS_BACKUP_VERSION}). The file may be from a newer or `
          + `older release. Import anyway?`)) {
          return;
        }
      }
      const settings = payload.localStorage || {};
      const keys = Object.keys(settings).filter(k => k.startsWith(SETTINGS_BACKUP_PREFIX));
      if (!keys.length) {
        showToast('No rbcf-* settings found in that file.', 'error', 3200);
        return;
      }
      if (!confirm(
        `Import ${keys.length} setting(s) from this backup? Your current `
        + `in-app preferences will be replaced.`)) {
        return;
      }
      // Apply
      for (const k of keys) {
        localStorage.setItem(k, settings[k]);
      }
      // data-theme attribute (theme switcher applies it before first paint
      // normally — set it now so the change is visible immediately)
      if (payload.data_theme) {
        document.documentElement.setAttribute('data-theme', payload.data_theme);
      }
      // Re-apply accent live (since the picker isn't re-rendered until popover reopen)
      try {
        const accVal = localStorage.getItem('rbcf-user-accent');
        if (accVal && typeof applyUserAccent === 'function') applyUserAccent(accVal);
        else if (typeof applyUserAccent === 'function') applyUserAccent(null);
      } catch (_) {}
      showToast(
        `Imported ${keys.length} setting(s). Reload the page to apply all changes.`,
        'success', 4000);
    } catch (err) {
      showToast('Import failed: ' + err.message, 'error', 4500);
    }
  };
  reader.onerror = () => {
    showToast('Could not read the file.', 'error', 3200);
  };
  reader.readAsText(file);
}

// Apply persisted accent BEFORE first paint — same pattern as the
// theme switcher does for `[data-theme]`. Avoids a flash of wrong colour.
(function preApplyAccent() {
  try {
    const v = localStorage.getItem(USER_ACCENT_KEY);
    if (v) applyUserAccent(v);
  } catch (_) {}
})();


function setupCollapsibles() {
  const sections = $$('section.collapsible');
  const stored = readCollapsedState();
  const initial = stored !== null ? stored : COLLAPSE_DEFAULT_CLOSED;
  for (const sec of sections) {
    setSectionCollapsed(sec, initial.includes(sec.id));
    const h2 = sec.querySelector(':scope > h2');
    if (!h2) continue;
    h2.addEventListener('click', () => {
      setSectionCollapsed(sec, !sec.classList.contains('collapsed'));
      writeCollapsedState();
    });
  }
}

// ============================================================
// Init
// ============================================================

(async function init() {
  setSourceSVG();
  await loadSystems();
  buildMappingRows();
  if (SYSTEMS.length) {
    selSystem.value = SYSTEMS[0].id;
    setTargetForSystem(SYSTEMS[0].id);
    buildGameOptions(SYSTEMS[0].id);
    await loadGames(SYSTEMS[0].id);
  }
  setupCollapsibles();
  // v0.1.5 13e: icon-bar injection. Each function inserts itself at the
  // correct workflow position via anchor-relative insertion, so call
  // order doesn't matter for final DOM order: Mappings → Overrides →
  // Notes → Settings (left-to-right).
  injectSettingsCog();
  injectNotesIcon();
  injectOverridesIcon();
  injectMappingsIcon();
  injectSuggestionsIcon();      // v0.1.5 Task 1 — first icon in workflow order
  wireTargetOverridesButton();   // legacy no-op kept for back-compat
  // v0.1.5 13e: pin state + pinned-card wiring. Must run AFTER the
  // injections (so the icons exist to receive [data-pinned] markers)
  // and AFTER buildMappingRows + buildGameOptions (so content exists
  // to be routed). The function checks for popover-open state and
  // leaves transient content alone.
  applyPinnedStates();
  wirePinnedUnpinButtons();
  updateIconBadges();
  setupClickAcross();
  // Initial templates pass for the default system (after loadSystems set it)
  if (selSystem.value) {
    await refreshTemplateButton(selSystem.value);
    await refreshClickAcrossForSystem(selSystem.value, selGame.value || '');
  }
  // Render the placeholder pad-list before the probe lands.
  renderPadList();
  loadDevices();  // fire & forget — drives the pad-list + popover body
  rbcfUpdateInit();  // fire & forget — reads cache, optionally refreshes
  loop();
})();
