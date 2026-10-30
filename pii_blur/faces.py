"""Face detection — blurs people's faces in a screenshot, not just text PII.

Uses OpenCV's YuNet (cv2.FaceDetectorYN) — a small (~230 KB), MIT-licensed ONNX
model from the official opencv_zoo project, bundled under assets/. It replaced
an earlier Haar-cascade version: testing on the user's real screenshots found
Haar both MISSED real faces (small/backlit avatar photos) and FALSELY flagged
plain colored-circle "letter" avatars (Telegram's default avatar for a contact
with no photo) as faces — a well-documented weakness of the 2001-era Haar
algorithm. YuNet fixed both: it caught every real face Haar missed in testing,
AND scored 0/26 false positives on synthetic letter-avatars (every letter,
several background colors) where Haar had false-positived. It also runs in
roughly 1/5 the time of Haar. Still tiny and CPU-only — no GPU, no network call
(the model ships inside the app), the right fit for an instant-reacting tray app.

On by default, toggleable in Settings/the tray menu — face detection is still a
different kind of guess than exact-match text PII, so a miss on an extremely
small or obscured face remains possible.
"""
from __future__ import annotations

import os
import sys

from pii_blur.detectors import Redaction

_DETECTOR = None  # built once, reused — loading the ONNX model per call is wasteful
_SCORE_THRESHOLD = 0.5  # calibrated against real screenshots: 0.5 caught every
                         # true face in testing (including two side-profile/
                         # low-light shots scoring ~0.58) with zero false
                         # positives on synthetic icon/letter-avatars.


def _model_path() -> str:
    """Path to the bundled YuNet ONNX model (works frozen via _MEIPASS and from
    source)."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", "face_detection_yunet.onnx")


def _detector():
    global _DETECTOR
    if _DETECTOR is None:
        import cv2
        # input_size is set per-image in detect_faces(); (0, 0) here is a
        # placeholder since FaceDetectorYN_create requires some initial size.
        _DETECTOR = cv2.FaceDetectorYN_create(
            _model_path(), "", (320, 320), score_threshold=_SCORE_THRESHOLD)
    return _DETECTOR


def detect_faces(img) -> list[Redaction]:
    """Return a Redaction per detected face (category='face'). Best-effort: any
    failure (missing OpenCV, missing model file, bad image) returns an empty list
    rather than raising — a screenshot with text PII should still get blurred even
    if face detection has a problem."""
    try:
        import cv2
        import numpy as np

        arr = np.array(img.convert("RGB"))
        bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        h, w = bgr.shape[:2]
        if h < 1 or w < 1:
            return []
        det = _detector()
        det.setInputSize((w, h))
        _, faces = det.detect(bgr)
        if faces is None:
            return []
        out = []
        for f in faces:
            x, y, fw, fh, score = int(f[0]), int(f[1]), int(f[2]), int(f[3]), float(f[-1])
            out.append(Redaction((x, y, fw, fh), "face", score, "face"))
        return out
    except Exception:
        return []
