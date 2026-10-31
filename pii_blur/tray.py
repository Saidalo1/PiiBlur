"""System-tray app — the real-use entry point.

Launch it and forget it: it sits in the tray, watches the clipboard, and after
every screenshot (Win+Shift+S / PrtSc → paste flow) silently replaces the
clipboard image with a PII-blurred one. You only notice it on Ctrl+V — the pasted
image is already clean. No window, no review step (you see the final image in
whatever app you paste into, e.g. Telegram Desktop).

Idle cost is ~zero: the loop only checks a cheap clipboard change-counter; OCR
runs only when a new image actually appears.

Run without a console window:
    pythonw -m pii_blur.tray
"""
from __future__ import annotations

import logging
import threading

from pii_blur.config import Settings
from pii_blur.watcher import Control, run

logger = logging.getLogger(__name__)


def _autostart_state() -> bool:
    try:
        from pii_blur import autostart
        return autostart.is_enabled()
    except Exception:
        return False


def _resource(name: str) -> str:
    """Path to a bundled data file (works frozen via _MEIPASS and from source)."""
    import os
    import sys
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def _icon_image(state: str = "active"):
    """The real app icon, tinted per state ("active" / "paused" / "busy");
    falls back to a drawn shield. "busy" briefly replaces "active" for the
    real duration of a screenshot being blurred — this IS the user-visible
    "it started / it's done" signal (the tray icon itself, bottom-right of the
    screen), chosen over a toast popup: a toast firing on every clipboard
    paste (potentially dozens of times a day) is exactly the kind of frequent,
    low-importance confirmation UX guidance says to suppress rather than pop
    up (see watcher.run's on_busy docstring for the research behind this)."""
    from PIL import Image, ImageDraw

    try:
        im = Image.open(_resource("app_icon.png")).convert("RGBA")
        if state == "active":
            return im
        if state == "busy":
            # A warm amber tint — visually distinct from both the full-colour
            # "active" icon and the desaturated-grey "paused" one, so the three
            # states read apart from each other at a glance, at tray-icon size.
            r, g, b, a = im.split()
            busy = Image.merge("RGBA", (r, g.point(lambda v: int(v * 0.65)),
                                        b.point(lambda v: int(v * 0.25)), a))
            return busy
        grey = im.convert("L").point(lambda v: int(v * 0.55)).convert("RGBA")
        grey.putalpha(im.split()[-1])  # keep the shield's transparency
        return grey
    except Exception:
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        color = {"active": (38, 150, 90), "busy": (219, 160, 40)}.get(state, (120, 120, 120))
        d.polygon([(32, 6), (56, 16), (56, 36), (32, 58), (8, 36), (8, 16)], fill=color)
        d.text((26, 22), "P", fill="white")
        return img


_SINGLE_INSTANCE_HANDLE = None  # keep the mutex alive for the process lifetime


def _already_running() -> bool:
    """True if another PiiBlur tray is already running (avoid double icons when
    autostart and a manual launch collide)."""
    global _SINGLE_INSTANCE_HANDLE
    try:
        import win32event
        import winerror

        _SINGLE_INSTANCE_HANDLE = win32event.CreateMutex(None, False, "PiiBlur_SingleInstance")
        import win32api
        return win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS
    except Exception:
        return False


def main():
    from pii_blur import crashguard
    crashguard.install()  # idempotent; also covers `python -m pii_blur.tray`

    if _already_running():
        logger.info("another instance is already running — exiting")
        return

    import pystray

    from pii_blur import autostart, settings_store

    settings = settings_store.load()  # persisted; defaults to silent auto
    crashguard.guard(autostart.ensure_enabled_once)  # run with Windows (first launch)
    control = Control()
    busy = threading.Event()

    def on_busy(is_busy: bool):
        # Called from the watcher thread; pystray's icon setter is safe to call
        # off the main thread. Never shows "busy" while paused -- the icon
        # already communicates "paused" and the watcher skips processing then
        # anyway, so this can only ever fire while actually active.
        busy.set() if is_busy else busy.clear()
        if not control.paused:
            set_icon()
            if is_busy:
                # Flash fires on START (not completion) -- the Doherty-
                # threshold point is confirming the paste was NOTICED within
                # the first few hundred ms, not visualizing how long the blur
                # takes (see status_overlay's own docstring).
                from pii_blur import onboarding, status_overlay
                # A plain colour flash with no text doesn't explain ITSELF --
                # research found that even Apple's own camera/mic dot, after
                # years of exposure, still confuses people ("what is this?").
                # One-time toast, the very first flash ever, then never again
                # -- explains it without becoming the habitual, fatiguing
                # per-paste popup the earlier research steered away from.
                if not onboarding.seen("flash_intro"):
                    try:
                        icon.notify(
                            "Если вы видите маленькую янтарную вспышку внизу "
                            "справа экрана — это PiiBlur: значит, скриншот "
                            "обработан.",
                            "PiiBlur",
                        )
                    except Exception:
                        pass
                    onboarding.mark_seen("flash_intro")
                status_overlay.flash()

    from pii_blur import status_overlay
    status_overlay.start()

    thread = threading.Thread(target=run, args=(settings,),
                              kwargs={"control": control, "on_busy": on_busy},
                              daemon=True)
    thread.start()

    # Prime the OCR engine in the background so the FIRST screenshot blurs fast
    # (otherwise the one-off model-load cost lands on the user's first paste).
    def _warm():
        from pii_blur import ocr
        ocr.warmup(settings.ocr_langs)
        if settings.name_model:
            from pii_blur import ner_model
            ner_model.warmup()
    threading.Thread(target=_warm, name="ocr-warmup", daemon=True).start()

    icon = pystray.Icon("pii_blur")

    def set_icon():
        if control.paused:
            icon.icon = _icon_image("paused")
        elif busy.is_set():
            icon.icon = _icon_image("busy")
        else:
            icon.icon = _icon_image("active")

    def toggle_pause(_icon, item):
        control.paused = not control.paused
        set_icon()

    def toggle_names(_icon, item):
        settings.detect_names = not settings.detect_names
        settings_store.save(settings)

    def toggle_faces(_icon, item):
        settings.blur_faces = not settings.blur_faces
        settings_store.save(settings)

    def toggle_model(_icon, item):
        settings.name_model = not settings.name_model
        settings_store.save(settings)

    def toggle_autostart(_icon, item):
        from pii_blur import autostart
        autostart.disable() if autostart.is_enabled() else autostart.enable()

    def open_settings(_icon, item):
        # tkinter wants its own thread here (pystray callbacks aren't the main thread).
        from pii_blur.gui import open_settings as show
        threading.Thread(target=show, args=(settings,), daemon=True).start()

    def quit_app(_icon, item):
        control.stop.set()
        icon.stop()

    icon.menu = pystray.Menu(
        pystray.MenuItem(lambda item: "Resume" if control.paused else "Pause", toggle_pause),
        pystray.MenuItem("Settings…", open_settings, default=True),
        pystray.MenuItem("Blur names (fuzzy)", toggle_names,
                         checked=lambda item: settings.detect_names),
        pystray.MenuItem("Smart name model (AI)", toggle_model,
                         checked=lambda item: settings.name_model),
        pystray.MenuItem("Blur faces", toggle_faces,
                         checked=lambda item: settings.blur_faces),
        pystray.MenuItem("Start with Windows", toggle_autostart,
                         checked=lambda item: _autostart_state()),
        pystray.MenuItem("Quit", quit_app),
    )
    set_icon()
    logger.info("tray started — auto blur is ON")
    icon.run()


if __name__ == "__main__":
    main()
