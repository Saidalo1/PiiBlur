# Contributing

Thanks for helping! The most valuable contributions are **more PII patterns for
more countries** and **real-world misses**.

## Add a country's PII

1. Add the regex + a validator (if the format has a checksum) in
   `pii_blur/patterns.py`, in `STRUCTURED` (most-specific first).
2. Add a generator in `tests/_gen.py` and wire it into `tests/test_massive.py`.
3. Keep the golden rule: **only match distinctive shapes** (dashes/prefix/checksum),
   never bare runs of digits — that's what keeps false-positives at ~0.
4. `pytest -q` must stay green (14,000+ cases), and the aggregate
   (`python tests/test_massive.py`) must keep **0% false-positives on decoys**.

## Report a miss / over-blur

Open an issue with the (fake!) text that was missed or wrongly blurred, and the
expected result. Never paste real personal data.

## Dev setup

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
python -m pii_blur.tray      # run
pytest -q                    # test
python build.py              # installer
```

Good first issues are labeled `good first issue`.
