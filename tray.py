"""
RB-Controller_fix — system tray host.

Phase 1 of the tray-app refactor (DECISIONS.md #1, sub-decision (i) pystray).
Phase 2 layers the GUID watcher daemon + Windows autostart toggle on top —
both are wired through the tray menu.

The tray icon is the long-lived process. The HTTP server runs in a daemon
thread under it; closing the browser leaves the icon (and server) alive.
The only way to actually quit is the tray menu's "Quit" item.

Phase 2 additions:
    * GUID watcher submenu — three radio items (Off / Detect only /
      Auto-fold (silent)) wired to ``guid_watcher.set_mode``. The watcher
      thread runs alongside the HTTP server thread under the same
      ``shutdown_event``.
    * "Run on Windows startup" toggle — writes/clears the
      ``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run`` value
      ``RetroControlMapper``. HKCU = no UAC prompt.

Public surface:
    start_tray_app(open_browser_on_start: bool = True) -> None
        Blocks until the user picks Quit from the tray menu. Spawns the
        HTTP server + GUID watcher in daemon threads before showing the
        icon.

Graceful fallback:
    If `pystray` (or its companions Pillow / pystray's platform backend)
    cannot be imported, start_tray_app() prints an installation hint and
    falls back to the legacy foreground server behaviour. This keeps the
    binary runnable on a fresh checkout where deps haven't been installed
    yet.
"""
from __future__ import annotations

import sys
import threading
import webbrowser
from pathlib import Path
from typing import Optional

try:
    import winreg  # type: ignore[import-not-found]
except ImportError:  # non-Windows; tray is Windows-only but keep import safe
    winreg = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parent
GUI_IMG_DIR = ROOT / "gui" / "img"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

# HKCU Run-key registration for the locked installer-spec autostart prompt.
# HKCU (current user) avoids the UAC elevation that HKLM would require.
_RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_KEY_VALUE = "RetroControlMapper"


def _autostart_command_line() -> str:
    """Return the command line we'd write into the Run key.

    Two cases:

    1. Frozen (PyInstaller --onefile): ``sys.executable`` is the bundled
       ``.exe`` and ``sys.argv[0]`` matches it. Use ``sys.executable``
       directly. Quote it so paths with spaces (Program Files) survive.
    2. Source / dev: ``sys.executable`` is the Python interpreter and
       ``sys.argv[0]`` is ``rbcf_gui.py``. Build ``"python.exe" "rbcf_gui.py"``
       so re-launching at startup works without a shell context.
    """
    if getattr(sys, "frozen", False):
        # PyInstaller / cx_Freeze: sys.executable is the .exe itself.
        return f'"{sys.executable}"'
    # Dev mode: invoke the interpreter on the script.
    script = Path(sys.argv[0]).resolve() if sys.argv and sys.argv[0] else None
    if script is None or not script.exists():
        # Fall back to module form if argv[0] is unreliable.
        return f'"{sys.executable}" -m rbcf_gui'
    return f'"{sys.executable}" "{script}"'


def _autostart_enabled() -> bool:
    """True if the Run-key value exists and points at the current binary.

    Returns False on any registry error rather than raising — a stale or
    foreign Run entry is treated as "not us".
    """
    if winreg is None:
        return False
    expected = _autostart_command_line()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH,
                            0, winreg.KEY_READ) as key:
            try:
                value, _kind = winreg.QueryValueEx(key, _RUN_KEY_VALUE)
            except FileNotFoundError:
                return False
    except OSError:
        return False
    if not isinstance(value, str):
        return False
    # Normalise whitespace; we don't need a strict equality — just
    # confirmation the entry is OURS, not some leftover from a different
    # install path.
    return value.strip() == expected.strip()


