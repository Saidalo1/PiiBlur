"""Glue: image in -> redacted image + the redaction list out.

Deliberately takes an `ocr_fn` so tests (and the review UI) can inject fake OCR
and never need a real engine. The default uses ocr.ocr_words.
"""
from __future__ import annotations

from PIL import Image

from pii_blur import detectors, redact
from pii_blur.config import DEFAULT, Settings


def process_image(img: Image.Image, settings: Settings = DEFAULT, ocr_fn=None):
    """Return (redacted_image, redactions). If no PII is found the image is
    returned unchanged and the list is empty (caller can skip the clipboard write)."""
    if ocr_fn is None:
        from pii_blur.ocr import ocr_words
        ocr_fn = lambda im: ocr_words(im, settings.ocr_langs)

    words = ocr_fn(img)
    redactions = detectors.detect(
        words,
        names=settings.detect_names,
        min_confidence=settings.min_confidence,
    )
    if not redactions:
        return img, []
    out = redact.apply(img, redactions, pad=settings.box_padding,
                       strength=settings.blur_strength)
    return out, redactions
