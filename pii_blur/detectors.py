"""PII detection over OCR output.

The hard, quality-deciding step. Research on screenshot redaction shows the main
failure is OCR splitting a value across word boxes (a spaced phone number, a
grouped card) so a per-word regex either misses it or over-redacts. We fix that
by working at the LINE level:

    1. group OCR words into lines (by vertical overlap),
    2. join each line's words into one string, remembering which character range
       belongs to which word box,
    3. run the regexes on the joined string,
    4. for every match, union the boxes of the words it touches -> one tight
       redaction box.

This keeps multi-word values whole and maps them back to exact pixels. Detection
is decoupled from OCR: feed it any list of Words, so it is unit-testable without
a screenshot or an OCR engine installed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pii_blur import patterns


# (x, y, w, h) in pixels, top-left origin.
Box = tuple


@dataclass
class Word:
    text: str
    box: tuple  # (x, y, w, h)


@dataclass
class Redaction:
    box: tuple          # (x, y, w, h) pixels to blur
    category: str       # "phone" | "card" | "pinfl" | "name" | ...
    confidence: float
    text: str           # what matched (for logging / the review overlay)


def group_lines(words: list[Word], y_tol: float = 0.6) -> list[list[Word]]:
    """Group words into reading lines by vertical overlap.

    Two words share a line if their vertical centers are within y_tol * height of
    each other. Words inside a line are sorted left-to-right. Robust to the small
    y jitter OCR engines produce.
    """
    remaining = sorted(words, key=lambda w: (w.box[1], w.box[0]))
    lines: list[list[Word]] = []
    for w in remaining:
        cy = w.box[1] + w.box[3] / 2
        placed = False
        for line in lines:
            ref = line[0]
            rcy = ref.box[1] + ref.box[3] / 2
            if abs(cy - rcy) <= y_tol * max(w.box[3], ref.box[3]):
                line.append(w)
                placed = True
                break
        if not placed:
            lines.append([w])
    for line in lines:
        line.sort(key=lambda w: w.box[0])
    return lines


def _union_box(boxes: list[tuple]) -> tuple:
    xs = [b[0] for b in boxes]
    ys = [b[1] for b in boxes]
    x2 = [b[0] + b[2] for b in boxes]
    y2 = [b[1] + b[3] for b in boxes]
    x, y = min(xs), min(ys)
    return (x, y, max(x2) - x, max(y2) - y)


def _line_text_and_spans(line: list[Word]) -> tuple[str, list[tuple]]:
    """Join a line's words with single spaces; return the joined string and, per
    word, the (start, end) char range it occupies in that string."""
    parts, spans, pos = [], [], 0
    for w in line:
        start = pos
        parts.append(w.text)
        pos += len(w.text)
        spans.append((start, pos))
        pos += 1  # the space separator
    return " ".join(parts), spans


def _words_touching(spans: list[tuple], line: list[Word], m_start: int, m_end: int) -> list[Word]:
    """All words whose char span intersects the match [m_start, m_end)."""
    out = []
    for word, (s, e) in zip(line, spans):
        if s < m_end and e > m_start:
            out.append(word)
    return out


def detect_structured(line: list[Word]) -> list[Redaction]:
    text, spans = _line_text_and_spans(line)
    found: list[Redaction] = []
    taken: list[tuple] = []  # char spans already claimed (avoid double-matching)
    for category, pattern, conf, validator in patterns.STRUCTURED:
        for m in pattern.finditer(text):
            if validator and not validator(m.group()):
                continue
            if any(m.start() < te and m.end() > ts for ts, te in taken):
                continue  # overlaps a stronger match already taken
            touched = _words_touching(spans, line, m.start(), m.end())
            if not touched:
                continue
            found.append(Redaction(_union_box([w.box for w in touched]), category, conf, m.group()))
            taken.append((m.start(), m.end()))
    return found


_PUNCT = ".,;:()[]{}«»\"'"


def _is_avatar_initials(t: str) -> bool:
    """A short ALL-CAPS token ('AM', 'ST') — an avatar monogram or acronym, never a
    real name. Excluded so it doesn't anchor or widen a name box."""
    return 2 <= len(t) <= 3 and t.isupper() and t.isalpha()


