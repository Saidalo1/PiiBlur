"""Runtime settings. Kept tiny and in one place so the tray app can later expose
these as checkboxes (which PII types, blur strength, auto vs review)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Settings:
    # Detection
    detect_names: bool = True          # the fuzzy name pass (toggleable)
    min_confidence: float = 0.60       # drop weaker guesses below this
    # Redaction look
    blur_strength: int = 12
    box_padding: int = 3
    # Behaviour
    auto: bool = False                 # True = silent auto; False = review-first
    # Windows OCR language tags, tried and MERGED so Latin (Uzbek/English) and
    # Cyrillic (Russian) are both read. A tag whose language pack isn't installed
    # is skipped automatically.
    ocr_langs: tuple = ("en-US", "ru")
    poll_seconds: float = 0.4          # clipboard poll interval
    # A screenshot we just wrote back must not retrigger us (loop guard).
    skip_own_writes: bool = True


DEFAULT = Settings()
