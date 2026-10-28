"""Apply redactions to an image.

Blur is the default (looks less aggressive than a black box and is what the user
asked for), but a strong blur must be IRREVERSIBLE — a light Gaussian can be
undone/guessed, so we also downsample ("pixelate") hard before blurring. A little
padding around each box hides character edges the box might miss by a pixel.
"""
from __future__ import annotations

from PIL import Image, ImageFilter

from pii_blur.detectors import Redaction


def _clamp_box(box, w, h, pad):
    x, y, bw, bh = box
    x0 = max(0, int(x) - pad)
    y0 = max(0, int(y) - pad)
    x1 = min(w, int(x + bw) + pad)
    y1 = min(h, int(y + bh) + pad)
    return x0, y0, x1, y1


def blur_region(img: Image.Image, x0, y0, x1, y1, strength: int = 12) -> None:
    """Pixelate then blur a region in place — irreversible obfuscation."""
    if x1 <= x0 or y1 <= y0:
        return
    region = img.crop((x0, y0, x1, y1))
    # Pixelate: shrink to a few blocks, blow back up (destroys the actual glyphs).
    small_w = max(1, (x1 - x0) // max(4, strength))
    small_h = max(1, (y1 - y0) // max(4, strength))
    region = region.resize((small_w, small_h), Image.BILINEAR).resize(
        (x1 - x0, y1 - y0), Image.NEAREST
    )
    region = region.filter(ImageFilter.GaussianBlur(radius=max(2, strength // 2)))
    img.paste(region, (x0, y0))


def apply(img: Image.Image, redactions: list[Redaction], *, pad: int = 3,
          strength: int = 12) -> Image.Image:
    """Return a copy of `img` with every redaction box obfuscated."""
    out = img.convert("RGB").copy()
    w, h = out.size
    for r in redactions:
        x0, y0, x1, y1 = _clamp_box(r.box, w, h, pad)
        blur_region(out, x0, y0, x1, y1, strength)
    return out
