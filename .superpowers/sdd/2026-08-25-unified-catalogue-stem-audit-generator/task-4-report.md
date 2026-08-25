# Task 4 — Merge the optional remote confidence audit

## Result

- Moved mvsepless checkpoint-confidence review code into
  `scripts/catalogue/stem_audit.py` as a distinct remote-audit path.
- Added the generator-only `--audit-stem-confidence` mode. It is mutually
  exclusive with publication modes and rejects audit-only filters outside the
  mode.
- Preserved `--guessed-only`, `--only`, `--limit`, `--json`, `--quiet`, and
  `--no-cache` (also exposed as `--no-hash-cache`). The default reuses warm
  source/config/hash caches; `--refresh` bypasses them; `--offline` is
  cache-only and rejects `--no-cache`.
- Kept JSON replacement atomic and Ctrl-C at exit 130. The audit bypasses all
  publication collection/rendering/writes.
- Removed the obsolete standalone script and migrated its behavioral coverage
  to generator/module tests. Updated live command and maintenance docs.

## TDD evidence

The first generator-mode tests were added before implementation. Their RED run
failed because `--audit-stem-confidence` was unrecognized and
`catalogue.stem_audit.run_stem_confidence_audit` did not exist. The same
focused mode suite passed after the implementation.

## Verification

```text
PYTHONPATH=.:scripts /home/rudam/ultimatevocalremovergui/.venv/bin/python -m unittest -q \
  tests.test_generate_models_catalogue tests.test_catalogue_stem_audit \
  tests.test_stem_confidence_audit tests.test_catalogue_coordinator \
  tests.test_catalogue_characterization tests.test_catalog_sources
Ran 225 tests in 0.657s
OK

basedpyright (changed source/tests): 0 errors, 0 warnings, 0 notes
ruff check + format --check (changed source/tests): clean
git diff --check: clean

PYTHONPATH=.:scripts .../python scripts/generate_models_catalogue.py \
  --audit-stem-confidence --offline --limit 0 --quiet
0 entries  0 curated  0 guessed
```

## Concerns

- A no-network offline audit can only report rows whose mvsepless/config/hash
  caches are already warm; a cold cache intentionally yields no remote work.
- Historical review/plan artifacts still mention the removed script as past
  evidence. All live source, test, and documentation references were updated.
