"""
RB-Controller_fix — system tray host.

Phase 1 of the tray-app refactor (DECISIONS.md #1, sub-decision (i) pystray).

The tray icon is the long-lived process. The HTTP server runs in a daemon
thread under it; closing the browser leaves the icon (and server) alive.
The only way to actually quit is the tray menu's "Quit" item.

Watcher / autostart subsystems are NOT in this phase — they land in later
waves once #1.implementation begins.

Public surface:
    start_tray_app(open_browser_on_start: bool = True) -> None
        Blocks until the user picks Quit from the tray menu. Spawns the
        HTTP server in a daemon thread before showing the icon.

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

ROOT = Path(__file__).resolve().parent
GUI_IMG_DIR = ROOT / "gui" / "img"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def _build_tray_image(size: int = 64):
    """Return a 64x64 PIL Image for the tray icon.

    Prefer gui/img/tray-icon.png if present; otherwise generate a solid
    blue square with white "RB" text via PIL.ImageDraw. Caller has already
    confirmed Pillow imports successfully.
    """
    from PIL import Image, ImageDraw, ImageFont  # type: ignore[import-not-found]

    asset = GUI_IMG_DIR / "tray-icon.png"
    if asset.is_file():
        try:
            img = Image.open(asset).convert("RGBA")
            if img.size != (size, size):
                img = img.resize((size, size), Image.NEAREST)
            return img
        except (OSError, ValueError):
            # Fall through to programmatic icon.
            pass

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


def _open_main_window(port: int = DEFAULT_PORT) -> None:
    webbrowser.open(f"http://localhost:{port}/")


def _open_about(port: int = DEFAULT_PORT) -> None:
    webbrowser.open(f"http://localhost:{port}/?about=1")


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

    # Lazy-import the server entry to keep tray import cheap.
    from rbcf_gui import serve_http

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

    menu = Menu(
        MenuItem("Show window", on_show, default=True),
        Menu.SEPARATOR,
        MenuItem("About RB-Controller_fix", on_about),
        Menu.SEPARATOR,
        MenuItem("Quit", on_quit),
    )

    icon = pystray.Icon(
        name="rb-controller-fix",
        icon=image,
        title="RB-Controller_fix",
        menu=menu,
    )
    icon_holder["icon"] = icon

    # icon.run() blocks until icon.stop() is called.
    icon.run()

    # After Icon.stop(): be sure shutdown_event is set so the server thread
    # exits cleanly even if the user closes via an OS-level kill. The thread
    # is daemon=True so the process exits regardless, but we'd like a clean
    # shutdown.
    shutdown_event.set()
    # Give the server a brief window to drain. Daemon thread, so don't block long.
    server_thread.join(timeout=3.0)


__all__ = ["start_tray_app"]
