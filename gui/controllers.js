// controllers.js — inline SVG schematics for the source + target panes.
//
// Each SVG declares <g id="X-btn-NAME"> nodes for every interactive button.
// JS toggles a `.pressed` class on those nodes; CSS lights them up.
//
// Source SVGs share id prefix `src-btn-`. Target SVGs use `tgt-btn-`.
// Bond between them is in TARGET_MAPPINGS below — keyed by RetroPad button
// name (a/b/x/y/l/r/l2/r2/select/start/up/down/left/right).
//
// IDs and exported constants are load-bearing — app.js keys off them.
// Visuals can be reworked freely; do not rename ids or remove buttons.
//
// Visual language: "Frosted Acrylic" (see docs/DESIGN_LANGUAGE.md).
// Light-theme-friendly pearl-grey bodies, soft scattered shadows, single
// upper-left light source. Theme awareness is handled in style.css via
// the `.src-btn`/`.tgt-btn`/`.face.*` class hooks.

const SRC_XINPUT = `
<svg viewBox="0 0 620 380" xmlns="http://www.w3.org/2000/svg" class="ctrl-svg" aria-label="Your XInput controller">
  <defs>
    <!-- Pearl-grey body, lit from upper left -->
    <linearGradient id="xiBody" x1="0.25" y1="0" x2="0.75" y2="1">
      <stop offset="0%"   stop-color="#eef1f6"/>
      <stop offset="45%"  stop-color="#cfd5de"/>
      <stop offset="100%" stop-color="#9aa3b0"/>
    </linearGradient>
    <linearGradient id="xiBodyHi" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%"  stop-color="rgba(255,255,255,0.85)"/>
      <stop offset="55%" stop-color="rgba(255,255,255,0)"/>
    </linearGradient>
    <linearGradient id="xiBodyLo" x1="0" y1="1" x2="0" y2="0">
      <stop offset="0%"  stop-color="rgba(20,24,38,0.18)"/>
      <stop offset="60%" stop-color="rgba(20,24,38,0)"/>
    </linearGradient>

    <!-- Recessed area for d-pad / stick (subtle inset) -->
    <radialGradient id="xiRecess" cx="0.5" cy="0.4" r="0.7">
      <stop offset="0%"  stop-color="rgba(20,24,38,0.04)"/>
      <stop offset="100%" stop-color="rgba(20,24,38,0.20)"/>
    </radialGradient>

    <!-- Stick rim and knob -->
    <radialGradient id="xiStickBase" cx="0.5" cy="0.4" r="0.65">
      <stop offset="0%"   stop-color="#d6dbe3"/>
      <stop offset="65%"  stop-color="#a7afba"/>
      <stop offset="100%" stop-color="#6b7280"/>
    </radialGradient>
    <radialGradient id="xiStickKnob" cx="0.4" cy="0.32" r="0.75">
      <stop offset="0%"   stop-color="#3a4049"/>
      <stop offset="60%"  stop-color="#22272f"/>
      <stop offset="100%" stop-color="#0d1117"/>
    </radialGradient>

    <!-- Soft drop-shadow under elevated body -->
    <filter id="xiBodyShadow" x="-10%" y="-10%" width="120%" height="135%">
      <feGaussianBlur stdDeviation="5" in="SourceAlpha"/>
      <feOffset dy="6" result="off"/>
      <feComponentTransfer><feFuncA type="linear" slope="0.30"/></feComponentTransfer>
      <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>

    <!-- Tighter shadow for face buttons / shoulders -->
    <filter id="xiBtnShadow" x="-30%" y="-30%" width="160%" height="170%">
      <feGaussianBlur stdDeviation="1.5" in="SourceAlpha"/>
      <feOffset dy="2" result="off"/>
      <feComponentTransfer><feFuncA type="linear" slope="0.32"/></feComponentTransfer>
      <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>

  <!-- Body — 8BitDo-style with proper ergonomic grips.
       v0.1.5 13c: extended grips from y=302 → y=342, bowed outward at the
       widest point (x=55 left, 565 right), deepened the central notch
       (y=275 vs prior y=258). Internal elements (d-pad, stick, face
       buttons, View/Menu, shoulders/triggers) keep their original
       positions on the upper/middle body and don't need to move. -->
  <g filter="url(#xiBodyShadow)">
    <path d="M 130 96
             Q 78 96 70 152
             L 70 215
             Q 55 290 90 325
             Q 115 345 150 342
             L 215 342
             Q 250 342 270 315
             Q 290 275 310 275
             Q 330 275 350 315
             Q 370 342 405 342
             L 470 342
             Q 505 345 530 325
             Q 565 290 550 215
             L 550 152
             Q 542 96 490 96
             Z"
          fill="url(#xiBody)" stroke="rgba(20,24,38,0.25)" stroke-width="1.25"/>
    <!-- Top sheen (unchanged — sits on top of body, doesn't depend on grip shape) -->
    <path d="M 132 100
             Q 84 100 78 148
             Q 200 132 310 132
             Q 420 132 542 148
             Q 536 100 488 100 Z"
          fill="url(#xiBodyHi)"/>
    <!-- Bottom shading — adjusted to follow the new grip shape. -->
    <path d="M 70 215
             Q 55 290 90 325
             Q 115 345 150 342
             L 215 342
             Q 250 342 270 315
             Q 290 275 310 275
             Q 330 275 350 315
             Q 370 342 405 342
             L 470 342
             Q 505 345 530 325
             Q 565 290 550 215
             Q 430 235 310 235
             Q 190 235 70 215 Z"
          fill="url(#xiBodyLo)" opacity="0.65"/>
    <!-- Centre console (slightly recessed plate where home/select/start sit) -->
    <ellipse cx="310" cy="170" rx="68" ry="34" fill="rgba(20,24,38,0.06)"/>
  </g>

  <!-- Triggers (top, drawn behind shoulders) -->
  <g filter="url(#xiBtnShadow)">
    <g id="src-btn-l2" class="src-btn">
      <rect x="100" y="40" width="84" height="22" rx="10"/>
      <text x="142" y="55" text-anchor="middle">LT</text>
    </g>
    <g id="src-btn-r2" class="src-btn">
      <rect x="436" y="40" width="84" height="22" rx="10"/>
      <text x="478" y="55" text-anchor="middle">RT</text>
    </g>

    <!-- Shoulders -->
    <g id="src-btn-l" class="src-btn">
      <rect x="92" y="68" width="100" height="22" rx="10"/>
      <text x="142" y="83" text-anchor="middle">LB</text>
    </g>
    <g id="src-btn-r" class="src-btn">
      <rect x="428" y="68" width="100" height="22" rx="10"/>
      <text x="478" y="83" text-anchor="middle">RB</text>
    </g>
  </g>

  <!-- D-pad recess -->
  <circle cx="171" cy="216" r="40" fill="url(#xiRecess)"/>
  <g class="dpad" filter="url(#xiBtnShadow)">
    <g id="src-btn-up" class="src-btn dpad">
      <rect x="160" y="180" width="22" height="24" rx="3"/>
    </g>
    <g id="src-btn-down" class="src-btn dpad">
      <rect x="160" y="228" width="22" height="24" rx="3"/>
    </g>
    <g id="src-btn-left" class="src-btn dpad">
      <rect x="136" y="204" width="24" height="22" rx="3"/>
    </g>
    <g id="src-btn-right" class="src-btn dpad">
      <rect x="182" y="204" width="24" height="22" rx="3"/>
    </g>
    <!-- Centre cap -->
    <circle cx="171" cy="216" r="6" fill="rgba(20,24,38,0.55)"/>
  </g>

  <!-- Left stick (upper-left of centre, like 8BitDo Ultimate) -->
  <g id="src-btn-l3" class="src-btn stick">
    <circle cx="240" cy="158" r="34" class="stick-base" fill="url(#xiStickBase)"/>
    <circle cx="240" cy="158" r="22" class="stick-knob" id="src-l3-knob" fill="url(#xiStickKnob)"/>
    <ellipse cx="234" cy="151" rx="9" ry="5" fill="rgba(255,255,255,0.18)"/>
  </g>

  <!-- Right stick (lower-right of centre) -->
  <g id="src-btn-r3" class="src-btn stick">
    <circle cx="380" cy="228" r="34" class="stick-base" fill="url(#xiStickBase)"/>
    <circle cx="380" cy="228" r="22" class="stick-knob" id="src-r3-knob" fill="url(#xiStickKnob)"/>
    <ellipse cx="374" cy="221" rx="9" ry="5" fill="rgba(255,255,255,0.18)"/>
  </g>

  <!-- Select / Start (View / Menu) on centre console -->
  <g filter="url(#xiBtnShadow)">
    <g id="src-btn-select" class="src-btn">
      <rect x="278" y="160" width="26" height="14" rx="7"/>
      <text x="291" y="170" text-anchor="middle" class="tiny">View</text>
    </g>
    <g id="src-btn-start" class="src-btn">
      <rect x="316" y="160" width="26" height="14" rx="7"/>
      <text x="329" y="170" text-anchor="middle" class="tiny">Menu</text>
    </g>
  </g>

  <!-- Face buttons (right cluster diamond) -->
  <g filter="url(#xiBtnShadow)">
    <g id="src-btn-y" class="src-btn face yellow">
      <circle cx="478" cy="132" r="20"/>
      <text x="478" y="138" text-anchor="middle">Y</text>
    </g>
    <g id="src-btn-a" class="src-btn face green">
      <circle cx="478" cy="192" r="20"/>
      <text x="478" y="198" text-anchor="middle">A</text>
    </g>
    <g id="src-btn-x" class="src-btn face blue">
      <circle cx="448" cy="162" r="20"/>
      <text x="448" y="168" text-anchor="middle">X</text>
    </g>
    <g id="src-btn-b" class="src-btn face red">
      <circle cx="508" cy="162" r="20"/>
      <text x="508" y="168" text-anchor="middle">B</text>
    </g>
  </g>

  <!-- Title (sits below the extended grips at y=342) -->
  <text x="310" y="356" text-anchor="middle" class="ctrl-caption">XInput / Xbox controller</text>
</svg>
`;

