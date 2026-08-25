# Final whole-branch fix report

## Result

All three Important review findings and the one Minor documentation finding are
implemented in one combined fix wave. The production implementation is commit
`8d4bc5f` (`fix(catalogue): complete stem audit publication fixes`). Nothing
was pushed.

The resulting normal generator behavior is:

- `StemAuditResult` carries immutable, deterministic native-to-role ambiguity
  and role-to-native variant projections with exact model, context, native
  spelling, and curated-role evidence.
- The projections are informational. They do not create diagnostics or change
  `ok`, `structurally_valid`, write, or check exit status.
- The bundled manifest projects 6 normalized-native ambiguity groups and 14
  role/native-variant groups. The warm summary renders both real sections and
  no longer reports `No stem semantic audit findings.` for that diversity.
- Normal generator modes validate the bundled stem registry once before
  collection, rendering, network, cache, or publication work. The same object
  is passed explicitly to the stem TSV renderer and structured audit.
- A malformed manifest produces one controlled `manifest-invalid` stderr line
  and exit 1 without a traceback or artifact/cache/collection side effect.
  Confidence-audit mode remains independent.
- Strict publication no longer loads, merges, fetches, or classifies the unused
  Politrees VR/MDX hash tables. The optional confidence audit retains its own
  checkpoint-hash path.
- Current documentation describes unified five-artifact write/check behavior;
  the legacy `--write-*` switches are deprecated accepted no-ops.

## TDD RED evidence

The relationship regressions were added and run before production changes:

```text
$ env -u PYTHONPATH .venv/bin/python -m unittest -v \
    tests.test_catalogue_stem_audit.StructuredCatalogueStemAuditTests.test_relationship_projections_are_model_specific_filtered_and_deterministic \
    tests.test_catalogue_stem_audit.StructuredCatalogueStemAuditTests.test_expected_relationship_diversity_is_informational_not_diagnostic \
    tests.test_catalogue_stem_audit.StructuredCatalogueStemAuditTests.test_bundled_relationship_projection_retains_reviewed_six_and_fourteen
Ran 3 tests
FAILED (errors=3)
```

The first two errors were:

```text
AttributeError: 'StemAuditResult' object has no attribute
'native_to_role_ambiguities'
```

The bundled regression failed because
`catalogue_stem_relationships` did not exist.

The generator-boundary regressions were then run before their production
changes:

```text
$ env -u PYTHONPATH .venv/bin/python -m unittest -v \
    tests.test_generate_models_catalogue.SummaryModeTests.test_semantic_summary_uses_structured_audit_counts_and_sections \
    tests.test_generate_models_catalogue.UnifiedPublicationCliTests.test_validated_registry_is_loaded_once_and_reused_by_render_and_audit \
    tests.test_generate_models_catalogue.UnifiedPublicationCliTests.test_missing_politrees_hash_files_do_not_degrade_a_complete_offline_bundle \
    tests.test_generate_models_catalogue.MalformedManifestCliTests
Ran 6 tests
FAILED (failures=5, errors=1)
```

Exact failure classes were:

- `StemAuditResult.__init__()` rejected the new structured relationship
  fields.
- the normal-mode manifest loader was called zero times rather than once;
- missing Politrees VR/MDX hash metadata incorrectly remained unavailable
  supplemental evidence; and
- write, check, and summary reached the collector sentinel before manifest
  validation.

The publication prose regression was also RED:

```text
$ env -u PYTHONPATH .venv/bin/python -m unittest -v \
    tests.test_generate_models_catalogue.ProvenanceBlockTests.test_intent_source_prose_excludes_unused_hash_supplements
Ran 1 test
FAILED (failures=1)
```

The rendered catalogue still claimed `yaml/hash metadata` and Politrees
`model_data` as intent sources.

## GREEN regression evidence

The final targeted set covers model/context evidence, exclusions,
determinism, the bundled 6/14 counts, informational exit semantics, summary
rendering, one-registry threading, missing hash supplements, malformed
write/check/summary behavior, confidence-mode independence, and publication
prose:

```text
$ env -u PYTHONPATH .venv/bin/python -m unittest -v \
    tests.test_catalogue_stem_audit.StructuredCatalogueStemAuditTests.test_relationship_projections_are_model_specific_filtered_and_deterministic \
    tests.test_catalogue_stem_audit.StructuredCatalogueStemAuditTests.test_expected_relationship_diversity_is_informational_not_diagnostic \
    tests.test_catalogue_stem_audit.StructuredCatalogueStemAuditTests.test_bundled_relationship_projection_retains_reviewed_six_and_fourteen \
    tests.test_generate_models_catalogue.SummaryModeTests.test_semantic_summary_uses_structured_audit_counts_and_sections \
    tests.test_generate_models_catalogue.UnifiedPublicationCliTests.test_validated_registry_is_loaded_once_and_reused_by_render_and_audit \
    tests.test_generate_models_catalogue.UnifiedPublicationCliTests.test_missing_politrees_hash_files_do_not_degrade_a_complete_offline_bundle \
    tests.test_generate_models_catalogue.MalformedManifestCliTests \
    tests.test_generate_models_catalogue.StemConfidenceAuditModeTests.test_audit_mode_does_not_collect_or_publish_catalogue_artifacts \
    tests.test_generate_models_catalogue.ProvenanceBlockTests.test_intent_source_prose_excludes_unused_hash_supplements
Ran 11 tests in 0.066s
OK
```

The two complete changed modules are also green without a `PYTHONPATH`
override:

```text
$ env -u PYTHONPATH .venv/bin/python -m unittest -q \
    tests.test_catalogue_stem_audit \
    tests.test_generate_models_catalogue
Ran 182 tests in 0.620s
OK
```

