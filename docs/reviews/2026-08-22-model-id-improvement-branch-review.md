# Model ID Improvement Branch Review

Date: 2026-08-22

Branch: `feat/model-id-improvement`

Base: `268ac2a75ea217cbfc1d4f5002d3e3fc4817ccc0`

Head: `6de2168947e78449ccd27de4a6573d17156e9959`

Range reviewed: `268ac2a75ea217cbfc1d4f5002d3e3fc4817ccc0..6de2168947e78449ccd27de4a6573d17156e9959`

The requested `docs/model_id_improvement.md` does not exist on this branch. I treated
[`docs/model_id_refinement.md`](../model_id_refinement.md) as the locked specification,
and [`docs/superpowers/plans/2026-08-21-model-id-improvement.md`](../superpowers/plans/2026-08-21-model-id-improvement.md)
plus `.superpowers/sdd/2026-08-21-model-id-improvement/` as the implementation plan
and handoff record.

## Verdict

**Needs fixes before merge.** No Critical issues were found, but seven Important
defects violate locked identity/runtime behavior and one Minor defect permits
unresolvable records into the published index.

The review covered all 84 changed files and 50 commits in the branch range, then
traced the identity index, repository cache, CLI boundaries, GUI consumers,
planning, nested model assembly, Apollo execution, manifests/replay, Demucs
registration, and the tests intended to lock those contracts. Important findings
were independently reproduced and independently reviewed.

## Important findings

### 1. Apollo restore validates the backend checkpoint but executes the canonical ID as a filename

Locations: `core/audio_plan.py:167-197`, `cli/audio.py:309-319`,
`core/audio_tools.py:95-103`, `core/audio_tools.py:287-295`.

`AudioJobResolver` correctly uses `record.backend_name` to validate and describe
the checkpoint while preserving the canonical ID in settings. Execution then
constructs both `ApolloModelData` and `AudioTools` from
`settings.audio_tools.apollo_model`. That value is still, for example,
`apollo:restorer`, so it becomes `APOLLO_MODELS_DIR/apollo:restorer` instead of
`APOLLO_MODELS_DIR/restorer.ckpt`.

This is branch-caused. The base resolver rewrote its copied runtime settings to
the engine filename; the branch correctly removed that mutation to satisfy the
canonical-settings contract, but did not replace it with an explicit descriptor
or backend handoff. A real installed model reproduced the split result:

```text
ApolloModelData("apollo:apollo_edm_big_by_essid") -> model_status=False
ApolloModelData("apollo_edm_big_by_essid.ckpt")   -> model_status=True
```

Impact: validation can succeed and the resolved plan can name the correct
checkpoint, yet both CLI and GUI execution send a nonexistent path to Apollo
inference. This conflicts with the spec's separate canonical-ID and backend-name
roles (`docs/model_id_refinement.md:21-26`, `:457-485`).

Fix direction: pass `plan.model.backend_name`, the resolved checkpoint, or an
equivalent immutable Apollo descriptor into `AudioToolRunner`/`AudioTools` and
`ApolloModelData`. Do not rewrite the settings snapshot. Add a non-dry handoff
test that observes the exact inference checkpoint path.

### 2. Configured installed MDX-C checkpoints are published as incomplete and rejected before YAML recovery

Locations: `core/model_inventory.py:140-178`, `core/model_inventory.py:291-316`,
`core/model_inventory.py:358-374`, `core/job_plan.py:866-885`,
`core/job_plan.py:1012-1064`.

Installed `.ckpt` projection only associates YAML files found in the MDX model
artifact listing. It does not use the trusted checkpoint-hash mapping and local
metadata that already associates checkpoints with configuration files under
`MDX_C_CONFIG_PATH`. If the filename also lacks a hard-coded architecture hint,
the record is published with `identity_complete=False`.

On this checkout, 15 installed MDX checkpoints were classified incomplete even
though the legacy dry resolver found every one configured and runnable. For
example, `mdx:bs_inst_large2_unwa` has an installed checkpoint, a local
`bs_inst_large2_unwa_config.yaml`, and metadata identifying BS Roformer, but the
record has no supporting YAML and reports an unknown architecture. CONFIG
planning rejects the primary in `_validate_dependency_family` before
`_ensure_mdx_yaml_configs` can recover or re-resolve it.

Impact: existing configured MDX-C models cannot be planned or run through the
new identity path, and online recovery is unreachable. This conflicts with the
MDX association rules and the later active-model YAML recovery stage
(`docs/model_id_refinement.md:379-389`, `:451-506`).

Fix direction: during offline, hash-free projection, use trusted cached
checkpoint-to-config metadata, catalogue `meta_by_family`, and the existing
local MDX-C configuration registry. Reuse the existing config loader because
some files contain Python tuple YAML tags. Add a real-repository test with a
checkpoint in `MDX_MODELS_DIR` and its config in `MDX_C_CONFIG_PATH`.

### 3. `models list --all-known` never attaches a catalogue

