# Final Contained Fix Report

## Implementation summary

- `core/model_repository.py` now treats dry-check construction as a per-row
  operation. The exception boundary covers identity lookup and
  `ModelConfig(...)` construction with the same exception tuple and `None`
  result shape as `resolve_model_dry`. `stem_check` and `karaoke_model_list`
  omit failed rows while preserving valid installed configs and cached pools.
- `core/model_inventory.py` now builds installed Demucs bags inside the same
  per-artifact `ValueError` boundary as ordinary installed records. An illegal
  bag entrypoint or owned weight drops only that bag.
- Added real-behavior regressions for an unrecognized installed Demucs YAML,
  valid ensemble/karaoke pool siblings, and malformed installed bag entrypoint
  and supporting-artifact paths with a valid sibling identity record.

## TDD RED evidence

The tests were added before either production module was edited.

```bash
UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
.venv/bin/python -m unittest \
  tests.test_model_pools_real_repository \
  tests.test_model_identity_contracts -v
```

Exit: `1`

```text
test_unrecognized_demucs_row_does_not_empty_valid_pools ... ERROR
test_malformed_installed_demucs_bag_does_not_empty_the_index
  (case='illegal entrypoint') ... ERROR
test_malformed_installed_demucs_bag_does_not_empty_the_index
  (case='illegal supporting artifact') ... ERROR

ValueError: demucs:Test-Unrecognized-Demucs is missing Demucs
version/layout metadata
ValueError: illegal artifact path '../bad.yaml'
ValueError: illegal artifact path '../sig-hash.th'

Ran 44 tests in 0.054s
FAILED (errors=3)
```

These are the intended failures: the first escaped from `ModelConfig(...)` in
`_dry_check_config`; the other two escaped from the Demucs-bag `_record(...)`
branch in `_merge_installed`.

## TDD GREEN evidence

After the two minimal production changes, the same command returned:

```text
Ran 44 tests in 0.052s
OK
```

Exit: `0`

## Verification

### Touched-file type check

```bash
.venv/bin/python -m basedpyright \
  core/model_repository.py core/model_inventory.py \
  tests/test_model_pools_real_repository.py \
  tests/test_model_identity_contracts.py
```

```text
0 errors, 0 warnings, 0 notes
```

### Full type check and whitespace

```bash
.venv/bin/python -m basedpyright
git diff --check
```

```text
0 errors, 0 warnings, 0 notes
(git diff --check produced no output; both commands exited 0)
```

### Full unittest discovery

The exact delivery-gate environment from the brief was attempted once:

```bash
WAYLAND_DISPLAY=wayland-0 DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000 \
GDK_BACKEND=wayland \
DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
MPLCONFIGDIR=/tmp/uvr-mpl-review PYTHONWARNINGS=ignore \
UVR_DISABLE_POLITREES=1 UVR_DISABLE_MVSEPLESS=1 \
.venv/bin/python -m unittest discover -s tests -q
```

Exit: `139`

```text
Gtk-CRITICAL **: gtk_icon_theme_get_for_display: assertion
'GDK_IS_DISPLAY (display)' failed
Gtk-CRITICAL **: gtk_icon_theme_add_resource_path: assertion
'GTK_IS_ICON_THEME (self)' failed
dconf-CRITICAL **: unable to create file '/run/user/1000/dconf/user':
Read-only file system. dconf will not work properly.
```

This is the brief's anticipated sandbox display-access limitation, not a test
assertion failure. The controller must rerun the full GTK-aware suite in its
working Wayland/DBus environment.

## Files changed

- `core/model_repository.py`
- `core/model_inventory.py`
- `tests/test_model_pools_real_repository.py`
- `tests/test_model_identity_contracts.py`
- `.superpowers/sdd/2026-08-21-model-id-improvement/final-contained-fix-report.md`

## Self-review

- The dry-check cache key, canonical IDs, catalogue/inventory generation,
  identity records, and replay contracts are unchanged.
- Unknown/collided IDs retain the existing unavailable legacy fallback;
  exceptions raised while resolving or constructing one row are contained and
  logged, and only that row is omitted.
- The installed bag branch reuses the existing artifact-rejection log and
  continuation. No registry, catalogue, or collision behavior changed.
- The deferred MDX secondary-slot mismatch and ensemble-page validation-warning
  UI were not touched.

## Concerns

- Full unittest discovery could not complete in this sandbox because the
  advertised Wayland display was unusable and dconf runtime storage was
  read-only. Focused non-GTK regressions and both type-check gates are green;
  controller-side full-suite verification remains required.
