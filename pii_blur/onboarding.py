"""One-time onboarding flags — persisted separately from settings_store.py's
config.json, since these aren't user-editable preferences, just "has this
one-time explanation already been shown" markers (e.g. explaining the amber
screen-corner flash the very first time it ever fires, see tray.py)."""
from __future__ import annotations

import json
import os

_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "PiiBlur")
_PATH = os.path.join(_DIR, "onboarding.json")


def seen(key: str) -> bool:
    try:
        with open(_PATH, encoding="utf-8") as f:
            return bool(json.load(f).get(key))
    except Exception:
        return False


def mark_seen(key: str) -> None:
    try:
        os.makedirs(_DIR, exist_ok=True)
        data = {}
        try:
            with open(_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
        data[key] = True
        with open(_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass
