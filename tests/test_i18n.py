"""Tests for i18n.py -- every key has all three languages, and the fallback
chain (missing language -> English -> raw key) never raises."""
from pii_blur import i18n
from pii_blur.config import Settings


def test_default_language_is_uzbek():
    assert i18n.DEFAULT_LANGUAGE == "uz"
    assert Settings().language == "uz"


def test_every_string_has_all_three_languages():
    for key, entry in i18n._STRINGS.items():
        for lang in ("uz", "en", "ru"):
            assert lang in entry and entry[lang], f"{key} missing {lang}"


def test_lookup_known_key():
    assert i18n.t("menu_quit", "uz") == "Chiqish"
    assert i18n.t("menu_quit", "en") == "Quit"
    assert i18n.t("menu_quit", "ru") == "Выход"


def test_unknown_language_falls_back_to_english():
    assert i18n.t("menu_quit", "fr") == "Quit"


def test_unknown_key_returns_the_key_itself():
    assert i18n.t("not_a_real_key", "uz") == "not_a_real_key"


def test_languages_dict_has_entries_for_every_translated_language():
    for lang in ("uz", "en", "ru"):
        assert lang in i18n.LANGUAGES
