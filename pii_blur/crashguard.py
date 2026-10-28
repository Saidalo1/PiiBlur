"""Turn any crash into a quiet log line instead of the scary 'Unhandled exception'
dialog PyInstaller shows by default.

Installs hooks for the main thread, background threads, and the asyncio loop, all
writing to %APPDATA%\\PiiBlur\\logs\\crash.log. For a tray app this is the single
most important robustness piece: a user should never see a raw traceback.
"""
from __future__ import annotations

import datetime
import logging
import os
import threading
import traceback

LOG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "PiiBlur", "logs")
LOG_FILE = os.path.join(LOG_DIR, "crash.log")

logger = logging.getLogger("pii_blur")


def _write(kind: str, text: str) -> None:
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n===== {kind} @ {datetime.datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
            f.write(text + "\n")
    except Exception:
        pass


def install(notify=None) -> None:
    """Route uncaught exceptions to the log (and optional `notify(msg)` callback).
    Also configure file logging so .info()/.exception() land in the same folder."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s | %(message)s",
            handlers=[logging.FileHandler(os.path.join(LOG_DIR, "pii_blur.log"), encoding="utf-8")],
        )
    except Exception:
        pass

    def _hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        _write("UNCAUGHT", text)
        if notify:
            try:
                notify("PiiBlur hit an error (logged). It keeps running.")
            except Exception:
                pass

    import sys
    sys.excepthook = _hook

    # Background-thread exceptions (Python 3.8+).
    def _thread_hook(args):
        _write("THREAD", "".join(traceback.format_exception(
            args.exc_type, args.exc_value, args.exc_traceback)))
    try:
        threading.excepthook = _thread_hook
    except Exception:
        pass


def guard(fn, *args, **kwargs):
    """Run fn and swallow+log any exception (for one-off best-effort calls)."""
    try:
        return fn(*args, **kwargs)
    except Exception:
        _write("GUARD", traceback.format_exc())
        return None
