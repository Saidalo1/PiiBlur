"""Unit tests for PII detection — no OCR engine or screenshot needed.

We build synthetic OCR `Word`s (text + box) and assert what gets flagged. This is
how we lock in the tricky cases the research warned about: values SPLIT across
word boxes (spaced phone / grouped card) and over-redaction.
"""
from pii_blur.detectors import Word, detect, _dedupe_words, preprocess_words


def _row(texts, y=10, x0=10, w=40, h=20, gap=8):
    """Lay words left-to-right on one line with boxes."""
    words, x = [], x0
    for t in texts:
        words.append(Word(t, (x, y, w, h)))
        x += w + gap
    return words


def cats(reds):
    return sorted(r.category for r in reds)


def test_email():
    reds = detect(_row(["Email:", "ali@mail.uz"]))
    assert "email" in cats(reds)


def test_phone_split_across_boxes():
    # "+998 90 123 45 67" arrives as 5 separate OCR words — must still be caught
    # as ONE phone, and the redaction box must cover all 5.
    reds = detect(_row(["+998", "90", "123", "45", "67"]))
    phones = [r for r in reds if r.category == "phone"]
    assert len(phones) == 1
    assert phones[0].box[2] > 150  # union spans the whole number, not one word


def _luhn_complete(base15: str) -> str:
    """Append the Luhn check digit so the 16-digit number validates."""
    digits = [int(c) for c in base15]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:  # position of the future check digit shifts parity
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return base15 + str((10 - total % 10) % 10)


def test_card_luhn_pass_and_fail():
    valid = _luhn_complete("860006919540683")  # UzCard BIN 8600..., valid Luhn
    groups = [valid[0:4], valid[4:8], valid[8:12], valid[12:16]]
    assert any(r.category == "card" for r in detect(_row(groups)))
    bad = detect(_row(["8600", "0000", "0000", "0001"]))   # fails Luhn
    assert not any(r.category == "card" for r in bad)


def test_pinfl_structural():
    ok = detect(_row(["PINFL", "31505901234560"]))   # 3 | 15.05.90 | ... -> valid
    assert any(r.category == "pinfl" for r in ok)
    bad = detect(_row(["99999999999999"]))           # first digit 9 -> rejected
    assert not any(r.category == "pinfl" for r in bad)


def test_passport():
    reds = detect(_row(["Pasport:", "AD1234567"]))
    assert any(r.category == "passport" for r in reds)


def test_uzbek_name_patronymic():
    reds = detect(_row(["Mijoz:", "Karimov", "Alisher", "Botir", "o'g'li"]))
    names = [r for r in reds if r.category == "name"]
    assert names, "patronymic o'g'li should trigger a name redaction"
    # The whole name cluster should be covered, not just the suffix word.
    assert names[0].box[2] > 120


def test_names_can_be_disabled():
    words = _row(["Karimov", "Alisher", "o'g'li"])
    assert not any(r.category == "name" for r in detect(words, names=False))


def test_plain_text_not_redacted():
    # Ordinary words must NOT be flagged (guard against over-redaction).
    reds = detect(_row(["Bugun", "ob-havo", "yaxshi", "va", "issiq"]))
    assert reds == []


def test_lowercase_surname_suffix_mid_sentence_not_redacted():
    # Cyrillic/Latin -ov/-ev/-ova endings are ALSO ordinary genitive-plural word
    # endings ("контактов", "городов") — a capitalized one embedded in a longer
    # sentence must not be treated as a surname (this is the korvisa.uz privacy-
    # page false positive the user hit).
    reds = detect(_row(["Shuningdek,", "reklama", "va", "tahlil", "uchun",
                        "cookie", "va", "shunga", "o'xshash"]))
    assert not any(r.category == "name" for r in reds)
    reds2 = detect(_row(["CSV-import", "kontaktov", "bajarildi", "muvaffaqiyatli"]))
    assert not any(r.category == "name" for r in reds2)