Locations: `cli/discovery.py:238-253`, `core/model_identity.py:272-282`,
`core/model_identity.py:305-329`, `tests/test_cli_list_models.py:428-478`.

`cmd_models_list` constructs a bare `ModelRepository`. With no catalogue
coordinator, `_snapshot()` returns `None`, so the published index contains only
installed artifacts. Fresh offline measurements were:

```text
bare repository:       70 total, 70 installed,  0 uninstalled
coordinator-backed:   147 total, 70 installed, 77 uninstalled
```

Impact: `--all-known` behaves like the default listing and hides every
catalogue-only `ModelRecord`. The existing test replaces the published index
with synthetic rows and therefore cannot catch the missing command integration.
This contradicts `docs/model_id_refinement.md:582-587` and the Task 17 contract
at `docs/superpowers/plans/2026-08-21-model-id-improvement.md:1881-1896`.

Fix direction: make the command own an offline `CatalogueCoordinator`, attach it
to the repository, use the cached snapshot without network, and close it in a
`finally` block. Add a command-level cached-catalogue integration test.

### 4. MDX secondary dependency selection disagrees with runtime topology

Locations: `core/job_plan.py:123-194`, `core/job_plan.py:1012-1049`,
`cli/job.py:221-285`, `core/model_config/determine.py:40-50`,
`core/model_config/determine.py:82-116`, `core/model_config/config.py:454-477`.

Planning selects the active MDX secondary slot from `settings.mdx.stems`.
Runtime selects it from the assembled model's native `primary_stem`. Those
values are not interchangeable. A reproduced configuration planned
`mdx.drums_secondary_model` while runtime selected
`mdx.voc_inst_secondary_model` for an Instrumental primary; a lowercase native
`drums` stem selected no runtime slot at all.

The CLI canonicalizer compounds this by treating every non-sentinel secondary
field in an enabled family as active. Thus an invalid inactive slot can reject a
valid run, while the slot actually loaded at runtime can be absent from the
dependency map and identity digest.

Impact: validation, manifests, replay topology, staleness checks, and runtime can
refer to different models. This violates the requirement that the flat map
contain exactly the active secondary and that runtime consume the planned map
(`docs/model_id_refinement.md:459-496`; plan Task 8 at `:1198-1236`).

Fix direction: assemble/resolve primary topology before selecting nested paths,
normalize native stem semantics once, and share the result across CLI
canonicalization, planning, `is_current`, replay, and `ModelConfig`. Pass planned
nested records into runtime. Cover Other, Bass, Drums, and lowercase native
stems.

### 5. Change Model Defaults passes canonical tags to `ModelConfig` without an identity

Locations: `core/model_repository.py:267-269`,
`ui/dialogs/model_params.py:541-570`, `core/model_config/config.py:210-220`.

The dialog now receives canonical IDs from `default_change_model_tags`, but its
`selected_model_data` helper still calls `ModelConfig(settings, repo, tag, ...)`
without resolving and passing `identity=`. The branch removed the old internal
canonical-tag fallback from `ModelConfig`, so the constructor interprets the
whole ID as an ensemble process tag and marks the model invalid.

Reproduction with the first real tag:

```text
tag: vr:13_SP-UVR-4B-44100-1
direct ModelConfig: model_status=False, process_method="vr:13_SP-UVR-4B-44100-1"
with identity:       model_status=True,  process_method="VR Arc"
```

Impact: editing and deleting stored parameters is broken for every model shown
by this dialog. This is a branch regression: the caller was not migrated when
the constructor contract changed.

Fix direction: exact-lookup the selected ID and pass the record into
`ModelConfig`, or reuse the repository's contained dry-check helper. Add a GTK
consumer test for both the change and hash-file-only paths.

### 6. Strict-ID cutover remains permissive at runtime and persistence boundaries

Locations: `core/model_identity.py:349-425`,
`core/model_identity.py:439-455`, `cli/profiles.py:120-145`,
`cli/audio.py:228-242`, `core/ensemble_service.py:206-237`,
`core/ensemble_presets.py:76-103`, `cli/discovery.py:1002-1027`.

`ModelIdentityService.resolve` still prefixes an unqualified input when a family
is supplied, and `resolve_model_record` still performs case-insensitive basename
matching. `canonical_id_from_member_tag` keeps legacy ensemble conversion alive.
Consequently runtime/profile/ensemble paths accept and silently convert values
which the locked cutover says must be rejected or preserved with a warning:

```text
resolve("13_SP-UVR-4B-44100-1")
    -> vr:13_SP-UVR-4B-44100-1
resolve("VR Architecture: 13_SP-UVR-4B-44100-1")
    -> vr:13_SP-UVR-4B-44100-1
lookup("13_SP-UVR-4B-44100-1")
    -> not a canonical model ID
```

Impact: identity semantics depend on the entry point, obsolete ensemble-tag
migration remains active, and CLI/profile writes can normalize illegal stored
values instead of preserving them. Some current tests explicitly assert the
contrary permissive behavior, masking the spec violation.

