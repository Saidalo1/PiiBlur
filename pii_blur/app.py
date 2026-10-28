"""Entry point.

    python -m pii_blur.app watch               # background watcher (review mode)
    python -m pii_blur.app watch --auto        # silent auto mode
    python -m pii_blur.app file in.png out.png # redact one file (for testing/eval)

The tray icon + global hotkey + settings window come later; this CLI is enough to
run and test the whole pipeline today. Packaging to a .exe is a PyInstaller step
on top of this entry point (see README).
"""
from __future__ import annotations

import argparse
import logging
import sys

from pii_blur.config import Settings


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="pii_blur")
    sub = p.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("watch", help="watch the clipboard and redact screenshots")
    w.add_argument("--auto", action="store_true", help="silent auto mode (no review)")
    w.add_argument("--no-names", action="store_true", help="only structured PII")

    f = sub.add_parser("file", help="redact a single image file")
    f.add_argument("src")
    f.add_argument("dst")
    f.add_argument("--no-names", action="store_true")

    args = p.parse_args(argv)
    settings = Settings(auto=getattr(args, "auto", False),
                        detect_names=not getattr(args, "no_names", False))

    if args.cmd == "watch":
        from pii_blur.watcher import run

        def review(original, redacted, redactions, accept):
            print(f"[review] {len(redactions)} region(s): "
                  + ", ".join(f"{r.category}={r.text!r}" for r in redactions))
            accept()  # placeholder: auto-accept until the review window exists

        run(settings, on_review=None if settings.auto else review)

    elif args.cmd == "file":
        from PIL import Image
        from pii_blur.pipeline import process_image

        img = Image.open(args.src)
        out, reds = process_image(img, settings)
        out.save(args.dst)
        print(f"redacted {len(reds)} region(s) -> {args.dst}")
        for r in reds:
            print(f"  {r.category:9} conf={r.confidence:.2f} {r.text!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
