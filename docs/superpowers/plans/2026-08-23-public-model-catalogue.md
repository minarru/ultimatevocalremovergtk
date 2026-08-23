# Public Model Catalogue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every upstream `*_vip_list` model immediately visible and downloadable, while deleting VIP-code state, settings, and UI.

**Architecture:** Collapse `CatalogueCoordinator` to one unconditional public projection and publish the former gated GitHub release as a second ordinary artifact base. Preserve `*_vip_list` and `VIP:` only at the upstream compatibility boundary; all application consumers receive one snapshot with no access-state dimension.

**Tech Stack:** Python 3.12+, stdlib `unittest`, GTK4/libadwaita, basedpyright

**Spec:** `docs/superpowers/specs/2026-08-23-public-model-catalogue-design.md`

**Status:** Complete — verified 2026-08-23

## Global Constraints

- Preserve canonical runtime model IDs exactly as `family:basename`.
- Preserve upstream `*_vip_list` keys and `VIP:` label parsing as wire-format compatibility.
- Publish `https://github.com/Anjok0109/ai_magic/releases/download/v5/` directly in source.
- Do not rename backend artifacts or alter normal-repository download routing.
- Do not fetch network data in read-only CLI listing or model-identity construction.
- Older JSON containing `process.user_code` must load without error and omit that key on the next normal save.
- Invalidate installed-model inventory only after every required artifact for a model is usable, using the existing download-completion path.
- Keep the vocal-splitter picker restricted to karaoke models; catalogue visibility must not widen picker eligibility.
- Do not stage or commit changes unless the user explicitly requests it.

---

### Task 1: Collapse the catalogue to one public projection

**Files:**
- Modify: `core/catalogue_types.py`
- Modify: `core/catalogue_coordinator.py`
- Modify: `core/model_repository.py`
- Modify: `core/model_identity.py`
- Modify: `core/mdx_c_registry.py`
- Modify: `cli/discovery.py`
- Modify: `scripts/catalogue/collect.py`
- Test: `tests/test_catalogue_coordinator.py`
- Test: `tests/test_catalogue_characterization.py`
- Test: `tests/test_cli_list_models.py`
- Test: `tests/test_core_downloads.py`
- Test: `tests/test_generate_models_catalogue.py`
- Test: `tests/test_model_identity_contracts.py`

**Interfaces:**
- Consumes: upstream mappings named by `UPSTREAM_VR_KEYS`,
  `UPSTREAM_VR_VIP_KEYS`, `UPSTREAM_DEMUCS_KEYS`,
  `UPSTREAM_DEMUCS_VIP_KEYS`, `UPSTREAM_MDX_KEYS`, and
  `UPSTREAM_MDX_VIP_KEYS`.
- Produces: `flatten_upstream_lists(payload) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]`; `CatalogueCoordinator.snapshot(*, mode, policy)` and `ensure(*, allow_network, policy)` returning the sole `CatalogueSnapshot`.

- [x] **Step 1: Write the failing all-lists projection test**

Replace `test_vip_is_a_projection_not_source_state` with a table-driven test whose literal expectations cover the VR, Demucs, and every MDX-family legacy list:

