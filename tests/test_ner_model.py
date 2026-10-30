"""Tests for the neural name pass (pii_blur.ner_model) and the hybrid wiring.

These don't assert specific model predictions (that's measured separately on real
screenshots) — they lock in the CONTRACT: the model pass is best-effort (never
raises), only ever emits 'name' redactions, and the UI stoplist / pipeline merge
behave. If the model files are present the import works; if not, it degrades to [].
"""
from PIL import Image

from pii_blur import patterns
from pii_blur.config import Settings
from pii_blur.detectors import Word
from pii_blur.ner_model import detect_names_model
from pii_blur.pipeline import _merge_overlaps, process_image


def _row(texts, y=10, x0=10, w=40, h=20, gap=8):
    words, x = [], x0
    for t in texts:
        words.append(Word(t, (x, y, w, h)))
        x += w + gap
    return words


def test_model_pass_never_raises_and_only_names():
    reds = detect_names_model(_row(["Alisher", "Karimov"]), stopwords=patterns.UI_STOPWORDS)
    assert all(r.category == "name" for r in reds)


def test_model_pass_empty_on_no_words():
    assert detect_names_model([], stopwords=patterns.UI_STOPWORDS) == []


def test_ui_stoplist_has_core_chrome():
    # The fixed-UI deny-list must cover the known chrome the model misfires on.
    for w in ("rad", "batafsil", "cookie", "voice", "message"):
        assert w in patterns.UI_STOPWORDS


def test_merge_overlaps_dedups_same_category():
    from pii_blur.detectors import Redaction
    a = Redaction((10, 10, 50, 20), "name", 0.7, "Ali")
    b = Redaction((12, 11, 46, 18), "name", 0.66, "Ali")   # ~inside a
    assert len(_merge_overlaps([a, b])) == 1


def test_merge_overlaps_keeps_different_categories():
    from pii_blur.detectors import Redaction
    a = Redaction((10, 10, 50, 20), "name", 0.7, "Ali")
    b = Redaction((10, 10, 50, 20), "face", 0.7, "face")
    assert len(_merge_overlaps([a, b])) == 2


def test_pipeline_runs_with_fake_ocr_and_model_default_on():
    # process_image with the default Settings (name_model=True) must work end to
    # end with injected OCR and not crash even if the model can't load.
    img = Image.new("RGB", (300, 60), "white")
    words = _row(["Karimov", "Alisher"])
    out, reds = process_image(img, Settings(blur_faces=False), ocr_fn=lambda im: words)
    assert isinstance(reds, list)
