# Manual / ad-hoc test scripts

These are **standalone manual scripts**, not part of the automated `pytest`
suite (which lives in `tests/` and is the source of truth — see
`setup.cfg: testpaths = tests`). They were historically dropped in the repo
root; they're collected here to keep the root clean.

They are smoke/integration probes (some hit a running server, some poke the DB
directly). Run them from the **repository root** so the top-level modules
resolve, e.g.:

```bash
python -m scripts.manual_tests.test_endpoints
```

Several overlap with — and are now superseded by — coverage in `tests/`
(e.g. `test_auth_current.py` is covered by `tests/test_backend_auth.py`).
They are kept for now as a convenience; prune freely once confirmed redundant.
