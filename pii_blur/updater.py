"""Self-update check against GitHub Releases.

Small-app pattern (not a heavyweight framework like Squirrel/WinSparkle):
query the GitHub Releases API for the latest tag, compare it to this build's
own version, and if newer, let the user trigger a download + install with one
click. Researched before building this (Presidio/DLP-style "don't guess"
discipline applied to infra too) -- this exact GitHub-Releases-API + version-
compare shape is a common, legitimate approach for small/indie Windows apps,
not a hack. See the asset's SHA-256 note on download_and_launch_installer for
the real security trade-off (no code-signing cert) and how it's mitigated.

Dev/source runs never check or offer an update -- only a frozen (PyInstaller)
build does; there's nothing sensible to "update" when running from source.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys

logger = logging.getLogger(__name__)

REPO = "Saidalo1/PiiBlur"
_API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
_ASSET_NAME = "PiiBlur_Setup_Net.exe"
_TIMEOUT = 6  # seconds -- never let a flaky connection delay startup noticeably


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _parse_version(v: str) -> tuple:
    """"v0.2.1" / "0.2.1" -> (0, 2, 1). Non-numeric parts are dropped rather
    than raising, so an unexpected tag format degrades to "no update" instead
    of crashing the check."""
    v = v.strip().lstrip("vV")
    parts = []
    for p in v.split("."):
        digits = "".join(c for c in p if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def check_for_update(current_version: str) -> dict | None:
    """Best-effort: returns {"tag", "download_url", "sha256"} if a newer
    release is published, else None (covers "up to date", "offline", "GitHub
    unreachable", "unexpected response shape" -- an update check must never
    be the reason the app fails to start or looks broken)."""
    if not is_frozen():
        return None
    try:
        import urllib.request
        import json as _json

        req = urllib.request.Request(_API_URL, headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = _json.loads(resp.read().decode("utf-8"))

        tag = data.get("tag_name", "")
        if not tag or _parse_version(tag) <= _parse_version(current_version):
            return None

        asset = next((a for a in data.get("assets", []) if a.get("name") == _ASSET_NAME), None)
        if not asset or not asset.get("browser_download_url"):
            return None

        # GitHub's API reports each asset's own server-computed checksum
        # ("sha256:<hex>") when available -- verifying the DOWNLOAD against
        # THIS (not a value baked into the release notes, which an attacker
        # with release-publish access could edit to match a tampered binary
        # just as easily) is the one meaningful integrity check possible
        # without a code-signing certificate. If GitHub doesn't report a
        # digest for this asset, sha256 is None and the download is skipped
        # (see download_and_launch_installer) rather than installed unverified.
        digest = asset.get("digest") or ""
        sha256 = digest.split(":", 1)[1] if digest.startswith("sha256:") else None

        return {"tag": tag, "download_url": asset["browser_download_url"], "sha256": sha256}
    except Exception:
        logger.debug("update check failed (non-fatal)", exc_info=True)
        return None


def download_and_launch_installer(download_url: str, sha256: str | None,
                                   on_progress=None) -> bool:
    """Downloads the new net installer to a temp file, verifies it against
    `sha256` (refuses to run it if that's missing or doesn't match -- fails
    CLOSED, never installs an unverified download), launches it, and returns
    True on success so the caller can quit the running app (the installer
    needs the old PiiBlur.exe not locked/running to overwrite its files).
    `on_progress(got_bytes, total_bytes)` is optional, called periodically."""
    import hashlib
    import tempfile
    import urllib.request

    if not sha256:
        logger.warning("update: no SHA-256 reported for this asset, refusing to install unverified")
        return False

    try:
        dest = os.path.join(tempfile.gettempdir(), "PiiBlur_Setup_Net.exe")
        req = urllib.request.Request(download_url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            got = 0
            hasher = hashlib.sha256()
            with open(dest, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    hasher.update(chunk)
                    got += len(chunk)
                    if on_progress:
                        on_progress(got, total)

        if hasher.hexdigest().lower() != sha256.lower():
            logger.warning("update: downloaded file's checksum doesn't match, discarding")
            try:
                os.remove(dest)
            except Exception:
                pass
            return False

        # /SILENT (not /VERYSILENT): the real purpose of running the
        # installer interactively is so the user SEES the familiar setup UI
        # instead of their app just vanishing and a new one appearing, which
        # would look like a crash or, worse, malware replacing itself.
        subprocess.Popen([dest, "/SILENT"], close_fds=True)
        return True
    except Exception:
        logger.exception("update: download/launch failed")
        return False