def _name_adjacent(a: tuple, b: tuple) -> bool:
    """True if two word boxes are close enough to belong to ONE name — either
    neighbours on the same visual line (small horizontal gap) or stacked vertically
    (a name wrapped onto the next line, e.g. 'Akram' over "mo'monov").

    The gap caps are what stop a name box from stretching across the whole card to
    grab a far-away status badge ('Rad etildi') or label ('Baxor')."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax1, ay1, bx1, by1 = ax + aw, ay + ah, bx + bw, by + bh
    h = max(ah, bh, 1)
    v_overlap = ay < by1 and by < ay1
    x_overlap = ax < bx1 and bx < ax1
    if v_overlap:                                 # same line → cap the horizontal gap
        hgap = max(ax - bx1, bx - ax1, 0)
        return hgap <= 2.0 * h
    if x_overlap:                                 # stacked → cap the vertical gap
        vgap = max(ay - by1, by - ay1, 0)
        return vgap <= 0.9 * h
    return False


def detect_names(words: list[Word], gazetteer: set | None = None) -> list[Redaction]:
    """Heuristic name detection (Latin UZ + Cyrillic RU), by 2D proximity.

    1. Mark ANCHOR words — a real name signal: an Uzbek particle ("o'g'li"/"qizi"),
       a fused patronymic (-ovich/-ович), a surname suffix (-ov/-ова…), or a
       gazetteer given name. Avatar monograms ('AM') and stopwords never anchor.
    2. A plain capitalized word ("Akram", "Baxor") joins in ONLY if it sits right
       next to an anchor — so a given name attaches to its surname, but a far-off
       label or status badge does not.
    3. Cluster the candidates by physical adjacency (same line OR wrapped to the
       next line), keep a cluster that carries a real signal (particle/fused/surname
       or >=2 words), and blur the tight union box of exactly those words.

    Working on 2D positions (not per text line) is what joins a name split across
    two OCR lines, while the adjacency caps keep the box from over-reaching. Lower
    confidence by design — names are the unreliable part."""
    gaz = patterns.COMMON_GIVEN_NAMES_ALL if gazetteer is None else gazetteer
    n = len(words)
    tokens = [w.text.strip(_PUNCT) for w in words]

    particle = [bool(patterns.NAME_PARTICLE.fullmatch(t)) for t in tokens]
    fused = [bool(patterns.PATRONYMIC_FUSED.fullmatch(t)) for t in tokens]
    surname = [bool(patterns.SURNAME_SUFFIX.fullmatch(t)) for t in tokens]

    def _usable(i: int) -> bool:
        t = tokens[i]
        return bool(t) and not _is_avatar_initials(t) and t.lower() not in patterns.NAME_STOPWORDS

    def _cap(i: int) -> bool:
        return bool(tokens[i]) and tokens[i][:1].isupper()

    def _plausible(i: int) -> bool:
        """A capitalized alphabetic token that could be a given name (not a label)."""
        t = tokens[i]
        return len(t) >= 2 and _cap(i) and t.isalpha() and _usable(i)

    def _gaz_compound_hit(t_lower: str) -> bool:
        """True if a gazetteer given name sits at the END of a longer word — a
        compound name like "Mir+alisher" or "Boto+yor", very common in Uzbek
        (a root prefix fused onto a recognizable base name, all one OCR token).
        Guarded three ways to avoid reopening the false-positive problem a plain
        suffix check would cause: it iterates ONLY the small curated core list (not
        the 11k imported names — a huge list of endings would match ordinary words),
        the entry must be reasonably long (>=5 chars), and the word must carry a
        real prefix (>=2 extra letters), not just be the bare name (exact match
        above covers that)."""
        for g in patterns.COMMON_GIVEN_NAMES:
            if len(g) >= 5 and len(t_lower) >= len(g) + 2 and t_lower.endswith(g):
                return True
        return False

    def _gaz_exact_hit(t_lower: str) -> bool:
        """Exact gazetteer given-name match — EXCEPT words that are genuinely
        ambiguous (also an everyday common noun, e.g. "Mamlakat" = a real name
        but also "country"). Those can't anchor a cluster on their own (that's
        what caused a real false positive on "Mamlakat — O'zbekiston tanlandi",
        an ordinary form label); they still join a cluster via the normal
        plausible-word-next-to-an-anchor path, so a real "Mamlakat Yusupova"
        full name is still caught."""
        return t_lower in gaz and t_lower not in patterns.AMBIGUOUS_GIVEN_NAMES

    # Base anchors — a strong, context-free name signal. A surname suffix counts
    # ONLY when the word is Capitalized: Cyrillic "-ов/-ев/-ин" (and Latin "-ov")
    # are also everyday word endings (genitive plural: "контактов", "один раз"…),
    # which appear lowercase in running text — so a lowercase suffix word is NOT a
    # surname by itself.
    anchor = [False] * n
    for i in range(n):
        if not _usable(i):
            continue
        is_ambiguous = (tokens[i].lower() in patterns.AMBIGUOUS_GIVEN_NAMES
                        or patterns.ocr_canon(tokens[i]) in patterns.AMBIGUOUS_CANON)
        if (particle[i] or fused[i] or (surname[i] and _cap(i))
                or (_cap(i) and not is_ambiguous
                    and (_gaz_exact_hit(tokens[i].lower()) or _gaz_compound_hit(tokens[i].lower())
                         or patterns.ocr_canon(tokens[i]) in patterns.CANON_GIVEN_NAMES))):
            anchor[i] = True

    # Rescue a LOWERCASE surname only when a REAL given name sits right next to it
    # ("Аброр абламидов", "Akram mo'monov") — a surname shown lowercase in a CRM
    # card. The neighbour must itself be an anchor (gazetteer/particle/fused), not
    # just any capitalized word — otherwise an ordinary Uzbek word that happens to
    # end in "-ov" ("to'lov" = "payment") gets rescued by sitting next to an
    # unrelated capitalized English/tech term ("Standard"), which is exactly the
    # false positive a bilingual Uzbek+English document (tech instructions, forms)
    # produces constantly. "импорт контактов" still has no anchor neighbour, so it
    # stays unflagged either way.
    for i in range(n):
        if anchor[i] or not (surname[i] and _usable(i)) or _cap(i):
            continue
        if any(anchor[j] and _name_adjacent(words[i].box, words[j].box) for j in range(n)):
            anchor[i] = True

    cand = anchor[:]
    # A plain capitalized word becomes a candidate only when it touches an anchor.
    for i in range(n):
        if cand[i] or not _plausible(i):
            continue
        for j in range(n):
            if anchor[j] and _name_adjacent(words[i].box, words[j].box):
                cand[i] = True
                break

    idx = [i for i in range(n) if cand[i]]
    parent = {i: i for i in idx}

    def _find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a in range(len(idx)):
        for b in range(a + 1, len(idx)):
            i, j = idx[a], idx[b]
            if _name_adjacent(words[i].box, words[j].box):
                parent[_find(i)] = _find(j)

    clusters: dict[int, list[int]] = {}
    for i in idx:
        clusters.setdefault(_find(i), []).append(i)

    # How many MEANING-BEARING words share a word's physical text line — used
    # below to tell a standalone contact name ("Isroilov", alone on its own UI
    # row) from an ordinary word that happens to end in -ов/-ev inside a sentence
    # ("...CSV-импорт контактов..."). A genitive-plural noun is always embedded in
    # a longer phrase; a name shown alone in a chat list or contact card is not.
    # Stopwords/honorifics ("aka", "Instagram"...) don't count — they regularly
    # sit next to a bare name (e.g. dual-language OCR reading "aka" AND "ака" on
    # the same row) without making it a sentence.
    line_size = {}
    for ln in group_lines(words):
        usable_count = sum(1 for w in ln if _usable(words.index(w)))
        for w in ln:
            line_size[words.index(w)] = usable_count

    def _is_ambiguous(i: int) -> bool:
        return (tokens[i].lower() in patterns.AMBIGUOUS_GIVEN_NAMES
                or patterns.ocr_canon(tokens[i]) in patterns.AMBIGUOUS_CANON)

    gaz_hit = [bool(_cap(i) and not _is_ambiguous(i)
                    and (_gaz_exact_hit(tokens[i].lower()) or _gaz_compound_hit(tokens[i].lower())
                         or patterns.ocr_canon(tokens[i]) in patterns.CANON_GIVEN_NAMES))
               for i in range(n)]

    out: list[Redaction] = []
    for members in clusters.values():
        has_particle = any(particle[k] for k in members)
        has_fused = any(fused[k] for k in members)
        has_surname = any(surname[k] for k in members)
        has_gaz = any(gaz_hit[k] for k in members)
        if not (has_particle or has_fused or has_surname or has_gaz or len(members) >= 2):
            continue
        members.sort()
        isolated = len(members) == 1 and line_size.get(members[0], 99) <= 2
        # A full name (given + surname, or with a patronymic) is confident. A LONE
        # surname or gazetteer given-name word scores 0.50 by default — below
        # min_confidence (0.60) — so a stray capitalized "-ов" word mid-sentence
        # ("Готов", "Контактов") or a dual-purpose gazetteer word used as an
        # ordinary adjective ("Озод" = "free") is not blurred. But when that word
        # is ISOLATED on its own short line (a contact name shown alone, not part
        # of a sentence — exactly how a chat-list/CRM card shows a bare "Timur" or
        # "Isroilov"), it's rescued to 0.65: real standalone names behave this way;
        # ordinary words embedded in a sentence don't.
        if has_particle or has_fused:
            conf = 0.78
        elif has_surname or has_gaz:
            if len(members) >= 2:
                conf = 0.70
            elif isolated:
                conf = 0.65
            else:
                conf = 0.50
        else:
            conf = 0.55
        out.append(Redaction(
            _union_box([words[k].box for k in members]),
            "name", conf, " ".join(words[k].text for k in members),
        ))
    return out


def explode_multiword(words: list[Word]) -> list[Word]:
    """Split any OCR 'word' that actually holds several space-separated tokens
    into per-token words, dividing its box width proportionally by token length.

    Line-box OCR engines (e.g. RapidOCR) return a whole line as one box. Structured
    regex copes (it joins text anyway), but the name heuristic needs per-token
    words — this gives it those, with boxes good enough to blur tightly.
    """
    out: list[Word] = []
    for w in words:
        toks = w.text.split()
        if len(toks) <= 1:
            out.append(w)
            continue
        x, y, bw, bh = w.box
        total = sum(len(t) for t in toks) or 1
        gap = max(1, int(bw * 0.015))
        cx = x
        for t in toks:
            tw = max(1, int((bw - gap * (len(toks) - 1)) * len(t) / total))
            out.append(Word(t, (cx, y, tw, bh)))
            cx += tw + gap
    return out


def _box_overlap_frac(a: tuple, b: tuple) -> float:
    """Intersection area as a fraction of the smaller box (1.0 = one inside the other)."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    smaller = min(aw * ah, bw * bh) or 1
    return inter / smaller


