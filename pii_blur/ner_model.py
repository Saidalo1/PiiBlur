"""Neural name detection — the model half of the hybrid.

A small (135 MB int8) mmBERT-small token-classifier, fine-tuned by this project
on Uzbek Latin + Cyrillic + Russian person names, run with onnxruntime (already
a dependency via RapidOCR) + the lightweight `tokenizers` library (no heavy
`transformers` needed). It catches names the gazetteer never saw — unknown
surnames, lowercase handles, dual-script text — which is what the hand-list
fundamentally can't scale to. Unlike the earlier Latin-only model this project
used, mmBERT was trained on real Cyrillic too, so it is fed the OCR text AS-IS
(no transliteration) — it reads Cyrillic natively, better than any hand-rolled
lookalike-character conversion could.

It is one layer of the hybrid, not the whole thing:
  * the gazetteer/rules still run (known names, instant and zero-risk);
  * a fixed-UI stoplist (patterns.UI_STOPWORDS) drops this model's
    characteristic false positives on app chrome ("Rad etildi", "Batafsil"…).

Everything is best-effort: any failure (missing model, missing tokenizers,
onnxruntime error) returns [] so the gazetteer still protects the user.
"""
from __future__ import annotations

import os
import re
import sys

from pii_blur.detectors import Redaction, Word, group_lines

_PER_LABELS = {7, 18}   # B-PER, I-PER in mmBERT's id2label (differs from the
                        # earlier Tahrirchi model — don't assume indices match
                        # if the model is ever swapped again; re-check id2label).
_SESSION = None
_TOKENIZER = None
_LOAD_FAILED = False
_INPUT_NAMES: list[str] = []


def _asset(name: str) -> str:
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", "ner", name)


def _load():
    """Lazily build the ONNX session + tokenizer once. Returns False if the model
    isn't available (so callers silently fall back to the gazetteer only)."""
    global _SESSION, _TOKENIZER, _LOAD_FAILED, _INPUT_NAMES
    if _LOAD_FAILED:
        return False
    if _SESSION is not None:
        return True
    try:
        import onnxruntime as ort
        from tokenizers import Tokenizer
        _TOKENIZER = Tokenizer.from_file(_asset("tokenizer.json"))
        _SESSION = ort.InferenceSession(
            _asset("ner_model_int8.onnx"), providers=["CPUExecutionProvider"])
        # Build the feed dict from whatever inputs THIS model actually declares
        # (mmBERT has no token_type_ids; the earlier model did) instead of
        # hardcoding a fixed set, so the module isn't tied to one architecture.
        _INPUT_NAMES = [i.name for i in _SESSION.get_inputs()]
        return True
    except Exception:
        _LOAD_FAILED = True
        return False


def is_available() -> bool:
    return _load()


def _softmax(x):
    import numpy as np
    e = np.exp(x - x.max(axis=-1, keepdims=True))
    return e / e.sum(axis=-1, keepdims=True)


def _person_char_mask(text: str, min_score: float) -> set[int]:
    """Char indices of `text` the model marks as a person name (>= min_score)."""
    import numpy as np

    enc = _TOKENIZER.encode(text)
    if not enc.ids:
        return set()
    available = {
        "input_ids": np.array([enc.ids], dtype=np.int64),
        "attention_mask": np.array([enc.attention_mask], dtype=np.int64),
        "token_type_ids": np.array([enc.type_ids], dtype=np.int64),
    }
    feed = {name: available[name] for name in _INPUT_NAMES if name in available}
    probs = _softmax(_SESSION.run(None, feed)[0][0])
    labels = probs.argmax(-1)
    flagged: set[int] = set()
    for i, lab in enumerate(labels):
        off = enc.offsets[i]
        if off == (0, 0):          # special token ([CLS]/[SEP]/pad)
            continue
        if int(lab) in _PER_LABELS and float(probs[i, int(lab)]) >= min_score:
            flagged.update(range(off[0], off[1]))
    return flagged


def detect_names_model(words: list[Word], min_score: float = 0.75,
                       stopwords: set | None = None) -> list[Redaction]:
    """Neural name pass. Returns a Redaction per OCR word the model flags as part
    of a person name, snapped to whole word boxes (so sub-word fragmentation never
    leaves half a name visible). Stopwords excluded. The line is fed to the model
    AS-IS — mmBERT was trained on real Cyrillic/Latin/mixed-script OCR text, so no
    transliteration step (that was only needed for the earlier Latin-only model)."""
    if not _load():
        return []
    from pii_blur import translit

    stop = stopwords if stopwords is not None else set()
    out: list[Redaction] = []
    try:
        for line in group_lines(words):
            line = sorted(line, key=lambda w: w.box[0])
            text, spans = "", []           # spans: (start, end, word) in `text`
            for w in line:
                if text:
                    text += " "
                start = len(text)
                text += w.text
                spans.append((start, start + len(w.text), w))
            flagged = _person_char_mask(text, min_score)
            if not flagged:
                continue
            for start, end, w in spans:
                if not any(c in flagged for c in range(start, end)):
                    continue
                token = re.sub(r"[^\w']", "", w.text)
                if len(token) < 3:   # real Uzbek/Russian given names are never this
                                     # short; drops 2-letter OCR noise ("Zi", "Si")
                    continue
                # Drop UI chrome (checked in both the original and a transliterated
                # form, since the stoplist itself is Latin — catches "Батафсил" too).
                if token.lower() in stop or translit.transliterate(token).lower() in stop:
                    continue
                out.append(Redaction(w.box, "name", 0.66, w.text))
    except Exception:
        return out
    return out


def warmup() -> None:
    """Prime the model (first inference is slower). Best-effort."""
    try:
        if _load():
            _person_char_mask("Alisher", 0.6)
    except Exception:
        pass
