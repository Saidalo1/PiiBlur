"""Preprocessing for a PHOTOGRAPHED document (a phone photo of printed paper),
as opposed to a digital UI screenshot.

A screenshot is already perfectly level, evenly lit, and high-contrast —
upscaling (see ocr.py) is the only thing it ever needs. A phone photo of paper
is a different problem: slightly rotated, unevenly lit, lower effective
contrast between ink and paper. Plain upscaling doesn't fix any of that (it
just makes the same blur bigger) — this is the standard document-scanner
pipeline instead: deskew, then boost contrast, then binarize (push text to
pure black, background to pure white) so the OCR engine sees a clean, level,
high-contrast page. This is deliberately pure PIL + numpy (both already
dependencies) — no OpenCV/scikit-image, to keep the installer small.

Not a universal fix: a severely degraded photo (heavy blur, very small
effective font size) stays hard to read even after this — deskew/contrast/
binarize recover what the capture lost to ANGLE and LIGHTING, not detail that
was never captured. Used as a conditional SECOND pass (see ocr.py) only when
the first, plain OCR pass looks unreliable, so it never costs a clean
screenshot anything.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter, ImageOps


def _deskew_angle(gray: Image.Image, max_angle: float = 5.0, step: float = 0.5) -> float:
    """Projection-profile deskew: try small rotation angles and pick the one
    that maximizes the variance of row-wise pixel-intensity sums. Text forms
    sharp alternating light/dark horizontal bands (the gaps between text
    lines) exactly when the lines are level; any skew blurs those bands
    together, lowering the variance. Reliable up to the +/-5 degree range a
    hand-held phone photo typically has — a page photographed badly crooked
    needs real perspective correction, out of scope here."""
    arr = np.asarray(gray, dtype=np.float32)
    best_angle, best_score = 0.0, float(arr.sum(axis=1).var())
    angle = -max_angle
    while angle <= max_angle:
        if angle != 0:
            rotated = gray.rotate(angle, resample=Image.BICUBIC, fillcolor=255)
            a = np.asarray(rotated, dtype=np.float32)
        else:
            a = arr
        score = float(a.sum(axis=1).var())
        if score > best_score:
            best_score, best_angle = score, angle
        angle += step
    return best_angle


def enhance_for_scan(img: Image.Image) -> Image.Image:
    """Deskew + contrast-boost + adaptively binarize a photographed document.
    Returns an RGB image (so callers don't need to special-case mode) ready
    for OCR. Order matters: deskewing on a greyscale (not yet binarized) image
    keeps the gradient information the angle search needs; binarizing first
    would throw that away."""
    gray = img.convert("L")
    angle = _deskew_angle(gray)
    if abs(angle) > 0.1:
        gray = gray.rotate(angle, resample=Image.BICUBIC, fillcolor=255)
    gray = ImageOps.autocontrast(gray, cutoff=1)

    # Adaptive (local-mean) binarization: a pixel is "ink" only if it's darker
    # than its OWN neighbourhood's average, not a single fixed cutoff for the
    # whole page -- this is what makes it robust to uneven lighting (one side
    # of a phone photo brighter than the other), unlike a single global
    # threshold. The blur radius is the neighbourhood size.
    arr = np.asarray(gray, dtype=np.float32)
    local_mean = np.asarray(gray.filter(ImageFilter.GaussianBlur(radius=15)), dtype=np.float32)
    binarized = np.where(arr > local_mean - 10, 255, 0).astype(np.uint8)
    return Image.fromarray(binarized, mode="L").convert("RGB")
