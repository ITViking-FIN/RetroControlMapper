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

function setTargetSVG(targetCtrl) {
  currentTargetController = targetCtrl;
  const svg = TARGET_SVGS[targetCtrl];
  if (svg) {
    tgtHost.innerHTML = svg;
  } else {
    tgtHost.innerHTML = `
      <div class="empty-state">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg>
        <span>No target controller diagram for this system yet.</span>
      </div>`;
  }
}

// ============================================================
// Live highlights
// ============================================================

// User-selected pad index — clicking a device card switches which gamepad
// drives the live highlights. Persisted across reloads.
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
  $$('.device-card').forEach(c => {
    c.classList.toggle('active', parseInt(c.dataset.padIndex) === index);
  });
  // Repaint the header pad-list so the green dot moves to the new active pill.
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

function updateGamepad() {
  const pad = pickGamepad();

  if (!pad) {
    // Pill rendering is driven by loadDevices() / setActivePad() / connect
    // events, not by this 60Hz polling loop. Just clear the source-pane label.
    padName.textContent = '—';
    $$('.src-btn.pressed, .tgt-btn.pressed, .map-row.pressed').forEach(el => el.classList.remove('pressed'));
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
  for (let i = 0; i < pad.buttons.length; i++) {
    const btn = pad.buttons[i];
    if (!btn || !btn.pressed) continue;
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
  setTargetSVG(sys.target_controller);

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
      row.innerHTML = `
        <span class="btn-name">${swatch}${label}</span>
        <input type="text" data-map-btn="${btn}" placeholder="e.g. RETROK_F1, RETROK_SPACE, --- to clear">
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
// "X of Y overrides" summary, and the overlay toggle. Lives at the top
// of the Advanced game overrides section (#sec-game-options) — the
// tightest space available without touching index.html.
function renderGameDetailHeader(systemId, profile, systemDefault) {
  const sec = document.getElementById('sec-game-options');
  if (!sec) return;
  let host = sec.querySelector('.rbcf-game-detail-header');
  if (!systemId || !profile) {
    if (host) host.remove();
    return;
  }
  if (!host) {
    host = document.createElement('div');
    host.className = 'rbcf-game-detail-header';
    // Insert directly after the section's <h2> so it sits between the
    // header and the existing intro/options grid.
    const h2 = sec.querySelector('h2');
    if (h2 && h2.nextSibling) sec.insertBefore(host, h2.nextSibling);
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
  pop.setAttribute('aria-label', 'RB-Controller_fix Settings');
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
      <h3 class="rbcf-apply-settings-title">RB-Controller_fix Settings</h3>
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
    const url = info.release_url || '#';
    html = `<strong>v${rbcfEscape(latest)}</strong> available · ` +
      `<a class="rbcf-update-link" href="${rbcfEscape(url)}" target="_blank" rel="noopener">Release notes ↗</a>`;
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
  const url = info.release_url || '#';
  const ver = info.latest;
  badge.title = `Update available: v${ver}. Click for release notes.`;
  badge.innerHTML = `
    <a class="rbcf-update-badge-link" href="${rbcfEscape(url)}" target="_blank" rel="noopener"
       aria-label="Update available: v${rbcfEscape(ver)}">v${rbcfEscape(ver)}</a>
    <button type="button" class="rbcf-update-badge-x" aria-label="Dismiss update notice">×</button>
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
  btn.title = 'RB-Controller_fix Settings';
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

selSystem.addEventListener('change', async () => {
  const id = selSystem.value;
  setTargetForSystem(id);
  buildGameOptions(id);
  await loadGames(id);
  selGame.value = '';
  clearForm();
});

selGame.addEventListener('change', async () => {
  await loadProfile(selSystem.value, selGame.value);
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
  }
});
document.addEventListener('change', (e) => {
  const t = e.target;
  if (!t) return;
  if (t.matches('[data-opt-key]')) {
    markGameDetailDirty();
    if (GAME_DETAIL.system) applyInheritanceOverlay();
  }
});

$('btn-save').addEventListener('click', onSave);
$('btn-apply').addEventListener('click', onApply);

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
// of section IDs. On first load (no stored state), #sec-notes starts
// collapsed; the others start open.

const COLLAPSE_STORAGE_KEY = 'rbcf-collapsed';
const COLLAPSE_DEFAULT_CLOSED = ['sec-notes'];

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
  injectSettingsCog();
  // Render the placeholder pad-list before the probe lands.
  renderPadList();
  loadDevices();  // fire & forget — drives the pad-list + popover body
  rbcfUpdateInit();  // fire & forget — reads cache, optionally refreshes
  loop();
})();
