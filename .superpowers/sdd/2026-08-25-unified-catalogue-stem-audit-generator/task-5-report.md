# Task 5 — Integrated verification and generated artefacts

## Result

- Regenerated the Markdown catalogue, IR sidecar, intent TSV, display TSV, and
  stem-semantics TSV from one authoritative `--refresh` snapshot.
- Kept all catalogue/config/cache writes outside the repository runtime tree by
  setting `UVR_DATA_DIR=/tmp/uvr-task5-catalogue.reJ2hv`.
- The refreshed universe retained exactly **485 canonical IDs** and the
  stem-semantics reference retained exactly **1,206 output/context rows**.
- Verified the same snapshot with a warm `--offline --check`; it exited 0, all
  five artefact hashes remained unchanged, and the isolated cache file/mtime/size
  fingerprint remained unchanged.
- Removed the obsolete `.gitignore` allowlist for the deleted
  `scripts/stem_semantics_audit.py`. A live-tree search found no remaining
  reference outside historical review/plan/SDD evidence.
- Fixed the two new test modules so the documented no-`PYTHONPATH` unittest
  discovery command can import them.
- No runtime settings, user caches, user model data, or model weights were
  changed. Test runtime data and Numba caches were isolated under `/tmp`.

## Authoritative generation and warm-offline parity

Authoritative refresh (network escalation was limited to this command):

```text
$ env UVR_DATA_DIR=/tmp/uvr-task5-catalogue.reJ2hv PYTHONPATH=.:scripts \
    /home/rudam/ultimatevocalremovergui/.venv/bin/python \
    scripts/generate_models_catalogue.py --refresh
Wrote .../docs/models-catalogue.md (485 models, 483 with metadata,
2 unknown, 3 flagged, 0 unsupported omitted)
Wrote .../docs/models-catalogue.ir.json
Wrote .../docs/model_intent_reference.tsv
Wrote .../docs/model_display_reference.tsv
Wrote .../docs/model_stem_semantics_reference.tsv
exit 0
```

Warm offline comparison, run again after all tests and edits:

```text
$ env UVR_DATA_DIR=/tmp/uvr-task5-catalogue.reJ2hv PYTHONPATH=.:scripts \
    .venv/bin/python scripts/generate_models_catalogue.py --offline --check
Up to date: .../docs/models-catalogue.md
exit 0
```

The isolated snapshot fingerprint, calculated from every cache file's path,
mtime, and size, was identical before and after offline checking:

```text
625dca640db90f68ca9729e9ca114c9030c36072340ebd5b62ccb081174cb8e0
```

Artefact SHA-256 values after the final offline check:

```text
34d06cee40315515375fa45e0584554f544294fea89fed532821d8a0177860d5  docs/models-catalogue.md
95c01254f57b57b9f03b1e0dd7c0f5e722f714379092a8be9959db15d360439c  docs/models-catalogue.ir.json
950e967a28242e50b23d92fce63cb5f15a3954ae22c38416e88c3f1a79a396a1  docs/model_intent_reference.tsv
dcf3996944628150aaa2c24f2570fb2b85e72436877544d339a8e6755f5af078  docs/model_display_reference.tsv
a7c5a29a2e11017e6ef11f2959e4041b86f43da249e185640fb39ce1225790d7  docs/model_stem_semantics_reference.tsv
```

The IR reports `entry_count=485`, contains 485 entries, and is tied to the
Markdown digest `34d06cee...60d5`. The display TSV has 485 data rows and 485
unique canonical IDs. The stem TSV has 1,207 physical lines: one header plus
1,206 data rows, covering 485 unique canonical IDs. Offline summary reported
455 reviewed models, 30 waived models, 0 raw models, and no stem semantic audit
findings.

The intent TSV was already byte-identical. Tracked regeneration updated the
Markdown catalogue, display TSV, and expanded stem-semantics TSV. The IR
sidecar is intentionally gitignored by repository contract, so it was generated
and verified but is not staged.

## Artefact interpretation

The isolated clean-checkout output has 483 rather than 485 resolved metadata
rows because the two Apollo execution sidecars contain no stem inventory and
the unified collector deliberately does not fetch them as supplemental stem
metadata. The old checked-in document had observed two untracked Apollo YAMLs
from the primary checkout's runtime MDX config directory. The clean output now
uses execution architecture `Apollo`, leaves those two metadata fields
unavailable, and retains both canonical IDs. This is environment cleanup, not
an upstream catalogue membership change.

## Focused suites

Non-GTK generator, audit, manifest, source, cache, probe, and sweep coverage was
run without a `PYTHONPATH` override:

```text
$ env -u PYTHONPATH .venv/bin/python -m unittest -q \
    tests.test_generate_models_catalogue \
    tests.test_catalogue_stem_audit \
    tests.test_stem_confidence_audit \
    tests.test_model_stem_manifest \
    tests.test_catalog_sources \
    tests.test_catalog_stem_merge \
    tests.test_catalog_dedupe \
    tests.test_catalogue_characterization \
    tests.test_catalogue_coordinator \
    tests.test_catalogue_stem_cache \
    tests.test_extra_catalog \
    tests.test_mvsepless_catalog \
    tests.test_politrees_catalog \
    tests.test_remote_catalog_cache \
    tests.test_model_probe \
    tests.test_model_sweep
Ran 537 tests in 12.417s
OK (skipped=2)
```

The GTK catalogue-preferences source test was run separately through the
private Wayland/Mutter runner. It reported a private `codex-gtk` socket and
returned the runner's own exit status:

```text
$ codex sandbox ... -P gtk-headless \
    run-private-wayland.sh -- env UVR_DISABLE_POLITREES=1 \
    UVR_DISABLE_MVSEPLESS=1 ... python -m unittest -v \
    tests.test_preferences_catalogue_refresh
Ran 5 tests in 0.443s
OK
exit 0
```

The two test modules that previously depended on `PYTHONPATH=.:scripts` were
also verified directly after adding local `scripts/` path setup:

```text
$ env -u PYTHONPATH .venv/bin/python -m unittest -v \
    tests.test_catalogue_stem_audit tests.test_stem_confidence_audit
Ran 23 tests in 0.011s
OK
```

## Static and whitespace verification

Ruff was scoped to the unified generator implementation and its directly
associated tests:

```text
$ .venv/bin/ruff check scripts/generate_models_catalogue.py \
    scripts/catalogue/collect.py scripts/catalogue/render.py \
    scripts/catalogue/stem_audit.py tests/test_generate_models_catalogue.py \
    tests/test_catalogue_stem_audit.py tests/test_stem_confidence_audit.py
All checks passed!

$ .venv/bin/ruff format --check <same seven files>
7 files already formatted

$ .venv/bin/python -m basedpyright
0 errors, 0 warnings, 0 notes

$ git diff --check
exit 0
```

`scripts/model_probe.py` and `scripts/model_tool_support.py` have comment-only
Task 4 edits but pre-existing Ruff formatting/import debt. They were not
mechanically reformatted in Task 5 because that would be unrelated cleanup;
their complete focused test modules are included in the 537-test green run.

## Complete unit suite and classified limitation

The exact documented discovery command was run without `PYTHONPATH`, inside
private Wayland. The tracked model seed tree, runtime data, and Numba cache were
copied/placed under `/tmp`:

```text
$ .venv/bin/python -m unittest discover -s tests -t . -v
Ran 2955 tests in 89.931s
FAILED (failures=1, skipped=22)
```

Sole failure:

```text
tests.test_cli_list_models.DiscoveryTests.
test_models_show_configures_installed_demucs_canonical_id
AssertionError: 2 != 0: error: unknown model 'demucs:hdemucs_mmi'
```

Classification evidence:

1. The test fails identically when run alone at Task 5 HEAD.
2. A clean archive of base `4fbc68e6b1d08f25141e274ca900fc2a59070ef1`
   was extracted under `/tmp`, linked only to the shared venv, and the same test
   was run with network catalogues disabled.
3. Base result: one test in 0.641s, same code 2 and same unknown canonical ID.

The test assumes that the ignored `hdemucs_mmi` model artefact is installed,
but a clean checkout ships no such weight. It is therefore pre-existing,
clean-checkout/data-dependent test debt rather than a regression caused by this
branch or the generated catalogue. Task 5 does not alter runtime model
discovery, and no failure-masking runtime or fixture change was made.

## Live-reference verification

```text
$ rg -n "stem_semantics_audit" . --hidden --glob '!.git/**' \
    --glob '!docs/superpowers/**' --glob '!docs/reviews/**' \
    --glob '!.superpowers/**'
<no matches>

$ test ! -e scripts/stem_semantics_audit.py
exit 0
```

Historical design/plan/review/SDD artefacts continue to mention the removed
script as past evidence; those are not live commands or imports.

## Concerns

- The complete suite retains the one proven baseline/data-dependent Demucs
  failure above. It is not concealed, skipped, or changed by Task 5.
- `docs/models-catalogue.ir.json` is one of the five synchronized outputs but
  remains intentionally ignored and uncommitted.
- Private Wayland teardown emits expected lost-compositor/portal warnings after
  the test command exits; the runner returned the test exit status directly.