def test_isolated_surname_alone_on_its_line_is_redacted():
    # A bare surname shown alone (a Telegram/CRM contact name, nothing else on its
    # row) IS a real name and should be caught even with no given-name neighbour —
    # this is the "Isroilov" case from the user's real chat list. Threshold passed
    # explicitly: this is what the app's default min_confidence (0.60) applies.
    reds = detect(_row(["Isroilov"]), min_confidence=0.60)
    assert any(r.category == "name" for r in reds)


def test_isolated_gazetteer_given_name_alone_is_redacted():
    # A bare given name alone on its row (no surname suffix at all) — e.g. "Timur"
    # shown as a contact's display name — should also be caught via the gazetteer.
    reds = detect(_row(["Timur"]), min_confidence=0.60)
    assert any(r.category == "name" for r in reds)


def test_gazetteer_name_mid_sentence_not_over_confident():
    # The same gazetteer word, embedded in a longer unrelated line (not isolated
    # on its own row), must NOT get the "isolated standalone name" boost — its
    # score (0.50) stays below the app's default min_confidence (0.60, applied by
    # Settings/pipeline — detect() itself defaults to 0.0), same as a lone
    # mid-sentence surname.
    reds = detect(_row(["Umid", "qilamizki", "barchasi", "yaxshi", "bo'ladi"]),
                  min_confidence=0.60)
    assert not any(r.category == "name" for r in reds)


def test_honorific_does_not_break_isolation():
    # Dual-language OCR often reads an honorific twice ("aka" + "ака") on the same
    # row as a bare contact name — that must not stop the name from being caught.
    reds = detect(_row(["Samandar", "aka", "ака", "(Idrok)"]), min_confidence=0.60)
    assert any(r.category == "name" and "Samandar" in r.text for r in reds)


def test_compound_name_with_gazetteer_suffix_is_redacted():
    # Many Uzbek names are compounds written as ONE word (a root prefix fused
    # onto a recognizable base name) — e.g. "Mir" + "alisher" = "Miralisher",
    # the user's real case. "alisher" is in the gazetteer but "Miralisher" isn't
    # an exact match, so this needs the suffix-compound check to catch it.
    reds = detect(_row(["Miralisher"]), min_confidence=0.60)
    assert any(r.category == "name" for r in reds)


def test_short_gazetteer_entries_do_not_match_as_compound_suffix():
    # The compound check only fires for long (>=5 char) gazetteer entries, so a
    # short one like "anna" (in the gazetteer) can't turn an unrelated word that
    # happens to end the same way into a false positive.
    reds = detect(_row(["Savanna"]), min_confidence=0.60)  # ends in "anna", not a name
    assert not any(r.category == "name" for r in reds)


def test_pinfl_survives_confusable_cyrillic_duplicate_digits():
    # Real bug from the user's own demo screenshot: dual-language OCR (en-US +
    # ru) sometimes reads the SAME glyph twice — once correctly as a Latin
    # digit, once as a visually-identical Cyrillic letter ("3"/"З", "0"/"О") at
    # the exact same box — which isn't caught by plain exact-text dedup (the
    # strings genuinely differ) and corrupts the 14-digit PINFL pattern:
    # "3 150590 123 456 0" arrived as "3 З 150590 123 456 0 О". Build that
    # exact corrupted word list and confirm PINFL is still found.
    words = [
        Word("PINFL:", (0, 10, 50, 20)),
        Word("3", (60, 10, 10, 20)),
        Word("З", (60, 10, 10, 20)),       # Cyrillic look-alike, same box
        Word("150590", (75, 10, 60, 20)),
        Word("123", (140, 10, 30, 20)),
        Word("456", (175, 10, 30, 20)),
        Word("0", (210, 10, 10, 20)),
        Word("О", (210, 10, 10, 20)),       # Cyrillic look-alike, same box
    ]
    reds = detect(words, min_confidence=0.0)
    assert any(r.category == "pinfl" for r in reds)