```python
def test_public_projection_includes_every_legacy_vip_list(self) -> None:
    payload = {
        "vr_download_list": {"VR Public": "public.pth"},
        "vr_download_vip_list": {"VR VIP: Added": "added.pth"},
        "mdx_download_list": {"MDX Public": "public.onnx"},
        "mdx_download_vip_list": {"MDX-Net Model VIP: Added MDX": "mdx.onnx"},
        "mdx23_download_vip_list": {"MDX23 Model VIP: Added MDX23": {"23.ckpt": "23.yaml"}},
        "mdx23c_download_vip_list": {"MDX23C Model VIP: Added MDX23C": {"23c.ckpt": "23c.yaml"}},
        "roformer_download_vip_list": {"Roformer Model VIP: Added Roformer": {"r.ckpt": "r.yaml"}},
        "scnet_download_vip_list": {"SCNet Model VIP: Added": {"s.ckpt": "s.yaml"}},
        "bandit_download_vip_list": {"Bandit Model VIP: Added": {"b.ckpt": "b.yaml"}},
        "demucs_download_vip_list": {"Demucs Model VIP: Added": "demucs.yaml"},
        "demucs_download_list": {},
    }
    coordinator = self._coordinator(payload)
    snapshot = coordinator.snapshot(
        mode=RefreshMode.OFFLINE,
        policy=AccessPolicy(False, False),
    )
    self.assertEqual(set(snapshot.vr), {"VR Public", "VR VIP: Added"})
    self.assertEqual(
        set(snapshot.mdx),
        {
            "MDX Public",
            "MDX-Net Model VIP: Added MDX",
            "MDX23 Model VIP: Added MDX23",
            "MDX23C Model VIP: Added MDX23C",
            "Roformer Model VIP: Added Roformer",
            "SCNet Model VIP: Added",
            "Bandit Model VIP: Added",
        },
    )
    self.assertEqual(set(snapshot.demucs), {"Demucs Model VIP: Added"})
    self.assertEqual(coordinator.builds, 1)
    coordinator.close()
```

This catches omission of any supported upstream list and any reintroduction of two projections.

Also add the original installed-model display regression before changing the
projection. It uses a real coordinator so it cannot pass from a synthetic
already-prettified display map:

```python
def _coordinator_for_payload(payload: dict[str, Any]) -> CatalogueCoordinator:
    sources = {
        SourceId.UPSTREAM: RemoteJsonSource(
            source_id=SourceId.UPSTREAM, local_loader=lambda: payload
        )
    }
    for source_id in (
        SourceId.POLITREES,
        SourceId.EXTRAS,
        SourceId.MVSEPLESS,
    ):
        sources[source_id] = RemoteJsonSource(
            source_id=source_id, enabled=lambda: False
        )
    return CatalogueCoordinator(sources=sources)


def test_former_vip_installed_model_uses_public_catalogue_display(self) -> None:
    payload = {
        "mdx_download_list": {},
        "mdx_download_vip_list": {
            "MDX-Net Model VIP: UVR-MDX-NET_Main_427":
                "UVR-MDX-NET_Main_427.onnx"
        },
        "vr_download_list": {},
        "demucs_download_list": {},
    }
    coordinator = _coordinator_for_payload(payload)
    self.addCleanup(coordinator.close)
    snapshot = coordinator.ensure(allow_network=False)
    repo = _empty_repo(
        _model_artifact_files=lambda family: (
            ["UVR-MDX-NET_Main_427.onnx"] if family == "mdx" else []
        )
    )
    record = build_identity_index(repo, snapshot=snapshot).lookup(
        "mdx:UVR-MDX-NET_Main_427"
    )
    self.assertEqual(record.display, "MDX-Net — UVR-MDX-NET_Main_427")
    self.assertEqual(record.backend_name, "UVR-MDX-NET_Main_427")
```

Add the required imports for `CatalogueCoordinator`, `SourceId`,
`RemoteJsonSource`, and `build_identity_index` beside the existing test
imports.

- [x] **Step 2: Run the test and verify RED**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_catalogue_coordinator.CatalogueCoordinatorTests.test_public_projection_includes_every_legacy_vip_list \
  tests.test_model_identity_contracts.DisplayEnrichmentTests.test_former_vip_installed_model_uses_public_catalogue_display -v
