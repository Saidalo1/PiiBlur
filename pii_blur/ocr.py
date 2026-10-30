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

from pii_blur.detectors import Word


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


def _winocr(img, langs) -> list[Word] | None:
    """Windows' built-in OCR (Windows.Media.Ocr) — native, ~30x faster than the
    ONNX engine, gives word-level boxes, and reads whatever language PACKS are
    installed (so Cyrillic works when the Russian pack is present).

    Two robustness touches:
      * small/narrow screenshots are upscaled ~2x first — more pixels per glyph
        makes the engine read small UI text far more reliably (it only adds
        detail, never drops any), and boxes are scaled back to the original
        coordinates. Checked on WIDTH specifically (not just overall size): a
        tall phone-style chat list (many rows stacked, narrow width) has small
        character pixel-height even though the total image is tall — real
        example that motivated this: a 536x1361 chat screenshot where two full
        names OCR'd as unreadable fragments ("Sa Iomat Ota 0ta m т u и rodova")
        at native size, but read perfectly ("Salomat Otamurodova") once
        upscaled 2x. (OCR research: the real target is glyph cap-height in
        pixels, not raw image dimensions — width is what actually constrains
        that for this kind of UI screenshot.)
      * every requested language is tried and the words MERGED, so a card mixing
        Latin (Uzbek) and Cyrillic (Russian) is fully read. A language whose pack
        isn't installed just raises and is skipped.

    Returns None if NO language could run, so the caller falls back to RapidOCR.
    """
    import winocr  # Windows.Media.Ocr wrapper

    base = img.convert("RGB")
    scale = 2 if (base.width < 900 or max(base.size) < 1200) else 1
    im = base if scale == 1 else base.resize((base.width * scale, base.height * scale))

    words: list[Word] = []
    ran_any = False
    for lang in (langs or ("en-US",)):
        try:
            result = winocr.recognize_pil_sync(im, lang)
        except Exception:
            continue  # language pack not installed / unsupported tag — skip it
        ran_any = True
        for line in result.get("lines", []) or []:
            for w in line.get("words", []) or []:
                r = w["bounding_rect"]
                words.append(Word(w["text"], (int(r["x"] / scale), int(r["y"] / scale),
                                              int(r["width"] / scale), int(r["height"] / scale))))
    return words if ran_any else None


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
