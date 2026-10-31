"""Smoke tests for status_overlay.py -- just the parts that don't need an
actual display (work-area lookup, and that start()/flash() never raise even
in a headless/best-effort-fail environment)."""
from pii_blur import status_overlay


def test_work_area_returns_positive_ints():
    right, bottom = status_overlay._work_area()
    assert right > 0 and bottom > 0


def test_flash_before_start_is_a_safe_noop():
    # Calling flash() before (or if) start() never came up must never raise --
    # the overlay is a best-effort extra, not something that can break the
    # watcher loop that calls it.
    status_overlay._QUEUE = None
    status_overlay.flash()  # no exception