const TGT_CD32_PAD = `
<svg viewBox="0 0 620 300" xmlns="http://www.w3.org/2000/svg" class="ctrl-svg" aria-label="Amiga CD32 control pad">
  <defs>
    <!-- CD32 black plastic body — light-theme readable mid-grey gradient -->
    <linearGradient id="cd32body" x1="0.3" y1="0" x2="0.7" y2="1">
      <stop offset="0%"   stop-color="#5b6371"/>
      <stop offset="55%"  stop-color="#3a4049"/>
      <stop offset="100%" stop-color="#1c2128"/>
    </linearGradient>
    <linearGradient id="cd32hi" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%"  stop-color="rgba(255,255,255,0.30)"/>
      <stop offset="55%" stop-color="rgba(255,255,255,0)"/>
    </linearGradient>
    <linearGradient id="cd32lo" x1="0" y1="1" x2="0" y2="0">
      <stop offset="0%"  stop-color="rgba(0,0,0,0.35)"/>
      <stop offset="60%" stop-color="rgba(0,0,0,0)"/>
    </linearGradient>
    <radialGradient id="cd32dpadDish" cx="0.5" cy="0.4" r="0.7">
      <stop offset="0%"  stop-color="#1a1d24"/>
      <stop offset="100%" stop-color="#2a2f38"/>
    </radialGradient>

    <filter id="cd32BodyShadow" x="-10%" y="-10%" width="120%" height="140%">
      <feGaussianBlur stdDeviation="5" in="SourceAlpha"/>
      <feOffset dy="7" result="off"/>
      <feComponentTransfer><feFuncA type="linear" slope="0.32"/></feComponentTransfer>
      <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="cd32BtnShadow" x="-30%" y="-30%" width="160%" height="170%">
      <feGaussianBlur stdDeviation="1.5" in="SourceAlpha"/>
      <feOffset dy="2" result="off"/>
      <feComponentTransfer><feFuncA type="linear" slope="0.40"/></feComponentTransfer>
      <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>

  <!-- Body — characteristic CD32 wing-curve. Higher in the middle,
       wings drop on the sides where the d-pad and face cluster sit. -->
  <g filter="url(#cd32BodyShadow)">
    <path d="M 78 168
             Q 80 110 140 100
             L 195 92
             Q 235 88 240 132
             L 240 188
             Q 240 224 205 232
             L 145 240
             Q 78 244 78 200 Z
             M 380 132
             Q 385 88 425 92
             L 480 100
             Q 540 110 542 168
             L 542 200
             Q 542 244 475 240
             L 415 232
             Q 380 224 380 188 Z"
          fill="url(#cd32body)" stroke="rgba(0,0,0,0.45)" stroke-width="1.25"/>
    <!-- Centre bar — connects the two wings. Houses the AMIGA CD32 logo
         and the play/reverse mid-buttons. -->
    <path d="M 220 140
             L 400 140
             Q 412 140 412 152
             L 412 198
             Q 412 212 400 212
             L 220 212
             Q 208 212 208 198
             L 208 152
             Q 208 140 220 140 Z"
          fill="url(#cd32body)" stroke="rgba(0,0,0,0.45)" stroke-width="1.25"/>

    <!-- Top sheen on both wings + centre -->
    <path d="M 86 168 Q 90 112 145 104 L 195 96 Q 232 92 236 130 L 236 140 Q 160 130 86 168 Z"
          fill="url(#cd32hi)"/>
    <path d="M 384 130 Q 388 92 425 96 L 478 104 Q 533 112 538 168 Q 460 130 384 140 Z"
          fill="url(#cd32hi)"/>
    <path d="M 220 144 L 400 144 Q 408 144 408 152 L 408 162 Q 310 156 212 162 L 212 152 Q 212 144 220 144 Z"
          fill="url(#cd32hi)"/>

    <!-- Subtle bottom shading -->
    <path d="M 78 200 Q 78 244 145 240 L 205 232 Q 240 224 240 188 L 240 200 Q 235 230 200 234 L 145 240 Q 88 244 84 220 Z"
          fill="url(#cd32lo)" opacity="0.6"/>

    <!-- AMIGA CD32 wordmark -->
    <text x="270" y="180" font-family="-apple-system, 'Segoe UI', system-ui, sans-serif"
          font-size="14" font-weight="800" letter-spacing="0.06em"
          fill="#c44a2c" opacity="0.92">AMIGA</text>
    <text x="318" y="180" font-family="-apple-system, 'Segoe UI', system-ui, sans-serif"
          font-size="14" font-weight="800" letter-spacing="0.04em"
          fill="rgba(255,255,255,0.85)">CD</text>
    <text x="343" y="184" font-family="-apple-system, 'Segoe UI', system-ui, sans-serif"
          font-size="9" font-weight="700"
          fill="rgba(255,255,255,0.85)">32</text>
  </g>

  <!-- Top transport buttons: REW (top of left wing), FWD (top of right wing) -->
  <g filter="url(#cd32BtnShadow)">
    <g id="tgt-btn-rewind" class="tgt-btn">
      <rect x="116" y="74" width="60" height="20" rx="8"/>
      <text x="146" y="87" text-anchor="middle" class="tiny">REW · LB</text>
    </g>
    <g id="tgt-btn-forward" class="tgt-btn">
      <rect x="444" y="74" width="60" height="20" rx="8"/>
      <text x="474" y="87" text-anchor="middle" class="tiny">FWD · RB</text>
    </g>
  </g>

  <!-- Mid-bar pause/play strip: REVERSE (left of centre), PLAY (right) -->
  <g filter="url(#cd32BtnShadow)">
    <g id="tgt-btn-reverse" class="tgt-btn">
      <rect x="246" y="194" width="64" height="14" rx="6"/>
      <text x="278" y="204" text-anchor="middle" class="tiny">REV · Sel</text>
    </g>
    <g id="tgt-btn-play" class="tgt-btn">
      <rect x="318" y="194" width="64" height="14" rx="6"/>
      <text x="350" y="204" text-anchor="middle" class="tiny">PLAY · Sta</text>
    </g>
  </g>

  <!-- D-pad: lives in a small dish on the upper-left wing -->
  <circle cx="146" cy="148" r="34" fill="url(#cd32dpadDish)" stroke="rgba(0,0,0,0.5)" stroke-width="1"/>
  <g class="dpad" filter="url(#cd32BtnShadow)">
    <g id="tgt-btn-up" class="tgt-btn dpad">
      <rect x="136" y="118" width="20" height="22" rx="3"/>
    </g>
    <g id="tgt-btn-down" class="tgt-btn dpad">
      <rect x="136" y="156" width="20" height="22" rx="3"/>
    </g>
    <g id="tgt-btn-left" class="tgt-btn dpad">
      <rect x="116" y="138" width="22" height="20" rx="3"/>
    </g>
    <g id="tgt-btn-right" class="tgt-btn dpad">
      <rect x="154" y="138" width="22" height="20" rx="3"/>
    </g>
    <circle cx="146" cy="148" r="5" fill="rgba(255,255,255,0.25)"/>
  </g>

  <!-- Coloured face buttons on the right wing.
       Photo layout: green top-left, yellow top-right, red bottom-left,
       blue bottom-right. Matches the IDs encoding A=blue, B=red,
       X=green, Y=yellow. -->
  <g filter="url(#cd32BtnShadow)">
    <g id="tgt-btn-green" class="tgt-btn face green">
      <circle cx="438" cy="132" r="17"/>
      <text x="438" y="138" text-anchor="middle">X</text>
    </g>
    <g id="tgt-btn-yellow" class="tgt-btn face yellow">
      <circle cx="488" cy="132" r="17"/>
      <text x="488" y="138" text-anchor="middle">Y</text>
    </g>
    <g id="tgt-btn-red" class="tgt-btn face red">
      <circle cx="438" cy="180" r="17"/>
      <text x="438" y="186" text-anchor="middle">B</text>
    </g>
    <g id="tgt-btn-blue" class="tgt-btn face blue">
      <circle cx="488" cy="180" r="17"/>
      <text x="488" y="186" text-anchor="middle">A</text>
    </g>
  </g>

  <text x="310" y="280" text-anchor="middle" class="ctrl-caption">Amiga CD32 Pad — 7 buttons</text>
</svg>
`;

