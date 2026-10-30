"""PII patterns — international (universal + UZ + RU), plus name heuristics.

Design rule that keeps the false-positive rate ~0: only match identifiers with a
DISTINCTIVE shape (an '@', a '+countrycode', dashes/dots in a fixed layout, a Luhn
checksum, dotted octets). Bare runs of digits (a 10-digit INN, an order number)
are deliberately NOT matched — they collide with everyday numbers. Names are a
separate, fuzzier pass (Latin + Cyrillic) with their own confidence.
"""
from __future__ import annotations

import re

# Apostrophe-like marks (Uzbek oʻ / gʻ). Bare chars for char-classes, [class] form
# for standalone use — do not nest them.
_APOS_CHARS = "'`ʻʼ‘’´"
_APOS = f"[{_APOS_CHARS}]"


# ── Universal structured identifiers ────────────────────────────────────────
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Bank card: 13–19 digits (Visa/MC/Amex/UzCard/Humo/…), optional 4-group spacing,
# validated by Luhn so random long numbers don't match.
CARD = re.compile(r"(?<!\d)(?:\d[ \-]?){12,18}\d(?!\d)")

# IPv4, octets validated separately.
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")

# IBAN: 2-letter country + 2 check digits + up to 30 alphanumerics.
IBAN = re.compile(r"\b[A-Z]{2}\d{2}[ ]?(?:[A-Z0-9][ ]?){11,30}\b")

# US SSN: ddd-dd-dddd (the dashes make it distinctive).
US_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# International phone in E.164-ish form: a leading '+', country code, 8–14 more
# digits, common separators. The leading '+' is what keeps it from matching plain
# numbers. (Local formats are added per country below.)
INTL_PHONE = re.compile(r"(?<!\w)\+\d{1,3}[\s\-]?(?:\(?\d{1,4}\)?[\s\-]?){2,5}\d{2,4}(?!\d)")


# ── Uzbekistan ──────────────────────────────────────────────────────────────
UZ_PHONE = re.compile(
    r"(?<!\d)(?:\+?998[\s\-]?)?"
    r"(?:20|33|50|55|77|78|88|90|91|93|94|95|97|98|99)"
    r"[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}(?!\d)"
)
UZ_PASSPORT = re.compile(r"\b[A-Z]{2}[\s\-]?\d{7}\b")
UZ_PINFL = re.compile(r"(?<!\d)\d(?:[\s\-]?\d){13}(?!\d)")  # 14 digits, structural check


# ── Russia ──────────────────────────────────────────────────────────────────
# Mobile: +7 / 8 then 10 digits in the usual (ddd) ddd-dd-dd shape.
RU_PHONE = re.compile(
    r"(?<!\d)(?:\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}(?!\d)"
)
# SNILS: ddd-ddd-ddd dd (distinctive dashes).
RU_SNILS = re.compile(r"\b\d{3}-\d{3}-\d{3}[\s]?\d{2}\b")
# Internal passport: dd dd dddddd (spaced 4+6). Spacing makes it distinctive.
RU_PASSPORT = re.compile(r"(?<!\d)\d{2}\s\d{2}\s\d{6}(?!\d)")


def luhn_ok(s: str) -> bool:
    digits = [int(c) for c in s if c.isdigit()]
    if not (13 <= len(digits) <= 19):
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def ipv4_ok(s: str) -> bool:
    parts = s.split(".")
    return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


def pinfl_structural_ok(s: str) -> bool:
    d = [c for c in s if c.isdigit()]
    if len(d) != 14 or d[0] not in "123456":
        return False
    day, month = int("".join(d[1:3])), int("".join(d[3:5]))
    return 1 <= day <= 31 and 1 <= month <= 12


