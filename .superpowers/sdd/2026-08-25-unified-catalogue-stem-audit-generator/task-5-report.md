# Task 5 — Integrated verification and generated artefacts

## Result

- Regenerated the Markdown catalogue, IR sidecar, intent TSV, display TSV, and
  stem-semantics TSV from one authoritative `--refresh` snapshot with both
  `UVR_DATA_DIR` and `UVR_CACHE_DIR` isolated under `/tmp`.
- The refreshed universe remains exactly **485 canonical IDs** and **1,206
  semantic output/context rows**.
- Fixed the Task 5 review findings: strict publication no longer reads runtime
  model configs, hash JSONs, or weights; remote YAML is fetched and persisted
  only through the URL-keyed generator cache; and unavailable/unparseable YAML
  evidence degrades with exit 2 before strict rendering or structural audit.
- The authoritative refresh created **330 cache files**, including **324 YAML
  files**, and created **zero files** under the isolated runtime data root.
- Warm `--offline --check` exited 0 with unchanged artifact hashes and an
  unchanged cache path/mtime/size fingerprint.
- A full-membership replay with the same source/supplement cache but no YAML
  cache exited 2 with one compact unavailable-evidence message and no structural
  diagnostic flood.
- The exact no-`PYTHONPATH` complete discovery suite retained only the already
  proven clean-base/data-dependent `demucs:hdemucs_mmi` failure.
- No runtime settings, user caches, user model data, or model weights were
  changed. All network/cache/runtime/test state was isolated under `/tmp`.

## Review fix and TDD evidence

The previous Task 5 run set only `UVR_DATA_DIR`. That isolated runtime model
storage, but it left `UVR_CACHE_DIR` pointing at the user cache and allowed
downloaded YAML to land in runtime config storage. Its cache-isolation claim was
therefore incorrect. Ordinary offline execution also consumed only the 18
checked-in/runtime YAMLs, guessed the remainder from filenames, and produced 873
structural diagnostics instead of classifying the missing evidence as
unavailable.

The new regressions were written first and run against the old implementation:

```text
$ env -u PYTHONPATH .venv/bin/python -m unittest -v \
    tests.test_generate_models_catalogue.StrictCatalogueInputIsolationTests
Ran 3 tests in 0.078s
FAILED (failures=3)
```

The three RED failures proved independently that:

1. A conflicting same-name runtime YAML/weight changed the complete publication
   projection and stem-audit diagnostics.
2. A full-membership cold-YAML offline run returned 1 after invoking structural
   audit instead of returning degraded exit 2 before it.
3. `--refresh` preferred a conflicting runtime YAML over replacing stale
   generator-cache evidence.

After the implementation change, the exact regression class was GREEN:

```text
$ env -u PYTHONPATH .venv/bin/python -m unittest -v \
    tests.test_generate_models_catalogue.StrictCatalogueInputIsolationTests
Ran 3 tests in 0.055s
OK
```

The isolation regression compares rendered Markdown, intent/display/stem TSV
projections, canonicalized IR, entry IR, and audit diagnostics across two
runtime data trees sharing one warm generator cache. One tree contains a
conflicting same-name YAML and checkpoint whose digest matches a conflicting
hash row; both output bundles are identical and the runtime tree remains
byte-identical. Additional coverage verifies that an unparseable cached YAML
cannot supply strict instruments/target evidence and that refreshed cache bytes
are served identically by the subsequent offline load.

The expanded YAML/cache-focused set was also GREEN:

```text
$ env -u PYTHONPATH .venv/bin/python -m unittest -q \
    tests.test_generate_models_catalogue.StrictCatalogueInputIsolationTests \
    tests.test_generate_models_catalogue.OfflineYamlCacheTests \
    tests.test_generate_models_catalogue.YamlProvenanceStabilityTests \
    tests.test_generate_models_catalogue.FetchHelperTests
Ran 10 tests in 0.065s
OK
```

## Strict publication input boundary

- Checked-in MDX-C configs are resolved explicitly from
  `models/MDX_Net_Models/model_data/mdx_c_configs`.
- Every remote config is read/refreshed through `_fetch_cached_bytes` in the
  URL-keyed `CACHE_DIR/models_catalogue/yaml` cache. Publication never calls
  `fetch_mdx_config_url` and never reads or writes `paths.MDX_C_CONFIG_PATH`.
- Architecture is inferred from the bytes already loaded by the generator; it
  no longer reopens a same-name config through runtime storage.
