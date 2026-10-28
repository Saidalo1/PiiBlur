"""Tests for the blur step: the box region must change, the rest must not."""
from PIL import Image

from pii_blur.detectors import Redaction
from pii_blur.redact import apply


def test_blur_only_target_region():
    img = Image.new("RGB", (200, 100), "white")
    # paint a readable-ish black bar where "PII" would be
    for x in range(40, 120):
        for y in range(40, 60):
            img.putpixel((x, y), (0, 0, 0))

    red = Redaction((40, 40, 80, 20), "phone", 0.95, "+998901234567")
    out = apply(img, [red], pad=2, strength=12)

    # Inside the box: pixels changed (no longer a crisp black bar).
    changed = sum(
        1 for x in range(40, 120) for y in range(40, 60)
        if out.getpixel((x, y)) != img.getpixel((x, y))
    )
    assert changed > 0

    # Far outside the box: untouched.
    assert out.getpixel((5, 5)) == (255, 255, 255)
    assert out.getpixel((190, 90)) == (255, 255, 255)


def test_no_redactions_returns_equivalent_image():
    img = Image.new("RGB", (50, 50), "white")
    out = apply(img, [])
    assert out.size == img.size
    assert out.getpixel((10, 10)) == (255, 255, 255)
