"""Tests for settings_store.py's persistence, isolated from the real
%APPDATA% path. Covers the new `language` field specifically -- it must round-
trip like the other persisted settings."""
from pii_blur import settings_store
from pii_blur.config import Settings


def test_language_round_trips(tmp_path, monkeypatch):
    path = str(tmp_path / "config.json")
    monkeypatch.setattr(settings_store, "_PATH", path)
    settings_store.save(Settings(language="ru"))
    loaded = settings_store.load()
    assert loaded.language == "ru"


def test_missing_file_defaults_to_uzbek(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_store, "_PATH", str(tmp_path / "nope.json"))
    assert settings_store.load().language == "uz"


def test_old_config_without_language_key_still_defaults_to_uzbek(tmp_path, monkeypatch):
    # A config.json saved before `language` existed (pre-upgrade users) must
    # still load cleanly and fall back to the default, not crash or leave an
    # unset attribute.
    path = tmp_path / "config.json"
    path.write_text('{"auto": true, "blur_strength": 10}', encoding="utf-8")
    monkeypatch.setattr(settings_store, "_PATH", str(path))
    loaded = settings_store.load()
    assert loaded.language == "uz"
    assert loaded.auto is True
