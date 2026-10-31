"""OCR backends -> a flat list of detectors.Word (text + pixel box).

Three backends, tried in order of "best fit for Windows + offline + free":

  1. winocr      -> Windows.Media.Ocr, built into Win10/11, offline, fast on CPU,
                    gives word bounding boxes. No GPU. Needs the language pack.
  2. rapidocr    -> ONNX neural OCR (CPU), better on small/low-contrast text,
                    ~15 MB models downloaded once.
  3. pytesseract -> Tesseract; `image_to_data` gives word boxes. Ubiquitous.

All imports are lazy so the core/tests don't require any OCR engine installed.
Each backend is normalized to the same Word list, so detection code never cares
which engine ran.
"""
from __future__ import annotations

from pii_blur.detectors import Word, _box_overlap_frac, _looks_garbled


def ocr_words(img, langs=("en-US",)) -> list[Word]:
    """Return OCR words with boxes using the first backend that is available."""
    for backend in (_winocr, _rapidocr, _tesseract):
        try:
            words = backend(img, langs)
            if words is not None:
                return words
        except Exception:
            continue
    raise RuntimeError(
        "No OCR backend available. Install one of: winocr (Windows), "
        "rapidocr-onnxruntime, or pytesseract + the Tesseract binary."
    )


_TARGET_CAP_HEIGHT = 26   # px; OCR tuning guidance puts the reliable sweet spot at
                          # ~20-40px glyph height, with accuracy collapsing below ~10px.
_MIN_READABLE_HEIGHT = 16  # px; below this a corrective upscale pass is worth the cost.


def _merge_scale_pass(base_words: list[Word], extra_words: list[Word]) -> list[Word]:
    """Merge a second OCR pass's words into the first, keeping only ONE reading
    per glyph region instead of stacking every scale's guess there.

    A truncated word at the edge of a narrow crop can OCR into a DIFFERENT
    garbled fragment at each scale ("Bakalavr" cut off at the image edge read as
    "llavr" at one scale, "Navr"/"ilavr" at another) -- these don't share any
    text, so the plain text-match dedup in detectors._dedupe_words can't catch
    them as duplicates, and they survived as extra, distinct-looking "words"
    wedged right next to real cell text. That was enough noise in the line fed
    to the neural name model to make it mistag the neighbouring real words
    ("Kechki"/"Kunduzgi") as part of a name -- a real false positive from a
    narrow, close-cropped table screenshot. Matching purely by BOX POSITION
    (same >50% overlap threshold the text-based dedup uses) catches this: for
    each extra-pass word landing on a region a base-pass word already covers,
    keep the single better reading (the longer one -- a truncation artifact is
    usually the shorter fragment -- tie-broken by preferring the non-garbled
    one), rather than keeping both. A region with no existing match is new
    information from the extra pass and is kept as before."""
    merged = list(base_words)
    for w in extra_words:
        dup_idx = next((i for i, k in enumerate(merged)
                        if _box_overlap_frac(w.box, k.box) > 0.5), None)
        if dup_idx is None:
            merged.append(w)
            continue
        existing = merged[dup_idx]
        if len(w.text) > len(existing.text):
            merged[dup_idx] = w
        elif (len(w.text) == len(existing.text)
                and _looks_garbled(existing.text) and not _looks_garbled(w.text)):
            merged[dup_idx] = w
    return merged


