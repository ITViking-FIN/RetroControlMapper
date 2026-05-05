// app-onboarding.js — first-run welcome flow for RB-Controller_fix.
//
// Self-contained, vanilla JS. Loaded from index.html *before* app.js so
// the overlay is the first thing painted on top of the existing UI.
//
// Gating:
//   localStorage['rbcf-onboarded'] === '1'   → don't show
//   URL contains   ?reset-onboarding=1       → clear flag, force show
//
// Persistence:
//   localStorage['rbcf-onboarded']           — set to '1' on apply / skip
//   localStorage['rbcf-retrobat-override']   — manual root path the user
//                                              typed when /api/retrobat-root
//                                              returned found:false
//
// All CSS classes prefixed `rbcf-onb-` so we don't leak into the main GUI.
// All DOM IDs prefixed `rbcf-onb-`.
//
// Endpoint contract (shared with the backend stream):
//   GET  /api/retrobat-root              → { root, found, probed }
//   POST /api/retrobat-root              → { ok, root, found, message,
//                                            restart_required, path_to_rbcfrc,
//                                            error? }
//      body: {"root": "<path>"}  persists to .rbcfrc and validates marker
//      body: {"root": null}      clears .rbcfrc
//   GET  /api/scan                       → { systems, totals, bezels_with_cutoffs }
//   GET  /api/scaffold-all               → { preview, applied:false, count }
//   GET  /api/scaffold-all?apply=true    → { preview, applied:true, count, written }
//   GET  /api/bezel-cutoffs              → { cutoffs, applied:false, count }
//   GET  /api/bezel-cutoffs?apply=true   → { cutoffs, applied:true, count, written,
//                                            skipped_existing? }
//
// 404 from any endpoint → backend not yet available, show inline notice
// + still let the user "Skip onboarding for now".