- Missing or unparseable required YAML names are deduplicated in the catalogue
  context. Filename-derived stems remain informational return values but are
  not copied into strict entry instruments/targets.
- Demucs and Apollo execution sidecars are not treated as MDX-C training
  evidence. Their existing family-specific publication overlays remain the
  semantic authority.
- Politrees and checked-in hash tables remain supplemental evidence, but strict
  publication no longer scans installed weights or performs a per-entry runtime
  weight/hash fallback. The checked-in hash seed paths are explicit repository
  paths, independent of `UVR_DATA_DIR`.
- `CLAUDE.md` now documents that generator YAML persistence is controlled by
  `allow_cache_writes` and never targets runtime model storage.

## Authoritative generation and warm-offline parity

Authoritative refresh (the only network-escalated generator command):

```text
$ env -u PYTHONPATH \
    UVR_DATA_DIR=/tmp/uvr-task5-data.busp4r \
    UVR_CACHE_DIR=/tmp/uvr-task5-cache.upCElw \
    .venv/bin/python -B scripts/generate_models_catalogue.py --refresh
Wrote .../docs/models-catalogue.md (485 models, 483 with metadata,
2 unknown, 3 flagged, 0 unsupported omitted)
Wrote .../docs/models-catalogue.ir.json
Wrote .../docs/model_intent_reference.tsv
Wrote .../docs/model_display_reference.tsv
Wrote .../docs/model_stem_semantics_reference.tsv
exit 0
```

Post-refresh storage counts:

```text
isolated runtime data files: 0
isolated generator cache files: 330
URL-keyed generator YAML files: 324
```

Warm offline comparison:

```text
$ env -u PYTHONPATH \
    UVR_DATA_DIR=/tmp/uvr-task5-data.busp4r \
    UVR_CACHE_DIR=/tmp/uvr-task5-cache.upCElw \
    .venv/bin/python -B scripts/generate_models_catalogue.py --offline --check
Up to date: .../docs/models-catalogue.md
exit 0
```

The cache fingerprint includes every cache file's relative path, mtime, and
size. It was identical before and after warm offline checking:

```text
d40d7ef56ef824aa8603bfb059dc058f29b15957a96fd398e27b8f5ec13e1b92
```

The empty runtime-data fingerprint likewise remained the SHA-256 of empty input:

```text
e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

Artifact SHA-256 values before and after the offline check were identical:

```text
637b959e4aae2c4660d6053f6ba50640473818812b32f55055440797438a1721  docs/models-catalogue.md
2fdbc19c5e2d84258d112681c045d3a18c8a90ddb9d4008cb18651d0eadf3bcb  docs/models-catalogue.ir.json
950e967a28242e50b23d92fce63cb5f15a3954ae22c38416e88c3f1a79a396a1  docs/model_intent_reference.tsv
4ca4e1421a5cb5fb3a911332c04f23f073035408a5d27af0bf4bc6697be02e3b  docs/model_display_reference.tsv
bb7275ace93bed5295a87edd5670e9783f9d82d327c83a9208189e15790ae157  docs/model_stem_semantics_reference.tsv
```

The IR reports `entry_count=485`, contains 485 entries, and is tied to the
Markdown digest `637b959e...1721`. The display TSV has 485 data rows and 485
unique canonical IDs. The stem TSV has 1,207 physical lines: one header plus
1,206 data rows, covering 485 unique canonical IDs.

The tracked artifact changes are intentional consequences of the corrected
input boundary: downloaded configs now report stable `remote_yaml` provenance
instead of being mislabeled as runtime/bundled files, and Demucs execution
sidecars no longer mislabel Demucs execution architecture as `MDX23C`. The
intent TSV remained byte-identical. The IR sidecar is generated and verified but
remains intentionally gitignored by repository contract.

## Cold-YAML degraded replay

A second isolated cache copied the complete coordinator and global supplemental
snapshot but deliberately omitted only the generator YAML directory:

```text
$ env -u PYTHONPATH \
    UVR_DATA_DIR=/tmp/uvr-task5-data.busp4r \
    UVR_CACHE_DIR=/tmp/uvr-task5-cold-yaml-cache.a5J5Yv \
    .venv/bin/python -B scripts/generate_models_catalogue.py --offline --check