const TGT_JOYSTICK_1BTN = `
<svg viewBox="0 0 620 300" xmlns="http://www.w3.org/2000/svg" class="ctrl-svg" aria-label="Competition Pro — single-button joystick">
  <defs>
    <!-- Black textured base -->
    <linearGradient id="cpBase" x1="0.5" y1="0" x2="0.5" y2="1">
      <stop offset="0%"   stop-color="#2c313a"/>
      <stop offset="55%"  stop-color="#171b22"/>
      <stop offset="100%" stop-color="#0a0d11"/>
    </linearGradient>
    <linearGradient id="cpBaseHi" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%"  stop-color="rgba(255,255,255,0.35)"/>
      <stop offset="50%" stop-color="rgba(255,255,255,0)"/>
    </linearGradient>
    <linearGradient id="cpBaseLo" x1="0" y1="1" x2="0" y2="0">
      <stop offset="0%"  stop-color="rgba(0,0,0,0.55)"/>
      <stop offset="60%" stop-color="rgba(0,0,0,0)"/>
    </linearGradient>

    <!-- Cream stripe along the top edge -->
    <linearGradient id="cpStripe" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%"   stop-color="#f6efd9"/>
      <stop offset="60%"  stop-color="#e8dfbe"/>
      <stop offset="100%" stop-color="#bdb389"/>
    </linearGradient>

    <!-- Stick black hat / collar -->
    <radialGradient id="cpHat" cx="0.5" cy="0.4" r="0.7">
      <stop offset="0%"   stop-color="#3a4049"/>
      <stop offset="60%"  stop-color="#1a1e24"/>
      <stop offset="100%" stop-color="#0a0d11"/>
    </radialGradient>

    <!-- Red shaft (pencil-thin column) -->
    <linearGradient id="cpShaft" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%"   stop-color="#7d1a14"/>
      <stop offset="50%"  stop-color="#d43d31"/>
      <stop offset="100%" stop-color="#7d1a14"/>
    </linearGradient>

    <!-- Big red ball top -->
    <radialGradient id="cpBall" cx="0.32" cy="0.28" r="0.85">
      <stop offset="0%"   stop-color="#ff8a7a"/>
      <stop offset="35%"  stop-color="#e8453a"/>
      <stop offset="80%"  stop-color="#a01f17"/>
      <stop offset="100%" stop-color="#5e0f08"/>
    </radialGradient>

    <!-- Red dome fire button -->
    <radialGradient id="cpFire" cx="0.35" cy="0.32" r="0.85">
      <stop offset="0%"   stop-color="#ff7a6a"/>
      <stop offset="50%"  stop-color="#d43a2e"/>
      <stop offset="100%" stop-color="#7a1810"/>
    </radialGradient>

    <filter id="cpBodyShadow" x="-10%" y="-15%" width="120%" height="135%">
      <feGaussianBlur stdDeviation="5" in="SourceAlpha"/>
      <feOffset dy="7" result="off"/>
      <feComponentTransfer><feFuncA type="linear" slope="0.40"/></feComponentTransfer>
      <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="cpBtnShadow" x="-30%" y="-30%" width="160%" height="170%">
      <feGaussianBlur stdDeviation="2" in="SourceAlpha"/>
      <feOffset dy="3" result="off"/>
      <feComponentTransfer><feFuncA type="linear" slope="0.45"/></feComponentTransfer>
      <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>

  <!-- Square base with rounded corners + cream stripe along top edge -->
  <g filter="url(#cpBodyShadow)">
    <!-- Main body -->
    <path d="M 165 138
             Q 165 122 181 122
             L 439 122
             Q 455 122 455 138
             L 455 254
             Q 455 270 439 270
             L 181 270
             Q 165 270 165 254 Z"
          fill="url(#cpBase)" stroke="rgba(0,0,0,0.6)" stroke-width="1.5"/>
    <!-- Cream stripe (a thin band along the top, like the photo) -->
    <path d="M 165 138
             Q 165 122 181 122
             L 439 122
             Q 455 122 455 138
             L 455 152
             L 165 152 Z"
          fill="url(#cpStripe)" stroke="rgba(0,0,0,0.35)" stroke-width="0.75"/>
    <!-- Top sheen on the black portion -->
    <path d="M 165 152 L 455 152 L 455 178 Q 310 168 165 178 Z"
          fill="url(#cpBaseHi)" opacity="0.55"/>
    <!-- Bottom shading -->
    <path d="M 165 240 Q 310 250 455 240 L 455 254 Q 455 270 439 270 L 181 270 Q 165 270 165 254 Z"
          fill="url(#cpBaseLo)" opacity="0.7"/>

    <!-- Recessed dish for stick (where the rubber hat sits) -->
    <ellipse cx="320" cy="206" rx="60" ry="32" fill="rgba(0,0,0,0.35)"/>
    <ellipse cx="320" cy="204" rx="56" ry="28" fill="#0d1117" stroke="rgba(255,255,255,0.05)" stroke-width="1"/>

    <!-- Competition Pro wordmark on the cream stripe -->
    <text x="178" y="143" font-family="-apple-system, 'Segoe UI', system-ui, sans-serif"
          font-size="11" font-weight="800" letter-spacing="0.10em"
          fill="#1f1a0d">COMPETITION</text>
    <text x="269" y="143" font-family="-apple-system, 'Segoe UI', system-ui, sans-serif"
          font-size="11" font-weight="800" letter-spacing="0.10em"
          fill="#9c2018">PRO</text>
  </g>

  <!-- Direction indicators around the stick base (light up via .pressed) -->
  <g class="dpad">
    <g id="tgt-btn-up" class="tgt-btn dpad">
      <polygon points="320,162 308,180 332,180"/>
    </g>
    <g id="tgt-btn-down" class="tgt-btn dpad">
      <polygon points="320,250 308,232 332,232"/>
    </g>
    <g id="tgt-btn-left" class="tgt-btn dpad">
      <polygon points="248,206 268,196 268,216"/>
    </g>
    <g id="tgt-btn-right" class="tgt-btn dpad">
      <polygon points="392,206 372,196 372,216"/>
    </g>
  </g>

  <!-- Stick column: black collar / hat at base, red shaft rising up -->
  <g filter="url(#cpBtnShadow)">
    <!-- Hat / rubber collar -->
    <ellipse cx="320" cy="200" rx="42" ry="20" fill="url(#cpHat)" stroke="rgba(0,0,0,0.6)" stroke-width="1.25"/>
    <ellipse cx="320" cy="196" rx="32" ry="13" fill="#0a0d11" stroke="rgba(255,255,255,0.05)" stroke-width="0.75"/>
    <!-- Red shaft -->
    <rect x="308" y="86" width="24" height="118" rx="6" fill="url(#cpShaft)" stroke="rgba(0,0,0,0.6)" stroke-width="1"/>
    <!-- Highlight on shaft -->
    <rect x="312" y="90" width="5" height="110" rx="2" fill="rgba(255,255,255,0.30)"/>
  </g>

  <!-- Big red ball top — the iconic Competition Pro feature -->
  <g filter="url(#cpBtnShadow)">
    <circle cx="320" cy="64" r="36" fill="url(#cpBall)" stroke="rgba(0,0,0,0.55)" stroke-width="1.25"/>
    <!-- Specular highlight (upper-left light source) -->
    <ellipse cx="306" cy="50" rx="14" ry="9" fill="rgba(255,255,255,0.55)"/>
    <ellipse cx="302" cy="46" rx="6" ry="3" fill="rgba(255,255,255,0.85)"/>
  </g>

  <!-- FIRE button: red dome on the base, photo-accurate placement (front-left of stick) -->
  <g id="tgt-btn-fire" class="tgt-btn face red">
    <!-- The face.red CSS rule fills <circle> elements; we wrap a halo
         and label OUTSIDE this group so they aren't recoloured on press -->
    <circle cx="206" cy="206" r="20"/>
  </g>
  <!-- Decorative halo + label (outside the .tgt-btn group so CSS
       doesn't repaint them; purely visual base under the button) -->
  <circle cx="206" cy="206" r="26" fill="#0d1117" stroke="rgba(0,0,0,0.6)"
          stroke-width="1" opacity="0.85" pointer-events="none"/>
  <!-- Re-render the dome highlight on top so the button reads as a 3D dome -->
  <ellipse cx="200" cy="198" rx="9" ry="5" fill="rgba(255,255,255,0.45)" pointer-events="none"/>
  <text x="206" y="246" text-anchor="middle"
        font-family="-apple-system, 'Segoe UI', system-ui, sans-serif"
        font-size="10" font-weight="700" letter-spacing="0.18em"
        fill="#e8dfbe">FIRE</text>

  <text x="310" y="290" text-anchor="middle" class="ctrl-caption">Competition Pro — 1-button joystick</text>
</svg>
`;