This conflicts directly with `docs/model_id_refinement.md:451-455`, `:598-607`,
and `:728-779`.

Fix direction: use `parse_stored_model_id` plus `IdentityIndex.lookup` or
`CliModelLookup` at every runtime boundary; remove `_qualify_stored_model` and
legacy member conversion. Fuzzy/basename matching should remain only in
catalogue search/download. Replace permissive tests with strict rejection and
keep-text cases.

### 7. Stored-identity warnings are not surfaced outside the primary method picker

Locations: `core/ensemble_service.py:98-140`,
`core/ensemble_service.py:190-233`, `ui/ensemble/window.py:1025-1052`,
`ui/ensemble/window.py:1369-1377`, `ui/widgets/vocal_split_row.py:128-146`,
`ui/widgets/vocal_split_row.py:198-230`, `ui/audio_tools/window.py:409-436`,
`ui/audio_tools/window.py:627-655`, `ui/views/base.py:701-725`.

The branch added effective write gates: an invalid stored secondary, splitter,
ensemble member, or Apollo value is generally not overwritten during picker
population. However, those controls show no selection without telling the user
what value was retained or how to recover. Saved ensemble loading creates
`EnsembleDocument.validation_warnings`, but `ResolvedEnsemblePreset` drops them.

Impact: the preservation half of the cutover works, but the mandatory warning
half does not. Users see an unexplained blank control or a generic readiness
failure. This conflicts with `docs/model_id_refinement.md:598-607` and
`:739-749`, and Task 15's interface at plan lines `1772-1777`.

Fix direction: propagate field-specific syntax and repository validation
warnings through resolved ensemble state and every non-primary picker. Surface
them in row/page banners until the user explicitly repicks. Add GTK coverage for
secondary, splitter, Apollo, and saved-ensemble cases.

## Minor finding

### 8. Invalid basenames and unexpected family subdirectories can become published records

Locations: `core/model_inventory.py:53-80`, `core/model_inventory.py:93-125`,
`core/model_identity.py:56-85`.

`validate_artifact_name` does not use its `family` argument or reject every
unexpected nested shape. `_record` then builds `id=f"{family}:{basename}"`
without running `ModelId` validation. Files such as `.pth` and `bad:name.pth`
can therefore publish `vr:` and `vr:bad:name`; the strict lookup parser can
never target those records.

Impact is contained to the malformed row by the branch's per-row guards.

Fix direction: construct/validate `ModelId(family, basename)` inside `_record`,
enforce the allowed family-relative layouts, and let existing row containment
drop failures. Add empty-stem, colon, and unexpected-subdirectory tests.

## Prior SDD finding disposition

Confirmed at head:

- MDX Other/Bass/Drums secondary-slot disagreement.
- Missing warnings on the ensemble page, now also confirmed for secondary,
  vocal-splitter, and Apollo controls.

Partially addressed:

- Exact display-to-record inversion is gone, but bare basename and legacy
  architecture-tag conversion remain at several runtime boundaries.
- Two-stage validation is invoked for CLI jobs and the primary method page, but
  warning propagation remains incomplete.

Addressed/stale at head:

- Empty dry-check model pools.
- Apollo picker refresh rewriting stored values.
- Demucs two-source secondary widening.
- Offline MDX YAML exceptions escaping as unstructured failures.
- Per-service identity cache misses.
- A malformed catalogue or installed row emptying the full identity index.
- Contained dry-check construction and malformed installed Demucs bag failures.
- The prior packaging/documentation cleanup items.

Newly confirmed beyond the SDD handoff:

- Apollo runtime backend handoff failure.
- Missing catalogue injection for `--all-known`.
- Change Model Defaults not passing identity.
- Configured installed MDX-C identity/config association failure.

## Verification evidence

Branch-wide fresh verification after review:

```text
.venv/bin/python -m unittest discover -s tests -q
Ran 2456 tests in 71.001s
OK (skipped=6)

.venv/bin/python -m basedpyright
0 errors, 0 warnings, 0 notes

Focused identity/planning/consumer suite
Ran 216 tests in 5.316s
OK

git diff --check 268ac2a75ea217cbfc1d4f5002d3e3fc4817ccc0..HEAD
clean
```

The full suite required the active Wayland/DBus session; a sandboxed headless
attempt exited 139 and was not treated as a valid result. The successful command
used `WAYLAND_DISPLAY=wayland-0`, `DISPLAY=:0`,
`XDG_RUNTIME_DIR=/run/user/1000`, `GDK_BACKEND=wayland`, and the active user DBus
socket.

The green suite does not invalidate the findings. The gaps are primarily
production integration boundaries currently mocked in tests: catalogue
coordinator ownership, real installed MDX metadata/config association, the
Apollo plan-to-runner handoff, native-stem secondary selection, and the real
Change Model Defaults consumer.

## Recommendation

Do not merge this branch until the seven Important findings have regression
tests and fixes. Re-run the focused identity suites, the full active-display
suite, basedpyright, and branch-range whitespace verification afterward.