# category -> (regex, confidence, validator or None). Longest / most specific
# first so a shorter pattern can't eat part of a longer value.
STRUCTURED = [
    ("email", EMAIL, 0.99, None),
    ("iban", IBAN, 0.90, None),
    # PINFL (exactly 14 digits + structural check) before CARD: in UZ/RU a 14-digit
    # PINFL is far likelier than a 14-digit Diners card, and its validator keeps it
    # from stealing real cards (they fail the date structure and fall through).
    ("pinfl", UZ_PINFL, 0.90, pinfl_structural_ok),
    ("card", CARD, 0.96, luhn_ok),
    ("passport", UZ_PASSPORT, 0.95, None),
    ("passport", RU_PASSPORT, 0.75, None),
    ("snils", RU_SNILS, 0.85, None),
    ("ssn", US_SSN, 0.80, None),
    ("phone", INTL_PHONE, 0.90, None),
    ("phone", UZ_PHONE, 0.95, None),
    ("phone", RU_PHONE, 0.92, None),
    ("ip", IPV4, 0.70, ipv4_ok),
]


# ── Name heuristics — Latin (UZ) + Cyrillic (RU) ────────────────────────────
# Standalone Uzbek particle "o'g'li" / "qizi".
NAME_PARTICLE = re.compile(
    rf"(?:o{_APOS}?g{_APOS}?li|og{_APOS}?li|ug{_APOS}?li|o{_APOS}li|qizi|kizi)",
    re.IGNORECASE,
)
# Fused patronymic: Latin -ovich/-ovna (Uzbek Russified) OR Cyrillic
# -ович/-овна/-евич/-евна/-ич/-инична (Russian).
PATRONYMIC_FUSED = re.compile(
    r"[A-Za-z" + _APOS_CHARS + r"]+(?:ovich|evich|ovna|evna)"
    r"|[А-ЯЁа-яё]+(?:ович|евич|ьич|овна|евна|инична)",
    re.IGNORECASE,
)
# Surname endings: Latin (-ov/-ova/-yev…) OR Cyrillic (-ов/-ова/-ин/-ский…).
SURNAME_SUFFIX = re.compile(
    r"[A-Za-z" + _APOS_CHARS + r"]+(?:ov|ova|ev|eva|yev|yeva|boyev|xonov|jonov)"
    r"|[А-ЯЁа-яё]+(?:ов|ова|ев|ева|ёв|ёва|ин|ина|ын|ына|ский|ская|цкий|цкая)",
    re.IGNORECASE,
)

# Words that often sit right next to a name in a CRM/chat card but are NOT part of
# the name — so a surname doesn't drag them into the blur (e.g. "Esirgapova Instagram").
NAME_STOPWORDS = {
    "instagram", "telegram", "facebook", "whatsapp", "viber", "tiktok", "youtube",
    "vk", "email", "phone", "tel", "lead", "new", "status", "source", "manager",
    "bugun", "kecha", "ertaga", "today", "сегодня", "вчера", "завтра", "новый",
    "lid", "mijoz", "client", "заявка", "клиент",
    "aka", "opa", "uka", "singil", "amaki", "xola", "ака", "апа", "ука",
    "voice", "message", "sticker", "video", "photo", "file", "saved", "messages",
}

# Fixed UI/chrome strings of chat & CRM apps (and a few common OCR-garbled forms)
# — a CLOSED, known set the neural model tends to misfire on. Used to filter the
# model pass (pii_blur.ner_model), kept separate from NAME_STOPWORDS so it doesn't
# touch the gazetteer logic. Deliberately excludes anything that could be a real
# name (e.g. "Bahor"), only app chrome and clear status words.
UI_STOPWORDS = {
    "rad", "pad", "ha", "pa", "batafsil", "batafsi", "qandu", "qanday", "cookie",
    "new", "all", "fixed", "yangi", "korea", "study", "yopish", "bosh", "sahifa",
    "vazifalar", "devices", "sozlamalar", "sorlamalar", "pdf", "telefon", "teiefon",
    "raqam", "yosh", "oquv", "0quv", "ochiq", "sohasi", "sohas", "til", "sertifikati",
    "sertlfikati", "topik", "izoh", "jarayonda", "bakalavr", "magistratura",
    "bitirganman", "olmaganman", "oturganman", "diurganman", "javobini", "javoblm",
    "javobi", "avval", "olish", "kotardi", "kotarmadi", "sinfni", "lichkaga",
    "chiqdim", "opam", "father", "sohada", "kasbiy", "mashinasozlik", "tashlab",
    "oktabr", "sayt", "ball", "daraja", "nomlarini", "nomlari", "field", "tepadegi",
    "man", "yoq", "koa", "kod", "ang", "eshitmaganakanman", "tushundim", "tushunmima",
    "qoyilindi", "telegramdan", "batafsii", "sticker", "messages", "voice", "message",
    "va", "aka", "ака", "had", "hop", "нор", "ok", "rahmat", "don", "know", "told",
}

