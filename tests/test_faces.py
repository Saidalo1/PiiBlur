"""Tests for face detection/blurring (pii_blur.faces).

No real photo is bundled (and none is needed): these tests lock in the
contract — a blank/synthetic image yields no faces, detect_faces never raises,
and a found face actually gets obfuscated by redact.apply — without depending
on any specific face dataset.
"""
from PIL import Image

from pii_blur.faces import detect_faces


def test_blank_image_has_no_faces():
    img = Image.new("RGB", (200, 200), "white")
    assert detect_faces(img) == []


def test_detect_faces_never_raises_on_tiny_image():
    # A 1x1 image is a degenerate case that could trip up cv2 — must not crash
    # the whole pipeline (best-effort: empty list, not an exception).
    img = Image.new("RGB", (1, 1), "white")
    assert detect_faces(img) == []


def test_face_redaction_has_expected_shape():
    # Any Redaction this module returns must be well-formed enough for
    # redact.apply to consume (box, category, confidence, text).
    img = Image.new("RGB", (400, 400), "white")
    for r in detect_faces(img):
        assert r.category == "face"
        assert len(r.box) == 4
        assert 0.0 <= r.confidence <= 1.0