```

Expected: both FAIL because the default snapshot omits all `*_vip_list` rows;
the display test reports the raw basename instead of the exact catalogue label.

- [x] **Step 3: Implement unconditional flattening and a single revision**

In `core/catalogue_coordinator.py`, remove the `vip` parameter and fold both ordinary and legacy list keys every time:

```python
def flatten_upstream_lists(
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    vr: dict[str, Any] = {}
    for key in (*UPSTREAM_VR_KEYS, *UPSTREAM_VR_VIP_KEYS):
        catalogue = payload.get(key)
        if isinstance(catalogue, dict):
            vr.update(catalogue)
    mdx: dict[str, Any] = {}
    for key in (*UPSTREAM_MDX_KEYS, *UPSTREAM_MDX_VIP_KEYS):
        catalogue = payload.get(key)
        if isinstance(catalogue, dict):
            mdx.update(catalogue)
    demucs = dict(payload.get("demucs_download_list") or {})
    return vr, mdx, demucs
```

Then:

- bump `ADAPTER_SCHEMA` from `1` to `2` because identical upstream bytes now produce a different projection;
- remove `RevisionVector.vip` and the `vip/locked` digest component;
- change `_snapshots` to `dict[str, CatalogueSnapshot]`;
- delete `_latest_unlocked`;
- remove `vip` from `snapshot`, `ensure`, `_revision`, `_publish`, and `_build_snapshot`;
- make refresh, source-update, force-refresh, and trusted-identity paths publish exactly once;
- retain delta comparison against `_latest` only.

Update every caller listed above from `ensure(vip=..., ...)`, `snapshot(vip=..., ...)`, or `flatten_upstream_lists(..., vip=...)` to the sole interface. Update mock assertions in CLI/catalogue-generator tests to match.

- [x] **Step 4: Run focused catalogue and caller tests and verify GREEN**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_catalogue_coordinator \
  tests.test_catalogue_characterization \
  tests.test_cli_list_models \
  tests.test_generate_models_catalogue \
  tests.test_model_identity_contracts.DisplayEnrichmentTests.test_former_vip_installed_model_uses_public_catalogue_display -v
```

Expected: PASS with no `vip=` caller left.

---

### Task 2: Publish the additional repository and remove backend gating

**Files:**
- Modify: `bundled/constants/urls.py`
- Modify: `bundled/constants/messages.py`
- Modify: `core/downloads.py`
- Modify: `core/model_catalogue.py`
- Test: `tests/test_core_downloads.py`
- Test: `tests/test_manual_downloads.py`
- Test: `tests/test_download_center_dedupe_refresh.py`

**Interfaces:**
- Consumes: legacy upstream selection labels containing `VIP:` and catalogue values already merged by Task 1.
- Produces: `ADDITIONAL_MODEL_REPO: str`; `LEGACY_ADDITIONAL_REPO_SELECTION: str`; `DownloadManager.resolve(...)` choosing a public base without access state.

- [x] **Step 1: Write failing public-routing tests**

Replace `VipDownloadsTests` with observable resolver tests:

```python
class AdditionalPublicRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = DownloadManager()

    def test_former_vip_vr_model_uses_additional_public_repo(self) -> None:
        label = "VR Arch Single Model VIP: Added"
        self.manager.vr_download_list = {label: "added.pth"}
        jobs = self.manager.resolve(label, VR_ARCH_TYPE)
        self.assertEqual(
            jobs[0][0],
            "https://github.com/Anjok0109/ai_magic/releases/download/v5/added.pth",
        )

    def test_former_vip_mdx_model_uses_additional_public_repo(self) -> None:
        label = "MDX-Net Model VIP: UVR-MDX-NET_Main_427"
        self.manager.mdx_download_list = {label: "UVR-MDX-NET_Main_427.onnx"}
        jobs = self.manager.resolve(label, MDX_ARCH_TYPE, fetch_config=False)
        self.assertEqual(
            jobs[0][0],
            "https://github.com/Anjok0109/ai_magic/releases/download/v5/UVR-MDX-NET_Main_427.onnx",
        )

    def test_former_vip_mdx_c_checkpoint_uses_additional_public_repo(self) -> None:
        label = "MDX23C Model VIP: MDX23C_D1581"
        self.manager.mdx_download_list = {
            label: {"MDX23C_D1581.ckpt": "model_2_stem_061321.yaml"}
        }
        jobs = self.manager.resolve(label, MDX_ARCH_TYPE, fetch_config=False)
        self.assertEqual(
            jobs[0][0],
            "https://github.com/Anjok0109/ai_magic/releases/download/v5/MDX23C_D1581.ckpt",
        )
```

Replace the locked/unlocked manual-download pair with:

```python
def test_vip_entries_are_public_without_state_or_code(self) -> None:
    self.manager.online_data = {
        "mdx23c_download_vip_list": {
            "MDX23C Model VIP: Added": {"v.ckpt": "v.yaml"}
        }
    }
    with mock.patch(
        "core.catalog_sources._supplemental_sources", return_value=({}, {}, {}, {})
    ):
        data = self.manager.manual_download_data()
    self.assertIn("MDX23C Model VIP: Added", data["mdx"])
```

Rewrite the journey as `ComposedPublicJourneyTests`: the row is present
immediately, pins `_latest`, resolves, and queues without setting any manager
field. Cover the manual-download link with the same additional public base.

- [x] **Step 2: Run the routing tests and verify RED**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_core_downloads.AdditionalPublicRepositoryTests \
  tests.test_manual_downloads \
  tests.test_download_center_dedupe_refresh.ComposedPublicJourneyTests -v
```

Expected: FAIL because the additional URL is encrypted and catalogue visibility depends on `decoded_vip_link`.

- [x] **Step 3: Implement public routing and delete backend access state**

Replace the encrypted constants with:

```python
ADDITIONAL_MODEL_REPO = (
    "https://github.com/Anjok0109/ai_magic/releases/download/v5/"
)
```

Rename the internal marker in `bundled/constants/messages.py`:

```python
LEGACY_ADDITIONAL_REPO_SELECTION = "VIP:"
```

In `core/downloads.py`:

- delete `vip_downloads` and its lazy `cryptography` imports;
- delete `decoded_vip_link` and `validate_vip_code`;
- always apply `coordinator._latest` on source deltas;
- request the sole snapshot in ensure, refresh, and identity reapplication;
- call `flatten_upstream_lists(self.online_data)` in compatibility rebuilds;
- choose `ADDITIONAL_MODEL_REPO` when the legacy marker is present, otherwise `NORMAL_REPO`;
- update module and method documentation to describe two public artifact bases.

Use this resolver branch:

```python
model_repo = (
    ADDITIONAL_MODEL_REPO
    if LEGACY_ADDITIONAL_REPO_SELECTION in selection
    else NORMAL_REPO
)
```

In `core/model_catalogue.py`, remove `decoded_vip_link` from `_snapshot_key`; the sole revision digest and list cardinalities remain the cache key.

In `ui/download_center.py`, simplify `_pin_current_snapshot` to pin only `coordinator._latest`. Update the composed journey tests to assert this behavior.

- [x] **Step 4: Run backend, manual, and pinning tests and verify GREEN**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_core_downloads \
  tests.test_manual_downloads \
  tests.test_download_center_dedupe_refresh -v
```

Expected: PASS; no password or unlock state is needed to resolve former VIP rows.

---

### Task 3: Remove the VIP setting and GTK surfaces

**Files:**
- Modify: `core/settings/model.py`
- Modify: `core/settings/defaults.py`
- Modify: `core/settings/flat_map.py`
- Modify: `bundled/constants/defaults.py`
- Modify: `ui/download.py`
- Modify: `ui/download_center.py`
- Modify: `ui/help_text.py`
- Modify: `requirements.txt`
- Test: `tests/test_core_settings.py`
- Test: `tests/test_settings_typed.py`
- Test: `tests/test_help_text.py`
- Create: `tests/test_download_center_public_ui.py`

**Interfaces:**
- Consumes: legacy settings JSON, GTK Download Center construction, and the public `DownloadManager` from Task 2.
- Produces: settings serialization with no `user_code`; Download Center header containing only public model-management controls.

- [x] **Step 1: Write the failing legacy-settings regression**

Add to `tests/test_settings_typed.py`:

```python
def test_legacy_vip_code_is_ignored_and_not_reserialized(self) -> None:
    payload = Settings.defaults().to_json_dict()
    payload["process"]["user_code"] = "old-secret"
    restored = Settings.from_json_dict(payload)
    self.assertFalse(hasattr(restored.process, "user_code"))
    self.assertNotIn("user_code", restored.to_json_dict()["process"])
    self.assertIsNone(restored.get("user_code"))
```

Change `test_atomic_save_uses_replace` so it exercises an ordinary setting instead of `user_code`:

```python
model.set("export_path", "/tmp/export")
model.save()
self.assertEqual(Settings.load(path).process.export_path, "/tmp/export")
```

- [x] **Step 2: Write the failing GTK header regression**

Create `tests/test_download_center_public_ui.py` using the same display-availability guard as other GTK tests. Construct a real `DownloadCenterWindow` with `Settings.defaults()`, a `DownloadManager`, and a harmless queue double; walk the widget tree and collect button icon names. The complete test shape is:

```python
from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest import mock


@unittest.skipUnless(
    os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"),
    "GTK widget construction needs a display",
)
class DownloadCenterPublicUiTests(unittest.TestCase):
    def test_header_has_public_menu_without_password_control(self) -> None:
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk

        from core.downloads import DownloadManager
        from core.settings import Settings
        from ui.download_center import DownloadCenterWindow

        context = SimpleNamespace(settings=Settings.defaults())
        center = DownloadCenterWindow(
            None, context, DownloadManager(), mock.MagicMock()
        )
        self.addCleanup(center.window.destroy)

        icon_names: list[str] = []
        stack: list[Gtk.Widget] = [center.window]
        while stack:
            widget = stack.pop()
            if isinstance(widget, (Gtk.Button, Gtk.MenuButton)):
                icon = widget.get_icon_name()
                if icon:
                    icon_names.append(icon)
            child = widget.get_first_child()
            while child is not None:
                stack.append(child)
                child = child.get_next_sibling()

        self.assertIn("open-menu-symbolic", icon_names)
        self.assertNotIn("dialog-password-symbolic", icon_names)
```

The test exercises the rendered widget tree, not source text or a mocked button.

- [x] **Step 3: Run the settings and GTK tests and verify RED**

Run settings directly:

```bash
.venv/bin/python -m unittest \
  tests.test_settings_typed.TypedSettingsTests.test_legacy_vip_code_is_ignored_and_not_reserialized -v
```

Expected: FAIL because `ProcessSettings` still has `user_code`.

Run the GTK test through the repository's isolated headless GTK runner:

```bash
/home/rudam/.codex/skills/testing-gtk-headless/scripts/run-private-wayland.sh \
  .venv/bin/python -m unittest tests.test_download_center_public_ui -v
```

Expected: FAIL because the password button is still present.

- [x] **Step 4: Remove the setting, dialog, and controls**

- Delete `ProcessSettings.user_code`, `default_process()["user_code"]`, and the `FLAT_TO_PATH["user_code"]` bridge.
- Remove the legacy key from `bundled.constants.DEFAULT_DATA`; older JSON remains safe because `_merge_dataclass` filters unknown fields.
- Remove saved-code reads from `DownloadCenterWindow.__init__` and `start_download_size_cache_warmup`.
- Remove the password button, `_open_vip`, `_on_vip_validated`, `open_vip_code_dialog`, and `VIP_DOWNLOAD_CODE_HINT`.
- Remove now-unused donation-link imports from `ui/download.py`; do not remove unrelated donation links elsewhere.
- Remove `cryptography==49.0.0` from `requirements.txt`, preserving CRLF/file formatting used by that file.
- Update module docstrings and help-text tests so no VIP-code behavior is advertised.

- [x] **Step 5: Run settings and isolated GTK tests and verify GREEN**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_core_settings \
  tests.test_settings_typed \
  tests.test_help_text -v
/home/rudam/.codex/skills/testing-gtk-headless/scripts/run-private-wayland.sh \
  .venv/bin/python -m unittest \
  tests.test_download_center_public_ui \
  tests.test_download_center_search \
  tests.test_download_center_sort \
  tests.test_download_center_state -v
```

Expected: PASS with the public menu still available and no password control.

---

### Task 4: Remove stale naming assumptions and validate picker scope

**Files:**
- Modify: `core/model_display.py`
- Modify: `core/mdx_c_registry.py`
- Modify: `docs/superpowers/specs/2026-08-23-public-model-catalogue-design.md`
- Modify: `docs/superpowers/plans/2026-08-23-public-model-catalogue.md`

**Interfaces:**
- Consumes: Task 1's passing end-to-end display regression and existing picker eligibility rules.
- Produces: compatibility documentation that treats VIP text as external syntax only, without widening display or karaoke policy.

- [x] **Step 1: Update compatibility comments without widening display policy**

- Change comments in `core/model_display.py` and `core/mdx_c_registry.py` from “code-gated/VIP projection” to “legacy upstream list/prefix.”
- Keep sanitizers for `MDX-Net Model VIP:`, `MDX23C Model VIP:`, and related external labels; removing those would leak the legacy prefix into display names.
- Keep raw-basename fallback for genuinely unknown custom models.
- Do not change karaoke eligibility or picker filtering.

- [x] **Step 2: Run identity, display, picker, and karaoke regressions**

Run:

```bash
.venv/bin/python -m unittest \
  tests.test_model_identity_contracts \
  tests.test_model_display \
  tests.test_model_picker_records \
  tests.test_vocal_split_row \
  tests.test_method_view_refresh -v
```

Expected: PASS; former VIP installed models are friendly while unknown custom models remain raw.

---

### Task 5: Final audit and verification

**Files:**
- Modify only if verification exposes a defect: files already listed above

**Interfaces:**
- Consumes: completed Tasks 1-4.
- Produces: evidence that access gating is absent and the repository remains type- and test-clean.

- [x] **Step 1: Audit residual access-state references**

Run:

```bash
rg -n --glob '*.py' --glob '*.txt' \
  '(decoded_vip_link|validate_vip_code|vip_downloads|VIP_REPO|NO_CODE|user_code|VIP_DOWNLOAD_CODE_HINT|open_vip_code_dialog|vip=)' \
  bundled core ui cli scripts tests requirements.txt
```

Expected: no production matches. The legacy-settings regression deliberately
mentions `user_code`. Separately inspect remaining `VIP:` and `*_vip_list`
matches and confirm each is an upstream compatibility parser, naming sanitizer,
dedupe rule, fixture, or approved documentation reference.

- [x] **Step 2: Run the full test suite**

Run:

```bash
/home/rudam/.codex/skills/testing-gtk-headless/scripts/run-private-wayland.sh \
  .venv/bin/python -m unittest discover -s tests -t . -v
```

Expected: exit 0 with zero failures and zero errors.

- [x] **Step 3: Run static type checking**

Run:

```bash
.venv/bin/python -m basedpyright
```

Expected: exit 0 with zero errors.

- [x] **Step 4: Verify generated catalogue and whitespace**

Run:

```bash
.venv/bin/python scripts/generate_models_catalogue.py --check --offline
git diff --check
git status --short
```

Expected: catalogue check does not rewrite files, `git diff --check` exits 0, and status lists only intended source/tests/spec/plan changes.

- [x] **Step 5: Verify representative live artifacts without downloading weights**

Run HEAD requests for:

```text
UVR-MDX-NET_Main_427.onnx
UVR-MDX-NET_Main_438.onnx
UVR-MDX-NET-Inst_full_292.onnx
```

against `ADDITIONAL_MODEL_REPO`. Expected: redirects terminate at HTTP 200. Record only status, filename, and content length; do not download the model bodies.

- [x] **Step 6: Update plan/spec status and report evidence**

Mark completed checkboxes only after their commands have passed. Report the exact full-suite and basedpyright results, any unavailable GTK infrastructure separately, and the uncommitted file list. Do not stage or commit.
