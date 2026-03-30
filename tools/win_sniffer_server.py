#!/usr/bin/env python
"""Windows-side Teledyne Frontline sniffer XML-RPC server.

Run this script on the Windows machine *alongside* ``autoptsserver.py`` to
enable sniffer capture control from the Linux AutoPTS client.

Usage::

    python win_sniffer_server.py [--port 9001] [--output-dir C:\\autopts_captures]

    # Debug mode (verbose):
    python win_sniffer_server.py --log-level DEBUG

XML-RPC API (consumed by ``autopts.tools.sniffer_controller.RpcBackend``)::

    ping()                     → True
    is_available()             → bool
    start(capture_name: str)   → None
    stop()                     → None
    save_and_fetch(name: str)  → xmlrpc.Binary  (raw .cfa bytes, or None)

The ``save_and_fetch`` method stops the current capture, saves it as
``<output_dir>/<name>.cfa``, reads the file back, and returns the bytes to
the caller over XML-RPC.  The Linux client then writes them to the per-test
artefact directory.

Sniffer control strategy
------------------------
1. **SDK / COM** — attempted first if ``pywintypes`` is available.
   Frontline SDK COM interface is vendor-specific; hook ``_sdk_start`` /
   ``_sdk_stop`` / ``_sdk_save`` below once you obtain the SDK type library.

2. **pywinauto UI automation** — fallback when COM SDK is unavailable.
   Searches for the Frontline application window and drives the toolbar
   buttons via the Windows UI Automation API.

3. **Noop** — logged warning when neither backend works.
"""

import argparse
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional
from xmlrpc.server import SimpleXMLRPCServer

log = logging.getLogger(__name__)

# ── Candidate Frontline window titles ─────────────────────────────────────────
# Adjust these if your installed version uses a different title.
_APP_TITLE_PATTERNS = [
    "Wireless Protocol Suite",
    "Frontline Protocol Analyzer",
    "Frame Data",           # WPS secondary window
    "Bluetooth Protocol Viewer",
    "Frontline Test Equipment",
    "ComProbe",
]

# Button captions used by Frontline; order matters (first match wins).
_START_BTN_LABELS = ["Record", "Start Capture", "Start Recording", "Start", "New"]
_STOP_BTN_LABELS  = ["Stop",  "Stop Capture",  "Stop Recording",  "Pause"]


# ── Frontline controller ──────────────────────────────────────────────────────

class FrontlineController:
    """Controls Teledyne Frontline Protocol Analyzer UI via pywinauto."""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._last_start_ts = 0.0

        try:
            from pywinauto import Application  # noqa: F401
            self._pywinauto_available = True
        except ImportError:
            log.warning(
                "pywinauto is not installed.  "
                "Install it with:  pip install pywinauto  "
                "Sniffer control will be a no-op until then."
            )
            self._pywinauto_available = False

    # ── COM / SDK hook (optional) ─────────────────────────────────────────────
    # If the Teledyne Frontline SDK exposes COM automation, implement these
    # three methods and set ``self._sdk_available = True`` in __init__.

    def _sdk_start(self, capture_name: str) -> bool:
        """Start capture via COM SDK.  Return True on success."""
        return False

    def _sdk_stop(self) -> bool:
        """Stop capture via COM SDK.  Return True on success."""
        return False

    def _sdk_save(self, dest: Path) -> bool:
        """Save capture to *dest* via COM SDK.  Return True on success."""
        return False

    # ── Window helpers ────────────────────────────────────────────────────────

    def _find_main_window(self):
        """Return a pywinauto WindowSpecification for the Frontline window."""
        from pywinauto import findwindows, Application
        for pattern in _APP_TITLE_PATTERNS:
            try:
                elems = findwindows.find_elements(title_re=f".*{pattern}.*",
                                                  control_type="Window")
                if elems:
                    app = Application(backend="uia").connect(handle=elems[0].handle)
                    return app.window(handle=elems[0].handle)
            except Exception:
                continue
        return None

    def is_available(self) -> bool:
        if not self._pywinauto_available:
            return False
        return self._find_main_window() is not None

    # ── Start ─────────────────────────────────────────────────────────────────

    def start(self, capture_name: str) -> None:
        log.info("Starting capture: %s", capture_name)
        self._last_start_ts = time.time()
        with self._lock:
            if not self._pywinauto_available:
                log.warning("pywinauto not available — cannot start capture")
                return
            win = self._find_main_window()
            if win is None:
                log.error("Frontline window not found")
                return
            if not self._click_button(win, _START_BTN_LABELS, fallback_key="{F5}"):
                log.warning("Could not start capture via UI")
            time.sleep(0.5)

    # ── Stop ──────────────────────────────────────────────────────────────────

    def stop(self) -> None:
        log.info("Stopping capture")
        with self._lock:
            if not self._pywinauto_available:
                return
            win = self._find_main_window()
            if win is None:
                log.error("Frontline window not found")
                return
            if not self._click_button(win, _STOP_BTN_LABELS, fallback_key="{F6}"):
                log.warning("Could not stop capture via UI")
            time.sleep(0.5)

    # ── Save ──────────────────────────────────────────────────────────────────

    def save_as(self, filename: str) -> Optional[Path]:
        """Save current capture to ``<output_dir>/<filename>.cfa``.

        Returns the :class:`pathlib.Path` on success, ``None`` on failure.
        """
        dest = self.output_dir / f"{filename}.cfa"
        log.info("Saving capture to %s", dest)
        with self._lock:
            if not self._pywinauto_available:
                log.warning("pywinauto not available — cannot save capture")
                return None
            win = self._find_main_window()
            if win is None:
                log.error("Frontline window not found")
                return None
            success = self._file_save_as(win, dest)
            if success and dest.exists():
                log.info("Saved %s (%d bytes)", dest, dest.stat().st_size)
                return dest
            log.error("Save failed (file not found at %s)", dest)
            return None

    def latest_capture_file(self, min_mtime: float = 0.0) -> Optional[Path]:
        """Return newest .cfa in output_dir with mtime >= min_mtime."""
        try:
            candidates = [p for p in self.output_dir.glob("*.cfa") if p.is_file()]
        except Exception:
            return None
        if not candidates:
            return None
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        newest = candidates[0]
        if newest.stat().st_mtime >= min_mtime:
            return newest
        return None

    # ── UI helpers ────────────────────────────────────────────────────────────

    def _click_button(self, win, labels: list[str], fallback_key: str = "") -> bool:
        """Try each label; fall back to keyboard shortcut.  Return True on success."""
        for label in labels:
            try:
                btn = win.child_window(title=label, control_type="Button")
                if btn.exists(timeout=1):
                    btn.click_input()
                    log.debug("Clicked button: %r", label)
                    return True
            except Exception as exc:
                log.debug("Button %r not found: %s", label, exc)

        # Also try toolbar split buttons / menu items
        for label in labels:
            try:
                item = win.child_window(title=label)
                if item.exists(timeout=0.5):
                    item.click_input()
                    log.debug("Clicked item: %r", label)
                    return True
            except Exception:
                pass

        if fallback_key:
            try:
                win.set_focus()
                win.type_keys(fallback_key)
                log.debug("Sent keyboard shortcut: %r", fallback_key)
                return True
            except Exception as exc:
                log.warning("Keyboard shortcut %r failed: %s", fallback_key, exc)
        return False

    def _file_save_as(self, win, dest: Path) -> bool:
        """Drive File → Save As dialog to save the capture."""
        try:
            win.set_focus()
            # Try the menu path
            try:
                win.menu_select("File->Save As...")
            except Exception:
                win.type_keys("%f")   # Alt+F to open File menu
                time.sleep(0.4)
                win.type_keys("a")    # 'a' for Save As
            time.sleep(1.0)

            # Find the Save As dialog
            from pywinauto import Desktop
            dlg = Desktop(backend="uia").window(title_re=r".*Save.*",
                                                control_type="Window")
            dlg.wait("exists visible", timeout=6)

            # Fill in the file name field
            try:
                fname = dlg.child_window(auto_id="1148", control_type="Edit")
            except Exception:
                fname = dlg.child_window(control_type="Edit", found_index=0)
            fname.set_edit_text(str(dest))
            time.sleep(0.3)

            # Click Save
            try:
                save_btn = dlg.child_window(title="Save", control_type="Button")
                save_btn.click_input()
            except Exception:
                dlg.type_keys("{ENTER}")
            time.sleep(1.5)
            return True

        except Exception as exc:
            log.error("File → Save As automation failed: %s", exc)
            return False