def _set_autostart(enabled: bool) -> None:
    """Write or remove the Run-key value. Best-effort — never raises.

    HKCU is per-user, so this works without UAC elevation. A registry
    failure here (locked-down policy, antivirus interception) shouldn't
    crash the tray; we log to stderr and the menu will reflect the
    actual state on next refresh.
    """
    if winreg is None:
        print("[tray] autostart unavailable: winreg not present "
              "(non-Windows host?)", file=sys.stderr)
        return
    try:
        if enabled:
            cmd = _autostart_command_line()
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                                  _RUN_KEY_PATH) as key:
                winreg.SetValueEx(key, _RUN_KEY_VALUE, 0, winreg.REG_SZ, cmd)
        else:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH,
                                    0, winreg.KEY_SET_VALUE) as key:
                    try:
                        winreg.DeleteValue(key, _RUN_KEY_VALUE)
                    except FileNotFoundError:
                        pass
            except FileNotFoundError:
                pass
    except OSError as e:
        print(f"[tray] autostart registry write failed: {e}",
              file=sys.stderr)


def _build_tray_image(size: int = 64):
    """Return a PIL Image for the tray icon.

    Tries (in order): gui/img/icon/RetroControlMapper_256.png (the official
    app icon — synthwave gamepad), then gui/img/tray-icon.png (legacy
    fallback location), then a programmatic blue square with white "RB"
    text. Caller has already confirmed Pillow imports successfully.
    """
    from PIL import Image, ImageDraw, ImageFont  # type: ignore[import-not-found]

    # The official app icon ships at multiple resolutions; use 256 as the
    # tray source — Pillow will downsample to `size` cleanly.
    candidates = (
        GUI_IMG_DIR / "icon" / "RetroControlMapper_256.png",
        GUI_IMG_DIR / "tray-icon.png",
    )
    for asset in candidates:
        if not asset.is_file():
            continue
        try:
            img = Image.open(asset).convert("RGBA")
            if img.size != (size, size):
                # LANCZOS for the photographic icon — NEAREST would alias
                # the synthwave gradients badly at small tray sizes.
                img = img.resize((size, size), Image.LANCZOS)
            return img
        except (OSError, ValueError):
            continue
    # Both assets missing or unreadable — fall through to programmatic icon.

    # Programmatic fallback: dark blue square, white "RB" centred.
    img = Image.new("RGBA", (size, size), (32, 80, 160, 255))
    draw = ImageDraw.Draw(img)
    # Border for definition against light/dark trays.
    draw.rectangle([0, 0, size - 1, size - 1], outline=(255, 255, 255, 255), width=2)
    text = "RB"
    try:
        font = ImageFont.truetype("arial.ttf", size=int(size * 0.55))
    except (OSError, IOError):
        font = ImageFont.load_default()
    # Centre the text.
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = (size - tw) / 2 - bbox[0]
        ty = (size - th) / 2 - bbox[1]
    except AttributeError:
        # Very old Pillow without textbbox: rough centre.
        tw, th = draw.textsize(text, font=font)  # type: ignore[attr-defined]
        tx = (size - tw) / 2
        ty = (size - th) / 2
    draw.text((tx, ty), text, fill=(255, 255, 255, 255), font=font)
    return img


_EDGE_PATHS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)
_CHROME_PATHS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)


def _find_app_browser() -> str | None:
    """Locate a Chromium-family browser that supports `--app=<url>`.

    --app mode opens the URL in a frameless window with no address bar,
    no tabs — looks and behaves like a real desktop app. Edge ships
    with Windows 10/11 so this almost always finds something. Falls
    back to webbrowser.open if not.
    """
    import shutil
    # PATH-resolution first (common case if Edge has been put on PATH
    # by the user's profile).
    for name in ("msedge", "msedge.exe", "chrome", "chrome.exe"):
        hit = shutil.which(name)
        if hit:
            return hit
    # Standard install locations on Windows 10/11.
    for candidate in _EDGE_PATHS + _CHROME_PATHS:
        if Path(candidate).is_file():
            return candidate
    return None