COMMON_GIVEN_NAMES = {
    # Uzbek — male
    "alisher", "aziz", "jasur", "bobur", "sardor", "jahongir", "akmal", "akbar",
    "ulugbek", "bekzod", "sherzod", "doston", "oybek", "temur", "timur", "sanjar",
    "akram", "sunnat", "murod", "jamshid", "jasurbek", "sardorbek", "ozod",
    "shuhrat", "rustam", "farhod", "umar", "husan", "hasan", "diyor", "asror",
    "saidolim", "saidali", "said", "samandar", "idrok", "mironshoh", "miron",
    "saparali", "adambay", "isroil", "islom", "shoh", "shohruh", "shohjahon",
    "botir", "botirjon", "davron", "davronbek", "elyor", "eldor", "fozil",
    "gayrat", "g'ayrat", "ilhom", "ilhomjon", "javlon", "javohir", "kamol",
    "kamoliddin", "komil", "lochin", "mansur", "muzaffar", "nodirbek", "nurbek",
    "nurlan", "ortiq", "otabek", "rasul", "ravshan", "sardor", "sobir",
    "sodiq", "tohir", "tolib", "ulug'bek", "umid", "umidjon", "xasan", "xurshid",
    "yusuf", "yusupjon", "zafar", "zafarjon", "zokir", "muhammadali", "mustafo",
    "abdulla", "abdullo", "abdurahmon", "muhammad", "sherali", "qahramon",
    "oybek", "og'abek", "jahon", "sarvar", "sarvarbek", "shavkat", "sobirjon",
    "shahzod", "shahzodbek", "bunyod", "bunyodbek", "sunnatillo",
    # "Muhammad-" compound names are extremely common in Uzbekistan and usually
    # written as ONE word, so each needs its own gazetteer entry (a prefix match
    # on "muhammad" alone would risk over-matching ordinary text).
    "muhammadsodiq", "muhammadamin", "muhammadjon", "muhammadrasul",
    "muhammadyusuf", "muhammadziyo", "muhammadaziz", "muhammadsolih",
    # Uzbek — female
    "dilnoza", "malika", "shahnoza", "nilufar", "zarina", "madina", "sevara",
    "gulnora", "feruza", "nodira", "charos", "saida", "saidalo", "laylo",
    "mehrona", "sabina", "nozima", "gavhar", "dilafruz", "shahzoda", "ruxshona",
    "soliha", "yasmina", "muslima", "ifora", "xadicha", "nigora", "dildora",
    "shoira", "zilola", "kamola", "nasiba", "umida", "gulbahor", "ozoda",
    "muborak", "mohira", "sarvinoz", "shahlo", "farangiz", "nargiza",
    "e'zoza", "ezoza", "eʻzoza", "zilola", "mubina", "robiya", "sojida",
    # Russian — male (Latin + Cyrillic)
    "ivan", "sergey", "andrey", "alexey", "dmitry", "mikhail", "nikolay",
    "pavel", "vladimir", "viktor", "oleg", "igor", "roman", "artem", "maxim",
    "денис", "евгений", "александр", "антон", "кирилл",
    "иван", "сергей", "андрей", "алексей", "дмитрий", "михаил", "николай",
    "павел", "владимир", "виктор", "олег", "игорь", "роман", "артём", "максим",
    "denis", "evgeny", "alexander", "anton", "kirill",
    # Russian — female (Latin + Cyrillic)
    "elena", "olga", "natalia", "anna", "maria", "ekaterina", "tatiana",
    "svetlana", "irina", "julia", "yulia", "marina", "oksana", "viktoria",
    "елена", "ольга", "наталья", "анна", "мария", "екатерина", "татьяна",
    "светлана", "ирина", "юлия", "марина", "оксана", "виктория",
}


