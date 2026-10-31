"""Tests for the on_busy callback in watcher.run() -- the tray icon's "working"
state hook. Drives one watch iteration against a fake clipboard module, no real
Windows clipboard or OCR engine needed."""
import threading
import time

from PIL import Image

from pii_blur import clipboard_win, watcher
from pii_blur.config import Settings
from pii_blur.watcher import Control


def _run_one_iteration(monkeypatch, img, process_fn):
    """Runs watcher.run() in a thread against a fake clipboard that reports one
    new image then never changes again; stops the loop once on_busy has fired
    both True and False (or after a short timeout)."""
    seqs = iter([1, 2, 2, 2, 2, 2, 2, 2])  # sequence changes once, then settles
    monkeypatch.setattr(clipboard_win, "sequence_number", lambda: next(seqs, 2))
    monkeypatch.setattr(clipboard_win, "get_image", lambda: img)
    monkeypatch.setattr(clipboard_win, "set_image", lambda im: None)
    monkeypatch.setattr(watcher, "process_image", process_fn)

    events = []
    done = threading.Event()

    def on_busy(is_busy):
        events.append(is_busy)
        if len(events) >= 2:
            done.set()

    control = Control()
    settings = Settings(auto=True, poll_seconds=0.02)
    t = threading.Thread(target=watcher.run,
                         args=(settings,), kwargs={"control": control, "on_busy": on_busy},
                         daemon=True)
    t.start()
    done.wait(timeout=2.0)
    control.stop.set()
    t.join(timeout=1.0)
    return events


def test_on_busy_fires_true_then_false_around_processing(monkeypatch):
    img = Image.new("RGB", (10, 10), "white")
    events = _run_one_iteration(monkeypatch, img, lambda im, s: (im, []))
    assert events[:2] == [True, False]


def test_on_busy_still_fires_false_when_process_image_raises(monkeypatch):
    img = Image.new("RGB", (10, 10), "white")

    def boom(im, s):
        raise RuntimeError("engine blew up")

    events = _run_one_iteration(monkeypatch, img, boom)
    assert events[:2] == [True, False]
