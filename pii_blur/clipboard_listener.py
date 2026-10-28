"""Event-driven clipboard trigger — fires the INSTANT the clipboard changes.

Instead of only polling the clipboard a few times a second (which adds visible
lag after a screenshot), we ask Windows to tell us the moment anything new is
copied: a hidden message-only window registers with AddClipboardFormatListener
and receives WM_CLIPBOARDUPDATE. That wakes the watcher immediately.

It's a pure speed-up layer, not a replacement: the watcher still keeps a slow
polling fallback, so if this listener can't start (locked-down system, missing
pywin32) nothing breaks — it just reacts a touch slower.
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

WM_CLIPBOARDUPDATE = 0x031D
_HWND_MESSAGE = -3  # message-only window: no taskbar entry, just receives messages


class ClipboardListener:
    """Calls `on_update()` (from its own thread) every time the clipboard changes.

    Start it with .start(); it runs a Win32 message loop on a daemon thread.
    """

    def __init__(self, on_update):
        self._on_update = on_update
        self._thread = threading.Thread(target=self._run, name="clip-listener", daemon=True)
        self._hwnd = None
        self.active = False

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        try:
            import ctypes

            import win32gui

            wc = win32gui.WNDCLASS()
            wc.lpszClassName = "PiiBlurClipboardListener"
            wc.lpfnWndProc = {WM_CLIPBOARDUPDATE: self._on_message}
            atom = win32gui.RegisterClass(wc)
            self._hwnd = win32gui.CreateWindowEx(
                0, atom, "PiiBlurClip", 0, 0, 0, 0, 0, _HWND_MESSAGE, 0, 0, None)

            if not ctypes.windll.user32.AddClipboardFormatListener(self._hwnd):
                logger.info("AddClipboardFormatListener failed; polling only")
                return
            self.active = True
            logger.info("clipboard listener active (instant trigger)")
            win32gui.PumpMessages()
        except Exception:
            # Any failure just leaves the watcher on its polling fallback.
            logger.info("clipboard listener unavailable; polling only", exc_info=True)

    def _on_message(self, hwnd, msg, wparam, lparam):
        try:
            self._on_update()
        except Exception:
            logger.exception("clipboard on_update callback failed")
        return 0
