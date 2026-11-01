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

    # Preprocess ONCE (split multi-token OCR "words", dedupe cross-language
    # duplicates) and feed the SAME clean list to every detector below — doing
    # this only inside detect() left the model seeing raw words instead, which
    # let a duplicate-but-garbled OCR reading survive as its own false positive
    # (see preprocess_words' docstring for the concrete bug this fixes).
    words = detectors.preprocess_words(ocr_fn(img))
    # The neural model runs FIRST (when enabled) so its hits can corroborate the
    # gazetteer pass below -- a bare dictionary-word match ("Olim"="scholar" but
    # also a rare real name) only gets rescued to blur-worthy confidence when
    # isolated AND the model independently agrees it's a name; see detect_names'
    # docstring for the false-positive class this fixes (the same context-
    # corroboration pattern Presidio/Google DLP use for the identical ambiguity,
    # researched before implementing). The gazetteer still covers known names and
    # Cyrillic (which the Latin model can't read) on its own; overlapping boxes
    # from both sources are merged below so a name caught by both is blurred once.
    ner_redactions = []
    ner_boxes = frozenset()
    if settings.detect_names and settings.name_model:
        from pii_blur import ner_model, patterns
        ner_redactions = ner_model.detect_names_model(
            words, stopwords=patterns.UI_STOPWORDS)
        ner_boxes = frozenset(r.box for r in ner_redactions)
    redactions = detectors.detect(
        words,
        names=settings.detect_names,
        min_confidence=settings.min_confidence,
        ner_corroborated=ner_boxes,
    ) + ner_redactions
    if settings.detect_names and redactions:
        # Cross-source bridge: a lowercase surname sitting next to ANY already-
        # confirmed name (from the gazetteer OR the model) joins the cluster —
        # catches e.g. a Cyrillic surname next to a model-only-caught given name,
        # which the gazetteer's own (deliberately stricter) rescue can't see.
        redactions = redactions + detectors.rescue_adjacent_lowercase_surnames(
            words, redactions)
    if settings.blur_faces:
        from pii_blur import faces
        redactions = redactions + faces.detect_faces(img)
    redactions = _merge_overlaps(redactions)
    if not redactions:
        return img, []
    out = redact.apply(img, redactions, pad=settings.box_padding,
                       strength=settings.blur_strength)
    return out, redactions