def test_ambiguous_word_name_homonym_bare_not_flagged():
    # Real false positive from a user's screenshot: "Mamlakat" is both a real
    # Uzbek given name AND the ordinary word for "country" -- in an everyday
    # form label ("Mamlakat — O'zbekiston tanlandi" = "Country — Uzbekistan
    # selected") it must NOT be flagged just because it's gazetteer-listed.
    reds = detect(_row(["Mamlakat", "—", "O'zbekiston", "tanlandi"]), min_confidence=0.60)
    assert not any(r.category == "name" for r in reds)


def test_ambiguous_word_name_homonym_still_caught_with_surname():
    # The same word, next to a REAL surname, is still a real full name and
    # must still be caught -- the ambiguity guard only blocks it from
    # anchoring ALONE, not from completing a genuine name cluster.
    reds = detect(_row(["Mamlakat", "Yusupova"]), min_confidence=0.60)
    assert any(r.category == "name" and "Mamlakat" in r.text for r in reds)


def test_ordinary_word_ending_in_ov_not_rescued_by_unrelated_capitalized_word():
    # Real false positive: "to'lov" ("payment") ends in "-ov" and sat next to
    # "Standard" (an English/tech term, not a name) in a bilingual Uzbek+
    # English tech document. The lowercase-surname rescue must require the
    # neighbour to be a REAL anchor (an actual name), not just any capitalized
    # word, or ordinary tech vocabulary next to Uzbek grammar gets flagged.
    reds = detect(_row(["bo'lmasa", "—", "Standard", "S0", "haqiqiy"]), min_confidence=0.60)
    assert not any(r.category == "name" for r in reds)


def test_numbers_and_weekdays_in_gazetteer_not_flagged_bare():
    # Found via a systematic scan (cross-referencing the full ~11.6k name list
    # against a real Uzbek dictionary, uz-hunspell): numbers and weekday names
    # are ALSO listed as rare given names in the gazetteer, but they appear
    # constantly as ordinary vocabulary ("Besh ming so'm" = "5000 so'm",
    # "Juma kuni" = "on Friday") -- bare, they must not be flagged.
    for word in ("Besh", "Yetti", "Juma", "Shanba", "Hozir", "Katta"):
        reds = detect(_row([word]), min_confidence=0.60)
        assert not any(r.category == "name" for r in reds), word


def test_compound_name_containing_ambiguous_root_still_works():
    # "Gul" is ambiguous (also "flower"), but a compound like "Gulnora" is an
    # unambiguous real name and must be unaffected by the ambiguous-word guard
    # (the guard only applies to the BARE word, not names containing it).
    reds = detect(_row(["Gulnora", "Karimova"]), min_confidence=0.60)
    assert any(r.category == "name" and "Gulnora" in r.text for r in reds)


def test_garbled_duplicate_does_not_survive_dedup_over_the_clean_reading():
    # Real bug: dual-language OCR reading the same Cyrillic word produced "A6pop"
    # (mixed letters+digits, garbled) from one pass and "Аброр" (clean Cyrillic)
    # from the other, at the SAME box -- plain first-seen dedup kept whichever
    # came first regardless of quality. A word mixing letters and digits must
    # lose to a clean one at the same spot.
    garbled = Word("A6pop", (10, 10, 50, 17))
    clean = Word("Аброр", (10, 10, 50, 17))
    out = _dedupe_words([garbled, clean])
    assert len(out) == 1 and out[0].text == "Аброр"


def test_preprocess_words_is_idempotent():
    # preprocess_words() is now called once in the pipeline and detect() calls it
    # again internally on whatever it's handed -- must be safe to run twice.
    words = _row(["Karimov", "Alisher"])
    once = preprocess_words(words)
    twice = preprocess_words(once)
    assert [w.text for w in once] == [w.text for w in twice]
