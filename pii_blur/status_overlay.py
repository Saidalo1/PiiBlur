"""A tiny, fixed-duration amber flash at the bottom-right of the screen — the
on-screen "I just noticed your clipboard screenshot" signal, for when the tray
icon itself (see tray.py's busy-tint) is hidden in Windows' "hidden icons"
overflow panel, which is common and not something the app can prevent.

Deliberately NOT a toast/balloon notification: see tray.py's busy-icon
docstring for why a popup firing on every clipboard paste (potentially dozens
of times a day) is the kind of frequent, low-importance confirmation UX
guidance says to suppress, not pop up.

Deliberately a FIXED ~800ms flash, not shown for the real processing duration:
this is the Doherty-threshold idea already applied to the tray icon — the
point is to confirm "registered" within the first few hundred ms, not to
visualize how long the blur actually took. A duration-matched bar would also
flicker illegibly for the common sub-100ms case.

Positioned at the bottom-right of the WORK AREA (screen minus the taskbar),
not the raw screen bottom edge — Windows docks the taskbar there by default,
and a window placed at the literal screen edge would render UNDER it,
invisible. Simple and deliberately NOT click-through: at this size and
position (hugging the work-area edge, where nothing is normally clicked) the
extra WS_EX_LAYERED/WS_EX_TRANSPARENT plumbing a true click-through window
needs isn't worth the added complexity or the known PyInstaller-packaging
click-through pitfall it would add.
"""
from __future__ import annotations

import logging
import queue
import threading

logger = logging.getLogger(__name__)

_QUEUE: "queue.Queue | None" = None
_THREAD: threading.Thread | None = None

_WIDTH = 160
_HEIGHT = 5
_MARGIN = 6
_FLASH_MS = 800
_COLOR = "#dba028"  # same amber as the tray icon's busy tint — one consistent
                    # "something's happening" colour across both signals.


def _work_area() -> tuple[int, int]:
    """(right, bottom) of the usable screen area, EXCLUDING the taskbar."""
    import ctypes
    from ctypes import wintypes

    rect = wintypes.RECT()
    SPI_GETWORKAREA = 0x0030
    ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
    return rect.right, rect.bottom


def _run(q: "queue.Queue") -> None:
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    try:
        root.attributes("-toolwindow", True)  # keep it off the taskbar/alt-tab
    except Exception:
        pass

    right, bottom = _work_area()
    x, y = right - _WIDTH - _MARGIN, bottom - _HEIGHT - _MARGIN
    root.geometry(f"{_WIDTH}x{_HEIGHT}+{x}+{y}")
    root.configure(bg=_COLOR)

    hide_job = [None]

    def show():
        if hide_job[0] is not None:
            root.after_cancel(hide_job[0])
        root.deiconify()
        hide_job[0] = root.after(_FLASH_MS, root.withdraw)

    def poll():
        try:
            while True:
                q.get_nowait()
                show()
        except queue.Empty:
            pass
        root.after(50, poll)

    root.after(50, poll)
    root.mainloop()


def start() -> None:
    """Start the overlay's own dedicated thread once (idempotent — a no-op on
    later calls). Best-effort: any failure (no display, tkinter unavailable)
    is swallowed silently — the tray icon's own busy-tint still works
    without this, it's a supplementary signal, not the only one."""
    global _QUEUE, _THREAD
    if _THREAD is not None:
        return
    try:
        q: "queue.Queue" = queue.Queue()
        t = threading.Thread(target=_run, args=(q,), name="status-overlay", daemon=True)
        t.start()
        _QUEUE, _THREAD = q, t
    except Exception:
        logger.debug("status overlay failed to start", exc_info=True)
        _QUEUE, _THREAD = None, None


def flash() -> None:
    """Trigger the flash from ANY thread. No-op if start() wasn't called or
    failed to come up."""
    if _QUEUE is not None:
        try:
            _QUEUE.put_nowait(None)
        except Exception:
            pass
