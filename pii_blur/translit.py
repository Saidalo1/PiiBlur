"""Cyrillic -> Latin transliteration (Uzbek + Russian).

A cheap bridge for the Latin-only neural name model: transliterate a Cyrillic
word to Latin, and both the model AND the Latin gazetteer can read it ("Аброр" ->
"Abror"). It's a stopgap until the dual-script (mmBERT) model lands — and even
after, it keeps the gazetteer working on Cyrillic input.

Not meant to be perfect orthography: it only needs to produce a Latin form close
enough for name matching. Uzbek official Latin rules where they differ from
Russian (ў->o', қ->q, ғ->g', ҳ->h); Russian multi-letter forms (щ->sch, ю->yu…).
"""
from __future__ import annotations

_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "'", "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    # Uzbek-specific Cyrillic letters
    "ў": "o'", "қ": "q", "ғ": "g'", "ҳ": "h", "ъ": "'",
}


def is_cyrillic(text: str) -> bool:
    """True if the word is predominantly Cyrillic letters."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    cyr = sum(1 for c in letters if "Ѐ" <= c.lower() <= "ӿ")
    return cyr >= len(letters) * 0.6


def transliterate(text: str) -> str:
    """Cyrillic -> Latin. Non-Cyrillic chars pass through. Preserves the word's
    leading capitalization so the result still looks like a proper name."""
    out = []
    for ch in text:
        low = ch.lower()
        rep = _MAP.get(low)
        if rep is None:
            out.append(ch)
            continue
        if ch.isupper() and rep:
            rep = rep[0].upper() + rep[1:]
        out.append(rep)
    return "".join(out)
