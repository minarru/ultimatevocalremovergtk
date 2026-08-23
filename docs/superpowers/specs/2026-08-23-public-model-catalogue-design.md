# Public Model Catalogue Design

**Date:** 2026-08-23

**Status:** Implemented and verified

## Goal

Make every model supplied through an upstream `*_vip_list` visible and
downloadable without a code, and remove the VIP-code UI and setting entirely.

## Scope

This change removes access gating. It does not rename upstream JSON keys or
change canonical runtime model IDs. The `*_vip_list` names and the `VIP:` label
fragment remain accepted only as legacy upstream wire-format details.

The former gated repository is published directly in source as:

```text
https://github.com/Anjok0109/ai_magic/releases/download/v5/
```

It is treated as a second public model artifact repository, not as an unlocked
or privileged state.

## Catalogue Architecture

`CatalogueCoordinator` publishes one catalogue projection. Its upstream
adapter always folds `vr_download_vip_list`, `demucs_download_vip_list`, and
every key in `UPSTREAM_MDX_VIP_KEYS` into the corresponding ordinary family
list before supplemental catalogues, deduplication, metadata, and display
indexes are built.

The coordinator no longer accepts a `vip` projection argument, stores
`_latest_unlocked`, builds a VIP revision, or publishes duplicate locked and
unlocked snapshots. `RevisionVector` no longer carries a VIP bit because
access state is no longer part of catalogue identity.

Callers request the sole snapshot. Installed-model presentation therefore
receives exact mappings from former `*_vip_list` entries through the same path
as every other catalogue entry.

## Download Routing

`bundled.constants.urls` exposes the former gated release as
`ADDITIONAL_MODEL_REPO`. The encrypted `VIP_REPO` value and `NO_CODE` sentinel
are removed.

The upstream catalogue still prefixes some selection keys with `VIP:`. That
marker is renamed internally to a legacy additional-repository marker and is
used only to choose the correct public artifact base. It grants no access and
does not affect catalogue visibility. Display-name canonicalization continues
to strip the marker from user-facing text.

Every former `*_vip_list` entry must resolve through the existing VR or MDX
job resolver with `ADDITIONAL_MODEL_REPO`; ordinary entries continue to use
`NORMAL_REPO`. Configuration and multi-file model resolution remain unchanged.

## Backend and UI Removal

`DownloadManager` has no decoded-link field, password validator, or decryption
helper. Catalogue refresh, manual downloads, and Download Center projection
all use the single public snapshot.

The Download Center header has no password button. The VIP-code dialog,
validation callbacks, unlock toast, and VIP help text are deleted. Startup no
longer reads or validates a saved code.

The `ProcessSettings.user_code` field and its typed/default/flat-map entries
are removed. Loading an older settings file containing `process.user_code`
must remain harmless: the settings loader ignores that unknown legacy key and
the next normal save omits it. No migration writes are performed merely by
starting the application.

The optional `cryptography` import used solely for URL decryption is removed.
If the package is declared solely for this feature, its dependency declaration
is removed as well.

## Refresh and Identity Behavior

A source refresh builds and publishes one snapshot and emits at most one
catalogue delta for that publication. Trusted download identities rebuild that
same snapshot once. Model inventory invalidation and widget repick behavior
remain driven by the existing catalogue-delta and repository-invalidation
paths; there is no unlock-triggered refresh.

Newly downloaded former VIP models follow the same usability boundary as all
other downloads: after every required artifact is committed successfully, the
repository is invalidated and widgets repick from the refreshed installed
inventory.

## Error Handling

Former VIP entries are visible even when offline because visibility comes from
the cached or bundled upstream catalogue. Download failures use the existing
download error path. There is no password-specific error state.

The public additional repository is a release endpoint controlled outside
this application. A missing artifact remains an ordinary HTTP/download error;
the application does not hide its catalogue row or fall back to the normal
repository.

## Tests

Regression tests must prove observable behavior rather than the absence of
source symbols:

- Flattening upstream data includes VR, Demucs, and every MDX-family
  `*_vip_list` without an option or code.
- The sole coordinator snapshot contains former VIP entries and has stable
  revision/cache behavior across refresh and trusted-identity rebuilds.
- A representative former VIP VR selection and representative former VIP MDX
  selections resolve jobs against `ADDITIONAL_MODEL_REPO` without validation.
- Manual downloads and Download Center projections include former VIP entries
  immediately.
- Settings containing legacy `process.user_code` load successfully and a
  subsequent save omits the field.
- GTK construction exposes no VIP-code control or dialog path, covered through
  the existing isolated GTK test harness where widget construction is needed.
- Model identity/display tests use a former VIP installed basename and confirm
  it receives its exact catalogue display mapping from the sole snapshot.
- Vocal-splitter tests continue to admit only installed models classified as
  karaoke or backing-vocal models; public catalogue membership is not enough.
- The focused catalogue, download, settings, UI, CLI, and model-identity tests
  pass, followed by the complete unittest suite and basedpyright.

## Non-Goals

- Renaming externally maintained `*_vip_list` JSON keys.
- Mirroring or repackaging upstream model artifacts.
- Changing catalogue display-name policy beyond making the formerly gated
  exact mappings available to the normal projection.
- Changing canonical `family:basename` runtime IDs or backend artifact names.
