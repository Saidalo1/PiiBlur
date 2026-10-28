"""End-to-end visual demo WITHOUT an OCR engine.

We render a fake 'screenshot' with PIL, and because we drew the text ourselves we
know each word's box — so we feed those boxes in as a stand-in for OCR output.
That exercises the real detect + blur pipeline and produces before/after images.
On a real machine, ocr.ocr_words() provides these boxes instead.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pii_blur.detectors import Word, detect
from pii_blur.redact import apply

LINES = [
    "Mijoz kartasi / Client card",
    "F.I.Sh: Karimov Alisher Botir o'g'li",
    "Telefon: +998 90 123 45 67",
    "Email: alisher.karimov@mail.uz",
    "Pasport: AD 1234567",
    "PINFL: 3 150590 123 456 0",
    "Karta: 8600 0691 9540 6832",
    "Manzil: Toshkent sh. (ochiq ma'lumot)",
]


def build():
    try:
        font = ImageFont.truetype("arial.ttf", 22)
    except Exception:
        font = ImageFont.load_default()
    W = 640
    pad, lh = 20, 38
    H = pad * 2 + lh * len(LINES)
    img = Image.new("RGB", (W, H), (245, 246, 248))
    d = ImageDraw.Draw(img)
    words = []
    for i, line in enumerate(LINES):
        y = pad + i * lh
        x = pad
        for tok in line.split(" "):
            d.text((x, y), tok, fill=(20, 20, 25), font=font)
            bb = d.textbbox((x, y), tok, font=font)
            w, h = bb[2] - bb[0], bb[3] - bb[1]
            words.append(Word(tok, (x, y, w, h)))
            x += w + d.textlength(" ", font=font)
    return img, words


def main():
    img, words = build()
    img.save(ROOT / "examples" / "demo_before.png")
    reds = detect(words, names=True, min_confidence=0.6)
    out = apply(img, reds, pad=3, strength=12)
    out.save(ROOT / "examples" / "demo_after.png")
    print(f"found {len(reds)} PII region(s):")
    for r in sorted(reds, key=lambda r: r.box[1]):
        print(f"  {r.category:9} conf={r.confidence:.2f}  {r.text!r}")


if __name__ == "__main__":
    main()
