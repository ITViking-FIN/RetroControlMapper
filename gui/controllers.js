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

const SRC_XINPUT = `
<svg viewBox="0 0 620 360" xmlns="http://www.w3.org/2000/svg" class="ctrl-svg" aria-label="Your XInput controller">
  <defs>
    <linearGradient id="xiBody" x1="0.5" y1="0" x2="0.5" y2="1">
      <stop offset="0%"   stop-color="#444c57"/>
      <stop offset="55%"  stop-color="#2a3038"/>
      <stop offset="100%" stop-color="#161b22"/>
    </linearGradient>
    <linearGradient id="xiBodyHi" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%"  stop-color="rgba(255,255,255,0.10)"/>
      <stop offset="55%" stop-color="rgba(255,255,255,0)"/>
    </linearGradient>
    <radialGradient id="xiStickBase" cx="0.5" cy="0.4" r="0.7">
      <stop offset="0%"  stop-color="#0a0d11"/>
      <stop offset="100%" stop-color="#1c2128"/>
    </radialGradient>
    <radialGradient id="xiStickKnob" cx="0.4" cy="0.35" r="0.7">
      <stop offset="0%"  stop-color="#3a4049"/>
      <stop offset="100%" stop-color="#1a1e24"/>
    </radialGradient>
    <filter id="xiShadow" x="-10%" y="-10%" width="120%" height="130%">
      <feGaussianBlur stdDeviation="3" in="SourceAlpha"/>
      <feOffset dy="4" result="off"/>
      <feComponentTransfer><feFuncA type="linear" slope="0.5"/></feComponentTransfer>
      <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>

  <!-- Body -->
  <g filter="url(#xiShadow)">
    <path d="M 110 95
             Q 60 95 60 155
             L 60 245
             Q 60 300 130 300
             L 205 300
             Q 245 300 258 278
             Q 278 252 310 252
             Q 342 252 362 278
             Q 375 300 415 300
             L 490 300
             Q 560 300 560 245
             L 560 155
             Q 560 95 510 95
             Z"
          fill="url(#xiBody)" stroke="#000" stroke-width="2"/>
    <!-- Top sheen -->
    <path d="M 120 96
             Q 70 96 65 145
             Q 200 130 310 130
             Q 420 130 555 145
             Q 550 96 500 96 Z"
          fill="url(#xiBodyHi)" opacity="0.7"/>
  </g>

  <!-- Triggers (top, drawn behind shoulders) -->
  <g id="src-btn-l2" class="src-btn">
    <rect x="100" y="40" width="80" height="22" rx="9" />
    <text x="140" y="56" text-anchor="middle">LT</text>
  </g>
  <g id="src-btn-r2" class="src-btn">
    <rect x="440" y="40" width="80" height="22" rx="9" />
    <text x="480" y="56" text-anchor="middle">RT</text>
  </g>

  <!-- Shoulders -->
  <g id="src-btn-l" class="src-btn">
    <rect x="92" y="70" width="96" height="20" rx="9" />
    <text x="140" y="85" text-anchor="middle">LB</text>
  </g>
  <g id="src-btn-r" class="src-btn">
    <rect x="432" y="70" width="96" height="20" rx="9" />
    <text x="480" y="85" text-anchor="middle">RB</text>
  </g>

  <!-- D-pad recess -->
  <circle cx="171" cy="211" r="38" fill="#0a0d11" opacity="0.55"/>
  <g class="dpad">
    <g id="src-btn-up" class="src-btn dpad">
      <rect x="160" y="178" width="22" height="22" rx="3"/>
    </g>
    <g id="src-btn-down" class="src-btn dpad">
      <rect x="160" y="222" width="22" height="22" rx="3"/>
    </g>
    <g id="src-btn-left" class="src-btn dpad">
      <rect x="138" y="200" width="22" height="22" rx="3"/>
    </g>
    <g id="src-btn-right" class="src-btn dpad">
      <rect x="182" y="200" width="22" height="22" rx="3"/>
    </g>
    <rect x="160" y="200" width="22" height="22" fill="#0d1117"/>
  </g>

  <!-- Left stick -->
  <g id="src-btn-l3" class="src-btn stick">
    <circle cx="240" cy="155" r="36" class="stick-base" fill="url(#xiStickBase)"/>
    <circle cx="240" cy="155" r="22" class="stick-knob" id="src-l3-knob" fill="url(#xiStickKnob)"/>
    <text x="240" y="159" text-anchor="middle" class="tiny" fill="#6e7681">L3</text>
  </g>

  <!-- Right stick -->
  <g id="src-btn-r3" class="src-btn stick">
    <circle cx="380" cy="225" r="36" class="stick-base" fill="url(#xiStickBase)"/>
    <circle cx="380" cy="225" r="22" class="stick-knob" id="src-r3-knob" fill="url(#xiStickKnob)"/>
    <text x="380" y="229" text-anchor="middle" class="tiny" fill="#6e7681">R3</text>
  </g>

  <!-- Select / Start -->
  <g id="src-btn-select" class="src-btn">
    <rect x="265" y="146" width="36" height="14" rx="7"/>
    <text x="283" y="156" text-anchor="middle" class="tiny">View</text>
  </g>
  <g id="src-btn-start" class="src-btn">
    <rect x="320" y="146" width="36" height="14" rx="7"/>
    <text x="338" y="156" text-anchor="middle" class="tiny">Menu</text>
  </g>

  <!-- Face buttons (right cluster diamond) -->
  <g id="src-btn-y" class="src-btn face yellow">
    <circle cx="480" cy="130" r="20"/>
    <text x="480" y="136" text-anchor="middle">Y</text>
  </g>
  <g id="src-btn-a" class="src-btn face green">
    <circle cx="480" cy="190" r="20"/>
    <text x="480" y="196" text-anchor="middle">A</text>
  </g>
  <g id="src-btn-x" class="src-btn face blue">
    <circle cx="450" cy="160" r="20"/>
    <text x="450" y="166" text-anchor="middle">X</text>
  </g>
  <g id="src-btn-b" class="src-btn face red">
    <circle cx="510" cy="160" r="20"/>
    <text x="510" y="166" text-anchor="middle">B</text>
  </g>

  <!-- Title -->
  <text x="310" y="338" text-anchor="middle" class="ctrl-caption">XInput / Xbox controller</text>
</svg>
`;

