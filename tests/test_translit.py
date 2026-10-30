"""Tests for Cyrillic->Latin transliteration and the OCR-tolerant name canon."""
from pii_blur import patterns
from pii_blur.translit import is_cyrillic, transliterate


def test_transliterate_uzbek_and_russian():
    assert transliterate("Аброр") == "Abror"
    assert transliterate("Иванов") == "Ivanov"
    assert transliterate("Қодиров") == "Qodirov"       # Uzbek-specific қ
    assert transliterate("Ўктам").lower().startswith("o'")  # ў -> o'


def test_transliterate_preserves_latin_and_case():
    assert transliterate("Akram") == "Akram"            # Latin passes through
    assert transliterate("Сапарали")[0].isupper()


def test_is_cyrillic():
    assert is_cyrillic("Аброр")
    assert not is_cyrillic("Akram")
    assert not is_cyrillic("919666169")


def test_ocr_canon_folds_confusable_chars():
    # Capital-I misread for lowercase-l must canon to the same form.
    assert patterns.ocr_canon("MiraIisher") == patterns.ocr_canon("Miralisher")
    assert patterns.ocr_canon("Said0lim") == patterns.ocr_canon("Saidolim")  # 0 vs o


def test_ocr_canon_does_not_overmerge_distinct_names():
    # Folding is limited to i/l/1 and o/0, so clearly different names stay distinct.
    assert patterns.ocr_canon("Akram") != patterns.ocr_canon("Akbar")