(function () {
  'use strict';

  // ----------------------------------------------------------------
  // Gate
  // ----------------------------------------------------------------

  const ONB_KEY    = 'rbcf-onboarded';
  const ROOT_KEY   = 'rbcf-retrobat-override';
  const RESET_PARAM = 'reset-onboarding';

  function shouldShow() {
    const url = new URL(window.location.href);
    if (url.searchParams.get(RESET_PARAM) === '1') {
      try { localStorage.removeItem(ONB_KEY); } catch (e) { /* ignore */ }
      return true;
    }
    try {
      return localStorage.getItem(ONB_KEY) !== '1';
    } catch (e) {
      // localStorage disabled — show every time, gracefully.
      return true;
    }
  }

  function markOnboarded() {
    try { localStorage.setItem(ONB_KEY, '1'); } catch (e) { /* ignore */ }
  }

  // ----------------------------------------------------------------
  // Tiny helpers
  // ----------------------------------------------------------------

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const k in attrs) {
        if (k === 'class') node.className = attrs[k];
        else if (k === 'text') node.textContent = attrs[k];
        else if (k === 'html') node.innerHTML = attrs[k];
        else if (k.startsWith('on') && typeof attrs[k] === 'function') {
          node.addEventListener(k.slice(2).toLowerCase(), attrs[k]);
        } else {
          node.setAttribute(k, attrs[k]);
        }
      }
    }
    if (children) {
      for (const c of children) {
        if (c == null) continue;
        node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
      }
    }
    return node;
  }

  function escapeHtml(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  async function fetchJson(method, url) {
    let resp;
    try {
      resp = await fetch(url, { method, headers: { 'Accept': 'application/json' } });
    } catch (e) {
      const err = new Error('network: ' + e.message);
      err.kind = 'network';
      throw err;
    }
    if (resp.status === 404) {
      const err = new Error('Backend endpoint not yet available — try again after server restart.');
      err.kind = 'not-implemented';
      err.status = 404;
      throw err;
    }
    if (!resp.ok) {
      const err = new Error(`${method} ${url} → ${resp.status}`);
      err.kind = 'http';
      err.status = resp.status;
      throw err;
    }
    try {
      return await resp.json();
    } catch (e) {
      const err = new Error('Bad JSON from ' + url);
      err.kind = 'json';
      throw err;
    }
  }

  // Toast — reuse main app's #toast if available; otherwise inline notice.
  function lightToast(msg, kind) {
    if (typeof window.showToast === 'function') {
      try { window.showToast(msg, kind || 'info'); return; } catch (e) { /* fall through */ }
    }
    // Fallback: brief inline notice at the bottom of the overlay
    const live = document.getElementById('rbcf-onb-live');
    if (live) live.textContent = msg;
  }

  // ----------------------------------------------------------------
  // State
  // ----------------------------------------------------------------

  const state = {
    step: 1,
    rootInfo: null,    // last /api/retrobat-root result
    scan: null,        // last /api/scan result
    preview: null,     // last scaffold preview result
    scaffoldMode: 'defaults', // 'defaults' (safe, ~258 max) or 'all' (per-game)
    busy: false,
    overlayEl: null,
    bodyEl: null,
    primaryEl: null,
    lastFocusBeforeOverlay: null,
    keyHandler: null,
    focusTrapHandler: null,
  };

  // ----------------------------------------------------------------
  // Overlay shell
  // ----------------------------------------------------------------

  function buildOverlay() {
    const overlay = el('div', {
      class: 'rbcf-onb-overlay',
      id: 'rbcf-onb-overlay',
      role: 'dialog',
      'aria-modal': 'true',
      'aria-labelledby': 'rbcf-onb-title',
      'aria-describedby': 'rbcf-onb-body',
    });

    const card = el('div', { class: 'rbcf-onb-card' });

    const head = el('header', { class: 'rbcf-onb-head' }, [
      el('div', { class: 'rbcf-onb-step-pill', id: 'rbcf-onb-step-pill', text: 'Step 1 of 3' }),
      el('h2', { class: 'rbcf-onb-title', id: 'rbcf-onb-title', text: 'Welcome' }),
      el('button', {
        class: 'rbcf-onb-x',
        type: 'button',
        'aria-label': 'Close onboarding',
        title: 'Skip onboarding',
        onclick: requestSkip,
      }, ['×']),
    ]);

    const body = el('div', { class: 'rbcf-onb-body', id: 'rbcf-onb-body' });

    const footer = el('footer', { class: 'rbcf-onb-foot' }, [
      el('div', { class: 'rbcf-onb-foot-secondary', id: 'rbcf-onb-foot-secondary' }),
      el('div', { class: 'rbcf-onb-foot-primary', id: 'rbcf-onb-foot-primary' }),
    ]);

    const live = el('div', {
      class: 'rbcf-onb-live',
      id: 'rbcf-onb-live',
      'aria-live': 'polite',
      role: 'status',
    });

    card.appendChild(head);
    card.appendChild(body);
    card.appendChild(footer);
    card.appendChild(live);
    overlay.appendChild(card);

    state.overlayEl = overlay;
    state.bodyEl = body;
    return overlay;
  }

  function setStepHeader(stepNum, title) {
    const pill  = document.getElementById('rbcf-onb-step-pill');
    const titleEl = document.getElementById('rbcf-onb-title');
    if (pill) pill.textContent = `Step ${stepNum} of 3`;
    if (titleEl) titleEl.textContent = title;
  }

  function clearFooter() {
    const sec = document.getElementById('rbcf-onb-foot-secondary');
    const pri = document.getElementById('rbcf-onb-foot-primary');
    if (sec) sec.innerHTML = '';
    if (pri) pri.innerHTML = '';
    state.primaryEl = null;
  }

  function setFooterPrimary(label, onclick, opts) {
    const pri = document.getElementById('rbcf-onb-foot-primary');
    if (!pri) return null;
    const btn = el('button', {
      type: 'button',
      class: 'rbcf-onb-btn rbcf-onb-btn-primary',
      onclick,
    }, [label]);
    if (opts && opts.disabled) btn.disabled = true;
    pri.appendChild(btn);
    state.primaryEl = btn;
    return btn;
  }

  function setFooterSecondary(label, onclick, kind) {
    const sec = document.getElementById('rbcf-onb-foot-secondary');
    if (!sec) return null;
    const btn = el('button', {
      type: 'button',
      class: 'rbcf-onb-btn ' + (kind === 'tertiary' ? 'rbcf-onb-btn-tertiary' : 'rbcf-onb-btn-secondary'),
      onclick,
    }, [label]);
    sec.appendChild(btn);
    return btn;
  }

  function focusPrimary() {
    if (state.primaryEl && typeof state.primaryEl.focus === 'function') {
      state.primaryEl.focus();
    }
  }

  // ----------------------------------------------------------------
  // STEP 1 — RetroBat detection
  // ----------------------------------------------------------------

  async function renderStep1() {
    state.step = 1;
    setStepHeader(1, 'Find your RetroBat install');
    clearFooter();

    state.bodyEl.innerHTML = '';
    state.bodyEl.appendChild(el('p', {
      class: 'rbcf-onb-lede',
      text: 'RB-Controller_fix needs to know where RetroBat lives so it can edit the right config files. We never write outside that folder without confirming first.',
    }));

    const status = el('div', { class: 'rbcf-onb-status', id: 'rbcf-onb-root-status' }, [
      el('span', { class: 'rbcf-onb-spinner' }),
      el('span', { text: 'Looking for RetroBat…' }),
    ]);
    state.bodyEl.appendChild(status);

    setFooterPrimary('Continue', () => goToStep2(), { disabled: true });
    setFooterSecondary('Skip onboarding for now', requestSkip, 'tertiary');

    try {
      const data = await fetchJson('GET', '/api/retrobat-root');
      state.rootInfo = data;
      paintRootStatus(data);
    } catch (e) {
      paintRootError(e);
    }
  }

  function paintRootStatus(data) {
    const wrap = document.getElementById('rbcf-onb-root-status');
    if (!wrap) return;
    wrap.innerHTML = '';

    if (data && data.found) {
      wrap.classList.remove('rbcf-onb-status-error');
      wrap.classList.add('rbcf-onb-status-ok');
      wrap.appendChild(el('span', { class: 'rbcf-onb-check', 'aria-hidden': 'true', text: '✓' }));
      const msg = el('div', { class: 'rbcf-onb-status-msg' }, [
        el('strong', { text: 'Found RetroBat.' }),
        el('div', {}, [
          'Located at ',
          el('code', { text: data.root || '(unknown)' }),
          '. Looks good.',
        ]),
      ]);
      wrap.appendChild(msg);
      if (state.primaryEl) state.primaryEl.disabled = false;
      focusPrimary();
      return;
    }

    // Not found — render probed list + override input.
    wrap.classList.remove('rbcf-onb-status-ok');
    wrap.classList.add('rbcf-onb-status-error');
    wrap.appendChild(el('span', { class: 'rbcf-onb-cross', 'aria-hidden': 'true', text: '!' }));

    const block = el('div', { class: 'rbcf-onb-status-msg' });
    block.appendChild(el('strong', { text: "We couldn't find RetroBat." }));
    block.appendChild(el('p', {
      class: 'rbcf-onb-muted',
      text: 'We looked in the usual places but came up empty. If RetroBat is installed somewhere else, type the install root here.',
    }));

    if (data && Array.isArray(data.probed) && data.probed.length) {
      const list = el('ul', { class: 'rbcf-onb-probed' });
      for (const p of data.probed) {
        list.appendChild(el('li', { text: String(p) }));
      }
      const det = el('details', { class: 'rbcf-onb-details' }, [
        el('summary', { text: `Where we looked (${data.probed.length})` }),
        list,
      ]);
      block.appendChild(det);
    }

    const override = (function () {
      try { return localStorage.getItem(ROOT_KEY) || ''; } catch (e) { return ''; }
    })();

    const form = el('form', {
      class: 'rbcf-onb-rootform',
      onsubmit: (e) => { e.preventDefault(); submitRootOverride(); },
    });
    const input = el('input', {
      type: 'text',
      id: 'rbcf-onb-root-input',
      class: 'rbcf-onb-input',
      placeholder: 'E:\\RetroBat\\',
      value: override,
      'aria-label': 'RetroBat install root',
    });
    const submitBtn = el('button', {
      type: 'submit',
      class: 'rbcf-onb-btn rbcf-onb-btn-secondary',
      text: 'Use this path',
    });
    form.appendChild(input);
    form.appendChild(submitBtn);
    block.appendChild(form);

    wrap.appendChild(block);

    if (state.primaryEl) state.primaryEl.disabled = true;
  }

  function paintRootError(e) {
    const wrap = document.getElementById('rbcf-onb-root-status');
    if (!wrap) return;
    wrap.innerHTML = '';
    wrap.classList.remove('rbcf-onb-status-ok');
    wrap.classList.add('rbcf-onb-status-error');
    wrap.appendChild(el('span', { class: 'rbcf-onb-cross', 'aria-hidden': 'true', text: '!' }));
    const msg = el('div', { class: 'rbcf-onb-status-msg' }, [
      el('strong', { text: e.kind === 'not-implemented' ? 'Backend not ready' : 'Probe error' }),
      el('p', { class: 'rbcf-onb-muted', text: e.message }),
      el('p', { class: 'rbcf-onb-muted', text: 'You can skip onboarding for now and try again after the server restarts.' }),
    ]);
    wrap.appendChild(msg);
    // Allow Continue to advance — step 2 will render its own error if /api/scan also 404s.
    if (state.primaryEl) state.primaryEl.disabled = false;
  }

  // POST /api/retrobat-root with JSON body. Returns the parsed JSON for both
  // 2xx (ok:true|false) and 4xx-with-JSON (ok:false). Throws with err.kind set
  // to 'not-implemented' / 'http' / 'network' / 'json' for callers that want
  // to render a generic "backend not running" message.
  async function postRetrobatRoot(rootPath) {
    let resp;
    try {
      resp = await fetch('/api/retrobat-root', {
        method: 'POST',
        headers: { 'Accept': 'application/json', 'Content-Type': 'application/json' },
        body: JSON.stringify({ root: rootPath }),
      });
    } catch (e) {
      const err = new Error('network: ' + e.message);
      err.kind = 'network';
      throw err;
    }
    if (resp.status === 404) {
      const err = new Error('Backend endpoint not yet available — try again after server restart.');
      err.kind = 'not-implemented';
      err.status = 404;
      throw err;
    }
    let body = null;
    try {
      body = await resp.json();
    } catch (e) {
      // No / bad JSON.
      if (!resp.ok) {
        const err = new Error(`POST /api/retrobat-root → ${resp.status}`);
        err.kind = 'http';
        err.status = resp.status;
        throw err;
      }
      const err = new Error('Bad JSON from /api/retrobat-root');
      err.kind = 'json';
      throw err;
    }
    // 4xx-with-JSON: surface as a normal failure body so the caller can show
    // the `error` field. Only treat as a hard HTTP error if the body has no
    // `ok` field at all (i.e. it's not a structured rejection).
    if (!resp.ok && (body == null || typeof body.ok === 'undefined')) {
      const err = new Error(`POST /api/retrobat-root → ${resp.status}`);
      err.kind = 'http';
      err.status = resp.status;
      throw err;
    }
    return body;
  }

  async function submitRootOverride() {
    const input = document.getElementById('rbcf-onb-root-input');
    if (!input) return;
    const path = (input.value || '').trim();
    if (!path) return;
    // Local-only fallback: lets the user see their last-typed path on reopen.
    // No longer load-bearing for behaviour — .rbcfrc on the server side is.
    try { localStorage.setItem(ROOT_KEY, path); } catch (e) { /* ignore */ }
    const wrap = document.getElementById('rbcf-onb-root-status');
    if (wrap) {
      wrap.innerHTML = '';
      wrap.classList.remove('rbcf-onb-status-error', 'rbcf-onb-status-ok');
      wrap.appendChild(el('span', { class: 'rbcf-onb-spinner' }));
      wrap.appendChild(el('span', { text: 'Saving…' }));
    }
    let data;
    try {
      data = await postRetrobatRoot(path);
    } catch (e) {
      paintRootSaveGenericError(e);
      return;
    }
    if (data && data.ok) {
      paintRootSaveSuccess(data);
    } else {
      paintRootSaveBadPath(data);
    }
  }

  // Success + restart_required: green block, two buttons.
  // (success without restart_required would be unusual — the backend always
  // says restart_required when a write succeeds — but we treat it as plain
  // success and let Continue advance.)
  function paintRootSaveSuccess(data) {
    const wrap = document.getElementById('rbcf-onb-root-status');
    if (!wrap) return;
    wrap.innerHTML = '';
    wrap.classList.remove('rbcf-onb-status-error');
    wrap.classList.add('rbcf-onb-status-ok');
    wrap.appendChild(el('span', { class: 'rbcf-onb-check', 'aria-hidden': 'true', text: '✓' }));

    const block = el('div', { class: 'rbcf-onb-status-msg' });
    block.appendChild(el('strong', { text: 'Saved.' }));
    const savedLine = el('div', {}, [
      'Saved RetroBat root to ',
      el('code', { text: data.path_to_rbcfrc || '.rbcfrc' }),
      '.',
    ]);
    block.appendChild(savedLine);

    if (data.restart_required) {
      block.appendChild(el('p', {
        class: 'rbcf-onb-muted',
        text: 'Restart the server for this to take effect.',
      }));

      const btnRow = el('div', { class: 'rbcf-onb-rootform' });
      const dismissBtn = el('button', {
        type: 'button',
        class: 'rbcf-onb-btn rbcf-onb-btn-secondary',
        text: "I'll restart it manually",
        onclick: () => {
          // Just dismiss the inline status — leave the form visible so the
          // user can re-enter / re-submit if needed.
          const input = document.getElementById('rbcf-onb-root-input');
          paintRootStatus(state.rootInfo || { found: false, probed: [] });
          if (input) {
            const fresh = document.getElementById('rbcf-onb-root-input');
            if (fresh) fresh.value = input.value;
          }
        },
      });
      const tryAnywayBtn = el('button', {
        type: 'button',
        class: 'rbcf-onb-btn rbcf-onb-btn-tertiary',
        text: 'Try anyway without restart',
        onclick: () => {
          // Advance to step 2 — the cached RETROBAT_ROOT is still wrong, so
          // step 2 will surface the right error if it does, but the path is
          // saved for next run.
          goToStep2();
        },
      });
      btnRow.appendChild(dismissBtn);
      btnRow.appendChild(tryAnywayBtn);
      block.appendChild(btnRow);
    } else if (data.message) {
      block.appendChild(el('p', { class: 'rbcf-onb-muted', text: data.message }));
    }

    wrap.appendChild(block);

    // If the backend confirms found:true (i.e. it loaded immediately without
    // restart), allow Continue.
    if (data.found && state.primaryEl) {
      state.rootInfo = { root: data.root, found: true, probed: [] };
      state.primaryEl.disabled = false;
    }
  }

  // failure — bad path: red block with the `error` field text.
  function paintRootSaveBadPath(data) {
    const wrap = document.getElementById('rbcf-onb-root-status');
    if (!wrap) return;
    wrap.innerHTML = '';
    wrap.classList.remove('rbcf-onb-status-ok');
    wrap.classList.add('rbcf-onb-status-error');
    wrap.appendChild(el('span', { class: 'rbcf-onb-cross', 'aria-hidden': 'true', text: '!' }));

    const errText = (data && data.error)
      ? String(data.error)
      : (data && data.message)
        ? String(data.message)
        : "That doesn't look like a RetroBat install.";

    const block = el('div', { class: 'rbcf-onb-status-msg' }, [
      el('strong', { text: "Couldn't save that path." }),
      el('p', { class: 'rbcf-onb-muted', text: errText }),
    ]);
    wrap.appendChild(block);

    // Re-render the form so the user can fix and retry.
    rebuildRootOverrideForm(block);

    if (state.primaryEl) state.primaryEl.disabled = true;
  }

  // failure — generic / network / 404: same gracefulness as the rest of the
  // onboarding flow's "backend may not be running" path.
  function paintRootSaveGenericError(e) {
    const wrap = document.getElementById('rbcf-onb-root-status');
    if (!wrap) return;
    wrap.innerHTML = '';
    wrap.classList.remove('rbcf-onb-status-ok');
    wrap.classList.add('rbcf-onb-status-error');
    wrap.appendChild(el('span', { class: 'rbcf-onb-cross', 'aria-hidden': 'true', text: '!' }));

    const headline = (e && e.kind === 'not-implemented')
      ? 'Backend not ready'
      : "Couldn't save the path";
    const sub = (e && e.kind === 'not-implemented')
      ? 'Try again after the server restarts.'
      : 'Backend may not be running.';

    const block = el('div', { class: 'rbcf-onb-status-msg' }, [
      el('strong', { text: headline }),
      el('p', { class: 'rbcf-onb-muted', text: sub }),
    ]);
    wrap.appendChild(block);

    rebuildRootOverrideForm(block);

    if (state.primaryEl) state.primaryEl.disabled = true;
  }

  // Re-attach the path-input form to a status block so the user can retry
  // after a failure. Pre-fills with the last-typed value from localStorage.
  function rebuildRootOverrideForm(block) {
    const override = (function () {
      try { return localStorage.getItem(ROOT_KEY) || ''; } catch (e) { return ''; }
    })();
    const form = el('form', {
      class: 'rbcf-onb-rootform',
      onsubmit: (e) => { e.preventDefault(); submitRootOverride(); },
    });
    const input = el('input', {
      type: 'text',
      id: 'rbcf-onb-root-input',
      class: 'rbcf-onb-input',
      placeholder: 'E:\\RetroBat\\',
      value: override,
      'aria-label': 'RetroBat install root',
    });
    const submitBtn = el('button', {
      type: 'submit',
      class: 'rbcf-onb-btn rbcf-onb-btn-secondary',
      text: 'Use this path',
    });
    form.appendChild(input);
    form.appendChild(submitBtn);
    block.appendChild(form);
  }

  // ----------------------------------------------------------------
  // STEP 2 — Scan summary
  // ----------------------------------------------------------------

  async function goToStep2() {
    state.step = 2;
    setStepHeader(2, "Here's what we found");
    clearFooter();
    state.bodyEl.innerHTML = '';
    state.bodyEl.appendChild(el('p', {
      class: 'rbcf-onb-lede',
      text: 'Quick scan of your ROM library and existing profile coverage.',
    }));

    const wrap = el('div', { class: 'rbcf-onb-scan', id: 'rbcf-onb-scan' }, [
      el('div', { class: 'rbcf-onb-loading' }, [
        el('span', { class: 'rbcf-onb-spinner' }),
        el('span', { text: 'Scanning systems and ROMs…' }),
      ]),
    ]);
    state.bodyEl.appendChild(wrap);

    setFooterPrimary('Scaffold defaults (preview)', () => goToStep3(), { disabled: true });
    setFooterSecondary("Skip — I'll do this later", requestSkip, 'tertiary');

    try {
      const data = await fetchJson('GET', '/api/scan');
      state.scan = data;
      paintScan(data);
    } catch (e) {
      paintScanError(e);
    }
  }

  function paintScan(data) {
    const wrap = document.getElementById('rbcf-onb-scan');
    if (!wrap) return;
    wrap.innerHTML = '';

    const totals = (data && data.totals) || {};
    const systems = (data && Array.isArray(data.systems)) ? data.systems : [];

    const summary = el('div', { class: 'rbcf-onb-summary' });
    summary.appendChild(el('strong', {
      text: `${totals.systems ?? systems.length} systems · ${totals.roms ?? '?'} games · ${totals.profiles ?? '?'} with per-game profiles · ${totals.missing ?? '?'} missing`,
    }));
    wrap.appendChild(summary);

    if (!systems.length) {
      wrap.appendChild(el('div', {
        class: 'rbcf-onb-empty',
        text: 'No systems detected. Drop ROMs into RetroBat\'s roms folder and rescan.',
      }));
      // Still allow user to skip past.
      if (state.primaryEl) state.primaryEl.disabled = true;
      focusPrimary();
      return;
    }

    const tbl = el('table', { class: 'rbcf-onb-table' });
    const thead = el('thead', {}, [
      el('tr', {}, [
        el('th', { text: 'System' }),
        el('th', { class: 'rbcf-onb-num', text: 'ROMs' }),
        el('th', { class: 'rbcf-onb-num', text: 'Per-game' }),
        el('th', { class: 'rbcf-onb-num', text: 'Missing' }),
        el('th', { class: 'rbcf-onb-row-action-col', text: '' }),
      ]),
    ]);
    const tbody = el('tbody');
    // Per-system exclude counts so we can show "(N)" pills next to the link.
    let excludesIndex = state.excludesIndex || {};
    function refreshExcludesIndex() {
      return fetch('/api/scaffold-excludes')
        .then(r => r.json())
        .then(j => { excludesIndex = j.excludes || {}; state.excludesIndex = excludesIndex; })
        .catch(() => { /* keep last-known */ });
    }
    refreshExcludesIndex();  // fire and forget; rows render now and refresh in place
    for (const s of systems) {
      const missingCls = (s.missing > 0) ? 'rbcf-onb-num rbcf-onb-warn' : 'rbcf-onb-num';
      const sysName = s.name || '?';
      const excludeLink = el('a', {
        href: '#',
        class: 'rbcf-onb-row-action',
        'data-system': sysName,
      }, ['Exclude folders…']);
      const excludeCount = el('span', { class: 'rbcf-onb-exclude-count' });
      function refreshLinkBadge() {
        const n = (excludesIndex[sysName] || []).length;
        excludeCount.textContent = n > 0 ? ` (${n})` : '';
      }
      refreshLinkBadge();
      excludeLink.addEventListener('click', (ev) => {
        ev.preventDefault();
        openExcludeModal(sysName, () => {
          refreshExcludesIndex().then(refreshLinkBadge);
        });
      });
      const tr = el('tr', {}, [
        el('td', { text: sysName }),
        el('td', { class: 'rbcf-onb-num', text: String(s.rom_count ?? 0) }),
        el('td', { class: 'rbcf-onb-num', text: String(s.profiles_count ?? 0) }),
        el('td', { class: missingCls, text: String(s.missing ?? 0) }),
      ]);
      const tdAction = el('td', { class: 'rbcf-onb-row-action-col' });
      tdAction.appendChild(excludeLink);
      tdAction.appendChild(excludeCount);
      tr.appendChild(tdAction);
      tbody.appendChild(tr);
    }
    tbl.appendChild(thead);
    tbl.appendChild(tbody);
    wrap.appendChild(tbl);

    const missingTotal = totals.missing ?? systems.reduce((a, s) => a + (s.missing || 0), 0);
    const systemsWithoutDefault = systems.filter(s => (s.rom_count || 0) > 0 && !s.has_default).length;

    function updatePrimaryForMode() {
      if (!state.primaryEl) return;
      if (state.scaffoldMode === 'defaults') {
        if (systemsWithoutDefault > 0) {
          state.primaryEl.disabled = false;
          state.primaryEl.textContent = `Scaffold ${systemsWithoutDefault} system default${systemsWithoutDefault === 1 ? '' : 's'} (preview)`;
        } else {
          state.primaryEl.disabled = true;
          state.primaryEl.textContent = 'All systems have defaults';
        }
      } else {
        if (missingTotal > 0) {
          state.primaryEl.disabled = false;
          state.primaryEl.textContent = `Scaffold ${missingTotal} per-game stub${missingTotal === 1 ? '' : 's'} (preview)`;
        } else {
          state.primaryEl.disabled = true;
          state.primaryEl.textContent = 'Every ROM already has a profile';
        }
      }
    }

    if (missingTotal === 0 && systemsWithoutDefault === 0) {
      wrap.appendChild(el('p', {
        class: 'rbcf-onb-muted',
        text: 'Every detected system has a default and every ROM has a profile. Nothing to do here.',
      }));
      if (state.primaryEl) {
        state.primaryEl.disabled = true;
        state.primaryEl.textContent = 'Nothing to scaffold';
      }
    } else {
      // Auto-default the toggle to whichever mode actually has work to
      // do. If defaults are all in place but per-game stubs are missing,
      // jump straight to "Every ROM" mode so the primary button is
      // already actionable. The user can flip back to "Defaults only"
      // (the no-op state) if they want to confirm — but they won't
      // be stuck with a disabled primary.
      if (systemsWithoutDefault === 0 && missingTotal > 0
          && state.scaffoldMode === 'defaults') {
        state.scaffoldMode = 'all';
      }
      // Mode toggle: defaults (safe) vs per-game stubs (advanced).
      const modeWrap = el('div', { class: 'rbcf-onb-mode-toggle' });
      const helpText = el('p', { class: 'rbcf-onb-muted rbcf-onb-mode-help' });

      function refreshModeHelp() {
        helpText.textContent = state.scaffoldMode === 'defaults'
          ? `Recommended. Creates one _default.yaml per system that's missing one (${systemsWithoutDefault} files). Empty stubs you fill in over time.`
          : `Advanced. Creates one .yaml per ROM that doesn't have a per-game profile (${missingTotal} files). Use only after a system's _default is set.`;
      }

      const btnDefaults = el('button', {
        type: 'button',
        class: 'rbcf-onb-mode-btn' + (state.scaffoldMode === 'defaults' ? ' rbcf-onb-mode-active' : ''),
        text: `Defaults only (${systemsWithoutDefault})`,
      });
      const btnAll = el('button', {
        type: 'button',
        class: 'rbcf-onb-mode-btn' + (state.scaffoldMode === 'all' ? ' rbcf-onb-mode-active' : ''),
        text: `Every ROM (${missingTotal})`,
      });
      btnDefaults.addEventListener('click', () => {
        state.scaffoldMode = 'defaults';
        btnDefaults.classList.add('rbcf-onb-mode-active');
        btnAll.classList.remove('rbcf-onb-mode-active');
        refreshModeHelp();
        updatePrimaryForMode();
      });
      btnAll.addEventListener('click', () => {
        state.scaffoldMode = 'all';
        btnAll.classList.add('rbcf-onb-mode-active');
        btnDefaults.classList.remove('rbcf-onb-mode-active');
        refreshModeHelp();
        updatePrimaryForMode();
      });
      modeWrap.appendChild(btnDefaults);
      modeWrap.appendChild(btnAll);
      wrap.appendChild(modeWrap);
      refreshModeHelp();
      wrap.appendChild(helpText);

      updatePrimaryForMode();
    }

    // Bezel-cutoff callout: non-blocking, sits below scaffolds. Renders only
    // when the scan reported >0 bezels needing fix-ups. Scaffolding and
    // bezel-fixing are independent — user can do either, both, or neither.
    const bezelCount = Number(data && data.bezels_with_cutoffs) || 0;
    if (bezelCount > 0) {
      wrap.appendChild(buildBezelCallout(bezelCount));
    }

    focusPrimary();
  }

  // ----------------------------------------------------------------
  // Bezel-cutoff callout (renders inside step 2, below the systems table)
  // ----------------------------------------------------------------

  // Reuses the .rbcf-onb-status / .rbcf-onb-status-msg / .rbcf-onb-banner
  // / .rbcf-onb-preview-* / .rbcf-onb-pill / .rbcf-onb-mode-btn class
  // families already defined in style.css — no new CSS required.
  function buildBezelCallout(initialCount) {
    const callout = el('div', {
      class: 'rbcf-onb-status rbcf-onb-bezel-callout',
      id: 'rbcf-onb-bezel-callout',
      role: 'group',
      'aria-labelledby': 'rbcf-onb-bezel-headline',
    });

    const block = el('div', { class: 'rbcf-onb-status-msg' });
    block.appendChild(el('strong', {
      id: 'rbcf-onb-bezel-headline',
      text: `${initialCount} bezel${initialCount === 1 ? '' : 's'} in your install ` +
            `${initialCount === 1 ? 'has' : 'have'} auto-detect cutoffs`,
    }));
    block.appendChild(el('p', {
      class: 'rbcf-onb-muted',
      text: 'The default RetroBat alpha threshold (235) crops some game viewports. ' +
            'Tighter detection (alpha 32) recovers the full play area.',
    }));

    const btnRow = el('div', { class: 'rbcf-onb-rootform' });

    const showBtn = el('button', {
      type: 'button',
      class: 'rbcf-onb-btn rbcf-onb-btn-secondary',
      'aria-expanded': 'false',
      'aria-controls': 'rbcf-onb-bezel-details',
      text: 'Show details ⌄',
    });
    const skipBtn = el('button', {
      type: 'button',
      class: 'rbcf-onb-btn rbcf-onb-btn-tertiary',
      text: 'Skip — leave bezels alone',
      onclick: () => {
        // No localStorage flag — re-prompts on next onboarding (per spec).
        if (callout.parentNode) callout.parentNode.removeChild(callout);
        lightToast('Bezels left unchanged.', 'info');
      },
    });
    btnRow.appendChild(showBtn);
    btnRow.appendChild(skipBtn);
    block.appendChild(btnRow);

    // Lazy-loaded details panel — populated when user clicks "Show details".
    const details = el('div', {
      class: 'rbcf-onb-bezel-details',
      id: 'rbcf-onb-bezel-details',
      hidden: '',
    });
    block.appendChild(details);

    showBtn.addEventListener('click', () => {
      const expanded = showBtn.getAttribute('aria-expanded') === 'true';
      if (expanded) {
        showBtn.setAttribute('aria-expanded', 'false');
        showBtn.textContent = 'Show details ⌄';
        details.hidden = true;
      } else {
        showBtn.setAttribute('aria-expanded', 'true');
        showBtn.textContent = 'Hide details ⌃';
        details.hidden = false;
        if (!details.dataset.loaded) {
          loadBezelDetails(details, callout);
        }
      }
    });

    callout.appendChild(block);
    return callout;
  }

  async function loadBezelDetails(details, callout) {
    details.innerHTML = '';
    details.appendChild(el('div', { class: 'rbcf-onb-loading' }, [
      el('span', { class: 'rbcf-onb-spinner' }),
      el('span', { text: 'Inspecting bezels…' }),
    ]));
    let data;
    try {
      data = await fetchJson('GET', '/api/bezel-cutoffs');
    } catch (e) {
      details.innerHTML = '';
      details.appendChild(el('div', { class: 'rbcf-onb-status rbcf-onb-status-error' }, [
        el('span', { class: 'rbcf-onb-cross', 'aria-hidden': 'true', text: '!' }),
        el('div', { class: 'rbcf-onb-status-msg' }, [
          el('strong', { text: e.kind === 'not-implemented' ? 'Backend endpoint not yet available' : 'Bezel scan failed' }),
          el('p', { class: 'rbcf-onb-muted', text: e.kind === 'not-implemented' ? 'Try again after the server restarts.' : e.message }),
        ]),
      ]));
      return;
    }
    details.dataset.loaded = '1';
    details.innerHTML = '';

    const cutoffs = (data && Array.isArray(data.cutoffs)) ? data.cutoffs : [];
    const count = data && typeof data.count === 'number' ? data.count : cutoffs.length;
    if (count === 0) {
      details.appendChild(el('p', {
        class: 'rbcf-onb-muted',
        text: 'No bezels need fixing — the on-disk scan came up empty on the second pass. You can dismiss this callout.',
      }));
      return;
    }

    const ul = el('ul', { class: 'rbcf-onb-preview-files' });
    for (const c of cutoffs) {
      const sys = c.system || '?';
      const sz = c.image_size || {};
      const vp = c.viewport || {};
      const pct = c.cutoff_pct || {};
      const playW = (typeof vp.r === 'number' && typeof vp.l === 'number') ? (vp.r - vp.l) : null;
      const playH = (typeof vp.b === 'number' && typeof vp.t === 'number') ? (vp.b - vp.t) : null;
      const sizeLine = (sz.w && sz.h && playW && playH)
        ? `${sz.w}×${sz.h} → play area ${playW}×${playH}`
        : '(size unknown)';
      const pctLine = (typeof pct.x === 'number' || typeof pct.y === 'number')
        ? `cutoff: ${pct.x ?? 0}% horizontal, ${pct.y ?? 0}% vertical`
        : '';
      const item = el('li', {}, [
        el('span', { class: 'rbcf-onb-rom', text: sys }),
        el('span', { class: 'rbcf-onb-arrow', 'aria-hidden': 'true', text: ' → ' }),
        el('code', { text: sizeLine }),
        pctLine ? el('span', { class: 'rbcf-onb-pill', text: pctLine }) : null,
        c.current_info_exists
          ? el('span', { class: 'rbcf-onb-pill', title: 'An .info already exists; this bezel will be skipped (delete to re-write).', text: '.info exists' })
          : null,
      ]);
      ul.appendChild(item);
    }
    details.appendChild(ul);

    const fixRow = el('div', { class: 'rbcf-onb-rootform' });
    const fixBtn = el('button', {
      type: 'button',
      class: 'rbcf-onb-btn rbcf-onb-btn-primary',
      text: `Fix ${count} bezel${count === 1 ? '' : 's'}`,
    });
    fixBtn.addEventListener('click', async () => {
      fixBtn.disabled = true;
      fixBtn.textContent = 'Applying…';
      try {
        // H2 audit fix: write-mode endpoint moved to POST.
        const res = await fetchJson('POST', '/api/bezel-cutoffs');
        const wrote = (res && Array.isArray(res.written)) ? res.written.length : 0;
        const skipped = (res && Array.isArray(res.skipped_existing)) ? res.skipped_existing.length : 0;
        const msg = skipped
          ? `Wrote ${wrote} .info file${wrote === 1 ? '' : 's'} (${skipped} skipped — already existed).`
          : `Wrote ${wrote} .info file${wrote === 1 ? '' : 's'}.`;
        lightToast(msg, 'success');
        if (callout && callout.parentNode) callout.parentNode.removeChild(callout);
      } catch (e) {
        fixBtn.disabled = false;
        fixBtn.textContent = `Retry fix ${count}`;
        lightToast('Bezel fix failed: ' + e.message, 'error');
      }
    });
    fixRow.appendChild(fixBtn);
    details.appendChild(fixRow);
  }

  function paintScanError(e) {
    const wrap = document.getElementById('rbcf-onb-scan');
    if (!wrap) return;
    wrap.innerHTML = '';
    wrap.appendChild(el('div', { class: 'rbcf-onb-status rbcf-onb-status-error' }, [
      el('span', { class: 'rbcf-onb-cross', 'aria-hidden': 'true', text: '!' }),
      el('div', { class: 'rbcf-onb-status-msg' }, [
        el('strong', { text: e.kind === 'not-implemented' ? 'Backend endpoint not yet available' : 'Scan failed' }),
        el('p', { class: 'rbcf-onb-muted', text: e.kind === 'not-implemented' ? 'Try again after the server restarts.' : e.message }),
      ]),
    ]));
    if (state.primaryEl) state.primaryEl.disabled = true;
    focusPrimary();
  }

  // ----------------------------------------------------------------
  // STEP 3 — Preview & apply
  // ----------------------------------------------------------------

  async function goToStep3() {
    state.step = 3;
    setStepHeader(3, 'Preview — nothing has been written yet');
    clearFooter();
    state.bodyEl.innerHTML = '';

    const wrap = el('div', { class: 'rbcf-onb-preview', id: 'rbcf-onb-preview' }, [
      el('div', { class: 'rbcf-onb-loading' }, [
        el('span', { class: 'rbcf-onb-spinner' }),
        el('span', { text: 'Computing preview…' }),
      ]),
    ]);
    state.bodyEl.appendChild(wrap);

    setFooterPrimary('Apply', onApply, { disabled: true });
    setFooterSecondary('Cancel', () => goToStep2(), 'secondary');
    // Tertiary "skip for now" lives inline in the preview body once it lands.

    try {
      const endpoint = state.scaffoldMode === 'defaults' ? '/api/scaffold-defaults' : '/api/scaffold-all';
      const data = await fetchJson('GET', endpoint);
      state.preview = data;
      paintPreview(data);
    } catch (e) {
      paintPreviewError(e);
    }
  }

  function paintPreview(data) {
    const wrap = document.getElementById('rbcf-onb-preview');
    if (!wrap) return;
    wrap.innerHTML = '';

    const items = (data && Array.isArray(data.preview)) ? data.preview : [];
    const count = data && typeof data.count === 'number' ? data.count : items.length;

    if (count === 0) {
      wrap.appendChild(el('div', { class: 'rbcf-onb-empty' }, [
        el('strong', { text: 'Nothing to scaffold.' }),
        ' Every detected ROM already has a profile.',
      ]));
      if (state.primaryEl) {
        state.primaryEl.disabled = true;
        state.primaryEl.textContent = 'Apply';
      }
      addSkipForNowFooter();
      return;
    }

    const banner = el('div', { class: 'rbcf-onb-banner' });
    banner.appendChild(el('strong', { text: 'Nothing has been written yet. ' }));
    banner.appendChild(document.createTextNode(
      `Click Apply to create these ${count} files. Click Cancel to back out.`
    ));
    wrap.appendChild(banner);

    // Group by system for legibility.
    const bySystem = new Map();
    for (const it of items) {
      const sys = it.system || '?';
      if (!bySystem.has(sys)) bySystem.set(sys, []);
      bySystem.get(sys).push(it);
    }

    const list = el('div', { class: 'rbcf-onb-preview-list' });
    for (const [sys, rows] of bySystem) {
      const sect = el('details', { class: 'rbcf-onb-preview-system', open: '' });
      sect.appendChild(el('summary', {}, [
        el('strong', { text: sys }),
        el('span', { class: 'rbcf-onb-pill', text: `${rows.length} file${rows.length === 1 ? '' : 's'}` }),
      ]));
      const ul = el('ul', { class: 'rbcf-onb-preview-files' });
      for (const r of rows) {
        // defaults entries have {system, path, rom_count}; per-game entries have {system, rom, path}
        const label = r.rom
          ? r.rom
          : `_default.yaml (${r.rom_count ?? '?'} ROM${r.rom_count === 1 ? '' : 's'} in this system)`;
        ul.appendChild(el('li', {}, [
          el('span', { class: 'rbcf-onb-rom', text: label }),
          el('span', { class: 'rbcf-onb-arrow', 'aria-hidden': 'true', text: ' → ' }),
          el('code', { text: r.path || '?' }),
        ]));
      }
      sect.appendChild(ul);
      list.appendChild(sect);
    }
    wrap.appendChild(list);

    if (state.primaryEl) {
      state.primaryEl.disabled = false;
      state.primaryEl.textContent = `Apply (create ${count} file${count === 1 ? '' : 's'})`;
    }
    addSkipForNowFooter();
    focusPrimary();
  }

  function addSkipForNowFooter() {
    // Tertiary skip lives in the body bottom — small, not destructive-looking.
    if (document.getElementById('rbcf-onb-skip-tertiary')) return;
    const wrap = document.getElementById('rbcf-onb-preview');
    if (!wrap) return;
    const row = el('div', { class: 'rbcf-onb-skip-row', id: 'rbcf-onb-skip-tertiary' });
    row.appendChild(el('button', {
      type: 'button',
      class: 'rbcf-onb-btn rbcf-onb-btn-tertiary',
      onclick: () => {
        markOnboarded();
        dismiss();
      },
    }, ['Skip onboarding for now']));
    wrap.appendChild(row);
  }

  function paintPreviewError(e) {
    const wrap = document.getElementById('rbcf-onb-preview');
    if (!wrap) return;
    wrap.innerHTML = '';
    wrap.appendChild(el('div', { class: 'rbcf-onb-status rbcf-onb-status-error' }, [
      el('span', { class: 'rbcf-onb-cross', 'aria-hidden': 'true', text: '!' }),
      el('div', { class: 'rbcf-onb-status-msg' }, [
        el('strong', { text: e.kind === 'not-implemented' ? 'Backend endpoint not yet available' : 'Preview failed' }),
        el('p', { class: 'rbcf-onb-muted', text: e.kind === 'not-implemented' ? 'Try again after the server restarts.' : e.message }),
      ]),
    ]));
    if (state.primaryEl) state.primaryEl.disabled = true;
    addSkipForNowFooter();
  }

  function onApply() {
    if (state.busy) return;
    state.busy = true;
    if (state.primaryEl) {
      state.primaryEl.disabled = true;
      state.primaryEl.textContent = 'Applying…';
    }
    // Replace the preview body with a progress UI before opening the
    // EventSource — the SSE stream may emit `start` immediately.
    const wrap = document.getElementById('rbcf-onb-preview');
    if (wrap) {
      wrap.innerHTML = '';
      const progress = el('div', { class: 'rbcf-onb-progress', id: 'rbcf-onb-progress' }, [
        el('div', { class: 'rbcf-onb-progress-label', id: 'rbcf-onb-progress-label',
                    text: 'Applying scaffolds…' }),
        el('div', { class: 'rbcf-onb-progress-bar' }, [
          el('div', { class: 'rbcf-onb-progress-fill', id: 'rbcf-onb-progress-fill',
                      style: 'width: 0%' }),
        ]),
        el('div', { class: 'rbcf-onb-progress-current', id: 'rbcf-onb-progress-current',
                    text: 'starting…' }),
      ]);
      wrap.appendChild(progress);
    }

    // H2 audit fix: streaming endpoints moved to POST. EventSource is
    // GET-only by spec, so we use fetch() + ReadableStream and parse
    // the SSE format manually. The wire protocol is identical
    // (`data: <json>\n\n` per event); only the transport differs.
    const endpoint = state.scaffoldMode === 'defaults'
      ? '/api/scaffold-defaults/stream'
      : '/api/scaffold-all/stream';
    let total = 0;
    let written = 0;
    let skipped = 0;
    let cancelled = false;

    function setProgress(done, current) {
      const fill = document.getElementById('rbcf-onb-progress-fill');
      const label = document.getElementById('rbcf-onb-progress-label');
      const cur = document.getElementById('rbcf-onb-progress-current');
      const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
      if (fill) fill.style.width = pct + '%';
      if (label) {
        label.textContent =
          `Applying scaffolds… ${pct}% — ${done.toLocaleString()} / ${total.toLocaleString()}`;
      }
      if (cur && current) cur.textContent = current;
    }

    function handleEvent(data) {
      if (data.event === 'start') {
        total = data.total || 0;
        setProgress(0, '');
      } else if (data.event === 'progress') {
        setProgress(data.done || 0, data.current || '');
      } else if (data.event === 'skipped') {
        skipped++;
      } else if (data.event === 'finish') {
        cancelled = true;
        state.busy = false;
        written = (data.count || 0);
        const wrap2 = document.getElementById('rbcf-onb-preview');
        if (wrap2) {
          wrap2.innerHTML = '';
          const skippedLine = skipped > 0
            ? ` (skipped ${skipped} that already existed)` : '';
          wrap2.appendChild(el('div', { class: 'rbcf-onb-status rbcf-onb-status-ok' }, [
            el('strong', { text: `Wrote ${written.toLocaleString()} profile${written === 1 ? '' : 's'}.` }),
            el('div', { class: 'rbcf-onb-muted', text: 'Onboarding complete' + skippedLine + '.' }),
          ]));
        }
        lightToast(`Scaffolded ${written} profile${written === 1 ? '' : 's'}.`, 'success');
        markOnboarded();
        setTimeout(dismiss, 1200);
      } else if (data.event === 'error') {
        cancelled = true;
        state.busy = false;
        if (state.primaryEl) {
          state.primaryEl.disabled = false;
          state.primaryEl.textContent = 'Retry apply';
        }
        lightToast('Apply failed: ' + (data.error || 'stream error'), 'error');
      }
    }

    (async () => {
      try {
        const resp = await fetch(endpoint, { method: 'POST',
                                              headers: { 'Accept': 'text/event-stream' } });
        if (!resp.ok || !resp.body) {
          throw new Error(`HTTP ${resp.status}`);
        }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buf = '';
        while (!cancelled) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          // Each SSE event ends with \n\n. Process complete events.
          let idx;
          while ((idx = buf.indexOf('\n\n')) !== -1) {
            const chunk = buf.slice(0, idx);
            buf = buf.slice(idx + 2);
            // SSE chunks may have multiple `data:` lines; join.
            const dataLines = chunk.split('\n')
              .filter(line => line.startsWith('data:'))
              .map(line => line.slice(5).trimStart());
            if (dataLines.length === 0) continue;
            try {
              handleEvent(JSON.parse(dataLines.join('\n')));
            } catch (e) { /* skip malformed */ }
          }
        }
      } catch (e) {
        if (cancelled) return;
        state.busy = false;
        if (state.primaryEl) {
          state.primaryEl.disabled = false;
          state.primaryEl.textContent = 'Retry apply';
        }
        lightToast('Apply stream failed: ' + e.message, 'error');
      }
    })();
  }

  // ----------------------------------------------------------------
  // Skip / dismiss
  // ----------------------------------------------------------------

  function requestSkip() {
    // If mid-flow (step 2 or 3 with state present), confirm. Step 1 = no friction.
    if (state.step >= 2 && (state.scan || state.preview)) {
      const ok = window.confirm("Skip onboarding? You can re-run it later by visiting `?reset-onboarding=1`.");
      if (!ok) return;
    }
    markOnboarded();
    dismiss();
  }

  function dismiss() {
    if (!state.overlayEl) return;
    state.overlayEl.classList.add('rbcf-onb-leaving');
    // Tear down listeners
    if (state.keyHandler) {
      window.removeEventListener('keydown', state.keyHandler, true);
      state.keyHandler = null;
    }
    if (state.focusTrapHandler) {
      document.removeEventListener('focusin', state.focusTrapHandler, true);
      state.focusTrapHandler = null;
    }
    document.documentElement.classList.remove('rbcf-onb-locked');
    setTimeout(() => {
      if (state.overlayEl && state.overlayEl.parentNode) {
        state.overlayEl.parentNode.removeChild(state.overlayEl);
      }
      state.overlayEl = null;
      // Restore focus to whatever was focused before the overlay
      if (state.lastFocusBeforeOverlay && typeof state.lastFocusBeforeOverlay.focus === 'function') {
        try { state.lastFocusBeforeOverlay.focus(); } catch (e) { /* ignore */ }
      }
    }, 180);
  }

  // ----------------------------------------------------------------
  // A11y: focus trap + escape
  // ----------------------------------------------------------------

  function focusableElsIn(root) {
    if (!root) return [];
    return Array.from(root.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    ));
  }

  function setupAccessibility() {
    state.keyHandler = function (e) {
      if (e.key === 'Escape') {
        e.stopPropagation();
        e.preventDefault();
        requestSkip();
        return;
      }
      if (e.key === 'Tab' && state.overlayEl) {
        const els = focusableElsIn(state.overlayEl);
        if (!els.length) return;
        const first = els[0];
        const last = els[els.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener('keydown', state.keyHandler, true);

    // Belt-and-braces: if focus escapes the overlay (e.g. via screen reader),
    // pull it back. Won't fight the user during normal Tab.
    state.focusTrapHandler = function (e) {
      if (!state.overlayEl) return;
      if (e.target && state.overlayEl.contains(e.target)) return;
      const els = focusableElsIn(state.overlayEl);
      if (els.length) els[0].focus();
    };
    document.addEventListener('focusin', state.focusTrapHandler, true);
  }

  // ----------------------------------------------------------------
  // Mount
  // ----------------------------------------------------------------

  function mount() {
    if (!shouldShow()) return;
    state.lastFocusBeforeOverlay = document.activeElement;
    document.documentElement.classList.add('rbcf-onb-locked');
    const overlay = buildOverlay();
    document.body.appendChild(overlay);
    setupAccessibility();
    renderStep1();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount, { once: true });
  } else {
    mount();
  }

  // Tiny dev-affordance: also expose a console reset.
  // Usage: rbcfResetOnboarding() in DevTools, then reload.
  window.rbcfResetOnboarding = function () {
    try { localStorage.removeItem(ONB_KEY); } catch (e) { /* ignore */ }
    console.info('[rbcf] onboarded flag cleared. Reload to see the welcome flow.');
  };

  // ----------------------------------------------------------------
  // Per-system "Exclude folders…" modal (v0.1.1)
  // ----------------------------------------------------------------

  function openExcludeModal(sysName, onSaved) {
    // Build the modal shell.
    const overlay = el('div', {
      class: 'rbcf-onb-exclude-modal',
      role: 'dialog',
      'aria-modal': 'true',
      'aria-labelledby': 'rbcf-onb-exclude-title',
    });
    const card = el('div', { class: 'rbcf-onb-exclude-card' });
    const title = el('h3', {
      id: 'rbcf-onb-exclude-title',
      class: 'rbcf-onb-exclude-title',
      text: `Exclude folders for ${sysName}`,
    });
    const body = el('div', { class: 'rbcf-onb-exclude-body', id: 'rbcf-onb-exclude-body' });
    body.appendChild(el('div', { class: 'rbcf-onb-loading' }, [
      el('span', { class: 'rbcf-onb-spinner' }),
      el('span', { text: 'Loading subdirectories…' }),
    ]));
    const foot = el('div', { class: 'rbcf-onb-exclude-foot' });
    const cancelBtn = el('button', {
      type: 'button',
      class: 'rbcf-onb-btn rbcf-onb-btn-secondary',
      text: 'Cancel',
    });
    const saveBtn = el('button', {
      type: 'button',
      class: 'rbcf-onb-btn rbcf-onb-btn-primary',
      text: 'Save',
      disabled: 'true',
    });
    foot.appendChild(cancelBtn);
    foot.appendChild(saveBtn);
    card.appendChild(title);
    card.appendChild(body);
    card.appendChild(foot);
    overlay.appendChild(card);
    document.body.appendChild(overlay);

    function close() {
      try { document.body.removeChild(overlay); } catch (e) { /* ignore */ }
    }
    cancelBtn.addEventListener('click', close);
    overlay.addEventListener('click', (ev) => {
      if (ev.target === overlay) close();
    });
    function escHandler(ev) {
      if (ev.key === 'Escape') {
        close();
        window.removeEventListener('keydown', escHandler, true);
      }
    }
    window.addEventListener('keydown', escHandler, true);

    fetch(`/api/system-subdirs?system=${encodeURIComponent(sysName)}`)
      .then(r => r.json())
      .then(data => {
        body.innerHTML = '';
        const subdirs = data.subdirs || [];
        if (subdirs.length === 0) {
          body.appendChild(el('div', {
            class: 'rbcf-onb-empty',
            text: 'This system has no subdirectories — ROMs sit at the top level. Nothing to exclude here.',
          }));
          saveBtn.disabled = true;
          return;
        }
        const list = el('ul', { class: 'rbcf-onb-exclude-list' });
        const checkboxes = [];
        for (const s of subdirs) {
          const id = `rbcf-onb-excl-${sysName}-${s.name}`.replace(/[^A-Za-z0-9_-]/g, '_');
          const cb = el('input', { type: 'checkbox', id });
          if (s.excluded) cb.checked = true;
          checkboxes.push({ name: s.name, cb });
          const lbl = el('label', { for: id }, [
            cb,
            el('span', { class: 'rbcf-onb-rom', text: s.name }),
            el('span', { class: 'rbcf-onb-muted', text: ` (${s.rom_count} ROMs)` }),
          ]);
          if (s.has_rbcf_ignore) {
            lbl.appendChild(el('span', {
              class: 'rbcf-onb-pill',
              text: '.rbcf-ignore',
              title: 'A .rbcf-ignore file in this directory already excludes it.',
            }));
          }
          list.appendChild(el('li', { class: 'rbcf-onb-exclude-row' }, [lbl]));
        }
        body.appendChild(list);
        saveBtn.disabled = false;
        saveBtn.addEventListener('click', () => {
          const excludes = checkboxes.filter(c => c.cb.checked).map(c => c.name);
          saveBtn.disabled = true;
          saveBtn.textContent = 'Saving…';
          fetch('/api/scaffold-excludes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ system: sysName, excludes }),
          })
            .then(r => r.json())
            .then(j => {
              if (j.ok) {
                lightToast(`Saved exclusions for ${sysName}.`, 'success');
                close();
                if (typeof onSaved === 'function') onSaved();
              } else {
                lightToast('Save failed: ' + (j.error || '?'), 'error');
                saveBtn.disabled = false;
                saveBtn.textContent = 'Save';
              }
            })
            .catch(e => {
              lightToast('Network error: ' + e.message, 'error');
              saveBtn.disabled = false;
              saveBtn.textContent = 'Save';
            });
        });
      })
      .catch(e => {
        body.innerHTML = '';
        body.appendChild(el('div', {
          class: 'rbcf-onb-status rbcf-onb-status-error',
          text: 'Could not load subdirectories: ' + e.message,
        }));
      });
  }
})();
