"""Deterministic generators for the large PII test suite.

Each generator yields realistic positive samples (must be detected) and the
negatives yield decoy text (must NOT be flagged as that category). Seeded, so the
suite is reproducible. We synthesize OCR `Word`s from a string so detection runs
exactly as it would on real OCR output, including values spread over several
tokens.
"""
from __future__ import annotations

import random

from pii_blur.detectors import Word

OPERATOR_CODES = ["20", "33", "50", "55", "77", "78", "88", "90", "91", "93", "94", "95", "97", "98", "99"]
CARD_BINS = ["8600", "9860", "5614", "4056"]
GIVEN = ["Alisher", "Aziz", "Jasur", "Bobur", "Sardor", "Dilnoza", "Malika",
         "Shahnoza", "Nilufar", "Zarina", "Madina", "Sevara", "Akmal", "Ulugbek"]
SURNAMES = ["Karimov", "Rashidov", "Abdullayev", "Toshmatov", "Yusupova",
            "Ergasheva", "Qodirov", "Saidova", "Normatov", "Islomova"]
PLAIN_WORDS = ["bugun", "ertaga", "narx", "xizmat", "hujjat", "viza", "Toshkent",
               "manzil", "soat", "kun", "yaxshi", "rahmat", "assalomu", "savol"]


def _rng(seed):
    return random.Random(seed)


def luhn_complete(base15: str) -> str:
    ds = [int(c) for c in base15]
    tot = 0
    for i, d in enumerate(reversed(ds)):
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        tot += d
    return base15 + str((10 - tot % 10) % 10)


def words_from(text: str, prefix: str = "") -> list[Word]:
    """Turn a (optionally prefixed) string into OCR-like Words with boxes."""
    toks = (prefix + " " + text).split() if prefix else text.split()
    words, x = [], 10
    for t in toks:
        w = 12 * len(t)
        words.append(Word(t, (x, 10, w, 20)))
        x += w + 8
    return words


# ── positive generators: (label, word-list, expected_category) ──────────────
def gen_phones(n, seed=1):
    r = _rng(seed)
    out = []
    for _ in range(n):
        code = r.choice(OPERATOR_CODES)
        rest = f"{r.randint(0,999):03d}{r.randint(0,99):02d}{r.randint(0,99):02d}"
        body = code + rest
        style = r.choice([
            f"+998{body}", f"+998 {code} {rest[:3]} {rest[3:5]} {rest[5:]}",
            f"998{body}", body, f"{code} {rest[:3]}-{rest[3:5]}-{rest[5:]}",
        ])
        out.append((f"phone:{style}", words_from(style, r.choice(["", "Tel:", "aloqa"])), "phone"))
    return out


def gen_cards(n, seed=2):
    r = _rng(seed)
    out = []
    for _ in range(n):
        bin_ = r.choice(CARD_BINS)
        base = bin_ + f"{r.randint(0, 10**11 - 1):011d}"
        num = luhn_complete(base)
        style = r.choice([num, f"{num[:4]} {num[4:8]} {num[8:12]} {num[12:]}",
                          f"{num[:4]}-{num[4:8]}-{num[8:12]}-{num[12:]}"])
        out.append((f"card:{style}", words_from(style, r.choice(["", "Karta:"])), "card"))
    return out


def gen_pinfls(n, seed=3):
    r = _rng(seed)
    out = []
    for _ in range(n):
        sex = r.randint(1, 6)
        dd, mm, yy = r.randint(1, 28), r.randint(1, 12), r.randint(0, 99)
        region = r.randint(1, 999)
        serial = r.randint(1, 999)
        check = r.randint(0, 9)
        num = f"{sex}{dd:02d}{mm:02d}{yy:02d}{region:03d}{serial:03d}{check}"
        style = r.choice([num, f"{num[:1]} {num[1:7]} {num[7:10]} {num[10:13]} {num[13]}"])
        out.append((f"pinfl:{num}", words_from(style, r.choice(["", "JSHSHIR:"])), "pinfl"))
    return out


def gen_passports(n, seed=4):
    r = _rng(seed)
    out = []
    A = "ABCDEFGHKLMNPR"
    for _ in range(n):
        s = f"{r.choice(A)}{r.choice(A)}{r.randint(0, 9999999):07d}"
        style = r.choice([s, f"{s[:2]} {s[2:]}"])
        out.append((f"pass:{s}", words_from(style, r.choice(["", "Pasport:"])), "passport"))
    return out


def gen_emails(n, seed=5):
    r = _rng(seed)
    doms = ["mail.uz", "gmail.com", "umail.uz", "inbox.ru", "exat.uz"]
    out = []
    for _ in range(n):
        u = "".join(r.choice("abcdefghijklmnopqrstuvwxyz0123456789._") for _ in range(r.randint(4, 12))).strip("._")
        e = f"{u or 'user'}@{r.choice(doms)}"
        out.append((f"email:{e}", words_from(e, r.choice(["", "Email:"])), "email"))
    return out