def _load_uz_names() -> set:
    """Load the large Uzbek given-name list (data/uz_names.txt), lowercased.

    Source: the ~12k-name gazetteer published with the open-access *Data in Brief*
    article behind the Uzbek hybrid NER–sentiment model (CC BY; a list of names is
    also factual data). Cleaned here to drop ~2% OCR-garbled entries. Used for
    EXACT given-name matches only (not the compound-suffix check), so a big list
    can't widen that check into false positives. Best-effort: missing file -> empty.
    """
    import os
    import sys
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    for path in (os.path.join(base, "pii_blur", "data", "uz_names.txt"),
                 os.path.join(base, "data", "uz_names.txt"),
                 os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "uz_names.txt")):
        try:
            with open(path, encoding="utf-8") as f:
                return {ln.strip().lower() for ln in f if ln.strip()}
        except Exception:
            continue
    return set()


# The curated core (above) drives the compound-suffix check; the full set (core +
# the imported list) drives exact given-name matching.
COMMON_GIVEN_NAMES_ALL = COMMON_GIVEN_NAMES | _load_uz_names()

# Words that are GENUINELY BOTH a real given name AND an everyday common noun —
# e.g. "Mamlakat" is a real Uzbek name but also the ordinary word for "country"
# (found via a real false positive: "Mamlakat — O'zbekiston tanlandi" = "Country —
# Uzbekistan selected" in an ordinary form, not a person). Simply deleting these
# from the gazetteer would lose real recall for people who actually have that
# name — instead, a word here is NOT allowed to anchor a name cluster on its own
# (so bare "Mamlakat" in a form label stays unflagged), but still joins a cluster
# normally when it sits next to a REAL anchor (a surname, patronymic, or another
# unambiguous given name) — so "Mamlakat Yusupova" (an actual full name) is still
# caught. The common-noun sense is far more frequent than the name sense in the
# UI/form text PiiBlur actually sees, so this is the safer default.
AMBIGUOUS_GIVEN_NAMES = {
    "mamlakat", "viloyat", "manzil", "maktub", "miqdor", "rahbar",
    # Found by systematically cross-referencing our full ~11.6k name list against
    # a real Uzbek dictionary (uz-hunspell, github.com/uzbek-net/uz-hunspell) —
    # 2115 overlaps total, but MOST are genuine rare names that a spellcheck
    # dictionary also lists (expected, not a problem). This subset is different:
    # numbers, days of the week, and extremely common adjectives/nouns that
    # appear constantly in ordinary text/forms — a far higher false-positive
    # risk than an archaic name that's merely also dictionary-listed.
    "bir", "besh", "olti", "yetti", "sakkiz", "toqqiz", "sakson", "yetmish",
    "chor", "qirq",
    "juma", "shanba", "payshanba", "seshanba", "dushanba",
    "yaxshi", "yomon", "yaqin", "uzoq", "uzun", "katta", "kichik", "yana",
    "hozir", "darrov", "baland",
    "ota", "non", "dam", "haq", "kuch", "tosh", "gul",
    "izoh", "maqsad", "natija", "vazifa",
}


def ocr_canon(s: str) -> str:
    """Fold the characters OCR most often confuses so a garbled name still matches
    the gazetteer: capital-I / lowercase-l / 1 / | all read alike, and o / 0 alike.
    Lets "MiraIisher" (OCR misread) match "Miralisher". Conservative — only these
    few well-known confusions, to keep accidental collisions rare."""
    s = s.lower()
    out = []
    for c in s:
        if c in "il1|!":
            out.append("i")
        elif c in "o0":
            out.append("o")
        else:
            out.append(c)
    return "".join(out)


# Canonical forms of every gazetteer name, for the OCR-tolerant fallback match.
CANON_GIVEN_NAMES = {ocr_canon(n) for n in COMMON_GIVEN_NAMES_ALL}

# Canonical (OCR-confusable-folded) forms of the ambiguous set — so an OCR-garbled
# duplicate of an ambiguous word (e.g. dual-language OCR reading "Mamlakat" twice
# and mangling one copy to "Mam1akat") is still recognized as ambiguous and can't
# anchor on its own either, closing the same loophole the fold-match would
# otherwise reopen.
AMBIGUOUS_CANON = {ocr_canon(w) for w in AMBIGUOUS_GIVEN_NAMES}