def _open_app_window(url: str) -> None:
    """Open `url` as a frameless desktop window via Chromium --app mode.

    Falls back to the user's default browser if neither Edge nor Chrome
    is found at the standard locations.
    """
    import subprocess
    browser = _find_app_browser()
    if browser:
        try:
            # CREATE_NEW_PROCESS_GROUP so the window survives if the tray
            # is restarted; the window is fully detached.
            subprocess.Popen(
                [browser, f"--app={url}"],
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                close_fds=True,
            )
            return
        except OSError:
            pass  # fall through to webbrowser
    webbrowser.open(url)


def _open_main_window(port: int = DEFAULT_PORT) -> None:
    _open_app_window(f"http://localhost:{port}/")


def _open_about(port: int = DEFAULT_PORT) -> None:
    _open_app_window(f"http://localhost:{port}/?about=1")


def _foreground_fallback(open_browser_on_start: bool) -> None:
    """No-tray legacy fallback. Used when pystray is missing."""
    # Lazy import to avoid circular dependency at module load time.
    from rbcf_gui import serve_http

    serve_http(
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        no_open=not open_browser_on_start,
        ready_event=None,
    )


def start_tray_app(open_browser_on_start: bool = True,
                   host: str = DEFAULT_HOST,
                   port: int = DEFAULT_PORT) -> None:
    """Run RB-Controller_fix as a tray-resident app.

    Blocks until the user clicks Quit on the tray menu. The HTTP server
    runs in a daemon thread; on Quit we ask it to shut down via the
    shared shutdown_event before stopping the icon.
    """
    # Import pystray + PIL inside the function so a missing dep doesn't
    # break `from tray import ...` at the module level (rbcf_gui's
    # __main__ does conditional fallback based on the ImportError).
    try:
        import pystray  # type: ignore[import-not-found]
        from pystray import Menu, MenuItem  # type: ignore[import-not-found]
        from PIL import Image  # noqa: F401  # type: ignore[import-not-found]
    except ImportError as e:
        print(
            f"[tray] required dependency not available ({e}).\n"
            f"       pip install pystray pillow\n"
            f"       Falling back to foreground server (--no-tray mode).",
            file=sys.stderr,
        )
        _foreground_fallback(open_browser_on_start)
        return

    # Lazy-import the server entry + watcher to keep tray import cheap.
    from rbcf_gui import serve_http
    import guid_watcher

    shutdown_event = threading.Event()
    ready_event = threading.Event()

    def _run_server() -> None:
        try:
            serve_http(
                host=host,
                port=port,
                no_open=True,  # tray opens the browser itself once ready
                ready_event=ready_event,
                shutdown_event=shutdown_event,
            )
        except OSError as exc:
            # Most likely: address already in use. Surface and let the
            # tray sit there with a dead server — user can quit via menu.
            print(f"[tray] HTTP server failed to start: {exc}", file=sys.stderr)
            ready_event.set()  # unblock the auto-open below

    server_thread = threading.Thread(
        target=_run_server,
        name="rbcf-http-server",
        daemon=True,
    )
    server_thread.start()

    # Spawn the GUID watcher alongside the HTTP server. It reads its
    # mode from the persisted state file; if no state has been saved
    # yet, default to 'detect' (safe — never modifies es_input.cfg).
    initial_state = guid_watcher.get_state()
    initial_mode = initial_state.get("mode") or guid_watcher.DEFAULT_MODE
    if initial_mode not in guid_watcher.VALID_MODES:
        initial_mode = guid_watcher.DEFAULT_MODE
    try:
        watcher_thread = guid_watcher.start_watcher(
            shutdown_event=shutdown_event,
            mode=initial_mode,
        )
    except Exception as exc:  # noqa: BLE001 — never let watcher kill the tray
        print(f"[tray] guid_watcher failed to start: {exc}", file=sys.stderr)
        watcher_thread = None

    # Wait for the server to actually be listening before opening the
    # browser, so we don't get a "connection refused" race.
    if open_browser_on_start:
        def _delayed_open() -> None:
            if ready_event.wait(timeout=5.0):
                _open_main_window(port)
            else:
                # Server didn't come up in 5s; open anyway — user will see
                # the error and can decide.
                _open_main_window(port)
        threading.Thread(target=_delayed_open, daemon=True).start()

    # Build the icon and menu. We capture `icon` via closure for the Quit
    # handler that calls icon.stop().
    image = _build_tray_image()

    icon_holder: dict[str, Optional["pystray.Icon"]] = {"icon": None}

    def on_show(icon, item):  # noqa: ARG001 — pystray callback signature
        _open_main_window(port)

    def on_about(icon, item):  # noqa: ARG001
        _open_about(port)

    def on_quit(icon, item):  # noqa: ARG001
        shutdown_event.set()
        ic = icon_holder["icon"]
        if ic is not None:
            ic.stop()

    # ------------- GUID watcher submenu callbacks -------------
    # pystray passes (icon, item) to checkable callbacks; the lambda we
    # bind via `checked=` reads the live mode every time the menu opens
    # so toggling stays in sync with `set_mode` from anywhere else.
    def _make_set_mode(mode: str):
        def _cb(icon, item):  # noqa: ARG001
            try:
                guid_watcher.set_mode(mode)
            except Exception as exc:  # noqa: BLE001
                print(f"[tray] set watcher mode failed: {exc}",
                      file=sys.stderr)
            # pystray re-renders the menu via the `checked` lambdas — no
            # explicit refresh needed.
        return _cb

    def _is_mode(mode: str):
        return lambda item: guid_watcher.get_state().get("mode") == mode  # noqa: ARG005

    watcher_submenu = Menu(
        MenuItem("Off",
                 _make_set_mode("off"),
                 checked=_is_mode("off"),
                 radio=True),
        MenuItem("Detect only",
                 _make_set_mode("detect"),
                 checked=_is_mode("detect"),
                 radio=True),
        MenuItem("Auto-fold (silent)",
                 _make_set_mode("auto-fold"),
                 checked=_is_mode("auto-fold"),
                 radio=True),
    )

    def _watcher_label(item):  # noqa: ARG001
        mode = guid_watcher.get_state().get("mode") or "detect"
        return f"GUID watcher: {mode}"

    # ------------- Autostart toggle -------------
    def on_toggle_autostart(icon, item):  # noqa: ARG001
        currently = _autostart_enabled()
        _set_autostart(not currently)

    def _autostart_label(item):  # noqa: ARG001
        return ("Run on Windows startup: on"
                if _autostart_enabled()
                else "Run on Windows startup: off")

    menu = Menu(
        MenuItem("Show window", on_show, default=True),
        Menu.SEPARATOR,
        MenuItem(_watcher_label, watcher_submenu),
        MenuItem(_autostart_label,
                 on_toggle_autostart,
                 checked=lambda item: _autostart_enabled()),  # noqa: ARG005
        Menu.SEPARATOR,
        MenuItem("About RetroControlMapper", on_about),
        Menu.SEPARATOR,
        MenuItem("Quit", on_quit),
    )

    icon = pystray.Icon(
        name="rb-controller-fix",
        icon=image,
        title="RetroControlMapper",
        menu=menu,
    )
    icon_holder["icon"] = icon

    # icon.run() blocks until icon.stop() is called.
    icon.run()

    # After Icon.stop(): be sure shutdown_event is set so the server +
    # watcher threads exit cleanly even if the user closes via an OS-level
    # kill. Both are daemon=True so the process exits regardless, but we'd
    # like a clean shutdown.
    shutdown_event.set()
    # Give the server a brief window to drain. Daemon thread, so don't block long.
    server_thread.join(timeout=3.0)
    if watcher_thread is not None:
        # Watcher polls in 1s steps so it should observe shutdown_event
        # within a couple of seconds at most.
        watcher_thread.join(timeout=3.0)


__all__ = [
    "start_tray_app",
    "_autostart_enabled",
    "_set_autostart",
]
