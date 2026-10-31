"""The background loop: watch the clipboard, redact new screenshots in place.

Uses the clipboard SEQUENCE NUMBER (not image polling) to notice a new copy
cheaply, and remembers the sequence number of our OWN write so we never re-blur
our own output (the infinite-loop trap of clipboard watchers).

Modes:
  * auto=True   -> blur and write back silently.
  * auto=False  -> hand (image, redactions) to `on_review`; the UI shows the
                   proposed blurs and calls `accept()` to write back. Safer:
                   a miss is visible before anything is "cleaned".
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from pii_blur.config import DEFAULT, Settings
from pii_blur.pipeline import process_image

logger = logging.getLogger(__name__)


@dataclass
class Control:
    """Lets the tray app pause/resume/stop the loop without killing the thread."""
    paused: bool = False
    stop: threading.Event = field(default_factory=threading.Event)


def run(settings: Settings = DEFAULT, on_review=None, control: Control | None = None,
        on_busy=None):
    """`on_busy`, if given, is called with True right before processing a newly
    pasted screenshot and False right after (success, no-PII, or error alike) --
    lets the tray swap its icon to a "working" state for the real duration of
    the blur, then back. Best-effort: never lets a UI-callback failure break
    the watch loop itself."""
    from pii_blur import clipboard_win as cb

    last_seq = cb.sequence_number()
    own_seq = -1
    logger.info("watcher started (auto=%s)", settings.auto)

    # Instant trigger: wake the loop the moment the clipboard changes, instead of
    # waiting out a poll interval. Polling stays as a fallback via the wait timeout,
    # so this only ever makes the reaction faster, never breaks it.
    wake = threading.Event()
    try:
        from pii_blur.clipboard_listener import ClipboardListener
        ClipboardListener(wake.set).start()
    except Exception:
        logger.info("clipboard listener unavailable; polling only", exc_info=True)

    while True:
        if control is not None and control.stop.is_set():
            logger.info("watcher stopped")
            return
        wake.wait(timeout=settings.poll_seconds)
        wake.clear()
        if control is not None and control.paused:
            continue
        try:
            seq = cb.sequence_number()
            if seq == last_seq:
                continue
            last_seq = seq
            if settings.skip_own_writes and seq == own_seq:
                continue

            img = cb.get_image()
            if img is None:
                continue

            if on_busy is not None:
                try:
                    on_busy(True)
                except Exception:
                    logger.debug("on_busy(True) callback failed", exc_info=True)
            try:
                redacted, redactions = process_image(img, settings)
            finally:
                if on_busy is not None:
                    try:
                        on_busy(False)
                    except Exception:
                        logger.debug("on_busy(False) callback failed", exc_info=True)
            if not redactions:
                continue

            logger.info("found %d PII region(s): %s", len(redactions),
                        ", ".join(f"{r.category}" for r in redactions))

            if settings.auto:
                cb.set_image(redacted)
                own_seq = cb.sequence_number()
            elif on_review is not None:
                def accept(final_img=redacted):
                    nonlocal own_seq
                    cb.set_image(final_img)
                    own_seq = cb.sequence_number()
                on_review(img, redacted, redactions, accept)
        except Exception:
            logger.exception("watcher iteration failed; continuing")