const TGT_COLECOVISION_PAD = `
<svg viewBox="0 0 620 320" xmlns="http://www.w3.org/2000/svg" class="ctrl-svg" aria-label="ColecoVision Standard Controller">
  <defs>
    <!-- Black plastic body, lit from upper-left.
         Slightly lighter at top, deeper black at bottom. -->
    <linearGradient id="cvBody" x1="0.3" y1="0" x2="0.7" y2="1">
      <stop offset="0%"   stop-color="#3a3f48"/>
      <stop offset="55%"  stop-color="#1c2026"/>
      <stop offset="100%" stop-color="#0a0d11"/>
    </linearGradient>
    <linearGradient id="cvBodyHi" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%"  stop-color="rgba(255,255,255,0.32)"/>
      <stop offset="55%" stop-color="rgba(255,255,255,0)"/>
    </linearGradient>
    <linearGradient id="cvBodyLo" x1="0" y1="1" x2="0" y2="0">
      <stop offset="0%"  stop-color="rgba(0,0,0,0.55)"/>
      <stop offset="60%" stop-color="rgba(0,0,0,0)"/>
    </linearGradient>

    <!-- Subtle inset under the d-pad cluster -->
    <radialGradient id="cvDpadDish" cx="0.5" cy="0.45" r="0.7">
      <stop offset="0%"  stop-color="#13161b"/>
      <stop offset="100%" stop-color="#262a31"/>
    </radialGradient>

    <!-- Red action-button dome (chunky, glossy). Fill is decorative —
         the actual press-state circle inside .tgt-btn.face.red is
         repainted by CSS. We layer a halo + highlight on top. -->
    <radialGradient id="cvFireDome" cx="0.35" cy="0.32" r="0.85">
      <stop offset="0%"   stop-color="#ff7a6a"/>
      <stop offset="50%"  stop-color="#d43a2e"/>
      <stop offset="100%" stop-color="#7a1810"/>
    </radialGradient>

    <filter id="cvBodyShadow" x="-10%" y="-10%" width="120%" height="135%">
      <feGaussianBlur stdDeviation="5" in="SourceAlpha"/>
      <feOffset dy="7" result="off"/>
      <feComponentTransfer><feFuncA type="linear" slope="0.32"/></feComponentTransfer>
      <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="cvBtnShadow" x="-30%" y="-30%" width="160%" height="170%">
      <feGaussianBlur stdDeviation="1.75" in="SourceAlpha"/>
      <feOffset dy="2.5" result="off"/>
      <feComponentTransfer><feFuncA type="linear" slope="0.42"/></feComponentTransfer>
      <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>

  <!-- Body — rectangular black slab, gently rounded corners. No cable. -->
  <g filter="url(#cvBodyShadow)">
    <rect x="56" y="60" width="508" height="200" rx="14" ry="14"
          fill="url(#cvBody)" stroke="rgba(0,0,0,0.6)" stroke-width="1.5"/>
    <!-- Top sheen -->
    <rect x="60" y="64" width="500" height="60" rx="12" ry="12"
          fill="url(#cvBodyHi)" opacity="0.85"/>
    <!-- Bottom shading -->
    <rect x="60" y="200" width="500" height="56" rx="12" ry="12"
          fill="url(#cvBodyLo)" opacity="0.7"/>
    <!-- Top bezel (small recessed strip near the very top) -->
    <rect x="80" y="78" width="460" height="14" rx="3" ry="3"
          fill="rgba(0,0,0,0.55)" stroke="rgba(255,255,255,0.04)" stroke-width="0.75"/>
  </g>

  <!-- Rainbow stripes — sit just below the bezel, left side of body,
       leaving room for the wordmark on the right. -->
  <g opacity="0.95">
    <rect x="92"  y="100" width="200" height="3" fill="#9b5cff"/>
    <rect x="92"  y="104" width="200" height="3" fill="#5c8eff"/>
    <rect x="92"  y="108" width="200" height="3" fill="#5cd6ff"/>
    <rect x="92"  y="112" width="200" height="3" fill="#5cff8e"/>
    <rect x="92"  y="116" width="200" height="3" fill="#ffeb3b"/>
    <rect x="92"  y="120" width="200" height="3" fill="#ff9c3b"/>
    <rect x="92"  y="124" width="200" height="3" fill="#ff5c5c"/>
  </g>

  <!-- Two-line ColecoVision wordmark, rainbow letters.
       Lower-right area of the body. -->
  <g font-family="-apple-system, 'Segoe UI', system-ui, sans-serif"
     font-weight="900" letter-spacing="0.06em" font-size="14">
    <!-- COLECO -->
    <text x="404" y="226" fill="#9b5cff">C</text>
    <text x="418" y="226" fill="#5c8eff">O</text>
    <text x="434" y="226" fill="#5cd6ff">L</text>
    <text x="446" y="226" fill="#5cff8e">E</text>
    <text x="460" y="226" fill="#ffeb3b">C</text>
    <text x="474" y="226" fill="#ff9c3b">O</text>
    <!-- VISION -->
    <text x="404" y="244" fill="#5c8eff">V</text>
    <text x="418" y="244" fill="#5cd6ff">I</text>
    <text x="426" y="244" fill="#5cff8e">S</text>
    <text x="440" y="244" fill="#ffeb3b">I</text>
    <text x="448" y="244" fill="#ff9c3b">O</text>
    <text x="464" y="244" fill="#ff5c5c">N</text>
  </g>

  <!-- D-pad cluster: black plus-shape, faint inset dish behind it.
       Center pivot dot. Photo's dashed reference circle intentionally omitted. -->
  <circle cx="138" cy="180" r="50" fill="url(#cvDpadDish)"
          stroke="rgba(0,0,0,0.6)" stroke-width="1"/>
  <g class="dpad" filter="url(#cvBtnShadow)">
    <g id="tgt-btn-up" class="tgt-btn dpad">
      <rect x="126" y="142" width="24" height="28" rx="3"/>
    </g>
    <g id="tgt-btn-down" class="tgt-btn dpad">
      <rect x="126" y="190" width="24" height="28" rx="3"/>
    </g>
    <g id="tgt-btn-left" class="tgt-btn dpad">
      <rect x="100" y="168" width="28" height="24" rx="3"/>
    </g>
    <g id="tgt-btn-right" class="tgt-btn dpad">
      <rect x="148" y="168" width="28" height="24" rx="3"/>
    </g>
    <!-- Centre pivot -->
    <circle cx="138" cy="180" r="5.5" fill="rgba(255,255,255,0.22)"
            stroke="rgba(0,0,0,0.55)" stroke-width="0.75"/>
  </g>

  <!-- Two slim keypad-style toggle buttons in the middle.
       Small labels above each (small "tiny" text). -->
  <text x="282" y="158" text-anchor="middle" class="tiny"
        fill="rgba(255,255,255,0.65)">*</text>
  <text x="346" y="158" text-anchor="middle" class="tiny"
        fill="rgba(255,255,255,0.65)">#</text>
  <g filter="url(#cvBtnShadow)">
    <g id="tgt-btn-star" class="tgt-btn">
      <rect x="258" y="164" width="48" height="14" rx="5"/>
    </g>
    <g id="tgt-btn-pound" class="tgt-btn">
      <rect x="322" y="164" width="48" height="14" rx="5"/>
    </g>
  </g>

  <!-- Two round red action buttons on the right.
       Each has a small white inset rectangle with the digit (1, 2)
       above the dome, photo-accurate. The dome itself uses the
       .tgt-btn.face.red CSS hook so it lights up on press. -->
  <!-- Button "1" — primary fire (left red, photo-accurate placement) -->
  <g filter="url(#cvBtnShadow)">
    <rect x="416" y="146" width="22" height="14" rx="2"
          fill="#f3eee0" stroke="rgba(0,0,0,0.55)" stroke-width="0.75"/>
    <text x="427" y="157" text-anchor="middle"
          font-family="-apple-system, 'Segoe UI', system-ui, sans-serif"
          font-size="10" font-weight="800" fill="#1a1d24">1</text>
  </g>
  <g id="tgt-btn-fire" class="tgt-btn face red">
    <circle cx="427" cy="186" r="20"/>
  </g>
  <!-- Decorative halo + dome highlight (outside .tgt-btn so they don't repaint) -->
  <circle cx="427" cy="186" r="26" fill="#0d1117"
          stroke="rgba(0,0,0,0.6)" stroke-width="1" opacity="0.85"
          pointer-events="none"/>
  <ellipse cx="421" cy="178" rx="9" ry="5"
           fill="rgba(255,255,255,0.45)" pointer-events="none"/>

  <!-- Button "2" — secondary fire (right red) -->
  <g filter="url(#cvBtnShadow)">
    <rect x="486" y="146" width="22" height="14" rx="2"
          fill="#f3eee0" stroke="rgba(0,0,0,0.55)" stroke-width="0.75"/>
    <text x="497" y="157" text-anchor="middle"
          font-family="-apple-system, 'Segoe UI', system-ui, sans-serif"
          font-size="10" font-weight="800" fill="#1a1d24">2</text>
  </g>
  <g id="tgt-btn-fire2" class="tgt-btn face red">
    <circle cx="497" cy="186" r="20"/>
  </g>
  <circle cx="497" cy="186" r="26" fill="#0d1117"
          stroke="rgba(0,0,0,0.6)" stroke-width="1" opacity="0.85"
          pointer-events="none"/>
  <ellipse cx="491" cy="178" rx="9" ry="5"
           fill="rgba(255,255,255,0.45)" pointer-events="none"/>

  <text x="310" y="300" text-anchor="middle" class="ctrl-caption">ColecoVision Standard Controller</text>
</svg>
`;

