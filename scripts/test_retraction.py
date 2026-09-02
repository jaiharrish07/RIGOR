"""Manual smoke test for the Crossref retraction lookup.

Run:  python -m scripts.test_retraction

The DOIs below were verified against the live Crossref API on 2026-08-26.
Note that week1_lokesh.md's two example DOIs are BOTH wrong:
  - its "retracted example" 10.1038/s41586-019-1666-5 returns `none`
    (the doc flags this one itself as a placeholder), and
  - its "clean example"  10.48550/arXiv.1706.03762 returns `unavailable`,
    because arXiv DOIs are registered with DataCite, not Crossref.

KNOWN COVERAGE LIMIT: this checks Crossref's `update-to` relation, which only
exists where the publisher deposited the retraction notice as a relation. Several
famous retractions are NOT represented there and come back `none` -- see the
"known retracted but undetected" group below. Treat `none` as "no retraction
relation found", not as proof the work is sound.
"""
from app.external.crossref import check_retraction

CASES = [
    # label,                          doi,                              expected
    ("retracted (Surgisphere/Lancet)", "10.1016/S0140-6736(20)31180-6", "retracted"),
    ("clean (BERT, NAACL 2019)",       "10.18653/v1/N19-1423",          "none"),
    ("clean (ResNet, CVPR 2016)",      "10.1109/CVPR.2016.90",          "none"),
    ("URL form normalises",            "https://doi.org/10.18653/v1/N19-1423", "none"),
    ("unknown DOI",                    "10.9999/does-not-exist-xyz",    "unavailable"),
    ("empty DOI",                      "",                              "unavailable"),
]

# Retracted in reality, but Crossref has no `update-to` relation for them.
UNDETECTED = [
    ("Wakefield MMR (Lancet 1998)",  "10.1016/S0140-6736(97)11096-0"),
    ("STAP cells (Nature 2014)",     "10.1038/nature12968"),
    ("Schon (Science 2001)",         "10.1126/science.1065389"),
]


def main() -> None:
    print("=== expected behaviour ===")
    failures = 0
    for label, doi, expected in CASES:
        result = check_retraction(doi)
        ok = result.status == expected
        failures += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {label:<32} -> {result.status}"
              f"{'' if ok else f' (expected {expected})'}")

    print("\n=== known coverage limit: retracted, but Crossref shows no relation ===")
    for label, doi in UNDETECTED:
        result = check_retraction(doi)
        print(f"  {label:<32} -> {result.status}")

    print(f"\n{'ALL EXPECTED CASES PASSED' if not failures else f'{failures} FAILED'}")


if __name__ == "__main__":
    main()