Cannot judge a complete catalogue: required supplemental evidence unavailable:
per-model YAML/config metadata (324 unavailable: bandit_30_zfturbo_config.yaml,
bandit_57_zfturbo_config.yaml, bandit_63_zfturbo_config.yaml,
bandit_last_config.yaml, bs_4stem_aname_config.yaml, ... (+319 more))
exit 2
```

There were no `Stem audit ...` lines, no network calls, no YAML/cache directory
creation, and no artifact writes. The ordinary no-environment-override command
now produces the same compact exit-2 classification rather than the former 873
structural diagnostics:

```text
$ env -u PYTHONPATH .venv/bin/python -B \
    scripts/generate_models_catalogue.py --offline --check
Cannot judge a complete catalogue: required supplemental evidence unavailable:
per-model YAML/config metadata (324 unavailable: ...)
exit 2
```

## Focused suites

The non-GTK Task 5 focused suite ran with no `PYTHONPATH` override and isolated
runtime/cache/Numba roots:

```text
$ env -u PYTHONPATH UVR_DATA_DIR=/tmp/uvr-task5-tests-data.fKe5OX \
    UVR_CACHE_DIR=/tmp/uvr-task5-tests-cache.g8wAWh \
    NUMBA_CACHE_DIR=/tmp/uvr-task5-numba.LCZAfi \
    .venv/bin/python -m unittest -q \
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
Ran 541 tests in 12.715s
OK (skipped=2)
```

The GTK catalogue-preferences source test ran through the private Mutter/Wayland
runner after the managed sandbox's missing named-profile configuration was
bypassed with a narrowly escalated private runner invocation. It created only a
private `codex-gtk` socket:

```text
Private Wayland socket: /tmp/codex-gtk.7zsI1G/codex-gtk
Ran 5 tests in 0.425s
OK
exit 0
```

## Static and whitespace verification

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

## Complete unit suite and classified limitation

The first fix-round full-suite attempt used a completely empty isolated data
root. It produced seven `FileNotFoundError`s plus one SCNet assertion because
those tests deliberately copy the tracked seed config
`config_musdb18_scnet.yaml` through `paths.MDX_C_CONFIG_PATH`. That was a test
harness error, not a code regression, and no implementation/test changes were
made in response. A fresh data root was then created with only the repository's
tracked `models/` seed tree copied into it, matching the documented Task 5
harness.

The corrected exact CLAUDE.md discovery command (inside private Wayland, with no
`PYTHONPATH`) produced:

```text
$ env -u PYTHONPATH UVR_DATA_DIR=/tmp/uvr-task5-full-data.WevfCa \
    UVR_CACHE_DIR=/tmp/uvr-task5-full-cache.OdrpuQ \
    NUMBA_CACHE_DIR=/tmp/uvr-task5-full-numba.JU4Dza \
    .venv/bin/python -m unittest discover -s tests -t . -v
Ran 2959 tests in 87.074s
FAILED (failures=1, skipped=18)
```

Sole failure:

```text
tests.test_cli_list_models.DiscoveryTests.
test_models_show_configures_installed_demucs_canonical_id
AssertionError: 2 != 0: error: unknown model 'demucs:hdemucs_mmi'
```

It was re-run alone after the complete suite and failed identically in 0.634s.
The original Task 5 classification remains valid: the same test was previously
run at clean base `4fbc68e6b1d08f25141e274ca900fc2a59070ef1` and returned the
same code 2/unknown canonical ID. The test assumes the ignored
`hdemucs_mmi` weight is installed; a clean tracked seed tree contains its YAML
but no weight. Task 5 does not alter runtime model discovery and does not mask,
skip, or repair this baseline/data-dependent test debt.

## Live-reference verification

The obsolete `.gitignore` allowlist for deleted
`scripts/stem_semantics_audit.py` remains removed. The existing live-tree audit
still reports no reference outside historical review/plan/SDD evidence, and the
deleted script remains absent.

## Concerns and limitations

- The complete suite retains the one independently proven baseline/data-dependent
  Demucs failure above.
- A strict offline publication now intentionally requires its URL-keyed
  generator YAML cache. A cold cache exits 2; filename heuristics cannot publish
  a guessed strict signature.
- `docs/models-catalogue.ir.json` is one of the five synchronized outputs but is
  intentionally ignored and uncommitted.
- The configured `codex sandbox -P gtk-headless` wrapper was unavailable because
  the active Codex config has no `[permissions]` table. The same skill-provided
  private runner succeeded under narrowly scoped escalation and did not touch
  the host compositor.
- Private Wayland teardown emits expected lost-compositor/portal warnings after
  the test command exits; the runner returned the test exit status directly.