const TGT_CD32_PAD = `
<svg viewBox="0 0 620 300" xmlns="http://www.w3.org/2000/svg" class="ctrl-svg" aria-label="Amiga CD32 control pad">
  <defs>
    <linearGradient id="cd32body" x1="0.5" y1="0" x2="0.5" y2="1">
      <stop offset="0%"  stop-color="#5a5a5a"/>
      <stop offset="55%" stop-color="#333"/>
      <stop offset="100%" stop-color="#161616"/>
    </linearGradient>
    <linearGradient id="cd32hi" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%"  stop-color="rgba(255,255,255,0.12)"/>
      <stop offset="50%" stop-color="rgba(255,255,255,0)"/>
    </linearGradient>
    <filter id="cd32Shadow" x="-10%" y="-10%" width="120%" height="130%">
      <feGaussianBlur stdDeviation="3" in="SourceAlpha"/>
      <feOffset dy="4" result="off"/>
      <feComponentTransfer><feFuncA type="linear" slope="0.5"/></feComponentTransfer>
      <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>

  <!-- Body (CD32 has a wedge / racetrack shape) -->
  <g filter="url(#cd32Shadow)">
    <path d="M 80 130
             Q 80 70 140 70
             L 480 70
             Q 540 70 540 130
             L 540 190
             Q 540 250 480 250
             L 140 250
             Q 80 250 80 190 Z"
          fill="url(#cd32body)" stroke="#000" stroke-width="2"/>
    <!-- Top sheen -->
    <path d="M 90 125
             Q 90 76 145 76
             L 475 76
             Q 530 76 530 125
             Q 310 110 90 125 Z"
          fill="url(#cd32hi)" opacity="0.85"/>
  </g>

  <!-- Top transport row: Rewind, Reverse, Play, Forward -->
  <g id="tgt-btn-rewind" class="tgt-btn">
    <rect x="120" y="100" width="44" height="14" rx="6"/>
    <text x="142" y="110" text-anchor="middle" class="tiny">REW · LB</text>
  </g>
  <g id="tgt-btn-reverse" class="tgt-btn">
    <rect x="200" y="100" width="60" height="14" rx="6"/>
    <text x="230" y="110" text-anchor="middle" class="tiny">REV · Sel</text>
  </g>
  <g id="tgt-btn-play" class="tgt-btn">
    <rect x="300" y="100" width="60" height="14" rx="6"/>
    <text x="330" y="110" text-anchor="middle" class="tiny">PLAY · Sta</text>
  </g>
  <g id="tgt-btn-forward" class="tgt-btn">
    <rect x="400" y="100" width="44" height="14" rx="6"/>
    <text x="422" y="110" text-anchor="middle" class="tiny">FWD · RB</text>
  </g>

  <!-- D-pad recess -->
  <circle cx="181" cy="171" r="38" fill="#0a0d11" opacity="0.55"/>
  <g class="dpad">
    <g id="tgt-btn-up" class="tgt-btn dpad">
      <rect x="170" y="138" width="22" height="22" rx="3"/>
    </g>
    <g id="tgt-btn-down" class="tgt-btn dpad">
      <rect x="170" y="182" width="22" height="22" rx="3"/>
    </g>
    <g id="tgt-btn-left" class="tgt-btn dpad">
      <rect x="148" y="160" width="22" height="22" rx="3"/>
    </g>
    <g id="tgt-btn-right" class="tgt-btn dpad">
      <rect x="192" y="160" width="22" height="22" rx="3"/>
    </g>
    <rect x="170" y="160" width="22" height="22" fill="#0d1117"/>
  </g>

  <!-- Coloured face buttons (CD32 layout: Yellow top, Red right, Blue bottom, Green left) -->
  <g id="tgt-btn-yellow" class="tgt-btn face yellow">
    <circle cx="430" cy="135" r="22"/>
    <text x="430" y="141" text-anchor="middle">Y</text>
  </g>
  <g id="tgt-btn-blue" class="tgt-btn face blue">
    <circle cx="430" cy="195" r="22"/>
    <text x="430" y="201" text-anchor="middle">A</text>
  </g>
  <g id="tgt-btn-green" class="tgt-btn face green">
    <circle cx="398" cy="165" r="22"/>
    <text x="398" y="171" text-anchor="middle">X</text>
  </g>
  <g id="tgt-btn-red" class="tgt-btn face red">
    <circle cx="462" cy="165" r="22"/>
    <text x="462" y="171" text-anchor="middle">B</text>
  </g>

  <text x="310" y="285" text-anchor="middle" class="ctrl-caption">Amiga CD32 Pad — 7 buttons</text>
</svg>
`;

