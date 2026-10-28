"""Run-on-login registration (HKCU Run key) — the 'installs itself' part.

On first launch the tray app adds itself here so it starts automatically with
Windows, with nothing for the user to configure. HKCU (current user) needs no
admin rights. A menu item / flag can remove it again.

Works both as a frozen .exe (uses the exe path) and when run from source
(pythonw -m pii_blur.tray).
"""
from __future__ import annotations

import sys

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_NAME = "PiiScreenshotBlur"


def _command() -> str:
    if getattr(sys, "frozen", False):          # bundled .exe
        return f'"{sys.executable}"'
    # from source: launch windowless via pythonw
    pyw = sys.executable.replace("python.exe", "pythonw.exe")
    return f'"{pyw}" -m pii_blur.tray'


def is_enabled() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
            winreg.QueryValueEx(k, _NAME)
        return True
    except OSError:
        return False


def enable() -> None:
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as k:
        winreg.SetValueEx(k, _NAME, 0, winreg.REG_SZ, _command())


def disable() -> None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, _NAME)
    except OSError:
        pass


def ensure_enabled_once() -> None:
    """Enable autostart on first run only (best-effort; never fatal)."""
    try:
        if not is_enabled():
            enable()
    except Exception:
        pass
