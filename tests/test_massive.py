"""Large generated PII suite — thousands of cases.

Positives must be detected; negatives must not trip the STRUCTURED detectors
(names are fuzzy, so we don't assert them on decoys — their false-positive rate
is reported by the __main__ aggregate instead).

Run with pytest (collects thousands of parametrized cases):
    pytest tests/test_massive.py -q
Or as an aggregate report (recall/precision), no pytest needed:
    python tests/test_massive.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pii_blur.detectors import detect
from tests import _gen

STRUCTURED_CATS = {"email", "card", "phone", "passport", "pinfl",
                   "snils", "ssn", "iban", "ip"}

# Build the datasets once (seeded → reproducible).
POSITIVES = (
    _gen.gen_phones(1500) + _gen.gen_cards(1500) + _gen.gen_pinfls(1200)
    + _gen.gen_passports(1000) + _gen.gen_emails(1000) + _gen.gen_names(1200)
    # international
    + _gen.gen_ru_phones(800) + _gen.gen_intl_phones(600) + _gen.gen_snils(600)
    + _gen.gen_ssn(600) + _gen.gen_iban(600) + _gen.gen_ipv4(600)
    + _gen.gen_ru_names(1000)
)
NEGATIVES = _gen.gen_negatives(2000)


def _cats(words, min_conf=0.5):
    return {r.category for r in detect(words, names=True, min_confidence=min_conf)}


# ── pytest: one case per sample (thousands of tests) ────────────────────────
try:
    import pytest

    @pytest.mark.parametrize("label,words,expected",
                             POSITIVES, ids=[p[0][:40] for p in POSITIVES])
    def test_positive(label, words, expected):
        cats = _cats(words, min_conf=0.0)
        assert expected in cats, f"{label}: expected {expected}, got {cats}"

    @pytest.mark.parametrize("label,words,_",
                             NEGATIVES, ids=[n[0][:40] for n in NEGATIVES])
    def test_negative_no_structured(label, words, _):
        cats = _cats(words, min_conf=0.5)
        leaked = cats & STRUCTURED_CATS
        assert not leaked, f"{label}: false positive {leaked}"
except ImportError:
    pass  # pytest not installed — use the __main__ aggregate below


# ── aggregate report (works without pytest) ─────────────────────────────────
def _aggregate():
    from collections import Counter
    rec_hit, rec_tot = Counter(), Counter()
    for label, words, expected in POSITIVES:
        rec_tot[expected] += 1
        if expected in _cats(words, 0.0):
            rec_hit[expected] += 1

    fp_struct = 0
    name_fp = 0
    for label, words, _ in NEGATIVES:
        cats = _cats(words, 0.5)
        if cats & STRUCTURED_CATS:
            fp_struct += 1
        if "name" in cats:
            name_fp += 1

    print(f"POSITIVES: {len(POSITIVES)}   NEGATIVES: {len(NEGATIVES)}")
    print("recall by category:")
    overall_hit = overall_tot = 0
    for cat in sorted(rec_tot):
        hit, tot = rec_hit[cat], rec_tot[cat]
        overall_hit += hit; overall_tot += tot
        print(f"  {cat:9} {hit}/{tot}  = {hit/tot*100:6.2f}%")
    print(f"  {'OVERALL':9} {overall_hit}/{overall_tot} = {overall_hit/overall_tot*100:6.2f}%")
    print(f"structured false-positives on decoys: {fp_struct}/{len(NEGATIVES)} "
          f"= {fp_struct/len(NEGATIVES)*100:.2f}%")
    print(f"name false-positives on decoys:       {name_fp}/{len(NEGATIVES)} "
          f"= {name_fp/len(NEGATIVES)*100:.2f}%")
    return overall_hit, overall_tot, fp_struct


def _structured_recall():
    hit = tot = 0
    for _, words, expected in POSITIVES:
        if expected == "name":
            continue
        tot += 1
        if expected in _cats(words, 0.0):
            hit += 1
    return hit, tot


if __name__ == "__main__":
    h, t, fp = _aggregate()
    sh, st = _structured_recall()
    # Hard gate: structured identifiers must be near-perfect and decoys clean.
    # Names are fuzzy by design -> reported, not gated.
    ok = (sh / st >= 0.995) and (fp / len(NEGATIVES) <= 0.02)
    print(f"\nstructured recall (gated): {sh}/{st} = {sh/st*100:.2f}%")
    print("RESULT:", "PASS" if ok else "NEEDS WORK")
    sys.exit(0 if ok else 1)
