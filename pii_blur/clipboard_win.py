"""Windows clipboard image get/set, with the retries real apps need.

OpenClipboard fails with "Access denied" (error 5) whenever ANOTHER process holds
the clipboard for a moment — extremely common right after a screenshot tool or a
paste. So every open is retried a few times with a short sleep, and CloseClipboard
always runs in `finally`. Lazy win32 imports — the core never needs this module.
"""
from __future__ import annotations

import io
import time

_RETRIES = 12
_SLEEP = 0.03  # ~0.36s worst case


def _open(win32clipboard):
    last = None
    for _ in range(_RETRIES):
        try:
            win32clipboard.OpenClipboard()
            return True
        except Exception as e:  # pywintypes.error: (5, 'OpenClipboard', 'Access denied')
            last = e
            time.sleep(_SLEEP)
    if last:
        raise last
    return False


def get_image():
    """Return a PIL.Image if the clipboard holds a bitmap, else None. Retries the
    grab because ImageGrab also opens the clipboard under the hood."""
    from PIL import Image, ImageGrab

    for _ in range(_RETRIES):
        try:
            data = ImageGrab.grabclipboard()
            if isinstance(data, Image.Image):
                return data
            return None  # text, file list, or empty — nothing to blur
        except Exception:
            time.sleep(_SLEEP)
    return None


def set_image(img) -> None:
    """Put a PIL image on the clipboard as CF_DIB."""
    import win32clipboard

    output = io.BytesIO()
    img.convert("RGB").save(output, "BMP")
    dib = output.getvalue()[14:]  # strip the 14-byte BMP file header; CF_DIB wants the DIB
    output.close()

    _open(win32clipboard)
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib)
    finally:
        win32clipboard.CloseClipboard()


def sequence_number() -> int:
    """Clipboard change counter — cheap, lets us notice a new copy and skip our own
    write. Returns -1 on the rare failure so the caller keeps polling."""
    import win32clipboard

    try:
        return win32clipboard.GetClipboardSequenceNumber()
    except Exception:
        return -1