// Map the source pad's RetroPad button name → target SVG button id, per system.
// `null` means there's no target equivalent (the physical button doesn't drive
// anything on the target controller — usable for keystroke remap instead).
const TARGET_MAPPINGS = {
  amigacd32: {
    a: 'blue', b: 'red', x: 'green', y: 'yellow',
    l: 'rewind', r: 'forward',
    select: 'reverse', start: 'play',
    up: 'up', down: 'down', left: 'left', right: 'right',
    l2: null, r2: null, l3: null, r3: null,
  },
  c64: {
    a: 'fire', b: 'fire',
    up: 'up', down: 'down', left: 'left', right: 'right',
    l: null, r: null, l2: null, r2: null, l3: null, r3: null,
    x: null, y: null, select: null, start: null,
  },
  amiga500: {
    a: 'fire', b: 'fire',
    up: 'up', down: 'down', left: 'left', right: 'right',
    l: null, r: null, l2: null, r2: null, l3: null, r3: null,
    x: null, y: null, select: null, start: null,
  },
  amiga1200: {
    a: 'fire', b: 'fire',
    up: 'up', down: 'down', left: 'left', right: 'right',
    l: null, r: null, l2: null, r2: null, l3: null, r3: null,
    x: null, y: null, select: null, start: null,
  },
  colecovision: {
    // RetroPad → ColecoVision per blueMSX libretro core defaults
    // (CrocoDS / FBNeo Coleco share the same convention).
    // ColecoVision pad has 2 fire buttons + a 12-key keypad. We expose
    // fire 1, fire 2, and the two most-used keypad keys (* and #).
    b: 'fire',     // RetroPad B = Fire 1 (left red button) — primary
    a: 'fire2',    // RetroPad A = Fire 2 (right red button) — secondary
    y: 'star',     // RetroPad Y = keypad *
    x: 'pound',    // RetroPad X = keypad #
    up: 'up', down: 'down', left: 'left', right: 'right',
    l: null, r: null, l2: null, r2: null, l3: null, r3: null,
    select: null, start: null,
  },
};

