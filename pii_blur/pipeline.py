"""Glue: image in -> redacted image + the redaction list out.

Deliberately takes an `ocr_fn` so tests (and the review UI) can inject fake OCR
and never need a real engine. The default uses ocr.ocr_words.
"""
from __future__ import annotations

from PIL import Image

from pii_blur import detectors, redact
from pii_blur.config import DEFAULT, Settings


def _merge_overlaps(redactions):
    """Drop a redaction whose box is (almost) covered by another of the same kind —
    e.g. a name caught by BOTH the gazetteer and the neural model. Keeps the list
    tidy so the same region isn't blurred twice / logged twice."""
    out = []
    for r in sorted(redactions, key=lambda r: r.box[2] * r.box[3], reverse=True):
        rx, ry, rw, rh = r.box
        dup = False
        for k in out:
            if k.category != r.category:
                continue
            kx, ky, kw, kh = k.box
            ix = max(0, min(rx + rw, kx + kw) - max(rx, kx))
            iy = max(0, min(ry + rh, ky + kh) - max(ry, ky))
            if ix * iy >= 0.6 * (rw * rh):
                dup = True
                break
        if not dup:
            out.append(r)
    return out


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
    # Hybrid name detection: the neural model adds names the gazetteer/rules can't
    # know (unlisted surnames, lowercase handles). The gazetteer still covers known
    # names and Cyrillic (which the Latin model can't read); overlapping boxes are
    # merged below so a name caught by both is blurred once.
    if settings.detect_names and settings.name_model:
        from pii_blur import ner_model, patterns
        redactions = redactions + ner_model.detect_names_model(
            words, stopwords=patterns.UI_STOPWORDS)
    if settings.blur_faces:
        from pii_blur import faces
        redactions = redactions + faces.detect_faces(img)
    redactions = _merge_overlaps(redactions)
    if not redactions:
        return img, []
    out = redact.apply(img, redactions, pad=settings.box_padding,
                       strength=settings.blur_strength)
    return out, redactions
