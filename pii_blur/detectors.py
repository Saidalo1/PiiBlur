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


def _adjacency_kind(a: tuple, b: tuple) -> str | None:
    """'line' if two boxes are same-line neighbours (small horizontal gap),
    'stack' if vertically stacked (small vertical gap — a name wrapped onto the
    next line, e.g. 'Akram' over "mo'monov"), else None. The gap caps are what
    stop a name box from stretching across the whole card to grab a far-away
    status badge ('Rad etildi') or label ('Baxor')."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax1, ay1, bx1, by1 = ax + aw, ay + ah, bx + bw, by + bh
    h = max(ah, bh, 1)
    v_overlap = ay < by1 and by < ay1
    x_overlap = ax < bx1 and bx < ax1
    if v_overlap:                                 # same line → cap the horizontal gap
        hgap = max(ax - bx1, bx - ax1, 0)
        return "line" if hgap <= 2.0 * h else None
    if x_overlap:                                 # stacked → cap the vertical gap
        vgap = max(ay - by1, by - ay1, 0)
        return "stack" if vgap <= 0.9 * h else None
    return None


def _name_adjacent(a: tuple, b: tuple) -> bool:
    """True if two word boxes are close enough to belong to ONE name — either
    on the same line or stacked vertically. See _adjacency_kind for the shape;
    this is the plain yes/no version used where the distinction doesn't matter
    (the lowercase-surname and cross-source rescues, which only ever fire
    between exactly two words, never chain transitively)."""
    return _adjacency_kind(a, b) is not None


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
        is_ambiguous_surname = (tokens[i].lower() in patterns.AMBIGUOUS_SURNAME_WORDS
                                or patterns.ocr_canon(tokens[i]) in patterns.AMBIGUOUS_SURNAME_CANON)
        # The OCR-canon fuzzy match (folds i/l/1/o/0 confusables) requires >=5
        # chars -- a real bug from a truncated table column: "Toil" (OCR's
        # misread of a "To'lov" header cut off at the image edge) canon-folds
        # to "toii", which collides with the gazetteer's real but rare name
        # "Toli". A short word has far fewer possible canon forms, so this kind
        # of accidental collision is much more likely there; an exact (non-
        # fuzzy) match is unaffected, so a real short name read cleanly is
        # still caught -- only a short word that needed the FUZZY rescue loses
        # it, which is the right trade for avoiding short-word collisions.
        canon_hit = (len(tokens[i]) >= 5
                    and patterns.ocr_canon(tokens[i]) in patterns.CANON_GIVEN_NAMES)
        if (particle[i] or fused[i] or (surname[i] and _cap(i) and not is_ambiguous_surname)
                or (_cap(i) and not is_ambiguous
                    and (_gaz_exact_hit(tokens[i].lower()) or _gaz_compound_hit(tokens[i].lower())
                         or canon_hit))):
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

    # Physical text lines, computed up front so the clustering step below can
    # use them as a hard boundary. Also: how many MEANING-BEARING words share a
    # word's line — used later to tell a standalone contact name ("Isroilov",
    # alone on its own UI row) from an ordinary word that happens to end in
    # -ов/-ev inside a sentence ("...CSV-импорт контактов..."). A genitive-
    # plural noun is always embedded in a longer phrase; a name shown alone in
    # a chat list or contact card is not. Stopwords/honorifics ("aka",
    # "Instagram"...) don't count — they regularly sit next to a bare name
    # (e.g. dual-language OCR reading "aka" AND "ака" on the same row) without
    # making it a sentence.
    line_size = {}
    line_id: dict[int, int] = {}
    line_has_anchor: dict[int, bool] = {}
    for lid, ln in enumerate(group_lines(words)):
        line_word_idx = [words.index(w) for w in ln]
        usable_count = sum(1 for i in line_word_idx if _usable(i))
        # A line counts as "complete" either via a strict anchor pattern, OR by
        # already having a pair of ADJACENT plausible capitalized words of its
        # own -- real gap found via a Ukrainian name list: a surname ending in
        # "-ко"/"-ько" (Онисько, Шевченко...) isn't covered by SURNAME_SUFFIX
        # (built around Russian -ов/-ев/-ский endings), so that row's own
        # surname never registered as an anchor, making the row look
        # "incomplete" and letting it wrongly absorb the NEXT row. A row with
        # "Surname Given Patronymic" (its words sitting close together) is
        # complete regardless of which specific suffix we do or don't
        # recognize. Adjacency is required, not just "2+ plausible words
        # anywhere on the line": a genuinely incomplete wrapped given name
        # ("Akram" alone, awaiting its surname on the next line) can still
        # share its OCR line with an unrelated, far-off capitalized UI label
        # ("Jarayonda") -- two plausible words that are nowhere near each
        # other must not count as a complete name.
        plausible_idx = [i for i in line_word_idx if _plausible(i)]
        has_own_anchor = (
            any(particle[i] or fused[i] or (surname[i] and _cap(i)) for i in line_word_idx)
            or any(_name_adjacent(words[i].box, words[j].box)
                  for a, i in enumerate(plausible_idx) for j in plausible_idx[a + 1:])
        )
        for i in line_word_idx:
            line_size[i] = usable_count
            line_id[i] = lid
            line_has_anchor[lid] = has_own_anchor

    idx = [i for i in range(n) if cand[i]]
    parent = {i: i for i in idx}

    def _find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    # A dense table (many short rows stacked tightly — a printed list, not a
    # sparse chat card) can put consecutive ROWS within the same small vertical
    # gap a genuinely wrapped name uses. Plain pairwise adjacency doesn't see
    # the difference and the union-find chains row 1 -> row 2 -> row 3 -> ...
    # transitively into ONE giant cluster spanning many unrelated people — a
    # real bug from a photographed name list. The fix (matching how engine-
    # grade OCR/layout pipelines bound this): a vertical ("stacked") link is
    # only allowed to cross into the line ABOVE when that upper line doesn't
    # already have its own complete anchor — i.e. it's a genuinely incomplete
    # fragment still waiting for its wrap (the real 2-line contact-card case:
    # "Akram" alone has no surname of its own yet). A line that's ALREADY a
    # complete name on its own (as every row in a dense table is) never
    # absorbs the next line, so the chain stops at each row's own boundary.
    for a in range(len(idx)):
        for b in range(a + 1, len(idx)):
            i, j = idx[a], idx[b]
            if _adjacency_kind(words[i].box, words[j].box) is None:
                continue
            # Gate on group_lines()'s OWN line membership, not just this pair's
            # local geometry: merging several OCR passes (native + upscaled +
            # a different engine) at slightly different box heights can make
            # two words from DIFFERENT physical rows pairwise LOOK like same-
            # line neighbours (their boxes happen to vertically overlap once
            # one source reports a taller box than usual) even though
            # group_lines's own, more careful pass correctly kept the rows
            # separate. Real bug this fixes: with a 3rd OCR source merged in,
            # exactly this height mismatch made two adjacent dense-table rows
            # geometrically read as "same line", bypassing the stack-only
            # guard above entirely. Any cross-line join -- whichever way the
            # pairwise check classified it -- gets the same anchor guard.
            if line_id.get(i) != line_id.get(j):
                upper = i if words[i].box[1] < words[j].box[1] else j
                if line_has_anchor.get(line_id.get(upper)):
                    continue
            parent[_find(i)] = _find(j)

    clusters: dict[int, list[int]] = {}
    for i in idx:
        clusters.setdefault(_find(i), []).append(i)

    def _is_ambiguous(i: int) -> bool:
        return (tokens[i].lower() in patterns.AMBIGUOUS_GIVEN_NAMES
                or patterns.ocr_canon(tokens[i]) in patterns.AMBIGUOUS_CANON)

    gaz_hit = [bool(_cap(i) and not _is_ambiguous(i)
                    and (_gaz_exact_hit(tokens[i].lower()) or _gaz_compound_hit(tokens[i].lower())
                         or (len(tokens[i]) >= 5
                             and patterns.ocr_canon(tokens[i]) in patterns.CANON_GIVEN_NAMES)))
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
# Also folds the plain-ASCII confusables (o/O/0, i/l/1) to the SAME target the
# Cyrillic о/О already fold to — a double-corrupted duplicate like "A6pop" (a
# Cyrillic name "Аброр" misread as Latin by one OCR pass, where its "о" ALSO
# landed as a Latin lowercase "o" instead of a digit) needs both fixed at once
# to fold to the same string as the correctly-read "Аброр" -> "A6p0p".
_CONFUSABLE_FOLD = str.maketrans({
    "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "0",
    "р": "p", "с": "c", "т": "t", "у": "y", "х": "x", "з": "3", "б": "6",
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "0",
    "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X", "З": "3", "Б": "6",
    "o": "0", "O": "0", "l": "i", "I": "i", "1": "i",
})


def _confusable_fold(t: str) -> str:
    return t.translate(_CONFUSABLE_FOLD)


def _looks_garbled(t: str) -> bool:
    """A word mixing letters AND digits (e.g. "A6pop") is almost always an OCR
    misread of a pure-letter word, not a genuine alphanumeric value — real names/
    words don't normally contain digits. Used to pick the BETTER of two
    confusable-duplicate readings, not just whichever came first."""
    has_digit = any(c.isdigit() for c in t)
    has_letter = any(c.isalpha() for c in t)
    return has_digit and has_letter


def _dedupe_words(words: list[Word]) -> list[Word]:
    """Drop words that repeat the same text at the same spot. Running Windows OCR
    for several languages (to read Latin AND Cyrillic) reads shared text twice; this
    collapses those copies so a value isn't double-detected and names aren't doubled.
    Genuine repeats elsewhere on the screen stay (text must also OVERLAP in place).
    Compares text after confusable-folding (see above), so a Latin/Cyrillic
    look-alike pair at the same spot counts as the same duplicate too. Normally
    keeps whichever copy was seen first (both OCR langs run in a fixed order, so
    that's deterministic) — EXCEPT when the first one looks garbled (letters mixed
    with digits, e.g. "A6pop" for "Аброр") and the new one doesn't: then the
    cleaner reading replaces it, since the garbled one is never the one worth
    keeping for detection or for what gets shown in logs."""
    out: list[Word] = []
    for w in words:
        t = _confusable_fold(w.text.strip().lower())
        dup_idx = next((i for i, k in enumerate(out)
                        if t == _confusable_fold(k.text.strip().lower())
                        and _box_overlap_frac(w.box, k.box) > 0.5), None)
        if dup_idx is None:
            out.append(w)
        elif _looks_garbled(out[dup_idx].text) and not _looks_garbled(w.text):
            out[dup_idx] = w
    return out


def _is_undecodable(t: str) -> bool:
    """True if a word is ENTIRELY the Unicode replacement character (U+FFFD) —
    one OCR language pass genuinely failing to decode a glyph it can't read
    (e.g. trying to read English "Mon" with the Russian/Cyrillic pass), not a
    confusable look-alike (that's a different, already-handled case). Pure
    noise, never meaningful content: real bug this fixes -- such a token at the
    SAME box as a real word (a dual-language OCR artifact, like "Mon"'s own
    overlap) doesn't text-match it for _dedupe_words (it isn't a confusable
    substitution, just garbage), so it survived as an extra, separate "real"
    word next to a name and was enough by itself to push a lone contact name's
    line over the "isolated single name" word-count cap, silently losing the
    confidence boost that name needed to clear min_confidence."""
    return bool(t) and all(c == "�" for c in t)


def preprocess_words(words: list[Word]) -> list[Word]:
    """Split multi-token OCR 'words', drop pure-garbage (undecodable) tokens, and
    dedupe cross-language duplicates. Public so the pipeline can run this ONCE
    and feed the same clean word list to every detector (rules, the neural
    model, the cross-source surname rescue) — doing it only inside detect() left
    the model seeing raw, un-deduped words, which is what let a duplicate-but-
    garbled reading ("A6pop" next to the correctly-read "Аброр") survive as its
    own false-positive redaction. Idempotent: safe to call again on an
    already-preprocessed list (e.g. detect() does, for any caller that hands it
    raw words directly)."""
    exploded = [w for w in explode_multiword(words) if not _is_undecodable(w.text)]
    return _dedupe_words(exploded)


def detect(words: list[Word], *, names: bool = True,
           min_confidence: float = 0.0, gazetteer: set | None = None) -> list[Redaction]:
    """Full detection over OCR words. `names=False` disables the fuzzy name pass
    (keep only rock-solid structured identifiers). `min_confidence` filters out
    weaker guesses. Returns redaction boxes ready for the blur step."""
    words = preprocess_words(words)
    results: list[Redaction] = []
    for line in group_lines(words):
        results.extend(detect_structured(line))
    # Names run over ALL words (2D), not per line, so a name wrapped onto the next
    # OCR line is still joined.
    if names:
        results.extend(detect_names(words, gazetteer))
    return [r for r in results if r.confidence >= min_confidence]


def rescue_adjacent_lowercase_surnames(words: list[Word],
                                       redactions: list[Redaction]) -> list[Redaction]:
    """Extend ANY already-found name (from the gazetteer, the neural model, or
    both) with a lowercase surname-suffix word sitting right next to it — e.g. a
    Cyrillic card showing "Аброр абламидов" where the model catches "Аброр" (it
    reads Cyrillic directly) but the surname "абламидов" is lowercase and has no
    independent anchor of its own in the Latin-biased gazetteer rules.

    This runs AFTER both detectors and their merge, as a cross-source bridge:
    detect_names()'s own lowercase-surname rescue only looks at RULES anchors
    (deliberately, to stop "to'lov" latching onto an unrelated capitalized word
    like "Standard" — see its docstring) and so can't see a name the MODEL
    alone found. Working from the final redaction list sidesteps that without
    reopening the false-positive hole: only a genuine CONFIRMED name (already
    past both detectors' own guards) counts as the anchor here, nothing looser.
    """
    name_boxes = [r.box for r in redactions if r.category == "name"]
    if not name_boxes:
        return []
    out = []
    for w in words:
        t = w.text.strip(_PUNCT)
        if not t or t[:1].isupper() or not patterns.SURNAME_SUFFIX.fullmatch(t):
            continue
        if t.lower() in patterns.NAME_STOPWORDS:
            continue
        if any(_name_adjacent(w.box, nb) for nb in name_boxes):
            out.append(Redaction(w.box, "name", 0.65, w.text))
    return out