const TARGET_SVGS = {
  cd32_pad:        TGT_CD32_PAD,
  joystick_1btn:   TGT_JOYSTICK_1BTN,
  colecovision_pad: TGT_COLECOVISION_PAD,
};

// ============================================================
// Generic target SVG generator
// ------------------------------------------------------------
// For systems we don't have a curated SVG for, render a clean
// schematic from a system-shape descriptor. Descriptor schema:
//   {
//     face: { layout: 'diamond'|'row'|'grid'|'single'|'none',
//             count: 0..6, labels?: [], colors?: [] },
//     dpad:      true|false,
//     sticks:    0..2,
//     shoulders: 0|2|4,         // 2 = L+R; 4 = + L2+R2
//     start:     true|false,
//     select:    true|false,
//     label:     "Display name",
//   }
//
// Output IDs stay stable so app.js's existing binding wiring keeps
// working: `tgt-btn-1` … `tgt-btn-N` for face buttons,
// `tgt-btn-up/down/left/right` for D-pad, `tgt-btn-l/r/l2/r2` for
// shoulders, `tgt-btn-start/select` for system buttons.
// ============================================================

function generateTargetSvg(layout) {
  if (!layout) return '';
  const W = 620, H = 280;
  const face = layout.face || { layout: 'none', count: 0 };
  const labels = face.labels || [];
  const dpad = layout.dpad !== false;
  const sticks = Number(layout.sticks || 0);
  const shoulders = Number(layout.shoulders || 0);
  const startBtn = layout.start !== false;
  const selectBtn = layout.select !== false;
  const labelText = layout.label || '';

  const out = [];
  out.push(`<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" class="ctrl-svg" aria-label="${escapeAttr(labelText || 'Target controller')}">`);
  out.push(`<defs>
    <linearGradient id="genBody" x1="0.5" y1="0" x2="0.5" y2="1">
      <stop offset="0%"  stop-color="#5a5a5a"/>
      <stop offset="55%" stop-color="#333"/>
      <stop offset="100%" stop-color="#1a1a1a"/>
    </linearGradient>
    <linearGradient id="genHi" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%"  stop-color="rgba(255,255,255,0.12)"/>
      <stop offset="50%" stop-color="rgba(255,255,255,0)"/>
    </linearGradient>
    <filter id="genShadow" x="-10%" y="-10%" width="120%" height="130%">
      <feGaussianBlur stdDeviation="3" in="SourceAlpha"/>
      <feOffset dy="4" result="off"/>
      <feComponentTransfer><feFuncA type="linear" slope="0.5"/></feComponentTransfer>
      <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>`);

  // Body
  out.push(`<g filter="url(#genShadow)">
    <path d="M 80 90 Q 80 50 130 50 L 490 50 Q 540 50 540 90 L 540 200 Q 540 240 490 240 L 130 240 Q 80 240 80 200 Z"
          fill="url(#genBody)" stroke="#000" stroke-width="2"/>
    <path d="M 90 80 Q 90 56 135 56 L 485 56 Q 530 56 530 80 Q 310 70 90 80 Z"
          fill="url(#genHi)" opacity="0.85"/>
  </g>`);

  // Shoulders (top edge) — RetroPad: L=10, R=11, L2=12, R2=13
  if (shoulders >= 2) {
    out.push(`<g id="tgt-btn-l" class="tgt-btn" data-retropad="10">
      <rect x="120" y="32" width="60" height="14" rx="6"/>
      <text x="150" y="42" text-anchor="middle" class="tiny">L</text>
    </g>`);
    out.push(`<g id="tgt-btn-r" class="tgt-btn" data-retropad="11">
      <rect x="440" y="32" width="60" height="14" rx="6"/>
      <text x="470" y="42" text-anchor="middle" class="tiny">R</text>
    </g>`);
  }
  if (shoulders >= 4) {
    out.push(`<g id="tgt-btn-l2" class="tgt-btn" data-retropad="12">
      <rect x="120" y="14" width="60" height="14" rx="6"/>
      <text x="150" y="24" text-anchor="middle" class="tiny">L2</text>
    </g>`);
    out.push(`<g id="tgt-btn-r2" class="tgt-btn" data-retropad="13">
      <rect x="440" y="14" width="60" height="14" rx="6"/>
      <text x="470" y="24" text-anchor="middle" class="tiny">R2</text>
    </g>`);
  }

  // D-pad (left cluster) — RetroPad: up=4, down=5, left=6, right=7
  if (dpad) {
    out.push(`<g class="dpad">
      <g id="tgt-btn-up" class="tgt-btn dpad" data-retropad="4"><rect x="170" y="120" width="22" height="22" rx="3"/></g>
      <g id="tgt-btn-down" class="tgt-btn dpad" data-retropad="5"><rect x="170" y="164" width="22" height="22" rx="3"/></g>
      <g id="tgt-btn-left" class="tgt-btn dpad" data-retropad="6"><rect x="148" y="142" width="22" height="22" rx="3"/></g>
      <g id="tgt-btn-right" class="tgt-btn dpad" data-retropad="7"><rect x="192" y="142" width="22" height="22" rx="3"/></g>
      <rect x="170" y="142" width="22" height="22" fill="#0d1117"/>
    </g>`);
  }

  // Stick(s)
  if (sticks >= 1) {
    out.push(`<g id="tgt-btn-l3" class="tgt-btn stick">
      <circle cx="${dpad ? 248 : 200}" cy="200" r="20" class="stick-base" fill="#1c2128"/>
      <circle cx="${dpad ? 248 : 200}" cy="200" r="13" class="stick-knob" fill="#2a2f36"/>
    </g>`);
  }
  if (sticks >= 2) {
    out.push(`<g id="tgt-btn-r3" class="tgt-btn stick">
      <circle cx="380" cy="200" r="20" class="stick-base" fill="#1c2128"/>
      <circle cx="380" cy="200" r="13" class="stick-knob" fill="#2a2f36"/>
    </g>`);
  }

  // Select / Start (centre pills) — RetroPad: select=2, start=3
  if (selectBtn) {
    out.push(`<g id="tgt-btn-select" class="tgt-btn" data-retropad="2">
      <rect x="252" y="92" width="46" height="13" rx="6"/>
      <text x="275" y="102" text-anchor="middle" class="tiny">Select</text>
    </g>`);
  }
  if (startBtn) {
    out.push(`<g id="tgt-btn-start" class="tgt-btn" data-retropad="3">
      <rect x="322" y="92" width="46" height="13" rx="6"/>
      <text x="345" y="102" text-anchor="middle" class="tiny">Start</text>
    </g>`);
  }

  // Face buttons (right cluster) — layout depends on count + style
  const fc = Number(face.count || 0);
  const fl = face.layout || (fc === 1 ? 'single' : fc === 2 ? 'row' : fc === 3 ? 'row' : fc === 4 ? 'diamond' : fc === 6 ? 'grid' : 'row');
  const cx = 470, cy = 145;  // centre of face cluster
  const r = 19;              // button radius
  const positions = (() => {
    switch (fl) {
      case 'single': return [{x: cx, y: cy}];
      case 'row':
        if (fc === 2) return [{x: cx-22, y: cy}, {x: cx+22, y: cy}];
        if (fc === 3) return [{x: cx-44, y: cy}, {x: cx, y: cy}, {x: cx+44, y: cy}];
        if (fc === 4) return [{x: cx-66, y: cy}, {x: cx-22, y: cy}, {x: cx+22, y: cy}, {x: cx+66, y: cy}];
        return [];
      case 'diamond':
        // Top, right, bottom, left — order matches our existing CD32 pad
        return [{x: cx, y: cy-32}, {x: cx+32, y: cy}, {x: cx, y: cy+32}, {x: cx-32, y: cy}];
      case 'grid':
        // 2 rows x 3 cols (Genesis 6-btn / Saturn / fight-stick layout)
        const dx = 30, dy = 28;
        return [
          {x: cx-dx, y: cy-dy/2}, {x: cx, y: cy-dy/2}, {x: cx+dx, y: cy-dy/2},
          {x: cx-dx, y: cy+dy/2}, {x: cx, y: cy+dy/2}, {x: cx+dx, y: cy+dy/2},
        ];
      default: return [];
    }
  })();

  // Per-position libretro RetroPad indices: prefer descriptor override,
  // fall back to layout-derived default. Embedded as data-retropad on
  // each face-button group so the click-across binder can read it.
  const retropadFace = (face.retropad && Array.isArray(face.retropad))
    ? face.retropad
    : defaultRetropadForFace(fl, fc);

  for (let i = 0; i < positions.length && i < fc; i++) {
    const p = positions[i];
    const lbl = labels[i] || String(i + 1);
    const colorClass = face.colors && face.colors[i] ? ` face ${face.colors[i]}` : '';
    const retropadIdx = retropadFace[i];
    const retropadAttr = (typeof retropadIdx === 'number') ? ` data-retropad="${retropadIdx}"` : '';
    out.push(`<g id="tgt-btn-${i + 1}" class="tgt-btn${colorClass}"${retropadAttr}>
      <circle cx="${p.x}" cy="${p.y}" r="${r}"/>
      <text x="${p.x}" y="${p.y + 5}" text-anchor="middle">${escapeAttr(lbl)}</text>
    </g>`);
  }

  // Caption
  if (labelText) {
    out.push(`<text x="${W/2}" y="${H - 8}" text-anchor="middle" class="ctrl-caption">${escapeAttr(labelText)}</text>`);
  }

  out.push(`</svg>`);
  return out.join('');
}