# ── XML-RPC handler ───────────────────────────────────────────────────────────

class SnifferRpcHandler:
    """Exposes FrontlineController over XML-RPC."""

    def __init__(self, output_dir: str):
        self._ctrl = FrontlineController(output_dir)

    def ping(self) -> bool:
        return True

    def is_available(self) -> bool:
        return self._ctrl.is_available()

    def start(self, capture_name: str) -> None:
        """Non-blocking: dispatch UI automation to a background thread and return immediately.

        Returning quickly is critical — the Linux AutoPTS client has a socket
        timeout and the test run blocks until this RPC call returns.  Running
        the pywinauto window search + button click in a daemon thread lets the
        Linux side continue within milliseconds.
        """
        threading.Thread(
            target=self._ctrl.start,
            args=(capture_name,),
            daemon=True,
            name=f"sniffer-start-{capture_name}",
        ).start()

    def stop(self) -> None:
        self._ctrl.stop()

    def save_and_fetch(self, filename: str):
        """Stop the capture, save it, and return the raw bytes.

        Returns an ``xmlrpc.client.Binary`` instance, or ``None`` if saving
        failed.
        """
        import xmlrpc.client as _xc

        # save_and_fetch is the authoritative end-of-test operation: stop then save.
        self._ctrl.stop()
        path = self._ctrl.save_as(filename)

        if path is None:
            # UI automation can fail intermittently. Fallback to newest recent
            # capture file in output directory, if one was produced after start().
            path = self._ctrl.latest_capture_file(min_mtime=self._ctrl._last_start_ts - 2.0)
            if path is not None:
                log.warning("Save As fallback used newest capture file: %s", path)

        if path is None or not path.exists():
            log.error("No capture file available to send for %s", filename)
            return None
        data = path.read_bytes()
        log.info("Sending %d bytes for %s", len(data), filename)
        return _xc.Binary(data)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AutoPTS Windows-side sniffer XML-RPC server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--port",       type=int, default=9001,
                        help="TCP port to listen on (default: 9001)")
    parser.add_argument("--host",       default="0.0.0.0",
                        help="Bind address (default: 0.0.0.0; use 127.0.0.1 for local only)")
    parser.add_argument("--output-dir", default=r"C:\autopts_captures",
                        metavar="DIR",
                        help=r"Directory to save .cfa files (default: C:\autopts_captures)")
    parser.add_argument("--log-level",  default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    handler = SnifferRpcHandler(args.output_dir)
    server  = SimpleXMLRPCServer(
        (args.host, args.port), allow_none=True, logRequests=False
    )
    server.register_instance(handler)
    server.register_introspection_functions()

    log.info("Sniffer RPC server listening on %s:%d", args.host, args.port)
    log.info("Capture output directory: %s", args.output_dir)
    log.info("pywinauto available: %s", handler._ctrl._pywinauto_available)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Server stopped.")


if __name__ == "__main__":
    main()