## Implementation notes by finding

### Structured relationship summary

`catalogue_stem_relationships()` intersects exact supplied catalogue IDs with
reviewed declarations and excludes waivers, manifest-only orphans, derived
outputs, and non-curated literals. Duplicate exact uses collapse through a
frozen evidence set.

Native ambiguity uses `StemId.casefold()` (trim plus casefold) and qualifies
only when one normalized native key has more than one curated role. Role
variants qualify only when one curated role has more than one normalized
native key; case-only spellings are retained as evidence but cannot qualify a
group by themselves. All outer groups, aggregate fields, and evidence tuples
have explicit deterministic ordering.

`context-duplicate-role` and `context-native-signature` remain unchanged and
render under `Signature and context findings`. Empty relationship sections are
omitted.

### Controlled malformed manifest

After argument/policy selection and the independent confidence-mode branch,
normal modes call `load_stem_manifest(BUNDLED_MANIFEST_PATH)` once. A typed
`StemManifestError` returns 1 after one compact stderr diagnostic. Tests use a
real malformed JSON manifest plus sentinels at every collection/render
boundary and all five output paths.

### Unused hash supplements

Normal collection no longer contains the Politrees VR/MDX hash URLs, hash
cache directory, repository hash seeds, merge/load helpers, or context hash
maps. Offline full-evidence write followed by check succeeds with all five
artifacts present and no network request. Confidence-mode hashing remains in
`stem_audit.py` and is covered separately.

## Integrated verification

The broader generator/audit/source/tool selection ran with isolated runtime,
generator cache, and Numba roots and no `PYTHONPATH` override:

```text
$ env -u PYTHONPATH \
    UVR_DATA_DIR=/tmp/uvr-finalfix-focused-data.0U9CiP \
    UVR_CACHE_DIR=/tmp/uvr-finalfix-focused-cache.CAuTb0 \
    NUMBA_CACHE_DIR=/tmp/uvr-finalfix-focused-numba.liyPlA \
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
Ran 550 tests in 12.453s
OK (skipped=2)
```

Warm isolated-cache verification used the previously captured complete
485-model/1,206-semantic-row snapshot. No network refresh was performed:

```text
$ env -u PYTHONPATH \
    UVR_DATA_DIR=/tmp/uvr-task5-data.busp4r \
    UVR_CACHE_DIR=/tmp/uvr-task5-cache.upCElw \
    .venv/bin/python -B scripts/generate_models_catalogue.py --offline --check
Up to date: .../docs/models-catalogue.md
exit 0
```

The warm summary reported:

```text
Total catalogue entries: 485
Reviewed catalogue models: 455
Waived catalogue models: 30
Raw catalogue models: 0
Native-to-role ambiguity groups: 6
Role-to-native variant groups: 14
```

The reference counts remain 485 display rows and 1,206 stem-semantic rows.
The intent, display, and stem TSVs are byte-identical to commit `461a600`.
Only `docs/models-catalogue.md` changed among tracked publication artifacts,
to remove the obsolete hash-source prose and Politrees hash-cache provenance.
The ignored IR sidecar was regenerated/rebound to the updated Markdown digest
so the five-artifact warm check is coherent.

Static verification:

```text
$ env -u PYTHONPATH .venv/bin/ruff check <six changed Python files>
All checks passed!

$ env -u PYTHONPATH .venv/bin/ruff format --check <six changed Python files>
6 files already formatted

$ env -u PYTHONPATH .venv/bin/basedpyright
0 errors, 0 warnings, 0 notes

$ git diff --check
exit 0
```

The independent final diff review found no Critical, Important, or Minor
findings. Its targeted regressions, full changed modules, Ruff, format, and
diff checks were also green, without network access.

## Complete private-GTK suite and limitation

The complete suite ran inside the repository's private Mutter/Wayland and
D-Bus runner with isolated runtime/cache/Numba roots:

```text
$ /home/rudam/.codex/skills/testing-gtk-headless/scripts/run-private-wayland.sh -- \
    env -u PYTHONPATH UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
    UVR_DATA_DIR=/tmp/uvr-finalfix-full-data.KENKnN \
    UVR_CACHE_DIR=/tmp/uvr-finalfix-full-cache.nxir2r \
    NUMBA_CACHE_DIR=/tmp/uvr-finalfix-full-numba.0EcHm3 \
    .venv/bin/python -m unittest discover -s tests -t . -q
Private Wayland socket: /tmp/codex-gtk.xwd9lS/codex-gtk
Private D-Bus: unix:path=/tmp/dbus-AElPGzQo6Z,...
Ran 2968 tests in 75.878s
FAILED (failures=1, skipped=18)
```

The only failure is the explicitly permitted, independently reproduced
clean-base/data-root limitation:

```text
FAIL: test_models_show_configures_installed_demucs_canonical_id
AssertionError: 2 != 0 : error: unknown model 'demucs:hdemucs_mmi'
```

The final-fix focused and module suites are green, and this failure is outside
the changed generator/audit paths. It was not masked or converted into a skip.
The named managed profile was unavailable because its local profile file lacks
a required `[permissions]` table, so the skill's private compositor runner was
used directly; it confirmed private Wayland and D-Bus endpoints.

## Commit and workspace state

- Base: `461a600cd65e0c3f6eadc5ca478115c44cd1eaf6`
- Implementation: `8d4bc5f` (`fix(catalogue): complete stem audit publication fixes`)
- Report: committed separately after this file was written so the
  implementation hash above is exact.
- Branch: `feat/unified-catalogue-stem-audit`
- Push/network refresh: not performed