function escapeAttr(s) {
  return String(s).replace(/[&<>"']/g, m => (
    {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]
  ));
}

// Standard gamepad button index → our naming
const PAD_INDEX_TO_NAME = {
  0:'a', 1:'b', 2:'x', 3:'y', 4:'l', 5:'r', 6:'l2', 7:'r2',
  8:'select', 9:'start', 10:'l3', 11:'r3',
  12:'up', 13:'down', 14:'left', 15:'right'
};

// Source-button name → libretro RetroPad index (used to build .rmp keys
// like `input_remap_id_1_btn_<src>` whose value is the destination index).
const SRC_TO_RETROPAD_INDEX = {
  a: 8, b: 0, x: 9, y: 1,
  l: 10, r: 11, l2: 12, r2: 13, l3: 14, r3: 15,
  select: 2, start: 3,
  up: 4, down: 5, left: 6, right: 7,
};

// Default libretro index per face-button POSITION for the generic
// descriptor's layouts. Diamond ordering is [top, right, bottom, left]
// → matches SNES face order natively. Row/grid use a sensible
// left-to-right / top-to-bottom convention.
const FACE_DEFAULT_RETROPAD = {
  // diamond → top=X(9), right=A(8), bottom=B(0), left=Y(1)
  diamond: [9, 8, 0, 1],
  // row(2) → [B(0), A(8)] ; row(3) → +[Y(1)]; row(4) → +[X(9)]
  row2:    [0, 8],
  row3:    [0, 8, 1],
  row4:    [0, 8, 1, 9],
  // grid 2x3 (Genesis 6-btn) → top L X R / bot B A Y
  grid:    [10, 9, 11, 0, 8, 1],
  // single → fire (B)
  single:  [0],
};

function defaultRetropadForFace(layout, count) {
  if (layout === 'diamond' && count === 4) return FACE_DEFAULT_RETROPAD.diamond;
  if (layout === 'grid'    && count === 6) return FACE_DEFAULT_RETROPAD.grid;
  if (layout === 'single'  && count === 1) return FACE_DEFAULT_RETROPAD.single;
  if (layout === 'row') {
    if (count === 2) return FACE_DEFAULT_RETROPAD.row2;
    if (count === 3) return FACE_DEFAULT_RETROPAD.row3;
    if (count === 4) return FACE_DEFAULT_RETROPAD.row4;
  }
  // Fallback: sequential B, A, Y, X, L, R
  return [0, 8, 1, 9, 10, 11].slice(0, count);
}
