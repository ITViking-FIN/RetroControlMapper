# rbcf.spec — PyInstaller --onefile build for RetroControlMapper v0.1.0
#
# Run via:  py -m PyInstaller --clean rbcf.spec
# Output:   dist/RetroControlMapper.exe
#
# The Windows installer (Stream IS, see installer/) takes this single .exe
# and wraps it in an Inno Setup wizard. The .exe itself is fully
# self-contained — at runtime it unpacks to a temp dir under
# %LOCALAPPDATA%/Temp/_MEIxxxxxx/ and runs from there.
#
# Bundled-vs-user-writable architecture:
#
#   Read-only (inside the .exe, accessed via sys._MEIPASS):
#     - gui/                   (HTML/CSS/JS + img assets)
#     - controller_catalog.yaml
#     - LICENSE, README.md, INSTRUCTIONS.md
#     - profiles/              (factory seed library — see note below)
#
#   User-writable (under %APPDATA%/RB-Controller_fix/, NOT in the .exe):
#     - profiles/              (user-edited copy)
#     - sync_manifest.json
#     - controller_sync.log
#     - rbcfrc                 (RetroBat root override; see config.py)
#     - backups/               (backup snapshots)
#
# First-run profile-seed handoff:
#
#   The bundled `profiles/` directory at sys._MEIPASS/profiles is the
#   read-only factory copy. The runtime user-editable copy lives at
#   %APPDATA%/RB-Controller_fix/profiles/. The Stream IS installer is
#   responsible for copying the bundled factory profiles to %APPDATA%
#   on install (or first run). This .spec file just makes sure the
#   factory copy gets bundled into the .exe so the installer has
#   something to copy. See BUILD.md for the full flow.

block_cipher = None

a = Analysis(
    ['rbcf_gui.py'],
    pathex=[],
    binaries=[],
    datas=[
        # GUI assets — vanilla HTML/CSS/JS served by the local HTTP server.
        ('gui/index.html',         'gui'),
        ('gui/style.css',          'gui'),
        ('gui/app.js',             'gui'),
        ('gui/app-onboarding.js',  'gui'),
        ('gui/controllers.js',     'gui'),

        # Top-level images referenced from controllers.js / app.js.
        ('gui/img/cd32-pad.jpg',         'gui/img'),
        ('gui/img/competition-pro.jpg',  'gui/img'),
        ('gui/img/xbox360-pad.svg',      'gui/img'),

        # Icons (svg + png ladder). The 256 png is reused for the tray.
        ('gui/img/icon/RetroControlMapper.svg',       'gui/img/icon'),
        ('gui/img/icon/RetroControlMapper_256.png',   'gui/img/icon'),
        ('gui/img/icon/RetroControlMapper_512.png',   'gui/img/icon'),
        ('gui/img/icon/RetroControlMapper_1024.png',  'gui/img/icon'),

        # Auto-synced known-controller images.
        ('gui/img/known/*',    'gui/img/known'),

        # User-supplied raw images (currently 2 8BitDo references — used
        # as input to clean_controller_photo.py when curating new entries).
        ('gui/img/contrib/*',  'gui/img/contrib'),

        # Controller catalog (VID:PID -> name, Wikimedia file).
        ('controller_catalog.yaml',  '.'),

        # Documentation surfaced via "About" / accessible from the tray.
        ('LICENSE',           '.'),
        ('README.md',         '.'),
        ('INSTRUCTIONS.md',   '.'),

        # Factory profile-seed library. The Stream IS installer copies
        # this tree to %APPDATA%/RB-Controller_fix/profiles/ on install
        # so the runtime app has a writable copy. The bundled tree
        # itself is read-only (it lives inside the .exe).
        ('profiles',  'profiles'),
    ],
    hiddenimports=[
        # pystray's win32 backend is loaded via importlib at runtime;
        # PyInstaller's static analyser misses it.
        'pystray._win32',

        # Pillow submodules used by tray.py for icon rendering. Pillow
        # uses a plugin-discovery mechanism that PyInstaller doesn't
        # always pick up.
        'PIL.ImageDraw',
        'PIL.ImageFont',
        'PIL._tkinter_finder',

        # Internal modules. PyInstaller usually catches these via the
        # static import graph from rbcf_gui.py, but several are imported
        # lazily inside functions (e.g. backups, guid_aliases,
        # guid_watcher) so we list them explicitly.
        'config',
        'rbcf',
        'tray',
        'system_lookup',
        'update_check',
        'guid_aliases',
        'guid_watcher',
        'backups',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Bundle-size pruning. None of these are imported by our code.
        'tkinter',
        'tk',
        'tcl',
        'PIL.ImageQt',
        'PIL.ImageTk',
        'curses',
        'lib2to3',
        'unittest',
        'pydoc_data',
        # We don't talk to numpy / scipy / matplotlib — make sure no
        # transitive import drags them in.
        'numpy',
        'scipy',
        'matplotlib',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='RetroControlMapper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,           # if UPX is on PATH it gets used; otherwise PyInstaller skips silently.
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,      # tray app: no console window.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # PyInstaller accepts PNG icons on Windows — Pillow converts to ICO
    # at build time. If you want a hand-tuned .ico (multi-resolution
    # with hinted hot pixels), generate one and swap the path.
    icon='gui/img/icon/RetroControlMapper_256.png',
    version_file=None,  # VERSIONINFO resource — defer to v0.1.1.
)
