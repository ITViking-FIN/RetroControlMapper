// app.js — RB-Controller_fix step 2 with inline SVGs.
// Depends on controllers.js (loaded before this).

const $  = (id) => document.getElementById(id);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const padStatus = $('pad-status');
const padName   = $('pad-name');
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
  // Honour the user's selection if that index is currently connected
  const sel = pads[activePadIndex];
  if (sel && sel.connected) return sel;
  // Otherwise fall back to first connected, and remember its index
  for (let i = 0; i < pads.length; i++) {
    if (pads[i] && pads[i].connected) {
      activePadIndex = i;
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
}

function updateGamepad() {
  const pad = pickGamepad();

  if (!pad) {
    padStatus.textContent = 'No pad — press a button';
    padStatus.classList.remove('connected');
    padName.textContent = '—';
    $$('.src-btn.pressed, .tgt-btn.pressed, .map-row.pressed').forEach(el => el.classList.remove('pressed'));
    return;
  }
  padStatus.textContent = pad.id.length > 36 ? pad.id.slice(0, 36) + '…' : pad.id;
  padStatus.classList.add('connected');
  padName.textContent = `${pad.buttons.length} buttons · ${pad.axes.length} axes`;

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
    return;
  }
  const data = await api('GET',
    `/api/profile?system=${encodeURIComponent(systemId)}&rom=${encodeURIComponent(rom)}`);
  populateForm(data.profile || {});
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
    apply: true,
  };
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
  btn.disabled = true;
  setStatus('saving…');
  try {
    const r = await api('POST', '/api/save', profile);
    if (!r.ok) {
      setStatus('save failed');
      showToast('Save failed: ' + (r.error || 'unknown'), 'error');
      return;
    }
    let msg = `Saved ${profile.system}/${profile.rom}`;
    if (r.apply && r.apply.ok) msg += ' · applied';
    else if (r.apply) msg += ' · apply failed (' + (r.apply.error || 'rc ' + r.apply.returncode) + ')';
    setStatus('saved · ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
    showToast(msg, 'success');
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

$('btn-save').addEventListener('click', onSave);
$('btn-apply').addEventListener('click', onApply);
$('btn-rescan').addEventListener('click', (e) => {
  e.stopPropagation();  // don't toggle the device-bar collapse
  loadDevices();
});

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
// Device bar (collapsible — summarises detected controllers)
// ============================================================

const DEVICE_BAR_KEY = 'rbcf-device-bar-expanded';

function setDeviceBarExpanded(expanded) {
  const bar = $('device-bar');
  bar.classList.toggle('expanded', expanded);
  const head = $('device-bar-toggle');
  if (head) head.setAttribute('aria-expanded', String(expanded));
  try { localStorage.setItem(DEVICE_BAR_KEY, expanded ? '1' : '0'); } catch (e) { /* ignore */ }
}

function setupDeviceBar() {
  const head = $('device-bar-toggle');
  if (!head) return;
  // Default: collapsed unless user previously expanded it.
  let expanded = false;
  try { expanded = localStorage.getItem(DEVICE_BAR_KEY) === '1'; } catch (e) { /* ignore */ }
  setDeviceBarExpanded(expanded);
  head.addEventListener('click', () => {
    setDeviceBarExpanded(!$('device-bar').classList.contains('expanded'));
  });
  head.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      setDeviceBarExpanded(!$('device-bar').classList.contains('expanded'));
    }
  });
}

// ============================================================
// Device probe (Windows VID:PID via PowerShell, surfaced as cards)
// ============================================================

async function loadDevices() {
  const list = $('device-list');
  const summary = $('device-summary');
  if (summary) summary.innerHTML = '<span class="spinner"></span> probing…';
  list.innerHTML = '';
  try {
    const data = await api('GET', '/api/devices');
    const devs = data.devices || [];
    if (!devs.length) {
      if (summary) {
        summary.classList.remove('has-pad');
        summary.textContent = 'No HID gamepads detected.';
      }
      list.innerHTML = '<span class="muted small">Nothing connected via Windows HID.</span>';
      return;
    }
    // Summary (collapsed view)
    if (summary) {
      const xinputCount = devs.filter(d => d.xinput).length;
      const total = devs.length;
      const parts = [];
      parts.push(`${total} controller${total === 1 ? '' : 's'} detected`);
      if (xinputCount) parts.push(`${xinputCount} XInput`);
      summary.classList.toggle('has-pad', total > 0);
      summary.textContent = parts.join(' · ');
    }
    // Expanded view
    list.innerHTML = '';
    devs.forEach((d, idx) => {
      const card = document.createElement('div');
      card.className = 'device-card' + (d.xinput ? ' xinput' : '');
      card.dataset.padIndex = String(idx);
      card.dataset.key = d.key || `${d.vid}:${d.pid}`;
      if (idx === activePadIndex) card.classList.add('active');
      const thumb = document.createElement('div');
      thumb.className = 'thumb' + (d.image ? '' : ' no-img');
      if (d.image) {
        const img = document.createElement('img');
        img.src = d.image;
        img.alt = d.name || '';
        img.referrerPolicy = 'no-referrer';
        thumb.appendChild(img);
      } else {
        thumb.textContent = d.xinput ? 'XI' : 'HID';
      }
      const meta = document.createElement('div');
      meta.className = 'meta';
      meta.innerHTML = `
        <span class="name"></span>
        <span class="vid-pid"></span>
      `;
      meta.querySelector('.name').textContent = d.name || d.friendly_name || 'Unknown device';
      meta.querySelector('.vid-pid').textContent = `${d.vid}:${d.pid}${d.xinput ? ' · XInput' : ''}`;
      card.appendChild(thumb);
      card.appendChild(meta);
      card.title = `${d.instance_id || ''}\n\nClick to use this controller as the live source.`;
      // Click → make this card the active source
      card.addEventListener('click', (e) => {
        e.stopPropagation();
        setActivePad(idx);
        showToast(`Active source: ${d.name || d.friendly_name || `${d.vid}:${d.pid}`}`, 'info', 2000);
      });
      list.appendChild(card);
    });
  } catch (e) {
    if (summary) summary.textContent = `probe error: ${e.message}`;
    list.innerHTML = `<span class="muted small">probe error: ${e.message}</span>`;
  }
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
  setupDeviceBar();
  loadDevices();  // fire & forget, populates the device bar
  loop();
})();
