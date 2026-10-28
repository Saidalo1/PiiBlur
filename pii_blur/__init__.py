"""pii_blur — local, automatic PII blurring for Windows screenshots.

Pipeline:  clipboard image -> OCR (words+boxes) -> detect PII -> blur -> clipboard.

Core (detectors, redact, patterns) depends only on Pillow + stdlib and is fully
unit-tested. The OCR and clipboard layers are Windows-specific and imported
lazily, so the core runs and tests anywhere.
"""
__version__ = "0.1.0"
