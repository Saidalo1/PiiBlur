"""Tests for the neural name pass (pii_blur.ner_model) and the hybrid wiring.

These don't assert specific model predictions (that's measured separately on real
screenshots) — they lock in the CONTRACT: the model pass is best-effort (never
raises), only ever emits 'name' redactions, and the UI stoplist / pipeline merge
behave. If the model files are present the import works; if not, it degrades to [].
"""
from PIL import Image

from pii_blur import patterns
from pii_blur.config import Settings
from pii_blur.detectors import Redaction, Word, rescue_adjacent_lowercase_surnames
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


def test_model_pass_drops_very_short_tokens():
    # Real Uzbek/Russian given names are never 1-2 letters; this filters out the
    # short OCR-noise fragments the model occasionally mistags on garbled text.
    reds = detect_names_model(_row(["Zi"]), stopwords=patterns.UI_STOPWORDS)
    assert reds == []


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


def test_rescue_bridges_a_model_only_name_to_an_adjacent_surname():
    # Real bug: a Cyrillic given name the MODEL alone catches (the Latin-biased
    # gazetteer rules have no anchor for it) sat next to a lowercase Cyrillic
    # surname that the gazetteer's own rescue couldn't reach either, since that
    # rescue only trusts RULES anchors (by design, to stop unrelated capitalized
    # words like "Standard" from rescuing "to'lov"). This cross-source bridge
    # runs after both detectors, so it sees the model's confirmed name too.
    words = row = _row(["Аброр", "абламидов"])
    model_only = [Redaction(words[0].box, "name", 0.66, "Аброр")]  # as if the
    # model (not the gazetteer) found the given name — rules never anchor it
    rescued = rescue_adjacent_lowercase_surnames(words, model_only)
    assert any("абламидов" in r.text for r in rescued)


def test_education_form_words_not_flagged_as_names():
    # Real false positive: a university group/schedule table has a "Ta'lim
    # shakli" (education form) column whose only possible values are these
    # words -- never real Uzbek person names, but the model mistagged them when
    # sitting next to OCR noise from a narrow, close-cropped screenshot.
    for word in ("Kechki", "Kunduzgi", "Sirtqi", "Bakalavr"):
        reds = detect_names_model(_row([word]), stopwords=patterns.UI_STOPWORDS)
        assert reds == [], word


def test_roman_numeral_section_marker_prefix_not_flagged_as_name():
    # Real false positive: formal Uzbek essay outlines number sections
    # "I.Kirish:", "III.Xulosa." etc. with NO space after the period, so OCR
    # reads it as ONE token -- a plain stopword check against "kirish"/
    # "xulosa" alone never matched the actual token "I.Kirish". Also covers
    # the OCR confusable "III." -> "Ill." (capital I misread as lowercase l).
    for word in ("I.Kirish", "III.Xulosa", "Ill.Xulosa", "I.Quyosh"):
        reds = detect_names_model(_row([word]), stopwords=patterns.UI_STOPWORDS)
        assert reds == [], word


def test_ocr_garbled_ai_acronym_not_flagged_as_name():
    # Real false positive: OCR misread the capital "I" in "AI'ga" (dative case
    # of the "AI" acronym, common in tech-content screenshots) as lowercase
    # "l", producing "Al'ga" -- which reads exactly like a real Uzbek given
    # name plus its dative suffix ("Alisher'ga"), so the model flagged it.
    reds = detect_names_model(_row(["Ularni", "Al'ga", "tashladik"]),
                              stopwords=patterns.UI_STOPWORDS)
    assert reds == []


def test_uzbek_sentence_connectors_not_flagged_as_names():
    # Real false positive: ordinary Uzbek prose (not CRM/UI chrome) starts
    # sentences with these discourse connectors capitalized -- "Aynan" and
    # OCR-garbled "Abatta" (from "Albatta") were both flagged as names on a
    # real screenshot of plain text, since the stoplist had never covered
    # this category before.
    for word in ("Aynan", "Albatta", "Abatta", "Lekin", "Chunki", "Masalan"):
        reds = detect_names_model(_row([word, "shu", "muammoni"]), stopwords=patterns.UI_STOPWORDS)
        assert reds == [], word


def test_crm_sidebar_label_not_flagged_as_name():
    # Real false positive from a KORVISA CRM sidebar screenshot: "Mijozlar"
    # ("Clients") is a plain menu label, but the model flagged it when fed
    # real OCR context -- a stray garbled icon-glyph token ("0)") sitting on
    # the same line shifted the model's prediction, even though the bare word
    # alone never reproduced it in isolation. The UI stoplist is what actually
    # filters the model pass, and only had the singular "mijoz", not this
    # plural sidebar form.
    reds = detect_names_model(_row(["0)", "Mijozlar"]), stopwords=patterns.UI_STOPWORDS)
    assert reds == []


def test_rescue_does_not_fire_without_a_real_confirmed_name_nearby():
    # No existing name redaction at all -> nothing to bridge to, even if a
    # lowercase surname-suffix word is present.
    words = _row(["импорт", "контактов"])
    assert rescue_adjacent_lowercase_surnames(words, []) == []
