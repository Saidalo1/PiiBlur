"""Persist Settings to %APPDATA%\\PiiBlur\\config.json (per-user, survives updates)."""
from __future__ import annotations

import json
import os
from dataclasses import asdict

from pii_blur.config import Settings

_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "PiiBlur")
_PATH = os.path.join(_DIR, "config.json")

# Only these fields are user-editable / persisted (the rest stay at defaults).
_KEYS = ("detect_names", "blur_faces", "min_confidence", "blur_strength", "auto",
         "poll_seconds")


def load() -> Settings:
    s = Settings(auto=True)  # tray default: silent auto
    try:
        with open(_PATH, encoding="utf-8") as f:
            data = json.load(f)
        for k in _KEYS:
            if k in data:
                setattr(s, k, data[k])
    except Exception:
        pass
    return s


def save(s: Settings) -> None:
    try:
        os.makedirs(_DIR, exist_ok=True)
        data = {k: getattr(s, k) for k in _KEYS}
        with open(_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass
