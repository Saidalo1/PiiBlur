"""Smoke tests for scan_preprocess.py (deskew + contrast + binarize for a
photographed document). No OCR engine needed -- just checks the image
transform itself behaves: runs without crashing, keeps the image's size and
mode contract, and actually levels a rotated page."""
from PIL import Image, ImageDraw

from pii_blur.scan_preprocess import _deskew_angle, enhance_for_scan


def _text_like_image(angle: float = 0.0) -> Image.Image:
    """A synthetic 'page' of horizontal dark bars on white, optionally rotated --
    stands in for printed text lines without needing a real font/OCR fixture."""
    img = Image.new("L", (300, 200), 255)
    draw = ImageDraw.Draw(img)
    for y in range(20, 180, 20):
        draw.rectangle([20, y, 280, y + 8], fill=0)
    return img.rotate(angle, resample=Image.BICUBIC, fillcolor=255, expand=False)


def test_enhance_for_scan_returns_same_size_rgb():
    img = Image.new("RGB", (120, 80), "white")
    out = enhance_for_scan(img)
    assert out.size == img.size
    assert out.mode == "RGB"


def test_enhance_for_scan_runs_on_blank_image():
    # Must not crash on a degenerate (blank, zero-variance) image -- a real
    # possibility if the clipboard holds a solid-color screenshot.
    img = Image.new("RGB", (50, 50), "white")
    enhance_for_scan(img)  # no exception


def test_deskew_detects_a_rotated_page():
    # A page rotated by a few degrees should be detected close to that angle
    # (the correction then rotates it back level).
    rotated = _text_like_image(angle=3.0)
    angle = _deskew_angle(rotated)
    assert 1.5 <= abs(angle) <= 4.5


def test_deskew_leaves_a_level_page_alone():
    level = _text_like_image(angle=0.0)
    angle = _deskew_angle(level)
    assert abs(angle) <= 0.5