# Cyrillic letters that are visually near-identical to a Latin letter or digit —
# the classic "confusable" set. Running OCR twice (once per language) can read
# the SAME glyph on screen as the Latin form in one pass and the Cyrillic
# look-alike in the other (e.g. a lone "3" read as Latin digit by the English
# pass and as Cyrillic "З" by the Russian pass). Exact-text dedup below doesn't
# catch that — the strings genuinely differ — so this folds both to one form
# first, purely for the DEDUP COMPARISON (the real detected text keeps its
# original spelling). Concrete bug this fixes: a PINFL like "3 150590 123 456 0"
# came through OCR as "3 З 150590 123 456 0 О" (duplicate 3/0 digits picked up
# as Cyrillic З/О), which doesn't match the 14-digit PINFL pattern at all.
_CONFUSABLE_FOLD = str.maketrans({
    "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "0",
    "р": "p", "с": "c", "т": "t", "у": "y", "х": "x", "з": "3", "б": "6",
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "0",
    "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X", "З": "3", "Б": "6",
})


def _confusable_fold(t: str) -> str:
    return t.translate(_CONFUSABLE_FOLD)


def _dedupe_words(words: list[Word]) -> list[Word]:
    """Drop words that repeat the same text at the same spot. Running Windows OCR
    for several languages (to read Latin AND Cyrillic) reads shared text twice; this
    collapses those copies so a value isn't double-detected and names aren't doubled.
    Genuine repeats elsewhere on the screen stay (text must also OVERLAP in place).
    Compares text after confusable-folding (see above), so a Latin/Cyrillic
    look-alike pair at the same spot counts as the same duplicate too — keeping
    whichever copy was seen first (both OCR langs run in a fixed order, so this
    is deterministic, not which one is "more correct")."""
    out: list[Word] = []
    for w in words:
        t = _confusable_fold(w.text.strip().lower())
        if any(t == _confusable_fold(k.text.strip().lower()) and _box_overlap_frac(w.box, k.box) > 0.5
               for k in out):
            continue
        out.append(w)
    return out


def detect(words: list[Word], *, names: bool = True,
           min_confidence: float = 0.0, gazetteer: set | None = None) -> list[Redaction]:
    """Full detection over OCR words. `names=False` disables the fuzzy name pass
    (keep only rock-solid structured identifiers). `min_confidence` filters out
    weaker guesses. Returns redaction boxes ready for the blur step."""
    words = _dedupe_words(explode_multiword(words))
    results: list[Redaction] = []
    for line in group_lines(words):
        results.extend(detect_structured(line))
    # Names run over ALL words (2D), not per line, so a name wrapped onto the next
    # OCR line is still joined.
    if names:
        results.extend(detect_names(words, gazetteer))
    return [r for r in results if r.confidence >= min_confidence]