const TGT_JOYSTICK_1BTN = `
<svg viewBox="0 0 620 300" xmlns="http://www.w3.org/2000/svg" class="ctrl-svg" aria-label="C64 / Amiga single-button joystick">
  <defs>
    <linearGradient id="joybase" x1="0.5" y1="0" x2="0.5" y2="1">
      <stop offset="0%"  stop-color="#262b33"/>
      <stop offset="55%" stop-color="#13171d"/>
      <stop offset="100%" stop-color="#06080b"/>
    </linearGradient>
    <linearGradient id="joybaseHi" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%"  stop-color="rgba(255,255,255,0.10)"/>
      <stop offset="40%" stop-color="rgba(255,255,255,0)"/>
    </linearGradient>
    <radialGradient id="joyBall" cx="0.35" cy="0.3" r="0.8">
      <stop offset="0%"  stop-color="#e76055"/>
      <stop offset="55%" stop-color="#a8281e"/>
      <stop offset="100%" stop-color="#5e150f"/>
    </radialGradient>
    <linearGradient id="joyShaft" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%"  stop-color="#1a1e24"/>
      <stop offset="50%" stop-color="#3a4049"/>
      <stop offset="100%" stop-color="#1a1e24"/>
    </linearGradient>
    <filter id="joyShadow" x="-10%" y="-10%" width="120%" height="130%">
      <feGaussianBlur stdDeviation="3" in="SourceAlpha"/>
      <feOffset dy="4" result="off"/>
      <feComponentTransfer><feFuncA type="linear" slope="0.55"/></feComponentTransfer>
      <feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>

  <!-- Square base -->
  <g filter="url(#joyShadow)">
    <rect x="170" y="130" width="280" height="140" rx="14" fill="url(#joybase)" stroke="#000" stroke-width="2"/>
    <rect x="172" y="132" width="276" height="50" rx="13" fill="url(#joybaseHi)" opacity="0.9"/>
  </g>

  <!-- Stick column -->
  <rect x="298" y="70" width="24" height="70" rx="6" fill="url(#joyShaft)" stroke="#000" stroke-width="1"/>

  <!-- Stick directions are the d-pad equivalent, shown as 4 arrows around the base -->
  <g id="tgt-btn-up"    class="tgt-btn dpad"><polygon points="310,30 290,55 330,55"/></g>
  <g id="tgt-btn-down"  class="tgt-btn dpad"><polygon points="310,290 290,265 330,265"/></g>
  <g id="tgt-btn-left"  class="tgt-btn dpad"><polygon points="170,200 195,180 195,220"/></g>
  <g id="tgt-btn-right" class="tgt-btn dpad"><polygon points="450,200 425,180 425,220"/></g>

  <!-- Red ball top of stick -->
  <circle cx="310" cy="60" r="24" fill="url(#joyBall)" stroke="#000" stroke-width="1.5"/>

  <!-- Single fire button (libretro default: RetroPad B = fire) -->
  <g id="tgt-btn-fire" class="tgt-btn face red">
    <circle cx="385" cy="200" r="22"/>
    <text x="385" y="206" text-anchor="middle">FIRE</text>
  </g>

  <text x="310" y="290" text-anchor="middle" class="ctrl-caption">C64 / Amiga 1-button joystick</text>
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
};

const TARGET_SVGS = {
  cd32_pad:      TGT_CD32_PAD,
  joystick_1btn: TGT_JOYSTICK_1BTN,
};

// Standard gamepad button index → our naming
const PAD_INDEX_TO_NAME = {
  0:'a', 1:'b', 2:'x', 3:'y', 4:'l', 5:'r', 6:'l2', 7:'r2',
  8:'select', 9:'start', 10:'l3', 11:'r3',
  12:'up', 13:'down', 14:'left', 15:'right'
};
