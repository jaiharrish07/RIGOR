# Test fixtures

The skipped tests in `tests/test_papers_api.py` need one real PDF here:

    tests/fixtures/demo_01_gold_transformer.pdf

It is not committed yet because the upload endpoint does not exist, so nothing
reads it. Drop the file in when `POST /papers` lands, then remove the `@blocked`
decorators in `test_papers_api.py`.

**Why this directory and not `demo_papers/`:** `week1_lokesh.md` points the tests
at a top-level `demo_papers/`, but `.gitignore` ignores `*.pdf` and whitelists
only `docs/**/*.pdf` and `tests/fixtures/**/*.pdf`. A PDF placed in
`demo_papers/` would be silently ignored by git and would never reach a
teammate's checkout.
