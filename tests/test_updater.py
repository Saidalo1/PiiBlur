"""Tests for updater.py: version comparison and the security-relevant
fail-closed behaviors (no network calls are made in these tests -- real
GitHub API behavior is exercised manually, see the session's own verification
of the live /releases/latest endpoint)."""
from pii_blur import updater


def test_parse_version_basic():
    assert updater._parse_version("v0.2.1") == (0, 2, 1)
    assert updater._parse_version("0.10.0") == (0, 10, 0)


def test_parse_version_handles_garbage_without_raising():
    assert updater._parse_version("not-a-version") == (0,)


def test_newer_version_compares_correctly():
    assert updater._parse_version("v0.2.1") > updater._parse_version("0.2.0")
    assert updater._parse_version("v0.10.0") > updater._parse_version("0.9.9")
    assert not (updater._parse_version("v0.2.0") > updater._parse_version("0.2.0"))


def test_check_for_update_is_noop_when_not_frozen(monkeypatch):
    # Dev/source runs never check -- nothing sensible to self-update to.
    monkeypatch.setattr(updater, "is_frozen", lambda: False)
    assert updater.check_for_update("0.1.0") is None


def test_download_and_launch_refuses_without_sha256(monkeypatch):
    # Fails CLOSED: never installs an unverified download, even if the
    # download itself would otherwise succeed.
    called = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda *a, **k: called.append(1))
    ok = updater.download_and_launch_installer("https://example.invalid/x.exe", None)
    assert ok is False
    assert called == []
