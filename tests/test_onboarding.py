"""Tests for onboarding.py's one-time-flag persistence, isolated from the
real %APPDATA% path so test runs never touch (or depend on) the user's actual
onboarding state."""
import json

from pii_blur import onboarding


def test_unseen_key_defaults_false(tmp_path, monkeypatch):
    monkeypatch.setattr(onboarding, "_PATH", str(tmp_path / "onboarding.json"))
    assert onboarding.seen("flash_intro") is False


def test_mark_seen_persists_across_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(onboarding, "_PATH", str(tmp_path / "onboarding.json"))
    onboarding.mark_seen("flash_intro")
    assert onboarding.seen("flash_intro") is True


def test_mark_seen_preserves_other_keys(tmp_path, monkeypatch):
    path = tmp_path / "onboarding.json"
    monkeypatch.setattr(onboarding, "_PATH", str(path))
    onboarding.mark_seen("a")
    onboarding.mark_seen("b")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"a": True, "b": True}


def test_corrupt_file_does_not_raise(tmp_path, monkeypatch):
    path = tmp_path / "onboarding.json"
    path.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(onboarding, "_PATH", str(path))
    assert onboarding.seen("flash_intro") is False
    onboarding.mark_seen("flash_intro")  # must not raise