def _median_word_height(words: list[Word]) -> float | None:
    """Median box height of real (2+ char) words — a cheap proxy for glyph
    cap-height. Single-char words (noise, punctuation, bullet glyphs) are
    excluded so they don't skew the estimate."""
    heights = sorted(w.box[3] for w in words if len(w.text.strip()) >= 2)
    return heights[len(heights) // 2] if heights else None


_SKEW_ANGLE_DEG = 0.3    # a digital screenshot is always perfectly level (0.0);
                         # Windows OCR's own skew estimate going past this on a
                         # wide-enough image is a strong, free signal that this
                         # is a PHOTOGRAPH of paper, not a screen capture.
_SCAN_MIN_WIDTH = 300    # below this, a narrow UI crop can show spurious tiny
                         # non-zero angles (sparse text confuses the estimate) —
                         # a photographed page is realistically never this narrow.


def _ocr_pass(base, scale: int, langs) -> tuple[list[Word], bool, float | None]:
    import winocr

    im = base if scale == 1 else base.resize((base.width * scale, base.height * scale))
    words: list[Word] = []
    ran_any = False
    angle: float | None = None
    for lang in langs:
        try:
            result = winocr.recognize_pil_sync(im, lang)
        except Exception:
            continue  # language pack not installed / unsupported tag — skip it
        ran_any = True
        if angle is None:
            angle = result.get("text_angle")
        for line in result.get("lines", []) or []:
            for w in line.get("words", []) or []:
                r = w["bounding_rect"]
                words.append(Word(w["text"], (int(r["x"] / scale), int(r["y"] / scale),
                                              int(r["width"] / scale), int(r["height"] / scale))))
    return words, ran_any, angle


def _scan_enhanced_pass(base, langs) -> list[Word]:
    """Deskew + contrast-boost + binarize (see scan_preprocess.py), then OCR the
    result at 2x and 3x -- the dedicated path for a PHOTOGRAPHED document (see
    the skew-angle trigger in _winocr). Verified directly on a real case: a
    phone photo of a printed Cyrillic name list OCR'd as near-total garbage
    ("ECbKOB" for a real surname) through the plain upscale path; after this
    enhancement, the same Russian pass read real, correct surnames
    ("АЛЕКСЕЕВ", "АНТОНОВ", "АРЕСТОВ"). Both scales' words are merged the same
    position-based way as the other extra passes."""
    from pii_blur.scan_preprocess import enhance_for_scan

    enhanced = enhance_for_scan(base)
    words, ran_any, _ = _ocr_pass(enhanced, 2, langs)
    extra, ok, _ = _ocr_pass(enhanced, 3, langs)
    if ran_any or ok:
        words = _merge_scale_pass(words, extra)
    else:
        words = []
    return _merge_scale_pass(words, _cyrillic_scan_words(enhanced))


_CYRILLIC_ENGINE = None  # built once and reused, same reasoning as _RAPID_ENGINE
                         # below — rebuilding an ONNX session per screenshot is
                         # the main cause of a slow/laggy blur.


def _cyrillic_scan_words(enhanced_img) -> list[Word]:
    """Cyrillic-script OCR of an already-enhanced (deskewed/binarized) photo via
    the `rapidocr` package's dedicated Cyrillic PP-OCRv5 model — a SEPARATE
    model from the Chinese+English one winocr/rapidocr-onnxruntime default to,
    which only approximates Cyrillic glyphs with similar-LOOKING Latin letters
    ("АЛЕКСЕЕВ" -> "AJEKCEEB") rather than reading the script. Verified
    directly: on the same real photographed Cyrillic list, this reads real,
    correctly-spelled surnames ("АЛЕКСЕЕВ Максим Михайлович") where winocr's
    Russian pass and the default rapidocr model both failed. Best-effort: any
    failure (package/model unavailable) returns [] so the rest of the scan
    pass still works without it."""
    global _CYRILLIC_ENGINE
    try:
        import numpy as np
        if _CYRILLIC_ENGINE is None:
            from rapidocr import RapidOCR
            from rapidocr.utils.typings import ModelType, OCRVersion
            _CYRILLIC_ENGINE = RapidOCR(params={
                "Rec.lang_type": "cyrillic",
                "Rec.ocr_version": OCRVersion.PPOCRV5,
                "Rec.model_type": ModelType.MOBILE,
            })
        result = _CYRILLIC_ENGINE(np.array(enhanced_img))
        if result is None or not result.txts:
            return []
        words: list[Word] = []
        for box, text in zip(result.boxes, result.txts):
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            x, y = min(xs), min(ys)
            words.append(Word(text, (int(x), int(y), int(max(xs) - x), int(max(ys) - y))))
        return words
    except Exception:
        return []


def _winocr(img, langs) -> list[Word] | None:
    """Windows' built-in OCR (Windows.Media.Ocr) — native, ~30x faster than the
    ONNX engine, gives word-level boxes, and reads whatever language PACKS are
    installed (so Cyrillic works when the Russian pack is present).

    Robustness touches:
      * small/narrow screenshots are upscaled ~2x+3x first (verified ensemble,
        see below) — more pixels per glyph makes the engine read small UI text
        far more reliably. Checked on WIDTH specifically (not just overall
        size): a tall phone-style chat list (many rows stacked, narrow width)
        has small character pixel-height even though the total image is tall —
        real example: a 536x1361 chat screenshot where two full names OCR'd as
        unreadable fragments at native size, but read perfectly once upscaled.
        This exact width-based branch and its 2x+3x merge is empirically
        verified against the full real-screenshot regression suite (19/19
        names caught, same 2 pre-existing false positives) — replacing it with
        a from-measurement approach was tried and made things WORSE on these
        same images (17/19, more false positives), so it stays exactly as
        tested rather than being "improved" on theory alone.
      * for an image that ISN'T small by that check — e.g. a screenshot of an
        entire large page taken "from far away", where the overall image is
        big but individual glyphs are still tiny (the width/size heuristic
        above has no way to see that) — this now MEASURES the actual median
        glyph height from the native-resolution pass's own word boxes, and
        only pays for a second, higher-resolution corrective pass when that
        measured height is below the ~16px floor, scaled to land the retry
        around the ~26px sweet spot (OCR tuning guidance: reliable accuracy
        needs ~20-40px cap-height, collapsing below ~10px). Real case this
        fixes: passport numbers in a wide full-page table screenshot read fine
        once cropped close, but were missed/garbled in the same table captured
        zoomed-out — raw image size alone said nothing about actual text size.
      * when a second pass runs (either branch), its words are MERGED with the
        first pass's, not replacing them — no single scale wins on every region
        of a page (confirmed directly: a watermarked passport number read as
        truncated "760134" at one scale but correct "AD1760134" at another),
        and the merge is safe because the PII pattern matchers downstream are
        strict enough to ignore a truncated/garbled leftover from the weaker
        pass while a correct reading from either pass still gets through. One
        exception found by testing: the SECOND pass's own single-character
        noise tokens (a stray "2", a misread symbol) are dropped before
        merging — they never carry enough signal to complete any PII pattern on
        their own, but one landing right next to an otherwise-bare gazetteer
        name (e.g. "akmal") broke the "isolated lone name" confidence boost by
        making it look like it had a neighbour. The first pass's own tokens,
        noise included, are kept as before — only a corrective second pass is
        filtered this way.
      * every requested language is tried and the words MERGED too, so a card
        mixing Latin (Uzbek) and Cyrillic (Russian) is fully read. A language
        whose pack isn't installed just raises and is skipped.

    Returns None if NO language could run, so the caller falls back to RapidOCR.
    """
    base = img.convert("RGB")
    langs = tuple(langs or ("en-US",))
    small = base.width < 900 or max(base.size) < 1200

    if small:
        # Verified ensemble (see docstring) — do not replace with a measured
        # approach without re-running the full real-screenshot regression suite.
        words, ran_any, angle = _ocr_pass(base, 2, langs)
        extra, ok, _ = _ocr_pass(base, 3, langs)
        ran_any = ran_any or ok
        extra = [w for w in extra if len(w.text.strip()) > 1]  # see docstring
        if not ran_any:
            return None
        words = _merge_scale_pass(words, extra)
    else:
        words, ran_any, angle = _ocr_pass(base, 1, langs)
        if not ran_any:
            return None
        med_h = _median_word_height(words)
        if med_h is not None and med_h < _MIN_READABLE_HEIGHT:
            scale = max(2, min(4, round(_TARGET_CAP_HEIGHT / med_h)))
            extra, _, _ = _ocr_pass(base, scale, langs)
            extra = [w for w in extra if len(w.text.strip()) > 1]  # see docstring
            words = _merge_scale_pass(words, extra)

    # A photographed document (see scan_preprocess.py / _scan_enhanced_pass):
    # Windows OCR's own skew estimate is reliably exactly 0.0 for a digital
    # screenshot (it's pixel-perfectly level) and non-zero for a hand-held
    # phone photo of paper, which is never perfectly level. Gated on width too
    # — a narrow UI crop with sparse text can report a spurious tiny angle.
    if angle is not None and abs(angle) > _SKEW_ANGLE_DEG and base.width >= _SCAN_MIN_WIDTH:
        words = _merge_scale_pass(words, _scan_enhanced_pass(base, langs))
    return words


_RAPID_ENGINE = None  # built once, reused — building it per call reloaded the ONNX
                      # models every screenshot (the main cause of slow/laggy blur).


def _rapid_engine():
    global _RAPID_ENGINE
    if _RAPID_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR
        _RAPID_ENGINE = RapidOCR()
    return _RAPID_ENGINE


def _rapidocr(img, langs) -> list[Word] | None:
    import numpy as np

    engine = _rapid_engine()
    res, _ = engine(np.array(img.convert("RGB")))
    if not res:
        return []
    words: list[Word] = []
    for box, text, _conf in res:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        x, y = min(xs), min(ys)
        words.append(Word(text, (int(x), int(y), int(max(xs) - x), int(max(ys) - y))))
    return words


def _tesseract(img, langs) -> list[Word] | None:
    import pytesseract
    from pytesseract import Output

    lang = "+".join(l.split("-")[0] for l in langs) or "eng"
    lang = lang.replace("en", "eng")
    data = pytesseract.image_to_data(img.convert("RGB"), lang=lang, output_type=Output.DICT)
    words: list[Word] = []
    for i, txt in enumerate(data["text"]):
        if txt and txt.strip() and int(data["conf"][i]) > 30:
            words.append(Word(txt, (data["left"][i], data["top"][i],
                                    data["width"][i], data["height"][i])))
    return words


def warmup(langs=("en-US",)) -> None:
    """Load and prime the OCR engine ahead of the first real screenshot.

    The first OCR call otherwise pays a one-off ~1-3 s model-load cost, which lands
    on the user's very first paste. Call this once from a background thread at
    startup so that first blur is already fast. Best-effort: any failure is ignored
    (the next real call just pays the cost itself)."""
    try:
        from PIL import Image
        ocr_words(Image.new("RGB", (32, 32), "white"), langs)
    except Exception:
        pass
