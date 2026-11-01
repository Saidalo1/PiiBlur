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

from pii_blur import i18n
from pii_blur.config import Settings
from pii_blur.watcher import Control, run

logger = logging.getLogger(__name__)


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
                        icon.notify(i18n.t("toast_flash_intro", settings.language), "PiiBlur")
                    except Exception:
                        pass
                    onboarding.mark_seen("flash_intro")
                status_overlay.flash()

    from pii_blur import gui
    # gui.start() also attaches the status-overlay flash to the SAME Tk root
    # it builds (see status_overlay.py's module docstring for why they can't
    # each run their own independent Tk interpreter/thread). `on_pause_change`
    # is a lambda (not `set_icon` directly) because `set_icon` isn't defined
    # yet at this point in main() -- fine, since gui.py only ever CALLS it
    # later (after the pause icon in its OWN window is clicked), by which
    # time set_icon below has long since been defined.
    gui.start(settings, control, on_pause_change=lambda: set_icon())

    # Real complaint: after install, the app silently vanishes into the tray
    # with zero visible confirmation it's actually running -- no window, no
    # animation, nothing (a hidden-icons tray overflow makes even the icon
    # itself easy to miss). Open Settings once, automatically, the very
    # first time the app ever runs, purely so the user SEES it start --
    # never again after that (onboarding.seen/mark_seen, same mechanism as
    # the one-time flash toast above).
    from pii_blur import onboarding as _onboarding
    if not _onboarding.seen("first_run_settings"):
        gui.request_open()
        _onboarding.mark_seen("first_run_settings")

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

    def open_settings(_icon, item):
        gui.request_open()

    def quit_app(_icon, item):
        control.stop.set()
        icon.stop()

    # Every item's text is a callable (not a plain string) so the menu re-reads
    # `settings.language` fresh each time it's opened -- changing the language
    # in Settings takes effect immediately, no restart needed.
    def _s(key):
        return lambda item: i18n.t(key, settings.language)

    # Just Pause/Resume, Settings, and Quit -- every actual toggle (names,
    # smart model, faces, autostart) lives in the Settings window now (with
    # its own hover explanations), not duplicated here too. A right-click
    # menu crammed with every option is harder to scan, not more convenient.
    icon.menu = pystray.Menu(
        pystray.MenuItem(lambda item: i18n.t("menu_resume" if control.paused else "menu_pause",
                                              settings.language), toggle_pause),
        pystray.MenuItem(_s("menu_settings"), open_settings, default=True),
        pystray.MenuItem(_s("menu_quit"), quit_app),
    )
    set_icon()
    logger.info("tray started — auto blur is ON")
    icon.run()


if __name__ == "__main__":
    main()