def gen_names(n, seed=6):
    r = _rng(seed)
    out = []
    for _ in range(n):
        # A realistic Russified patronymic: father's given name + -ovich/-ovna,
        # capitalized (e.g. "Alisher Azizovich").
        patr = r.choice(GIVEN) + r.choice(["ovich", "ovna"])
        style = r.choice([
            f"{r.choice(SURNAMES)} {r.choice(GIVEN)} {r.choice(GIVEN)} o'g'li",
            f"{r.choice(SURNAMES)} {r.choice(GIVEN)} {r.choice(GIVEN)} qizi",
            f"{r.choice(SURNAMES)} {r.choice(GIVEN)}",
            f"{r.choice(GIVEN)} {patr}",
        ])
        out.append((f"name:{style}", words_from(style, r.choice(["", "Mijoz:", "F.I.Sh:"])), "name"))
    return out


# ── negative generators: text that must NOT trigger a given category ─────────
def gen_negatives(n, seed=7):
    """Decoys: random sentences, order numbers, years, prices — must NOT be
    flagged as structured PII (names allowed to be noisy, so we only assert the
    structured categories are absent)."""
    r = _rng(seed)
    out = []
    for _ in range(n):
        kind = r.choice(["sentence", "order", "year", "price", "shortnum"])
        if kind == "sentence":
            s = " ".join(r.choice(PLAIN_WORDS) for _ in range(r.randint(3, 8)))
        elif kind == "order":
            s = f"Buyurtma raqami {r.randint(1000, 99999)}"
        elif kind == "year":
            s = f"{r.randint(1990, 2026)} yilda {r.choice(PLAIN_WORDS)}"
        elif kind == "price":
            s = f"narx {r.randint(10000, 9999999)} som"
        else:
            s = f"№ {r.randint(1, 999)}"
        out.append((f"neg:{s}", words_from(s), None))
    return out


# ── international generators ─────────────────────────────────────────────────
RU_SUR = ["Иванов", "Петров", "Сидоров", "Смирнова", "Кузнецова", "Попов", "Соколова"]
RU_GIV = ["Пётр", "Иван", "Сергей", "Мария", "Анна", "Дмитрий", "Ольга"]
RU_PATR = ["Сергеевич", "Иванович", "Петрович", "Сергеевна", "Ивановна", "Дмитриевна"]


def gen_ru_phones(n, seed=11):
    r = _rng(seed)
    out = []
    for _ in range(n):
        body = f"({r.randint(900,999)}) {r.randint(100,999)}-{r.randint(10,99)}-{r.randint(10,99)}"
        s = r.choice([f"+7 {body}", f"8{body}", f"+7{r.randint(9000000000,9999999999)}"])
        out.append((f"ruphone:{s}", words_from(s, r.choice(["", "Тел:"])), "phone"))
    return out


def gen_intl_phones(n, seed=12):
    r = _rng(seed)
    cc = ["+1", "+44", "+49", "+33", "+91", "+90", "+86"]
    out = []
    for _ in range(n):
        s = f"{r.choice(cc)} {r.randint(100,999)} {r.randint(100,999)} {r.randint(1000,9999)}"
        out.append((f"intlphone:{s}", words_from(s), "phone"))
    return out


def gen_snils(n, seed=13):
    r = _rng(seed)
    out = []
    for _ in range(n):
        s = f"{r.randint(100,999)}-{r.randint(100,999)}-{r.randint(100,999)} {r.randint(10,99)}"
        out.append((f"snils:{s}", words_from(s, r.choice(["", "СНИЛС:"])), "snils"))
    return out


def gen_ssn(n, seed=14):
    r = _rng(seed)
    out = []
    for _ in range(n):
        s = f"{r.randint(100,899)}-{r.randint(10,99)}-{r.randint(1000,9999)}"
        out.append((f"ssn:{s}", words_from(s, r.choice(["", "SSN:"])), "ssn"))
    return out


def gen_iban(n, seed=15):
    r = _rng(seed)
    cc = ["GB", "DE", "FR", "NL", "ES"]
    out = []
    for _ in range(n):
        body = "".join(str(r.randint(0, 9)) for _ in range(18))
        s = f"{r.choice(cc)}{r.randint(10,99)}{body}"
        s = " ".join(s[i:i+4] for i in range(0, len(s), 4))
        out.append((f"iban:{s}", words_from(s), "iban"))
    return out


def gen_ipv4(n, seed=16):
    r = _rng(seed)
    out = []
    for _ in range(n):
        s = ".".join(str(r.randint(0, 255)) for _ in range(4))
        out.append((f"ip:{s}", words_from(s, r.choice(["", "IP:"])), "ip"))
    return out


def gen_ru_names(n, seed=17):
    r = _rng(seed)
    out = []
    for _ in range(n):
        s = r.choice([
            f"{r.choice(RU_SUR)} {r.choice(RU_GIV)} {r.choice(RU_PATR)}",
            f"{r.choice(RU_SUR)} {r.choice(RU_GIV)}",
            f"{r.choice(RU_GIV)} {r.choice(RU_PATR)}",
        ])
        out.append((f"runame:{s}", words_from(s, r.choice(["", "ФИО:"])), "name"))
    return out
