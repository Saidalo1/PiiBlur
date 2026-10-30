"""Face detection — blurs people's faces in a screenshot, not just text PII.

Uses OpenCV's bundled Haar cascade (frontal face). It's the lightweight classic
choice: no extra download, no GPU, a few milliseconds per screenshot on CPU — the
right trade-off for a background tray app that must react instantly. It isn't as
accurate as a modern deep model (profile/angled faces, very small/blurry faces can
be missed), but it has zero extra install weight since OpenCV already ships as a
RapidOCR dependency, and it never phones out.

Off by default — face blurring is a different kind of guess than text PII (no
exact match, just "this looks like a face"), so it's an opt-in toggle in Settings/
the tray menu rather than silently changing what gets blurred.
"""
from __future__ import annotations

from pii_blur.detectors import Redaction

_CASCADE = None  # built once, reused — loading the XML file per call is wasteful


def _cascade():
    global _CASCADE
    if _CASCADE is None:
        import cv2
        path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        _CASCADE = cv2.CascadeClassifier(path)
    return _CASCADE


def detect_faces(img) -> list[Redaction]:
    """Return a Redaction per detected face (category='face'). Best-effort: any
    failure (missing OpenCV, bad image) returns an empty list rather than raising —
    a screenshot with text PII should still get blurred even if face detection has
    a problem."""
    try:
        import cv2
        import numpy as np

        arr = np.array(img.convert("RGB"))
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        # minNeighbors=6 (stricter than the OpenCV default of 3) trades a few
        # missed faces for far fewer false positives on UI icons/avatars — the
        # same "don't over-blur" bias as the text detectors.
        boxes = _cascade().detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=6, minSize=(24, 24))
        return [
            Redaction((int(x), int(y), int(w), int(h)), "face", 0.70, "face")
            for (x, y, w, h) in boxes
        ]
    except Exception:
        return []
