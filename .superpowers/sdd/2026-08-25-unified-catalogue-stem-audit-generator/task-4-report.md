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

## Fix round 1/5 — offline refresh precedence and cold-cache audit loading

### Root cause

- `FetchPolicy.refresh` retained `--refresh` under `--offline`, so the remote
  audit deliberately bypassed warm legacy config and checkpoint-hash caches
  before refusing network access.
- `STALE_WHILE_REVALIDATE` is correct for the UI, but a cold source cache only
  schedules its fetch and immediately returns no content. An audit must have
  its target list before it can report findings.

### TDD evidence

RED:

```text
$ PYTHONPATH=.:scripts /home/rudam/ultimatevocalremovergui/.venv/bin/python -m unittest -v \
  tests.test_stem_confidence_audit.ConfidenceAuditSelectionAndPolicyTests \
  tests.test_generate_models_catalogue.StemConfidenceAuditModeTests
FAIL: test_cold_online_catalogue_load_blocks_until_one_target_is_available
AssertionError: [] != ['fetched']
FAIL: test_offline_refresh_reuses_warm_source_config_and_hash_caches
AssertionError: Expected 'load_mdx_c_config' to have been called once. Called 0 times.
Ran 13 tests — FAILED (failures=2)
```

GREEN:

```text
$ PYTHONPATH=.:scripts /home/rudam/ultimatevocalremovergui/.venv/bin/python -m unittest -q \
  tests.test_generate_models_catalogue tests.test_catalogue_stem_audit \
  tests.test_stem_confidence_audit tests.test_catalogue_coordinator \
  tests.test_catalogue_characterization tests.test_catalog_sources
Ran 227 tests in 0.651s
OK

$ PYTHONPATH=.:scripts /home/rudam/ultimatevocalremovergui/.venv/bin/python -m basedpyright \
  scripts/generate_models_catalogue.py scripts/catalogue/stem_audit.py \
  tests/test_generate_models_catalogue.py tests/test_stem_confidence_audit.py
0 errors, 0 warnings, 0 notes

$ ruff check ... && ruff format --check ... && git diff --check
All checks passed; all files formatted; no whitespace errors
```

### Fix

- The generator now normalizes effective refresh to `args.refresh and not
  args.offline`, so every downstream audit boundary reuses warm caches when
  offline.
- The audit now loads mvsepless disk cache with `OFFLINE` first, uses any
  available cache immediately, then performs one blocking `FORCE` fetch only
  for a cold online cache or explicit refresh.
- Regression coverage proves `--offline --refresh` reaches warm source,
  config, and hash caches without invoking network boundaries, and that a
  cold online cache audits the fetched target instead of reporting zero rows.
